"""Página Consulta: exploração de uma série tratada, com gráfico, tabela e download."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.app.estado import (
    FORMATO_DATA,
    csv_excel_br,
    fmt_data_pt,
    formatar_df_numerico_pt,
    obter_ambiente,
)

st.title("Consulta")

amb = obter_ambiente()
if amb is None:
    st.stop()

status = sv.status_bases(amb)
if status.empty:
    st.info("Nenhuma fonte cadastrada.")
    st.stop()

fontes_amigaveis = {f["fonte"]: f["descricao"] for f in sv.fontes()}
fonte_ids = sorted(status["fonte"].unique())
fonte_escolhida = st.selectbox("Fonte", fonte_ids, format_func=lambda f: fontes_amigaveis.get(f, f))

series_da_fonte = status.loc[status["fonte"] == fonte_escolhida, ["serie", "descricao"]].set_index("serie")
serie = st.selectbox("Série", list(series_da_fonte.index),
                     format_func=lambda s: series_da_fonte.loc[s, "descricao"])

versoes = sv.versoes(amb, serie)
versao = None
if versoes:
    versao = st.selectbox("Versão", versoes, index=len(versoes) - 1)

try:
    df, meta = sv.ler_serie(amb, serie, versao)
except FileNotFoundError as e:
    st.error(str(e))
    st.stop()

st.subheader("Metadados")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Linhas", meta.get("linhas", len(df)))
c2.markdown(f"**Início**\n\n{fmt_data_pt(meta.get('inicio'))}")
c3.markdown(f"**Fim**\n\n{fmt_data_pt(meta.get('fim'))}")
c4.markdown(f"**Atualizado em**\n\n{fmt_data_pt(meta.get('atualizado_em'))}")
if meta.get("descricao"):
    st.caption(meta["descricao"] + (f" ({meta['unidade']})" if meta.get("unidade") else ""))
if meta.get("avisos"):
    with st.expander(f"{len(meta['avisos'])} aviso(s)"):
        for a in meta["avisos"]:
            st.warning(a)

recorte = df
if "data" in df.columns:
    st.subheader("Período")
    minimo, maximo = df["data"].min(), df["data"].max()
    if isinstance(minimo, str):
        minimo, maximo = date.fromisoformat(minimo), date.fromisoformat(maximo)
    inicio, fim = st.date_input("Intervalo", value=(minimo, maximo), min_value=minimo, max_value=maximo,
                                format=FORMATO_DATA)
    recorte = df[(pd.to_datetime(df["data"]) >= pd.Timestamp(inicio)) & (pd.to_datetime(df["data"]) <= pd.Timestamp(fim))]

    numericas = [c for c in recorte.columns if c != "data" and pd.api.types.is_numeric_dtype(recorte[c])]
    if numericas:
        coluna = st.selectbox("Coluna do gráfico", numericas, index=0)
        st.line_chart(recorte.set_index("data")[coluna])
    st.dataframe(formatar_df_numerico_pt(recorte, exceto=("data",)), width="stretch", hide_index=True)
else:
    st.subheader("Tabela")
    busca = st.text_input("Buscar (texto em qualquer coluna)")
    if busca:
        colunas_texto = recorte.select_dtypes(include="object").columns
        mascara = pd.Series(False, index=recorte.index)
        for c in colunas_texto:
            mascara |= recorte[c].astype(str).str.contains(busca, case=False, na=False)
        recorte = recorte[mascara]
    st.dataframe(formatar_df_numerico_pt(recorte), width="stretch", hide_index=True)

st.download_button(
    "Baixar CSV (Excel, pt-BR)",
    data=csv_excel_br(recorte),
    file_name=f"{serie}{'_' + versao if versao else ''}.csv",
    mime="text/csv",
)
