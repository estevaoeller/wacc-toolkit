"""Página Novo WACC: monta um ``ConfigProjeto``, salva e calcula (modo 1)."""

from __future__ import annotations

from datetime import date

import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.app.estado import FORMATO_DATA, formatar_valor, obter_ambiente

st.title("Novo WACC")

amb = obter_ambiente()
if amb is None:
    st.stop()

FASES_PADRAO = [{"setor": "", "peso": 100.0, "fase": "", "base_peso": ""}]

if "nw_fases" not in st.session_state:
    st.session_state.nw_fases = [dict(f) for f in FASES_PADRAO]
    st.session_state.nw_projeto = ""
    st.session_state.nw_data_base = date.today()
    st.session_state.nw_notas = ""
    st.session_state.nw_regiao = "global"
    st.session_state.nw_linha_bndes = None
    st.session_state.nw_spread = 0.0
    st.session_state.nw_spread_descricao = ""
    st.session_state.nw_spread_fonte = ""
    st.session_state.nw_opcoes = {}
    st.session_state.nw_ntnb = "2035-05-15"
    st.session_state.nw_ipca_anos = 10
    st.session_state.nw_carregado = None


def _carregar(cfg: sv.ConfigProjeto) -> None:
    st.session_state.nw_fases = [
        {"setor": f.setor, "peso": f.peso * 100, "fase": f.fase, "base_peso": f.base_peso} for f in cfg.fases
    ]
    # os widgets de cada fase e de opções usam chaves fixas por posição/campo; como já podem
    # existir de uma configuração anterior, é preciso sobrescrevê-las também (não só a lista),
    # senão o widget reexibe o valor antigo em vez do valor recém-carregado.
    for i, f in enumerate(cfg.fases):
        st.session_state[f"nw_fase_setor_{i}"] = f.setor
        st.session_state[f"nw_fase_peso_{i}"] = f.peso * 100
        st.session_state[f"nw_fase_fase_{i}"] = f.fase
        st.session_state[f"nw_fase_base_{i}"] = f.base_peso
    for campo in sv.CATALOGO_OPCOES:
        st.session_state[f"nw_op_{campo}"] = getattr(cfg.opcoes, campo)
    st.session_state.nw_projeto = cfg.projeto
    st.session_state.nw_data_base = cfg.data_base
    st.session_state.nw_notas = cfg.notas
    st.session_state.nw_regiao = cfg.regiao
    st.session_state.nw_linha_bndes = cfg.linha_bndes
    st.session_state.nw_linha_bndes_sel = cfg.linha_bndes
    st.session_state.nw_spread = cfg.spread_credito * 100
    st.session_state.nw_spread_descricao = cfg.spread_descricao
    st.session_state.nw_spread_fonte = cfg.spread_fonte
    st.session_state.nw_opcoes = {k: getattr(cfg.opcoes, k) for k in sv.CATALOGO_OPCOES}
    st.session_state.nw_ntnb = cfg.opcoes.ntnb_vencimento
    st.session_state.nw_ipca_anos = cfg.opcoes.ipca_anos


# ------------------------------------------------------------------ carregar projeto existente
projetos = sv.listar_projetos(amb)
escolha = st.selectbox(
    "Carregar projeto existente", [None, *projetos], format_func=lambda p: "Novo (em branco)" if p is None else p.name,
)
if escolha is not None and st.session_state.nw_carregado != str(escolha):
    try:
        _carregar(sv.carregar_projeto(escolha))
    except Exception as e:  # noqa: BLE001
        st.error(f"Não foi possível carregar {escolha.name}: {e}")
    else:
        st.session_state.nw_carregado = str(escolha)
        st.session_state.nw_nome_arquivo = escolha.stem
elif escolha is None and st.session_state.nw_carregado is not None:
    st.session_state.nw_carregado = None

# ------------------------------------------------------------------ dados gerais
c1, c2 = st.columns(2)
projeto = c1.text_input("Projeto", key="nw_projeto")
data_base = c2.date_input("Data-base", key="nw_data_base", format=FORMATO_DATA)
notas = st.text_area("Notas", key="nw_notas")
regiao = st.selectbox("Região", ["global", "emerging"], key="nw_regiao")

try:
    setores_disponiveis = sv.setores_damodaran(amb, regiao, data_base)
except Exception as e:  # noqa: BLE001
    st.warning(f"Não foi possível listar setores Damodaran para {regiao}/{data_base}: {e}")
    setores_disponiveis = []

# ------------------------------------------------------------------ fases
st.subheader("Fases")
for i, fase in enumerate(st.session_state.nw_fases):
    cols = st.columns([3, 2, 2, 2, 1])
    opcoes_setor = sorted(set(setores_disponiveis) | ({fase["setor"]} if fase["setor"] else set()))
    fase["setor"] = cols[0].selectbox(
        "Setor", opcoes_setor, index=opcoes_setor.index(fase["setor"]) if fase["setor"] in opcoes_setor else None,
        placeholder="escolha o setor", key=f"nw_fase_setor_{i}",
    )
    fase["peso"] = cols[1].number_input("Peso (%)", value=float(fase["peso"]), min_value=0.0, max_value=100.0,
                                        step=1.0, key=f"nw_fase_peso_{i}")
    fase["fase"] = cols[2].text_input("Fase", value=fase["fase"], key=f"nw_fase_fase_{i}",
                                      placeholder="ex.: construção")
    fase["base_peso"] = cols[3].text_input("Base do peso", value=fase["base_peso"], key=f"nw_fase_base_{i}",
                                           placeholder="ex.: CAPEX")
    if cols[4].button("Remover", key=f"nw_fase_remover_{i}") and len(st.session_state.nw_fases) > 1:
        st.session_state.nw_fases.pop(i)
        st.rerun()

