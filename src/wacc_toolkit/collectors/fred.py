"""FRED (Federal Reserve Bank of St. Louis): Treasury nominal e TIPS de 10 anos.

Implementação de referência do contrato de coletor.

Séries (valores em % a.a., como publicados):
- DGS10  diária   Treasury 10 anos nominal (constant maturity)
- GS10   mensal   média mensal do DGS10 (equivale ao H.15 RIFLGFCY10_N.M)
- DFII10 diária   TIPS 10 anos (real)
- FII10  mensal   média mensal do DFII10
- T10YIE diária   breakeven 10 anos (DGS10 − DFII10), calculado pelo FRED

Endpoint público, sem chave: https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>
"""

from __future__ import annotations

import io

import pandas as pd

from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"

_SERIES = {
    "DGS10": ("fred_dgs10", "Treasury 10 anos nominal, diária", "D", (-2.0, 25.0), 10),
    "GS10": ("fred_gs10", "Treasury 10 anos nominal, média mensal", "M", (-2.0, 25.0), 32),
    "DFII10": ("fred_dfii10", "TIPS 10 anos (real), diária", "D", (-5.0, 10.0), 10),
    "FII10": ("fred_fii10", "TIPS 10 anos (real), média mensal", "M", (-5.0, 10.0), 32),
    "T10YIE": ("fred_t10yie", "Inflação implícita 10 anos (breakeven), diária", "D", (-5.0, 10.0), 10),
}


def interpretar_csv(conteudo: bytes, codigo: str) -> pd.DataFrame:
    """CSV do FRED: colunas ``observation_date`` (ou ``DATE``) e ``<codigo>``.
    Dias sem cotação vêm vazios ou como '.'; são descartados."""
    df = pd.read_csv(io.BytesIO(conteudo), na_values=["."])
    col_data = "observation_date" if "observation_date" in df.columns else df.columns[0]
    if codigo not in df.columns:
        raise ValueError(f"coluna {codigo} ausente no CSV do FRED (colunas: {list(df.columns)})")
    out = pd.DataFrame({"data": pd.to_datetime(df[col_data]).dt.date,
                        "valor": pd.to_numeric(df[codigo], errors="coerce")})
    return out.dropna(subset=["valor"]).reset_index(drop=True)


@registrar
class FRED(Coletor):
    fonte = "fred"
    descricao = "FRED: Treasury 10a nominal e TIPS 10a (diárias e médias mensais)"
    series = tuple(
        SerieSpec(id=sid, descricao=desc, unidade="% a.a.", frequencia=freq, faixa=faixa,
                  max_lacuna_dias=lac, extras={"codigo_fred": cod})
        for cod, (sid, desc, freq, faixa, lac) in _SERIES.items()
    )

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        out = []
        for codigo in _SERIES:
            url = URL.format(id=codigo)
            r = baixar(ctx.sessao, url)
            out.append(ArquivoBruto(r.content, "csv", url=url, rotulo=codigo))
        return out

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        saida = {}
        for reg in brutos:
            sid = _SERIES[reg.rotulo][0]
            saida[sid] = interpretar_csv(reg.caminho.read_bytes(), reg.rotulo)
        return saida
