"""Página Painel: últimos cálculos por projeto e as variáveis mais relevantes de mercado."""

from __future__ import annotations

import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.app.estado import (
    fmt_data_pt,
    fmt_mes_ano_pt,
    fmt_num_sinal_pt,
    fmt_pct,
    grafico_linha,
    indicadores_painel_cacheados,
    obter_ambiente,
)

COLUNAS_POR_LINHA = 3


def _bloco(rotulo: str, valor: str, variacao: str | None = None) -> str:
    """Valor em destaque que quebra linha em colunas estreitas (st.metric corta o texto)."""
    html = (f"<div style='font-size:0.85rem;opacity:0.75'>{rotulo}</div>"
            f"<div style='font-size:1.6rem;font-weight:600;line-height:1.2;overflow-wrap:anywhere'>{valor}</div>")
    if variacao:
        seta = "▲" if variacao.lstrip().startswith("+") else "▼" if variacao.lstrip().startswith("-") else ""
        html += f"<div style='font-size:0.85rem;opacity:0.85'>{seta} {variacao}</div>"
    return html


st.title("Painel")

amb = obter_ambiente()
if amb is None:
    st.stop()

# ------------------------------------------------------------------ últimos cálculos por projeto
st.subheader("Últimos cálculos por projeto")
ultimos = sv.ultimos_calculos_por_projeto(amb)
if ultimos.empty:
    st.info("Nenhum cálculo gravado ainda. Vá à página Novo WACC.")
else:
    for _, linha in ultimos.iterrows():
        c1, c2, c3 = st.columns([2, 1, 1])
        c1.markdown(f"**{linha['projeto']}**  \nData-base: {fmt_mes_ano_pt(linha['data_base'])}")
        c2.markdown(_bloco("WACC real", fmt_pct(linha["wacc_real"], 2)), unsafe_allow_html=True)
        c3.markdown(_bloco("WACC nominal", fmt_pct(linha["wacc_nominal"], 2)), unsafe_allow_html=True)

st.divider()

# ------------------------------------------------------------------ indicadores de mercado
st.subheader("Indicadores")


def _fmt_valor(item: dict) -> str:
    if item["ultimo_valor"] is None:
        return "-"
    numero = sv.formatar_numero_pt(item["ultimo_valor"], 2)
    return f"{numero}{item['unidade']}" if item["unidade"].startswith("%") else f"{numero} {item['unidade']}"


def _fmt_variacao(item: dict) -> str | None:
    if item["variacao"] is None:
        return None
    if item["tipo_variacao"] == "pb":
        return f"{fmt_num_sinal_pt(item['variacao'], 0)} p.b. em 12 meses"
    return f"{fmt_num_sinal_pt(item['variacao'], 2)}% em 12 meses"


indicadores = indicadores_painel_cacheados(amb, meses=24)
colunas = st.columns(COLUNAS_POR_LINHA)
for i, item in enumerate(indicadores):
    with colunas[i % COLUNAS_POR_LINHA].container(border=True):
        if item["status"] != "ok":
            st.markdown(f"**{item['nome']}**")
            st.caption("Sem dados nas bases.")
            continue
        st.markdown(_bloco(item["nome"], _fmt_valor(item), _fmt_variacao(item)), unsafe_allow_html=True)
        st.caption(f"Fonte: {item['fonte']} - {fmt_data_pt(item['data_ultimo'])}")
        if not item["serie"].empty:
            st.altair_chart(grafico_linha(item["serie"], altura=130), use_container_width=True)
