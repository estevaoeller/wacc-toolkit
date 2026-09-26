"""Página Consulta: exploração de uma série tratada, com gráfico, tabela e download.

Por padrão mostra só os últimos 2 anos (a leitura em si é cacheada por
``wacc_toolkit.app.estado.ler_serie_cacheada``, então reabrir a página ou trocar o período
não relê o CSV da base a cada clique)."""

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
    grafico_linha,
    ler_serie_cacheada,
    obter_ambiente,
)

LINHAS_TABELA_MAX = 1000
ATALHOS_PERIODO = {
    "6 meses": pd.DateOffset(months=6), "1 ano": pd.DateOffset(years=1), "2 anos": pd.DateOffset(years=2),
    "5 anos": pd.DateOffset(years=5), "10 anos": pd.DateOffset(years=10), "Tudo": None,
}
PERIODO_PADRAO = "2 anos"

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
    df, meta = ler_serie_cacheada(amb, serie, versao)
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
    minimo, maximo = df["data"].min(), df["data"].max()
    if isinstance(minimo, str):
        minimo, maximo = date.fromisoformat(minimo), date.fromisoformat(maximo)

    with st.expander("Opções", expanded=False):
        chave_atalho, chave_intervalo = f"consulta_atalho_{serie}", f"consulta_intervalo_{serie}"
        chave_atalho_anterior = f"{chave_atalho}_anterior"
        atalho = st.radio("Período", list(ATALHOS_PERIODO), index=list(ATALHOS_PERIODO).index(PERIODO_PADRAO),
                          horizontal=True, key=chave_atalho)
        deslocamento = ATALHOS_PERIODO[atalho]
        inicio_padrao = minimo if deslocamento is None else max(minimo, (pd.Timestamp(maximo) - deslocamento).date())
        if st.session_state.get(chave_atalho_anterior) != atalho:
            # o atalho mudou: substitui o intervalo personalizado pelo novo padrão (senão o
            # date_input manteria o valor anterior, ignorando o atalho escolhido)
            st.session_state[chave_intervalo] = (inicio_padrao, maximo)
            st.session_state[chave_atalho_anterior] = atalho
        inicio, fim = st.date_input("Intervalo personalizado", min_value=minimo, max_value=maximo,
                                    format=FORMATO_DATA, key=chave_intervalo)
        numericas = [c for c in df.columns if c != "data" and pd.api.types.is_numeric_dtype(df[c])]
        coluna = st.selectbox("Coluna do gráfico", numericas, index=0) if numericas else None

    recorte = df[(pd.to_datetime(df["data"]) >= pd.Timestamp(inicio)) & (pd.to_datetime(df["data"]) <= pd.Timestamp(fim))]

    st.subheader("Período")
    st.caption(f"{fmt_data_pt(inicio)} a {fmt_data_pt(fim)} ({len(recorte)} linhas)")
    if coluna:
        st.altair_chart(grafico_linha(recorte, y=coluna, titulo_y=coluna), use_container_width=True)

    tabela = recorte
    if len(tabela) > LINHAS_TABELA_MAX:
        st.caption(f"Mostrando as últimas {LINHAS_TABELA_MAX} de {len(tabela)} linhas do período "
                  f"(o download abaixo traz o período inteiro).")
        tabela = tabela.tail(LINHAS_TABELA_MAX)
    st.dataframe(formatar_df_numerico_pt(tabela, exceto=("data",)), width="stretch", hide_index=True)
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
