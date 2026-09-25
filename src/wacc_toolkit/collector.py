"""Contrato dos coletores e orquestração de uma atualização.

Cada fonte é uma subclasse de :class:`Coletor` com dois métodos:

- ``coletar(ctx)``: obtém os arquivos originais (da internet, ou de ``entrada/<fonte>/``
  para fontes manuais) e devolve uma lista de :class:`ArquivoBruto`. Não interpreta nada.
- ``interpretar(ctx, brutos)``: lê os arquivos **já gravados em bruto** e devolve
  ``{serie_id: DataFrame}`` com as colunas do :class:`SerieSpec`. Para séries
  versionadas, devolve ``{serie_id: {versao: DataFrame}}``.

Como a interpretação parte sempre do bruto gravado, qualquer série tratada pode ser
reproduzida a partir dos originais.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

from .http import nova_sessao
from .series import SerieSpec
from .storage import ArquivoBruto, RegistroBruto, Repositorio
from .validate import Problema, normalizar, tem_erro, validar

log = logging.getLogger("wacc_toolkit")


@dataclass
class Contexto:
    repo: Repositorio
    sessao: requests.Session = field(default_factory=nova_sessao)

    def entrada(self, fonte: str) -> Path:
        return self.repo.dir_entrada(fonte)


class Coletor(ABC):
    fonte: str = ""
    descricao: str = ""
    manual: bool = False  # True: lê de entrada/<fonte>/ em vez da internet
    series: tuple[SerieSpec, ...] = ()

    def spec(self, serie_id: str) -> SerieSpec:
        for s in self.series:
            if s.id == serie_id:
                return s
        raise KeyError(f"{self.fonte}: série desconhecida {serie_id}")

    @abstractmethod
    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]: ...

    @abstractmethod
    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict: ...


@dataclass
class ResultadoSerie:
    serie: str
    status: str  # "gravada" | "rejeitada" | "sem_mudanca"
    versao: str | None = None
    linhas: int = 0
    fim: str | None = None
    problemas: list[Problema] = field(default_factory=list)


@dataclass
class ResultadoColeta:
    fonte: str
    status: str  # "ok" | "sem_novidade" | "parcial" | "falhou"
    brutos_novos: int = 0
    series: list[ResultadoSerie] = field(default_factory=list)
    erro: str | None = None


def executar(coletor: Coletor, ctx: Contexto, reprocessar: bool = False) -> ResultadoColeta:
    """Roda uma coleta completa. Nunca apaga nem sobrescreve uma série com dados que
    falharam na validação; em caso de falha, a última versão boa permanece."""
    repo = ctx.repo
    fonte = coletor.fonte
    try:
        arquivos = coletor.coletar(ctx)
    except Exception as e:  # noqa: BLE001 — qualquer falha de fonte é registrada, não propagada
        log.exception("%s: falha na coleta", fonte)
        repo.registrar({"tipo": "falha", "fonte": fonte, "etapa": "coletar", "erro": repr(e)})
        return ResultadoColeta(fonte, "falhou", erro=repr(e))

    if not arquivos:
        msg = "nenhum arquivo obtido" + (f" (coloque arquivos em entrada/{fonte}/)" if coletor.manual else "")
        repo.registrar({"tipo": "falha", "fonte": fonte, "etapa": "coletar", "erro": msg})
        return ResultadoColeta(fonte, "falhou", erro=msg)

    registros = [repo.gravar_bruto(fonte, a) for a in arquivos]
    novos = sum(r.novo for r in registros)
    series_existem = all(
        (repo.versoes(s) if s.versionada else repo.caminho_serie(s).exists()) for s in coletor.series
    )
    if novos == 0 and series_existem and not reprocessar:
        log.info("%s: sem novidade (arquivos idênticos aos já registrados)", fonte)
        return ResultadoColeta(fonte, "sem_novidade", 0)

    try:
        saida = coletor.interpretar(ctx, registros)
    except Exception as e:  # noqa: BLE001
        log.exception("%s: falha na interpretação", fonte)
        repo.registrar({"tipo": "falha", "fonte": fonte, "etapa": "interpretar", "erro": repr(e)})
        return ResultadoColeta(fonte, "falhou", novos, erro=repr(e))

    resultado = ResultadoColeta(fonte, "ok", novos)
    for serie_id, conteudo in saida.items():
        spec = coletor.spec(serie_id)
        if spec.versionada:
            for versao, df in conteudo.items():
                resultado.series.append(_gravar(repo, spec, df, registros, versao))
        else:
            resultado.series.append(_gravar(repo, spec, conteudo, registros, None))
    if any(s.status == "rejeitada" for s in resultado.series):
        resultado.status = "parcial"
    return resultado


def _gravar(repo: Repositorio, spec: SerieSpec, df: pd.DataFrame, origem: list[RegistroBruto],
            versao: str | None) -> ResultadoSerie:
    try:
        novo = normalizar(spec, df)
    except Exception as e:  # noqa: BLE001
        prob = [Problema("erro", f"normalização: {e}")]
        repo.registrar({"tipo": "serie", "status": "rejeitada", "serie": spec.id, "versao": versao,
                        "problemas": [str(x) for x in prob]})
        return ResultadoSerie(spec.id, "rejeitada", versao, problemas=prob)

    anterior = repo.ler_serie(spec, versao) if (not spec.versionada or versao in repo.versoes(spec)) else None
    if anterior is not None:
        anterior = normalizar(spec, anterior)
    if spec.modo == "acumular" and anterior is not None:
        novo = (pd.concat([anterior, novo]).drop_duplicates(subset=list(spec.chave), keep="last")
                .sort_values(list(spec.chave), kind="stable").reset_index(drop=True))

    problemas = validar(spec, novo, anterior)
    fim = str(max(novo["data"])) if "data" in novo.columns and len(novo) else None
    if tem_erro(problemas):
        log.warning("%s: rejeitada — %s", spec.id, "; ".join(map(str, problemas)))
        repo.registrar({"tipo": "serie", "status": "rejeitada", "serie": spec.id, "versao": versao,
                        "problemas": [str(x) for x in problemas]})
        return ResultadoSerie(spec.id, "rejeitada", versao, len(novo), fim, problemas)

    if anterior is not None and len(anterior) == len(novo) and anterior.equals(novo):
        return ResultadoSerie(spec.id, "sem_mudanca", versao, len(novo), fim, problemas)

    repo.gravar_serie(spec, novo, origem, [str(x) for x in problemas], versao)
    for x in problemas:
        log.info("%s: %s", spec.id, x)
    return ResultadoSerie(spec.id, "gravada", versao, len(novo), fim, problemas)
