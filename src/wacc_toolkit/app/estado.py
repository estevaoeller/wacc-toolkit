"""Utilidades compartilhadas pelas páginas da interface Streamlit.

Só orquestra chamadas a :mod:`wacc_toolkit.servicos` e formata valores para exibição;
nenhuma regra de cálculo, validação ou gravação vive aqui.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.config import ConfiguracaoAusente

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


# ------------------------------------------------------------------ formatação
def fmt_pct(valor, casas: int = 2) -> str:
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    return f"{valor * 100:.{casas}f}%"


def fmt_num(valor, casas: int = 2) -> str:
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    return f"{valor:.{casas}f}"


# id do componente -> ("pct" | "num", casas decimais)
FORMATOS_COMPONENTE: dict[str, tuple[str, int]] = {
    "beta_u": ("num", 2),
    "beta_l": ("num", 3),
    "d_v": ("pct", 1),
    "t": ("pct", 1),
}


def formatar_valor(id_componente: str, valor: float) -> str:
    tipo, casas = FORMATOS_COMPONENTE.get(id_componente, ("pct", 2))
    return fmt_num(valor, casas) if tipo == "num" else fmt_pct(valor, casas)


def csv_excel_br(df: pd.DataFrame) -> bytes:
    """CSV com separador ';' e decimal ',', para abrir direto no Excel em pt-BR."""
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
