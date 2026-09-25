"""BCB (Banco Central do Brasil): TLP e Focus.

Implementação do contrato de coletor para séries do Banco Central do Brasil.

Séries (valores em % a.a., como publicados):
- bcb_tlp: TLP: Taxa de Longo Prazo, série SGS 27572 (mensal)
- bcb_focus_ipca_anual: Focus: Expectativas de IPCA (mediana anual)

Endpoint públicos, sem chave:
- TLP: https://api.bcb.gov.br/dados/serie/bcdata.sgs.27572/dados?formato=json
- Focus: https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais
"""

from __future__ import annotations

import io
import json

import pandas as pd

from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

URL_TLP = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.27572/dados?formato=json"
URL_FOCUS = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoAnuais?$filter=Indicador%20eq%20'IPCA'&$format=json&"
    "$select=Indicador,Data,DataReferencia,Media,Mediana,DesvioPadrao,Minimo,Maximo,"
    "numeroRespondentes,baseCalculo"
)


def interpretar_tlp(conteudo: bytes) -> pd.DataFrame:
    """Parse JSON da TLP.

    Formato: [{"data":"01/01/2018","valor":"4.74"}, ...]
    - data: string dd/mm/aaaa
    - valor: string com número decimal (ponto como separador)
    """
    dados = json.loads(conteudo)
    df = pd.DataFrame(dados)

    # Converter data de dd/mm/aaaa para datetime
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y").dt.date

    # Converter valor para float
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Descartar linhas com valor NaN
    out = df[["data", "valor"]].dropna(subset=["valor"]).reset_index(drop=True)

    return out


def interpretar_focus(conteudo: bytes) -> pd.DataFrame:
    """Parse JSON do Focus: Expectativas de IPCA anual.

    Formato: {"value": [{"Indicador":"IPCA","Data":"2018-01-22","DataReferencia":"2019", ...}, ...]}

    Colunas de saída:
    - data: Data de coleta (ISO format)
    - ano_referencia: DataReferencia como inteiro
    - base_calculo: baseCalculo (0 = últimos 30 dias, 1 = últimos 5 dias úteis)
    - mediana: Mediana (float)
    - media: Media (float)
    - desvio_padrao: DesvioPadrao (float)
    - minimo: Minimo (float)
    - maximo: Maximo (float)
    - respondentes: numeroRespondentes (int)
    """
    dados_json = json.loads(conteudo)
    items = dados_json.get("value", [])

    df = pd.DataFrame(items)

    # Converter Data (ISO) para date
    df["data"] = pd.to_datetime(df["Data"]).dt.date

    # Converter DataReferencia (string) para int
    df["ano_referencia"] = df["DataReferencia"].astype(int)

    # Renomear e manter colunas necessárias
    df_out = pd.DataFrame({
        "data": df["data"],
        "ano_referencia": df["ano_referencia"],
        "base_calculo": df["baseCalculo"].astype(int),
        "mediana": pd.to_numeric(df["Mediana"], errors="coerce"),
        "media": pd.to_numeric(df["Media"], errors="coerce"),
        "desvio_padrao": pd.to_numeric(df["DesvioPadrao"], errors="coerce"),
        "minimo": pd.to_numeric(df["Minimo"], errors="coerce"),
        "maximo": pd.to_numeric(df["Maximo"], errors="coerce"),
        "respondentes": pd.to_numeric(df["numeroRespondentes"], errors="coerce").astype("Int64"),
    })

    # Descartar linhas com NaN em colunas críticas
    df_out = df_out.dropna(subset=["data", "ano_referencia", "base_calculo", "mediana"]).reset_index(drop=True)

    return df_out


@registrar
class BCB(Coletor):
    fonte = "bcb"
    descricao = "BCB: TLP (Taxa de Longo Prazo) e Focus (Expectativas de IPCA)"
    series = (
        SerieSpec(
            id="bcb_tlp",
            descricao="TLP: Taxa de Longo Prazo para cálculo da TNLP (série SGS 27572), mensal",
            unidade="% a.a.",
            frequencia="M",
            faixa=(0.0, 30.0),
            max_lacuna_dias=35,
        ),
        SerieSpec(
            id="bcb_focus_ipca_anual",
            descricao="Focus: Expectativas de IPCA para o ano (mediana), por data de coleta",
            unidade="% a.a.",
            frequencia="D",  # diária, pois há múltiplos registros por data (por ano_referencia e base_calculo)
            colunas=("data", "ano_referencia", "base_calculo", "mediana", "media",
                    "desvio_padrao", "minimo", "maximo", "respondentes"),
            chave=("data", "ano_referencia", "base_calculo"),
            valores=("mediana", "media", "desvio_padrao", "minimo", "maximo"),
            faixa=(-5.0, 50.0),
            max_lacuna_dias=None,
            notas=("baseCalculo: 0 = expectativas informadas nos últimos 30 dias; 1 = nos últimos "
                   "5 dias úteis (conferido pelo nº de respondentes: base 1 ≈ metade da base 0). "
                   "A Metodologia do Tesouro (gross-up das debêntures) usa a base 1."),
            extras={"origem": "Olinda BCB"},
        ),
    )

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        out = []

        # TLP
        r_tlp = baixar(ctx.sessao, URL_TLP)
        out.append(ArquivoBruto(r_tlp.content, "json", url=URL_TLP, rotulo="tlp"))

        # Focus
        r_focus = baixar(ctx.sessao, URL_FOCUS)
        out.append(ArquivoBruto(r_focus.content, "json", url=URL_FOCUS, rotulo="focus_ipca_anual"))

        return out

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        saida = {}

        for reg in brutos:
            conteudo = reg.caminho.read_bytes()

            if reg.rotulo == "tlp":
                saida["bcb_tlp"] = interpretar_tlp(conteudo)
            elif reg.rotulo == "focus_ipca_anual":
                saida["bcb_focus_ipca_anual"] = interpretar_focus(conteudo)

        return saida
