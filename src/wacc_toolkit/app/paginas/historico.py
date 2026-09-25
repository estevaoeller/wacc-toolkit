"""Página Histórico: cálculos gravados, detalhe de um cálculo e comparação entre dois."""

from __future__ import annotations

import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.app.estado import (
    fmt_datahora_local_pt,
    fmt_mes_ano_pt,
    fmt_num_sinal_pt,
    fmt_pct,
    obter_ambiente,
)

st.title("Histórico")

amb = obter_ambiente()
if amb is None:
    st.stop()

lista = sv.listar_calculos(amb)
if lista.empty:
    st.info("Nenhum cálculo gravado ainda.")
    st.stop()

st.subheader("Cálculos")
exibicao = lista.copy()
exibicao["data_base"] = exibicao["data_base"].map(fmt_mes_ano_pt)
exibicao["gerado_em"] = exibicao["gerado_em"].map(fmt_datahora_local_pt)
exibicao["wacc_real"] = exibicao["wacc_real"].map(lambda v: fmt_pct(v, 2))
exibicao["wacc_nominal"] = exibicao["wacc_nominal"].map(lambda v: fmt_pct(v, 2))
st.dataframe(
    exibicao[["projeto", "data_base", "gerado_em", "wacc_real", "wacc_nominal"]]
    .rename(columns={"projeto": "Projeto", "data_base": "Data-base", "gerado_em": "Gerado em",
                     "wacc_real": "WACC real", "wacc_nominal": "WACC nominal"}),
    width="stretch", hide_index=True,
)

st.subheader("Detalhe de um cálculo")
arquivo = st.selectbox("Cálculo", lista["arquivo"], format_func=lambda a: a,
                       key="hist_detalhe")
if arquivo:
    dados = sv.ler_calculo(amb, arquivo)
    cfg = dados.get("config", {})
    st.caption(f"{cfg.get('projeto', '')} - data-base {fmt_mes_ano_pt(cfg.get('data_base'))} "
              f"- gerado em {fmt_datahora_local_pt(dados.get('gerado_em'))}")
    tabela = sv.tabela_custo_de_capital_de_registro(dados)
    for secao in ("KE", "KD", "WACC"):
        st.markdown(f"**{secao}**")
        linhas = tabela.loc[tabela["secao"] == secao, ["item", "valor", "descricao"]]
        st.dataframe(linhas.rename(columns={"item": "Item", "valor": "Valor", "descricao": "Descrição"}),
                    width="stretch", hide_index=True)
    excel = amb.calculos / arquivo
    excel = excel.with_suffix(".xlsx")
    if excel.exists():
        st.download_button("Baixar Excel", data=excel.read_bytes(), file_name=excel.name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    else:
        st.caption("Sem Excel gravado para este cálculo.")

st.subheader("Comparar dois cálculos")
c1, c2 = st.columns(2)
arquivos = list(lista["arquivo"])
a = c1.selectbox("Cálculo A", arquivos, index=0 if arquivos else None, key="hist_a")
b = c2.selectbox("Cálculo B", arquivos, index=min(1, len(arquivos) - 1) if arquivos else None, key="hist_b")
if a and b:
    comp = sv.comparar_calculos(amb, a, b)
    comp = comp.rename(columns={"item": "Item", "a": "A", "b": "B", "dif_bp": "Diferença (p.b.)"})
    comp["A"] = comp["A"].map(lambda v: fmt_pct(v, 2))
    comp["B"] = comp["B"].map(lambda v: fmt_pct(v, 2))
    tabela = comp[["Item", "A", "B", "Diferença (p.b.)"]]
    maior = comp["Diferença (p.b.)"].abs().max()

    def _destacar_maior_variacao(linha):
        cor = "background-color: #4d2020" if maior and abs(linha["Diferença (p.b.)"]) >= maior * 0.5 else ""
        return [cor] * len(linha)

    st.dataframe(
        tabela.style.apply(_destacar_maior_variacao, axis=1).format({"Diferença (p.b.)": fmt_num_sinal_pt}),
        width="stretch", hide_index=True,
    )
