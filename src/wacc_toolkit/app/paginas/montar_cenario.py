"""Página Montar cenário: monta um ``ConfigProjeto`` (Variável × Janela por grupo), com prévia
ao vivo, e salva/gera a versão definitiva. Layout no estilo da aba de opções da planilha Santa
Maria original: por grupo, Grupo | Variável | Valor | Janela/Obs | Fonte, com a linha ativa
destacada."""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.app.estado import (
    FORMATO_DATA,
    alternativas_cacheadas,
    formatar_valor,
    obter_ambiente,
)

MESES_PT = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
           "Setembro", "Outubro", "Novembro", "Dezembro")
ORDEM_GRUPOS = ("rf", "rm", "rf_estrutural", "risco_brasil", "d_v", "inflacao_us", "tlp", "ipca")
GRUPOS_2_JANELAS = {"janela_vol"}  # chave extra da variável (além da que a tabela varia)

st.title("Montar cenário")

amb = obter_ambiente()
if amb is None:
    st.stop()

linhas_bndes = sv.linhas_bndes(amb)  # id -> descrição legível; usado aqui e em _carregar()

# ------------------------------------------------------------------ estado inicial
if "mc_fases" not in st.session_state:
    st.session_state.mc_fases = [{"setor": "", "peso": 100.0, "fase": "", "base_peso": ""}]
    st.session_state.mc_projeto = ""
    st.session_state.mc_mes = date.today().month
    st.session_state.mc_ano = date.today().year
    st.session_state.mc_notas = ""
    st.session_state.mc_regiao = "global"
    st.session_state.mc_focus_modo = "ultimo"
    st.session_state.mc_focus_data = date.today()
    st.session_state.mc_linha_bndes = None
    st.session_state.mc_spread = 0.0
    st.session_state.mc_spread_predefinido = "Financ. BNDES"
    st.session_state.mc_spread_descricao = ""
    st.session_state.mc_spread_fonte = ""
    st.session_state.mc_variaveis = {}  # grupo -> Escolha; preenchido pelo ConfigProjeto default
    st.session_state.mc_carregado = None
    st.session_state.mc_empresas_setor = None  # índice da fase cujas empresas estão exibidas


def _data_base_atual() -> date:
    return date(st.session_state.mc_ano, st.session_state.mc_mes, 1)


def _carregar(cfg: sv.ConfigProjeto, nome_arquivo: str) -> None:
    st.session_state.mc_fases = [
        {"setor": f.setor, "peso": f.peso * 100, "fase": f.fase, "base_peso": f.base_peso} for f in cfg.fases
    ]
    for i, f in enumerate(cfg.fases):
        st.session_state[f"mc_fase_setor_{i}"] = f.setor
        st.session_state[f"mc_fase_peso_{i}"] = f.peso * 100
        st.session_state[f"mc_fase_fase_{i}"] = f.fase
        st.session_state[f"mc_fase_base_{i}"] = f.base_peso
    st.session_state.mc_projeto = cfg.projeto
    st.session_state.mc_mes = cfg.data_base.month
    st.session_state.mc_ano = cfg.data_base.year
    st.session_state.mc_notas = cfg.notas
    st.session_state.mc_regiao = cfg.regiao
    st.session_state.mc_focus_modo = "especifica" if cfg.focus_relatorio else "ultimo"
    st.session_state.mc_focus_data = cfg.focus_relatorio or cfg.data_focus
    st.session_state.mc_linha_bndes = cfg.linha_bndes
    st.session_state.mc_linha_bndes_sel = linhas_bndes.get(cfg.linha_bndes, cfg.linha_bndes)
    st.session_state.mc_spread = cfg.spread_credito * 100
    st.session_state.mc_spread_predefinido = "Financ. BNDES"
    st.session_state.mc_spread_descricao = cfg.spread_descricao
    st.session_state.mc_spread_fonte = cfg.spread_fonte
    st.session_state.mc_variaveis = dict(cfg.variaveis)
    st.session_state.mc_nome_arquivo = nome_arquivo
    st.session_state.pop("mc_previa", None)
    st.session_state.pop("mc_previa_cfg", None)
    st.session_state.pop("mc_gerado", None)
    # os seletores "Escolher alternativa"/"Janela da volatilidade" de cada grupo têm chave fixa
    # por grupo; se a página já tiver renderizado antes (ex.: em branco, antes deste carregamento),
    # essas chaves já existem com o valor de então e "sobrevivem" ao carregamento (o widget só é
    # reinicializado quando a chave ainda não existe). Descartá-las aqui força cada grupo a
    # recalcular o índice padrão a partir da escolha recém-carregada, em vez de manter a seleção
    # anterior (que pode nem ser mais uma alternativa "ativa" correta).
    for chave in [k for k in st.session_state if k.startswith("mc_escolha_") or k.startswith("mc_vol_")]:
        del st.session_state[chave]


