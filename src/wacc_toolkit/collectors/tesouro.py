"""Tesouro Transparente (CKAN): Taxas dos títulos ofertados pelo Tesouro Direto.

Série (painel único, todos os títulos; o filtro de NTN-B/IPCA+ é do motor de cálculo):
- tesouro_td_taxas  diária  taxas de compra/venda e PUs de todos os títulos do Tesouro Direto

Endpoint público, sem chave, histórico completo (~170 mil linhas, ~14 MB):
https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/
resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv

Layout do CSV (verificado em 2026-09-25 baixando o arquivo real):
- separador ``;``, decimal ``,``, sem separador de milhar;
- encoding ASCII puro (subconjunto de UTF-8 e latin-1: os nomes dos títulos não têm
  acento: "Educa+", "IPCA+", "IGPM+", "Prefixado", "Selic", "Renda+ Aposentadoria Extra");
- colunas: ``Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;
  PU Compra Manha;PU Venda Manha;PU Base Manha``;
- datas em ``dd/mm/aaaa``;
- ~176 mil linhas, ``Data Base`` de 2004-12-31 até a data da coleta.

Faixa das taxas: no histórico completo (baixado em 2026-09-25) a Taxa Compra Manha varia
de -3,53 a 20,10 e a Taxa Venda Manha de -3,41 a 20,13 (% a.a.). Taxas negativas são reais
e legítimas: ocorrem sobretudo na Tesouro Selic em janelas de juros básicos muito baixos
(ágio sobre a Selic). Não há valores vazios/nulos nessas colunas no arquivo completo.
A faixa (-5, 40) do contrato dá margem confortável sem deixar de capturar erro grosseiro
de parsing (ex.: vírgula decimal virando 457 em vez de 4,57).

Duplicatas na chave (data, titulo, vencimento): investigado no arquivo completo (176622
linhas, baixado em 2026-09-25): não há nenhuma linha duplicada nessa chave hoje. Como o
CKAN pode publicar uma nova versão do CSV com registros corrigidos/repetidos em outra
coleta futura, tratamos isso de forma determinística mesmo assim: ordenamos pela ordem
original do arquivo e, ao encontrar chave repetida, mantemos a ÚLTIMA ocorrência (a mais
recente na ordem de publicação do CSV), via ``drop_duplicates(keep="last")`` antes de
qualquer outra transformação.
"""

from __future__ import annotations

import io

import pandas as pd

from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)

_COLUNAS_FONTE = (
    "Tipo Titulo",
    "Data Vencimento",
    "Data Base",
    "Taxa Compra Manha",
    "Taxa Venda Manha",
    "PU Compra Manha",
    "PU Venda Manha",
    "PU Base Manha",
)

_COLUNAS = ("data", "titulo", "vencimento", "taxa_compra", "taxa_venda", "pu_compra", "pu_venda", "pu_base")
_CHAVE = ("data", "titulo", "vencimento")


def interpretar_csv(conteudo: bytes) -> pd.DataFrame:
    """CSV do Tesouro Transparente: separador ``;``, decimal ``,``, datas ``dd/mm/aaaa``.

    Trata BOM e ambos os encodings comuns (utf-8/latin-1); os nomes dos títulos são
    ASCII puro, então qualquer um dos dois decodifica corretamente.
    """
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1")

    df = pd.read_csv(io.StringIO(texto), sep=";", decimal=",", dtype=str)

    faltando = [c for c in _COLUNAS_FONTE if c not in df.columns]
    if faltando:
        raise ValueError(f"tesouro_td_taxas: colunas ausentes no CSV do Tesouro ({faltando}); "
                          f"colunas encontradas: {list(df.columns)}")

    out = pd.DataFrame({
        "data": pd.to_datetime(df["Data Base"], format="%d/%m/%Y", errors="coerce"),
        "titulo": df["Tipo Titulo"].str.strip(),
        "vencimento": pd.to_datetime(df["Data Vencimento"], format="%d/%m/%Y", errors="coerce"),
        "taxa_compra": pd.to_numeric(df["Taxa Compra Manha"].str.replace(",", ".", regex=False),
                                      errors="coerce"),
        "taxa_venda": pd.to_numeric(df["Taxa Venda Manha"].str.replace(",", ".", regex=False),
                                     errors="coerce"),
        "pu_compra": pd.to_numeric(df["PU Compra Manha"].str.replace(",", ".", regex=False),
                                    errors="coerce"),
        "pu_venda": pd.to_numeric(df["PU Venda Manha"].str.replace(",", ".", regex=False),
                                   errors="coerce"),
        "pu_base": pd.to_numeric(df["PU Base Manha"].str.replace(",", ".", regex=False),
                                  errors="coerce"),
    })

    if out["data"].isna().any() or out["vencimento"].isna().any():
        raise ValueError("tesouro_td_taxas: datas fora do formato dd/mm/aaaa esperado")

    out["data"] = out["data"].dt.date
    out["vencimento"] = out["vencimento"].dt.strftime("%Y-%m-%d")

    # Duplicatas na chave (data, titulo, vencimento): mantém a última ocorrência na ordem
    # original do CSV (ver docstring do módulo).
    out = out.drop_duplicates(subset=list(_CHAVE), keep="last").reset_index(drop=True)

    return out.loc[:, list(_COLUNAS)]


@registrar
class Tesouro(Coletor):
    fonte = "tesouro"
    descricao = "Tesouro Transparente: taxas e PUs de todos os títulos do Tesouro Direto"
    series = (
        SerieSpec(
            id="tesouro_td_taxas",
            descricao="Taxas de compra/venda e PUs diários de todos os títulos do Tesouro Direto",
            unidade="% a.a. (taxas) / R$ (PU)",
            frequencia="D",
            colunas=_COLUNAS,
            chave=_CHAVE,
            valores=("taxa_compra", "taxa_venda"),
            modo="substituir",
            faixa=(-5.0, 40.0),
            max_lacuna_dias=15,
            notas=(
                "Painel com todos os títulos (Selic, Prefixado, IPCA+, IGPM+, Educa+, "
                "Renda+ etc.); o filtro de NTN-B/IPCA+ para o cálculo do WACC é feito pelo "
                "motor de cálculo, não pelo coletor. Duplicatas na chave "
                "(data, titulo, vencimento), se existirem, são resolvidas mantendo a última "
                "ocorrência na ordem original do CSV publicado."
            ),
        ),
    )

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        r = baixar(ctx.sessao, URL)
        return [ArquivoBruto(r.content, "csv", url=URL, rotulo="precotaxatesourodireto")]

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        reg = brutos[0]
        return {"tesouro_td_taxas": interpretar_csv(reg.caminho.read_bytes())}
