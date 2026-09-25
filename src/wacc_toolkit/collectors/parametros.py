"""Parâmetros manuais (sem fonte automatizável): alíquotas, remuneração BNDES etc.

O usuário mantém ``<bases>/entrada/parametros/parametros_manuais.toml`` (modelo em
``parametros_manuais.example.toml`` na raiz do repositório). Cada alteração do arquivo
gera um novo bruto versionado por hash, de modo que o valor vigente em qualquer data
possa ser reconstituído pelo manifesto.

Formato::

    [[parametro]]
    id = "ir_csll"
    valor = 34.0
    unidade = "%"
    fonte = "Receita Federal: IRPJ 15% + adicional 10% + CSLL 9%"
    verificado_em = 2026-09-25
    responsavel = "..."
    notas = ""
"""

from __future__ import annotations

import tomllib

import pandas as pd

from ..collector import Coletor, Contexto
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

ARQUIVO = "parametros_manuais.toml"
COLUNAS = ("parametro", "valor", "unidade", "fonte", "verificado_em", "responsavel", "notas")


def interpretar_toml(conteudo: bytes) -> pd.DataFrame:
    dados = tomllib.loads(conteudo.decode("utf-8"))
    itens = dados.get("parametro", [])
    if not itens:
        raise ValueError(f"{ARQUIVO}: nenhuma entrada [[parametro]]")
    linhas = []
    for it in itens:
        faltando = [k for k in ("id", "valor", "unidade", "fonte", "verificado_em") if k not in it]
        if faltando:
            raise ValueError(f"{ARQUIVO}: parâmetro {it.get('id', '?')} sem {faltando}")
        linhas.append({"parametro": it["id"], "valor": float(it["valor"]), "unidade": it["unidade"],
                       "fonte": it["fonte"], "verificado_em": str(it["verificado_em"]),
                       "responsavel": it.get("responsavel", ""), "notas": it.get("notas", "")})
    return pd.DataFrame(linhas, columns=COLUNAS)


@registrar
class Parametros(Coletor):
    fonte = "parametros"
    descricao = "Parâmetros manuais (IR/CSLL, remuneração BNDES...): entrada/parametros/"
    manual = True
    series = (SerieSpec("parametros_manuais", "Parâmetros manuais vigentes", "ver coluna unidade", "V",
                        colunas=COLUNAS, chave=("parametro",), valores=("valor",)),)

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        caminho = ctx.entrada(self.fonte) / ARQUIVO
        if not caminho.exists():
            return []
        return [ArquivoBruto(caminho.read_bytes(), "toml", nome_original=ARQUIVO, rotulo="parametros")]

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        return {"parametros_manuais": interpretar_toml(brutos[-1].caminho.read_bytes())}