# ------------------------------------------------------------------ carregar projeto existente
projetos = sv.listar_projetos(amb)
escolha_projeto = st.selectbox(
    "Carregar projeto existente", [None, *projetos], format_func=lambda p: "Novo (em branco)" if p is None else p.name,
)
if escolha_projeto is not None and st.session_state.mc_carregado != str(escolha_projeto):
    try:
        _carregar(sv.carregar_projeto(escolha_projeto), escolha_projeto.stem)
    except Exception as e:  # noqa: BLE001
        st.error(f"Não foi possível carregar {escolha_projeto.name}: {e}")
    else:
        st.session_state.mc_carregado = str(escolha_projeto)
elif escolha_projeto is None and st.session_state.mc_carregado is not None:
    st.session_state.mc_carregado = None

# ------------------------------------------------------------------ topo: projeto, data-base, Focus
c1, c2, c3 = st.columns([3, 2, 2])
projeto = c1.text_input("Projeto", key="mc_projeto")
mes = c2.selectbox("Mês (data-base)", list(range(1, 13)), format_func=lambda m: MESES_PT[m - 1], key="mc_mes")
ano = c3.selectbox("Ano (data-base)", list(range(1990, date.today().year + 6)), key="mc_ano")
data_base = date(ano, mes, 1)
notas = st.text_area("Notas", key="mc_notas")

st.markdown("**Relatório Focus**")
c1, c2 = st.columns([1, 2])
focus_modo = c1.radio("Relatório Focus", ["ultimo", "especifica"], key="mc_focus_modo",
                     format_func=lambda v: "Último do mês-base" if v == "ultimo" else "Data específica",
                     label_visibility="collapsed")
focus_data = None
if focus_modo == "especifica":
    focus_data = c2.date_input("Data do relatório Focus", key="mc_focus_data", format=FORMATO_DATA)

st.caption(f"Janelas terminam em {sv.mes_corte_rotulo(data_base)}.")

# ------------------------------------------------------------------ configuração provisória (para as tabelas)
def _montar_cfg(variaveis_override: dict | None = None) -> sv.ConfigProjeto | None:
    fases = [{"setor": f["setor"] or "", "peso": f["peso"] / 100.0, "fase": f["fase"], "base_peso": f["base_peso"]}
             for f in st.session_state.mc_fases]
    linha_bndes_atual = st.session_state.get("mc_linha_bndes") or ""
    try:
        return sv.nova_config(
            projeto=projeto or "(sem nome)", data_base=data_base,
            focus_relatorio=focus_data if focus_modo == "especifica" else None,
            notas=notas, regiao=st.session_state.mc_regiao, fases=fases,
            linha_bndes=linha_bndes_atual, spread_credito=st.session_state.mc_spread / 100.0,
            spread_descricao=st.session_state.mc_spread_descricao, spread_fonte=st.session_state.mc_spread_fonte,
            variaveis={**st.session_state.mc_variaveis, **(variaveis_override or {})},
        )
    except ValueError as e:
        st.error(str(e))
        return None


cfg_base = _montar_cfg()
if cfg_base is not None:
    # o ConfigProjeto pode ter completado grupos ausentes com os padrões (1ª vez): sincroniza de volta
    st.session_state.mc_variaveis = dict(cfg_base.variaveis)

