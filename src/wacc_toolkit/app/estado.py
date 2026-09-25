"""Utilidades compartilhadas pelas páginas da interface Streamlit.

Só orquestra chamadas a :mod:`wacc_toolkit.servicos` e formata valores para exibição;
nenhuma regra de cálculo, validação ou gravação vive aqui.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.config import ConfiguracaoAusente

FORMATO_DATA = "DD/MM/YYYY"  # usado em todo st.date_input da interface

# ------------------------------------------------------------------ ambiente
def obter_ambiente() -> sv.Ambiente | None:
    """Devolve o ambiente (pastas de bases/projetos/cálculos), com cache em ``session_state``.

    Mostra um erro e devolve ``None`` se as bases não estiverem configuradas.
    """
    if "amb" in st.session_state:
        return st.session_state.amb
    try:
        amb = sv.ambiente()
    except ConfiguracaoAusente as e:
        st.error(str(e))
        return None
    st.session_state.amb = amb
    return amb


# ------------------------------------------------------------------ formatação de números (pt-BR)
# a formatação em si (vírgula decimal) é regra de apresentação pura, sem cálculo: delega para
# wacc_toolkit.servicos, que é quem também formata a tabela Custo de Capital.
def fmt_pct(valor, casas: int = 2) -> str:
    return sv.formatar_percentual_pt(valor, casas) or "-"


def fmt_num(valor, casas: int = 2) -> str:
    return sv.formatar_numero_pt(valor, casas) or "-"


def formatar_valor(id_componente: str, valor: float) -> str:
    return sv.formatar_valor_componente(id_componente, valor) or "-"


def fmt_num_sinal_pt(valor, casas: int = 2) -> str:
    """Número com sinal explícito e vírgula decimal (ex.: +12,34 / -5,00), para diferenças."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    sinal = "+" if valor >= 0 else "-"
    return f"{sinal}{fmt_num(abs(valor), casas)}"


def formatar_df_numerico_pt(df: pd.DataFrame, casas: int = 2, exceto: tuple[str, ...] = ()) -> pd.DataFrame:
    """Cópia de ``df`` com as colunas numéricas (exceto as em ``exceto``) formatadas em pt-BR,
    para exibição em ``st.dataframe`` (a tabela original, para gráfico/download, não é alterada)."""
    saida = df.copy()
    for col in saida.columns:
        if col in exceto or not pd.api.types.is_numeric_dtype(saida[col]):
            continue
        inteira = pd.api.types.is_integer_dtype(saida[col])
        saida[col] = saida[col].map(lambda v: fmt_num(v, 0 if inteira else casas))
    return saida


# ------------------------------------------------------------------ formatação de datas (pt-BR)
def fmt_data_pt(valor) -> str:
    """Data como dd/mm/aaaa. Aceita ``date``/``datetime``/``Timestamp`` ou string ISO."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    if isinstance(valor, str):
        if not valor:
            return "-"
        valor = date.fromisoformat(valor[:10])
    return f"{valor.day:02d}/{valor.month:02d}/{valor.year:04d}"


def fmt_mes_ano_pt(valor) -> str:
    """Data-base como mm/aaaa. Aceita ``date`` ou string ISO ('AAAA-MM-DD')."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    if isinstance(valor, str):
        if not valor:
            return "-"
        valor = date.fromisoformat(valor[:10])
    return f"{valor.month:02d}/{valor.year:04d}"


def fmt_datahora_local_pt(iso_utc: str | None) -> str:
    """Um "gerado_em" UTC ISO (``ResultadoWACC``/registro) como dd/mm/aaaa hh:mm no horário local."""
    if not iso_utc:
        return "-"
    dt = datetime.fromisoformat(iso_utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    return f"{local.day:02d}/{local.month:02d}/{local.year:04d} {local.hour:02d}:{local.minute:02d}"


def csv_excel_br(df: pd.DataFrame) -> bytes:
    """CSV com separador ';' e decimal ',', para abrir direto no Excel em pt-BR."""
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
