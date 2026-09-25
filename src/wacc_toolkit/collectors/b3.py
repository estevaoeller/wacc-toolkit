"""B3 — Ibovespa oficial, via endpoint não documentado de estatísticas de índice.

Endpoint (não documentado, mas verificado funcionando em 2026-09):
    https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/GetPortfolioDay/{token}

``token`` é o base64 do JSON ``{"index": "IBOVESPA", "language": "pt-br", "year": "<ano>"}``
(essa ordem de chaves e esses valores de string são os que funcionam; outras combinações
não foram testadas). A resposta traz, para o ano pedido, o fechamento diário do Ibovespa
organizado em ``results``: uma lista de até 31 entradas (uma por dia do mês, 1..31), cada
uma com ``rateValue1``..``rateValue12`` (um por mês). Dias sem pregão (fim de semana,
feriado) ou datas inexistentes (ex.: 31 de abril) vêm como ``null`` ou simplesmente não
correspondem a uma data de calendário válida; ambos os casos são descartados. Os números
vêm no formato brasileiro (``"126.601,55"``).

Como o endpoint só devolve um ano por vez, a série ``b3_ibov`` é coletada em modo
``acumular``: cada arquivo bruto representa um ano e é mesclado ao histórico já gravado.
Na primeira carga (quando a série tratada ainda não existe), baixamos 1995 até o ano
corrente; nas cargas seguintes, só o ano corrente e o anterior (para capturar eventuais
revisões de fim de ano/virada). Entre requisições, uma pausa curta evita sobrecarregar o
servidor da B3.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import date, datetime

import pandas as pd

from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

URL = "https://sistemaswebb3-listados.b3.com.br/indexStatisticsProxy/IndexCall/GetPortfolioDay/{token}"

PAUSA_ENTRE_REQUISICOES_S = 0.5
PRIMEIRO_ANO = 1995


def _token(ano: int) -> str:
    payload = {"index": "IBOVESPA", "language": "pt-br", "year": str(ano)}
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _parse_numero_br(texto: str) -> float:
    """Converte um número no formato brasileiro (``"126.601,55"``) para float."""
    return float(texto.replace(".", "").replace(",", "."))


def interpretar_b3_json(conteudo: bytes, ano: int) -> pd.DataFrame:
    """Interpreta a resposta de ``GetPortfolioDay`` para um único ano."""
    dados = json.loads(conteudo)
    resultados = dados.get("results")
    if not resultados:
        raise ValueError(f"resposta da B3 sem 'results' para o ano {ano}")

    linhas = []
    for r in resultados:
        dia = r.get("day")
        if dia is None:
            continue
        for mes in range(1, 13):
            valor_str = r.get(f"rateValue{mes}")
            if not valor_str:
                continue
            try:
                data = date(ano, mes, dia)
            except ValueError:
                continue  # dia inexistente para o mês (ex.: 31 de abril)
            try:
                valor = _parse_numero_br(valor_str)
            except ValueError as e:
                raise ValueError(f"valor não numérico da B3 em {data}: {valor_str!r}") from e
            linhas.append((data, valor))

    if not linhas:
        raise ValueError(f"nenhum fechamento válido encontrado para o ano {ano}")

    out = pd.DataFrame(linhas, columns=["data", "fechamento"])
    out = out.sort_values("data", kind="stable").reset_index(drop=True)
    return out


@registrar
class B3(Coletor):
    fonte = "b3"
    descricao = "B3 — Ibovespa oficial, fechamento diário por ano (GetPortfolioDay)"
    series = (
        SerieSpec(
            id="b3_ibov",
            descricao="Ibovespa, fechamento diário oficial da B3",
            unidade="pontos",
            frequencia="D",
            colunas=("data", "fechamento"),
            chave=("data",),
            valores=("fechamento",),
            modo="acumular",
            faixa=(100.0, 1000000.0),
            max_lacuna_dias=15,
            notas=("Nível nominal da época, sem reescalonamento: o índice foi dividido por 10 em "
                   "1997-03-03 (88.287,30 → 8.978,22). O Yahoo (^BVSP) já traz o período anterior "
                   "dividido por 10. Retornos que cruzem 1997-03-03 devem ser ajustados pelo motor."),
        ),
    )

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        ano_atual = datetime.now().year
        primeira_carga = ctx.repo.ler_serie(self.spec("b3_ibov")) is None
        anos = range(PRIMEIRO_ANO, ano_atual + 1) if primeira_carga else range(ano_atual - 1, ano_atual + 1)

        out = []
        for i, ano in enumerate(anos):
            if i:
                time.sleep(PAUSA_ENTRE_REQUISICOES_S)
            url = URL.format(token=_token(ano))
            r = baixar(ctx.sessao, url)
            out.append(ArquivoBruto(r.content, "json", url=url, rotulo=f"IBOV_{ano}"))
        return out

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        partes = []
        for reg in brutos:
            ano = int(reg.rotulo.rsplit("_", 1)[1])
            partes.append(interpretar_b3_json(reg.caminho.read_bytes(), ano))
        df = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=["data", "fechamento"])
        df = df.drop_duplicates(subset=["data"], keep="last").sort_values("data", kind="stable").reset_index(drop=True)
        return {"b3_ibov": df}