if st.button("Adicionar fase", key="nw_botao_add_fase"):
    st.session_state.nw_fases.append({"setor": "", "peso": 0.0, "fase": "", "base_peso": ""})
    st.rerun()

soma_pesos = sum(f["peso"] for f in st.session_state.nw_fases)
pesos_ok = abs(soma_pesos - 100.0) < 1e-6
(st.success if pesos_ok else st.error)(
    f"Soma dos pesos: {sv.formatar_numero_pt(soma_pesos, 2)}%" + ("" if pesos_ok else " (deve ser 100%)"))

# ------------------------------------------------------------------ dívida (BNDES)
st.subheader("Dívida")
linhas = sv.linhas_bndes(amb)
c1, c2 = st.columns(2)
if linhas:
    ids = list(linhas)
    linha_bndes = c1.selectbox(
        "Linha BNDES", ids,
        index=ids.index(st.session_state.nw_linha_bndes) if st.session_state.nw_linha_bndes in ids else 0,
        format_func=lambda i: linhas[i], key="nw_linha_bndes_sel",
    )
else:
    c1.info("Nenhuma linha BNDES cadastrada em parâmetros manuais.")
    linha_bndes = st.session_state.nw_linha_bndes or ""
spread_pct = c2.number_input("Spread de crédito (%)", key="nw_spread", step=0.01, format="%.4f")
c3, c4 = st.columns(2)
spread_descricao = c3.text_input("Descrição do spread", key="nw_spread_descricao")
spread_fonte = c4.text_input("Fonte do spread", key="nw_spread_fonte")

# ------------------------------------------------------------------ opções
with st.expander("Opções"):
    opcoes_kw = {}
    for campo, valores in sv.CATALOGO_OPCOES.items():
        atual = st.session_state.nw_opcoes.get(campo)
        ids = list(valores)
        opcoes_kw[campo] = st.selectbox(
            sv.ROTULOS_OPCOES.get(campo, campo), ids,
            index=ids.index(atual) if atual in ids else 0,
            format_func=lambda i, valores=valores: valores[i], key=f"nw_op_{campo}",
        )
    ntnb_vencimento = st.text_input(sv.ROTULOS_OPCOES["ntnb_vencimento"], key="nw_ntnb")
    ipca_anos = st.number_input(sv.ROTULOS_OPCOES["ipca_anos"], key="nw_ipca_anos", min_value=1, step=1)
    opcoes_kw["ntnb_vencimento"] = ntnb_vencimento
    opcoes_kw["ipca_anos"] = int(ipca_anos)

# ------------------------------------------------------------------ montar configuração
cfg = None
try:
    cfg = sv.nova_config(
        projeto=projeto, data_base=data_base, notas=notas, regiao=regiao,
        fases=[{"setor": f["setor"] or "", "peso": f["peso"] / 100.0, "fase": f["fase"], "base_peso": f["base_peso"]}
               for f in st.session_state.nw_fases],
        linha_bndes=linha_bndes, spread_credito=spread_pct / 100.0,
        spread_descricao=spread_descricao, spread_fonte=spread_fonte, opcoes=opcoes_kw,
    )
except ValueError as e:
    st.error(str(e))

# ------------------------------------------------------------------ ações
st.subheader("Ações")
c1, c2 = st.columns(2)
with c1:
    nome_arquivo = st.text_input("Nome do arquivo", value=(projeto or "projeto"), key="nw_nome_arquivo")
    sobrescrever = st.checkbox("Sobrescrever se já existir", key="nw_sobrescrever")
    if st.button("Salvar projeto", disabled=cfg is None, key="nw_botao_salvar"):
        try:
            caminho = sv.salvar_projeto(amb, cfg, nome_arquivo, sobrescrever)
        except (ValueError, FileExistsError) as e:
            st.error(str(e))
        else:
            st.success(f"Projeto salvo em {caminho}")

with c2:
    calcular_desabilitado = cfg is None or not pesos_ok
    if st.button("Calcular", disabled=calcular_desabilitado, type="primary", key="nw_botao_calcular"):
        try:
            calculo = sv.calcular_projeto(amb, cfg, excel=True)
        except (ValueError, KeyError, FileNotFoundError) as e:
            st.error(f"{e}\n\nSe a mensagem indicar uma base desatualizada ou ausente, "
                     f"vá à página Bases e atualize ou importe a fonte correspondente.")
            st.session_state.pop("nw_resultado", None)
        else:
            st.session_state.nw_resultado = calculo

# ------------------------------------------------------------------ resultado
calculo = st.session_state.get("nw_resultado")
if calculo is not None:
    resultado = calculo.resultado
    st.subheader("Resultado")
    m1, m2 = st.columns(2)
    m1.metric("WACC real", formatar_valor("wacc_real", resultado["wacc_real"]))
    m2.metric("WACC nominal", formatar_valor("wacc_nominal", resultado["wacc_nominal"]))

    tabela = sv.tabela_custo_de_capital(resultado)
    for secao in ("KE", "KD", "WACC"):
        st.markdown(f"**{secao}**")
        linhas = tabela.loc[tabela["secao"] == secao, ["item", "valor", "descricao"]]
        st.dataframe(linhas.rename(columns={"item": "Item", "valor": "Valor", "descricao": "Descrição"}),
                    width="stretch", hide_index=True)

    st.caption(f"Registro: {calculo.registro}")
    if calculo.excel:
        st.caption(f"Excel: {calculo.excel}")
        st.download_button("Baixar Excel", data=calculo.excel.read_bytes(), file_name=calculo.excel.name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
