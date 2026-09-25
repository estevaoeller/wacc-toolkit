"""Página Bases: status das séries, atualização automática e fontes manuais."""

from __future__ import annotations

import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.app.estado import obter_ambiente

st.title("Bases")

amb = obter_ambiente()
if amb is None:
    st.stop()

st.caption(f"Diretório das bases: {amb.bases}")

# ------------------------------------------------------------------ status
st.subheader("Status das séries")
status = sv.status_bases(amb)
if status.empty:
    st.info("Nenhuma fonte cadastrada.")
else:
    sem_dados = status["linhas"].fillna(0) == 0

    def _destacar_sem_dados(linha):
        return ["background-color: #4d2020" if sem_dados.loc[linha.name] else "" for _ in linha]

    st.dataframe(status.style.apply(_destacar_sem_dados, axis=1), width="stretch")
    if sem_dados.any():
        st.warning(f"{int(sem_dados.sum())} série(s) sem dados (destacadas acima).")

# ------------------------------------------------------------------ atualização automática
st.subheader("Atualizar bases automáticas")
col1, col2 = st.columns([1, 2])
with col1:
    if st.button("Atualizar bases automáticas", width="stretch"):
        with st.spinner("Coletando..."):
            resultados = sv.atualizar(amb)
        for r in resultados:
            titulo = f"{r.fonte}: {r.status}" + (f" — {r.erro}" if r.erro else "")
            (st.success if r.status in ("ok", "sem_novidade") else st.error)(titulo)
            for s in r.series:
                v = f" v{s.versao}" if s.versao else ""
                linha = f"　{s.serie}{v}: {s.status}, {s.linhas} linhas, fim {s.fim}"
                st.write(linha)
                for p in s.problemas:
                    st.caption(str(p))

with col2:
    automaticas = [f["fonte"] for f in sv.fontes() if not f["manual"]]
    alvo = st.selectbox("Atualizar uma fonte específica", automaticas, index=None,
                        placeholder="escolha uma fonte")
    if alvo and st.button(f"Atualizar '{alvo}'"):
        with st.spinner(f"Coletando {alvo}..."):
            [resultado] = sv.atualizar(amb, [alvo])
        titulo = f"{resultado.fonte}: {resultado.status}" + (f" — {resultado.erro}" if resultado.erro else "")
        (st.success if resultado.status in ("ok", "sem_novidade") else st.error)(titulo)
        for s in resultado.series:
            st.write(f"　{s.serie}: {s.status}, {s.linhas} linhas, fim {s.fim}")
            for p in s.problemas:
                st.caption(str(p))

# ------------------------------------------------------------------ fontes manuais
st.subheader("Fontes manuais")

st.markdown("**Investing.com (CDS Brasil 10 anos)**")
st.markdown(
    "Abra https://br.investing.com/rates-bonds/brazil-cds-10-years-usd-historical-data, "
    "vá em Dados Históricos, escolha o período Mensal e clique em Baixar. "
    "O nome do arquivo deve conter \"CDS\" e \"10\"."
)
arquivos_investing = st.file_uploader("Arquivos CSV do Investing.com", type=["csv"],
                                      accept_multiple_files=True, key="upload_investing")
if arquivos_investing and st.button("Importar arquivos do Investing.com"):
    pares = [(a.name, a.getvalue()) for a in arquivos_investing]
    try:
        resultado = sv.importar_arquivos(amb, "investing", pares)
    except (ValueError, FileNotFoundError) as e:
        st.error(str(e))
    else:
        (st.success if resultado.status in ("ok", "sem_novidade") else st.error)(
            f"investing: {resultado.status}" + (f" — {resultado.erro}" if resultado.erro else ""))
        for s in resultado.series:
            st.write(f"　{s.serie}: {s.status}, {s.linhas} linhas, fim {s.fim}")
            for p in s.problemas:
                st.caption(str(p))

st.markdown("**Parâmetros manuais**")
st.markdown("Envie o arquivo `parametros_manuais.toml` atualizado (IR/CSLL, remuneração BNDES etc.).")
arquivo_parametros = st.file_uploader("Arquivo parametros_manuais.toml", type=["toml"],
                                      accept_multiple_files=False, key="upload_parametros")
if arquivo_parametros and st.button("Importar parâmetros"):
    try:
        resultado = sv.importar_arquivos(amb, "parametros", [(arquivo_parametros.name, arquivo_parametros.getvalue())])
    except (ValueError, FileNotFoundError) as e:
        st.error(str(e))
    else:
        (st.success if resultado.status in ("ok", "sem_novidade") else st.error)(
            f"parametros: {resultado.status}" + (f" — {resultado.erro}" if resultado.erro else ""))
        for s in resultado.series:
            st.write(f"　{s.serie}: {s.status}, {s.linhas} linhas, fim {s.fim}")
            for p in s.problemas:
                st.caption(str(p))

st.markdown("Parâmetros vigentes:")
try:
    df_param, _ = sv.ler_serie(amb, "parametros_manuais")
    st.dataframe(df_param, width="stretch")
except FileNotFoundError:
    st.info("Ainda não há parâmetros manuais gravados.")

# ------------------------------------------------------------------ últimas falhas
st.subheader("Últimas falhas")
falhas = sv.ultimas_falhas(amb)
if falhas:
    st.table(falhas)
else:
    st.caption("Nenhuma falha registrada.")