# ------------------------------------------------------------------ seções por grupo (Variável × Janela)
st.subheader("Variáveis")
if cfg_base is not None:
    bases = sv.bases_de(amb)
    for grupo in ORDEM_GRUPOS:
        with st.expander(sv.NOMES_GRUPOS[grupo], expanded=True):
            tabela = alternativas_cacheadas(amb, cfg_base, grupo, bases=bases)
            if tabela.empty:
                st.info("Nenhuma variável cadastrada para este grupo.")
                continue

            exibir = sv.tabela_alternativas_exibicao(cfg_base, grupo, tabela)

            def _estilo(linha, _exibir=exibir):
                i = linha.name
                if _exibir.loc[i, "Ativa"]:
                    return ["background-color: #234b23"] * len(linha)
                if _exibir.loc[i, "erro"]:
                    return ["color: #808080"] * len(linha)
                return [""] * len(linha)

            mostrar = exibir[["Variável", "Valor", "Janela/Obs", "Fonte", "Ativa"]]
            st.dataframe(mostrar.style.apply(_estilo, axis=1), width="stretch", hide_index=True)

            selecionaveis = tabela[~exibir["erro"].to_numpy()].reset_index(drop=True)
            if selecionaveis.empty:
                st.warning("Nenhuma alternativa deste grupo pôde ser calculada com as bases atuais.")
            else:
                # rótulos precisam ser únicos (viram chave de "por_rotulo"): duas variantes sem
                # janela podem gerar o mesmo texto (ex.: dois "base_calculo" do Focus caindo no
                # mesmo relatório) - repetições ganham um sufixo " (2)", " (3)" etc.
                rotulos, contagem = [], {}
                for r in selecionaveis.itertuples():
                    base = f"{r.variavel_nome} | {r.janela_nome or r.rotulo or 'padrão'}"
                    n = contagem.get(base, 0)
                    contagem[base] = n + 1
                    rotulos.append(base if n == 0 else f"{base} ({n + 1})")
                por_rotulo = dict(zip(rotulos, selecionaveis["escolha"]))
                ativa_rotulos = [rot for rot, ativa in zip(rotulos, selecionaveis["ativa"]) if ativa]
                indice_padrao = rotulos.index(ativa_rotulos[0]) if ativa_rotulos else 0
                chave_sel = f"mc_escolha_{grupo}"
                criado_agora = chave_sel not in st.session_state
                if criado_agora or st.session_state[chave_sel] not in rotulos:
                    st.session_state[chave_sel] = rotulos[indice_padrao]
                escolhido = st.selectbox("Escolher alternativa", rotulos, key=chave_sel)
                # só sincroniza a escolha do projeto a partir do seletor quando ele de fato
                # reflete a escolha ativa (ou uma troca deliberada do usuário): se a escolha ativa
                # está com erro, o seletor cai para a 1ª opção só para exibição, e não deve
                # substituir silenciosamente a escolha atual do projeto por esse fallback.
                if not (criado_agora and not ativa_rotulos):
                    st.session_state.mc_variaveis[grupo] = por_rotulo[escolhido]

            # Risco Brasil: variáveis com 2 janelas também expõem a janela da volatilidade
            escolha_atual = st.session_state.mc_variaveis.get(grupo)
            if escolha_atual and "janela_vol" in (escolha_atual.janelas or {}):
                catalogo = sv.listar_janelas(amb)
                especs = [j["espec"] for j in catalogo]
                nomes = {j["espec"]: j["nome"] for j in catalogo}
                atual_vol = escolha_atual.janelas.get("janela_vol", especs[0])
                indice_vol = especs.index(atual_vol) if atual_vol in especs else 0
                chave_vol = f"mc_vol_{grupo}"
                if chave_vol not in st.session_state:
                    st.session_state[chave_vol] = especs[indice_vol]
                espec_vol = st.selectbox("Janela da volatilidade", especs, format_func=lambda e: nomes.get(e, e),
                                         key=chave_vol)
                if espec_vol != escolha_atual.janelas.get("janela_vol"):
                    st.session_state.mc_variaveis[grupo] = replace(
                        escolha_atual, janelas={**escolha_atual.janelas, "janela_vol": espec_vol})

