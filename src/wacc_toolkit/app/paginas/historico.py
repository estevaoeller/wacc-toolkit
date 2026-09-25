"""Página Histórico: cálculos gravados, detalhe de um cálculo e comparação entre dois."""

from __future__ import annotations

import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.app.estado import fmt_pct, formatar_valor, obter_ambiente

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
exibicao["wacc_real"] = exibicao["wacc_real"].map(lambda v: fmt_pct(v, 2))
exibicao["wacc_nominal"] = exibicao["wacc_nominal"].map(lambda v: fmt_pct(v, 2))
st.dataframe(
    exibicao[["projeto", "data_base", "gerado_em", "wacc_real", "wacc_nominal"]], width="stretch", hide_index=True,
)

st.subheader("Detalhe de um cálculo")
arquivo = st.selectbox("Cálculo", lista["arquivo"], format_func=lambda a: a,
                       key="hist_detalhe")
if arquivo:
    dados = sv.ler_calculo(amb, arquivo)
    componentes = dados.get("componentes", {})
    linhas = [{"id": k, "item": v.get("nome", k), "valor": formatar_valor(k, v.get("valor")),
              "descrição": v.get("rotulo", "")} for k, v in componentes.items()]
    st.dataframe(linhas, width="stretch", hide_index=True)
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
        tabela.style.apply(_destacar_maior_variacao, axis=1).format({"Diferença (p.b.)": "{:+.2f}"}),
        width="stretch", hide_index=True,
    )
