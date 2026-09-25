"""Ponto de entrada da interface Streamlit (``wacc-app``).

Executa-se com ``streamlit run principal.py`` (normalmente via o script ``wacc-app``,
que também resolve ``--bases``). Não contém regra de cálculo: só monta a navegação.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

st.set_page_config(page_title="WACC Toolkit", layout="wide")

_PAGINAS = Path(__file__).parent / "paginas"

pagina = st.navigation(
    [
        st.Page(_PAGINAS / "bases.py", title="Bases", url_path="bases"),
        st.Page(_PAGINAS / "consulta.py", title="Consulta", url_path="consulta"),
        st.Page(_PAGINAS / "novo_wacc.py", title="Novo WACC", url_path="novo-wacc"),
        st.Page(_PAGINAS / "historico.py", title="Histórico", url_path="historico"),
    ]
)
pagina.run()