# ------------------------------------------------------------------ catálogo de janelas
with st.expander("Janelas"):
    catalogo = sv.listar_janelas(amb)
    tabela_janelas = [{"Nome": j["nome"], "Especificação": j["espec"],
                      "Origem": "Padrão" if j["padrao"] else "Do usuário"} for j in catalogo]
    st.dataframe(tabela_janelas, width="stretch", hide_index=True)

    removiveis = [j["espec"] for j in catalogo if not j["padrao"]]
    if removiveis:
        c1, c2 = st.columns([3, 1])
        espec_remover = c1.selectbox("Remover janela do usuário", removiveis, key="mc_janela_remover")
        if c2.button("Remover", key="mc_botao_remover_janela"):
            try:
                sv.remover_janela(amb, espec_remover)
            except (ValueError, KeyError) as e:
                st.error(str(e))
            else:
                st.success(f"Janela removida: {espec_remover}")

    st.markdown("**Nova janela**")
    tipo = st.selectbox("Tipo", ["Últimos N meses", "N anos-calendário", "Desde um mês", "Intervalo fixo"],
                        key="mc_janela_tipo")
    nome_janela = st.text_input("Nome (opcional)", key="mc_janela_nome")
    espec_nova = None
    if tipo == "Últimos N meses":
        n = st.number_input("N (meses)", min_value=1, step=1, key="mc_janela_n_meses")
        espec_nova = f"{int(n)}m"
    elif tipo == "N anos-calendário":
        n = st.number_input("N (anos)", min_value=1, step=1, key="mc_janela_n_anos")
        espec_nova = f"{int(n)}a"
    elif tipo == "Desde um mês":
        c1, c2 = st.columns(2)
        mes_ini = c1.selectbox("Mês", list(range(1, 13)), format_func=lambda m: MESES_PT[m - 1],
                               key="mc_janela_desde_mes")
        ano_ini = c2.selectbox("Ano", list(range(1990, date.today().year + 1)), key="mc_janela_desde_ano")
        espec_nova = f"desde:{ano_ini:04d}-{mes_ini:02d}"
    else:
        st.caption('O intervalo fixo não acompanha a data-base: o fim fica travado no mês informado '
                  '(ou no corte, se ele for anterior).')
        c1, c2, c3, c4 = st.columns(4)
        mes_ini = c1.selectbox("Mês inicial", list(range(1, 13)), format_func=lambda m: MESES_PT[m - 1],
                               key="mc_janela_int_mes_ini")
        ano_ini = c2.selectbox("Ano inicial", list(range(1990, date.today().year + 1)), key="mc_janela_int_ano_ini")
        mes_fim = c3.selectbox("Mês final", list(range(1, 13)), format_func=lambda m: MESES_PT[m - 1],
                               key="mc_janela_int_mes_fim")
        ano_fim = c4.selectbox("Ano final", list(range(1990, date.today().year + 6)), key="mc_janela_int_ano_fim")
        espec_nova = f"intervalo:{ano_ini:04d}-{mes_ini:02d}:{ano_fim:04d}-{mes_fim:02d}"

    if st.button("Adicionar janela", key="mc_botao_add_janela"):
        try:
            sv.salvar_janela(amb, espec_nova, nome_janela)
        except ValueError as e:
            st.error(str(e))
        else:
            st.success(f"Janela adicionada: {espec_nova}")

# ------------------------------------------------------------------ demais insumos: fases/beta
st.subheader("Fases (beta)")
regiao = st.selectbox("Região (Damodaran)", ["global", "emerging"], key="mc_regiao")
try:
    setores_disponiveis = sv.setores_damodaran(amb, regiao, data_base)
except Exception as e:  # noqa: BLE001
    st.warning(f"Não foi possível listar setores Damodaran para {regiao}/{data_base}: {e}")
    setores_disponiveis = []

for i, fase in enumerate(st.session_state.mc_fases):
    cols = st.columns([3, 2, 2, 2, 1, 1])
    opcoes_setor = sorted(set(setores_disponiveis) | ({fase["setor"]} if fase["setor"] else set()))
    fase["setor"] = cols[0].selectbox(
        "Setor", opcoes_setor, index=opcoes_setor.index(fase["setor"]) if fase["setor"] in opcoes_setor else None,
        placeholder="escolha o setor", key=f"mc_fase_setor_{i}",
    )
    fase["peso"] = cols[1].number_input("Peso (%)", value=float(fase["peso"]), min_value=0.0, max_value=100.0,
                                        step=1.0, key=f"mc_fase_peso_{i}")
    fase["fase"] = cols[2].text_input("Fase", value=fase["fase"], key=f"mc_fase_fase_{i}",
                                      placeholder="ex.: construção")
    fase["base_peso"] = cols[3].text_input("Base do peso", value=fase["base_peso"], key=f"mc_fase_base_{i}",
                                           placeholder="ex.: CAPEX")
    if cols[4].button("Empresas", key=f"mc_fase_empresas_{i}", disabled=not fase["setor"]):
        st.session_state.mc_empresas_setor = i if st.session_state.mc_empresas_setor != i else None
    if cols[5].button("Remover", key=f"mc_fase_remover_{i}") and len(st.session_state.mc_fases) > 1:
        st.session_state.mc_fases.pop(i)
        st.rerun()

    if st.session_state.mc_empresas_setor == i and fase["setor"]:
        try:
            empresas = sv.empresas_do_setor(amb, fase["setor"], regiao)
        except FileNotFoundError as e:
            st.warning(str(e))
        else:
            if empresas.empty:
                st.caption(f"Nenhuma empresa encontrada para {fase['setor']!r} ({regiao}).")
            else:
                paises = sorted(empresas["country"].dropna().unique())
                pais = st.selectbox("País", ["Todos", *paises], key=f"mc_fase_pais_{i}")
                filtradas = empresas if pais == "Todos" else empresas[empresas["country"] == pais]
                st.caption(f"{len(filtradas)} empresa(s) de {len(empresas)}.")
                st.dataframe(
                    filtradas.rename(columns={"company_name": "Empresa", "country": "País",
                                              "exchange_ticker": "Ticker", "primary_sector": "Setor primário"}),
                    width="stretch", hide_index=True,
                )

if st.button("Adicionar fase", key="mc_botao_add_fase"):
    st.session_state.mc_fases.append({"setor": "", "peso": 0.0, "fase": "", "base_peso": ""})
    st.rerun()

soma_pesos = sum(f["peso"] for f in st.session_state.mc_fases)
pesos_ok = abs(soma_pesos - 100.0) < 1e-6
(st.success if pesos_ok else st.error)(
    f"Soma dos pesos: {sv.formatar_numero_pt(soma_pesos, 2)}%" + ("" if pesos_ok else " (deve ser 100%)"))

# ------------------------------------------------------------------ dívida (BNDES e spread)
st.subheader("Dívida")
c1, c2 = st.columns(2)
if linhas_bndes:
    id_por_rotulo = {rotulo: id_ for id_, rotulo in linhas_bndes.items()}
    rotulo_escolhido = c1.selectbox("Linha BNDES", list(linhas_bndes.values()), key="mc_linha_bndes_sel")
    linha_bndes = id_por_rotulo[rotulo_escolhido]
    st.session_state.mc_linha_bndes = linha_bndes
else:
    c1.info("Nenhuma linha BNDES cadastrada em parâmetros manuais.")
    linha_bndes = st.session_state.get("mc_linha_bndes") or ""

predefinido = c2.selectbox("Spread: predefinidos da planilha", list(sv.SPREADS_PREDEFINIDOS),
                           key="mc_spread_predefinido")
valor_predefinido = sv.SPREADS_PREDEFINIDOS[predefinido]
if valor_predefinido is not None and abs(st.session_state.mc_spread / 100.0 - valor_predefinido) > 1e-9:
    st.session_state.mc_spread = valor_predefinido * 100
    st.session_state.mc_spread_descricao = predefinido
    st.rerun()

spread_pct = st.number_input("Spread de crédito (%)", key="mc_spread", step=0.01, format="%.4f")
c3, c4 = st.columns(2)
spread_descricao = c3.text_input("Descrição do spread", key="mc_spread_descricao")
spread_fonte = c4.text_input("Fonte do spread", key="mc_spread_fonte")

# ------------------------------------------------------------------ montar configuração final
cfg = _montar_cfg()

# ------------------------------------------------------------------ ações
st.subheader("Ações")
previa_atual = st.session_state.get("mc_previa")
previa_cfg = st.session_state.get("mc_previa_cfg")
previa_atualizada = previa_atual is not None and cfg is not None and previa_cfg == cfg

c1, c2, c3 = st.columns(3)
with c1:
    nome_arquivo = st.text_input("Nome do arquivo", value=(projeto or "projeto"), key="mc_nome_arquivo")
    sobrescrever = st.checkbox("Sobrescrever se já existir", key="mc_sobrescrever")
    if st.button("Salvar projeto", disabled=cfg is None, key="mc_botao_salvar"):
        try:
            caminho = sv.salvar_projeto(amb, cfg, nome_arquivo, sobrescrever)
        except (ValueError, FileExistsError) as e:
            st.error(str(e))
        else:
            st.success(f"Projeto salvo em {caminho}")

with c2:
    calcular_desabilitado = cfg is None or not pesos_ok
    if st.button("Calcular", disabled=calcular_desabilitado, key="mc_botao_calcular",
                help="Calcula uma prévia do WACC, sem gravar nada em Calculos/."):
        try:
            resultado_previa = sv.calcular_previa(amb, cfg)
        except (ValueError, KeyError, FileNotFoundError) as e:
            st.error(f"{e}\n\nSe a mensagem indicar uma base desatualizada ou ausente, "
                     f"vá à página Bases e atualize ou importe a fonte correspondente.")
        else:
            st.session_state.mc_previa = resultado_previa
            st.session_state.mc_previa_cfg = cfg
            previa_atual, previa_cfg, previa_atualizada = resultado_previa, cfg, True

with c3:
    gerar_desabilitado = not previa_atualizada
    if st.button("Gerar versão", disabled=gerar_desabilitado, type="primary", key="mc_botao_gerar",
                help="Grava o registro (JSON) e o Excel em Calculos/, a partir da prévia atual."):
        try:
            calculo = sv.calcular_projeto(amb, cfg, excel=True)
        except (ValueError, KeyError, FileNotFoundError) as e:
            st.error(str(e))
        else:
            st.session_state.mc_gerado = calculo

# ------------------------------------------------------------------ resultado (prévia)
if previa_atual is not None:
    st.subheader("Resultado (prévia)")
    if not previa_atualizada:
        st.warning("A prévia está desatualizada: recalcule (\"Calcular\") antes de gerar a versão.")

    m1, m2 = st.columns(2)
    m1.metric("WACC real", formatar_valor("wacc_real", previa_atual["wacc_real"]))
    m2.metric("WACC nominal", formatar_valor("wacc_nominal", previa_atual["wacc_nominal"]))

    tabela_cc = sv.tabela_custo_de_capital(previa_atual)
    for secao in ("KE", "KD", "WACC"):
        st.markdown(f"**{secao}**")
        linhas_secao = tabela_cc.loc[tabela_cc["secao"] == secao, ["item", "valor", "descricao"]]
        st.dataframe(linhas_secao.rename(columns={"item": "Item", "valor": "Valor", "descricao": "Descrição"}),
                    width="stretch", hide_index=True)

# ------------------------------------------------------------------ versão gerada
gerado = st.session_state.get("mc_gerado")
if gerado is not None:
    st.subheader("Versão gerada")
    st.success(f"Registro: {gerado.registro}")
    if gerado.excel:
        st.caption(f"Excel: {gerado.excel}")
        st.download_button("Baixar Excel", data=gerado.excel.read_bytes(), file_name=gerado.excel.name,
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
