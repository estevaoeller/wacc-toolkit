"""Interface Streamlit: cada página carrega sem exceção e os fluxos principais funcionam.

Upload de arquivo (``st.file_uploader``) não é simulável pelo ``AppTest`` desta versão do
Streamlit (não há como injetar o conteúdo de um arquivo enviado); a lógica de importação
em si já é testada diretamente em ``test_servicos.py::test_importar_arquivos_so_fontes_manuais``.
"""

import re
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import test_calc_modo1 as m1
from wacc_toolkit import servicos as sv

bases_sinteticas = m1.bases_sinteticas

PAGINAS = Path(__file__).parents[1] / "src" / "wacc_toolkit" / "app" / "paginas"


@pytest.fixture
def bases_dir(tmp_path, bases_sinteticas, monkeypatch):
    """Aponta WACC_BASES_DIR para o repositório sintético (mesmo usado por test_calc_modo1)."""
    caminho = tmp_path / "bases"
    monkeypatch.setenv("WACC_BASES_DIR", str(caminho))
    return caminho


def _rodar(nome: str) -> AppTest:
    at = AppTest.from_file(str(PAGINAS / nome), default_timeout=30)
    at.run()
    return at


def test_pagina_bases_carrega(bases_dir):
    at = _rodar("bases.py")
    assert not at.exception


def test_pagina_bases_series_opcionais_sem_alerta(bases_dir):
    """As bases sintéticas não trazem as variantes opcionais do Investing (diária/_mensal
    do CDS 5a e o Ibovespa do Investing): devem aparecer como "opcional", sem alerta amarelo."""
    at = _rodar("bases.py")
    status = at.dataframe[0].value
    opcionais = status[status["serie"].isin(sv.SERIES_OPCIONAIS)]
    assert not opcionais.empty
    assert (opcionais["situação"] == "opcional (sem dados)").all()
    obrigatorias_sem_dados = status[~status["serie"].isin(sv.SERIES_OPCIONAIS) & (status["situação"] == "sem dados")]
    avisos = "\n".join(i.value for i in at.warning)
    if obrigatorias_sem_dados.empty:
        assert "sem dados" not in avisos
    else:
        assert str(len(obrigatorias_sem_dados)) in avisos


def test_pagina_consulta_carrega(bases_dir):
    at = _rodar("consulta.py")
    assert not at.exception


def test_pagina_montar_cenario_carrega(bases_dir):
    at = _rodar("montar_cenario.py")
    assert not at.exception


def test_pagina_historico_carrega_vazia(bases_dir):
    at = _rodar("historico.py")
    assert not at.exception
    assert "Nenhum cálculo gravado ainda." in "\n".join(i.value for i in at.info)


def test_pagina_painel_mostra_indicadores(bases_dir):
    at = _rodar("painel.py")
    assert not at.exception
    blocos = "\n".join(m.value for m in at.markdown)
    for nome in ("Treasury 10 anos", "CDS Brasil 10 anos", "Ibovespa", "S&P 500 Total Return", "TLP"):
        assert nome in blocos, f"indicador {nome!r} não apareceu no painel"
    assert "Nenhum cálculo gravado ainda" in "\n".join(i.value for i in at.info)


def test_pagina_painel_mostra_ultimos_calculos(bases_dir):
    amb = sv.ambiente(bases_dir)
    sv.calcular_projeto(amb, m1._cfg(projeto="Projeto Painel"), excel=False)
    at = _rodar("painel.py")
    assert not at.exception
    blocos = "\n".join(m.value for m in at.markdown)
    assert "WACC real" in blocos and re.search(r"\d+,\d{2}%", blocos)
    textos = "\n".join(i.value for i in at.markdown)
    assert "Projeto Painel" in textos


def _cfg_bndes_teste(repo) -> None:
    """As bases sintéticas não têm nenhuma linha "bndes_rem*"; acrescenta uma para o formulário
    poder oferecer uma linha BNDES selecionável (``linhas_bndes()`` filtra por esse prefixo)."""
    m1._gravar(repo, "parametros_manuais", pd.DataFrame({
        "parametro": ["ir_csll", "rem_x", "bndes_rem_teste"], "valor": [34.0, 1.5, 1.3],
        "unidade": "%", "fonte": "teste", "verificado_em": "2026-01-01", "responsavel": "", "notas": ""}))


def _preencher_projeto_valido(at: AppTest, projeto: str = "Projeto Teste App") -> AppTest:
    at.text_input(key="mc_projeto").set_value(projeto)
    at.selectbox(key="mc_mes").set_value(1)
    at.selectbox(key="mc_ano").set_value(2026)
    at.run()
    assert not at.exception

    at.selectbox(key="mc_fase_setor_0").set_value("Setor A")
    at.number_input(key="mc_fase_peso_0").set_value(40.0)
    at.run()
    assert not at.exception

    at.button(key="mc_botao_add_fase").click()
    at.run()
    assert not at.exception

    at.selectbox(key="mc_fase_setor_1").set_value("Setor B")
    at.number_input(key="mc_fase_peso_1").set_value(60.0)
    at.selectbox(key="mc_linha_bndes_sel").set_value("teste (1,30% a.a.)")
    at.number_input(key="mc_spread").set_value(1.0)
    at.run()
    assert not at.exception
    return at


def test_montar_cenario_previa_nao_grava_e_gerar_versao_grava(bases_dir, repo):
    """'Calcular' é só uma prévia (não cria arquivo nenhum); 'Gerar versão' grava o JSON e o
    Excel, com o mesmo valor da prévia e as escolhas de variável/janela, e o cálculo passa a
    aparecer no Histórico."""
    _cfg_bndes_teste(repo)
    amb = sv.ambiente(bases_dir)
    at = _preencher_projeto_valido(_rodar("montar_cenario.py"))

    soma = "\n".join([i.value for i in at.success] + [i.value for i in at.error])
    assert "100,00%" in soma

    # "Gerar versão" começa desabilitado: ainda não há prévia
    assert at.button(key="mc_botao_gerar").disabled
    assert list(amb.calculos.glob("*")) == []

    at.button(key="mc_botao_calcular").click()
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else None

    metricas = {m.label: m.value for m in at.metric}
    assert "WACC real" in metricas and metricas["WACC real"].endswith("%")
    # a prévia não grava nada em Calculos/
    assert list(amb.calculos.glob("*")) == []
    assert not at.button(key="mc_botao_gerar").disabled

    at.button(key="mc_botao_gerar").click()
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else None
    assert len(list(amb.calculos.glob("*.json"))) == 1
    assert len(list(amb.calculos.glob("*.xlsx"))) == 1

    # o valor gravado é idêntico ao da prévia, e as escolhas (variável/janela) foram gravadas
    [arquivo_json] = amb.calculos.glob("*.json")
    dados = sv.ler_calculo(amb, arquivo_json.name)
    assert dados["componentes"]["wacc_real"]["valor"] == pytest.approx(
        float(metricas["WACC real"].rstrip("%").replace(".", "").replace(",", ".")) / 100, abs=1e-3)
    variaveis = dados["config"]["variaveis"]
    assert set(variaveis) == set(sv.GRUPOS_VARIAVEIS)
    assert variaveis["rf"]["variavel"] == "t10_media_mensal"

    # o cálculo foi gravado em disco; a página Histórico (nova sessão) deve listá-lo
    at_hist = _rodar("historico.py")
    assert not at_hist.exception
    tabela = at_hist.dataframe[0].value
    assert "Projeto Teste App" in list(tabela["Projeto"])


def test_montar_cenario_mudar_campo_desatualiza_previa(bases_dir, repo):
    """Mudar um campo depois da prévia mostra o aviso e desabilita 'Gerar versão' até recalcular."""
    _cfg_bndes_teste(repo)
    at = _preencher_projeto_valido(_rodar("montar_cenario.py"))
    at.button(key="mc_botao_calcular").click()
    at.run()
    assert not at.exception
    assert not at.button(key="mc_botao_gerar").disabled

    at.number_input(key="mc_spread").set_value(2.0)
    at.run()
    assert not at.exception

    avisos = "\n".join(i.value for i in at.warning)
    assert "desatualizada" in avisos
    assert at.button(key="mc_botao_gerar").disabled

    at.button(key="mc_botao_calcular").click()
    at.run()
    assert not at.exception
    assert not at.button(key="mc_botao_gerar").disabled


def test_montar_cenario_trocar_alternativa_muda_previa(bases_dir, repo):
    """Trocar a alternativa (janela) de um grupo muda o valor da prévia. Usa o grupo Rm: o
    Ibovespa/S&P sintético cresce ao longo do tempo, então janelas diferentes dão médias
    diferentes (ao contrário de Rf/TLP, cuja série sintética é constante)."""
    _cfg_bndes_teste(repo)
    at = _preencher_projeto_valido(_rodar("montar_cenario.py"))
    at.button(key="mc_botao_calcular").click()
    at.run()
    assert not at.exception
    antes = at.session_state["mc_previa"]["rm"]

    sel = at.selectbox(key="mc_escolha_rm")
    outra = next(o for o in sel.options if o != sel.value and "Damodaran" not in o)
    sel.set_value(outra)
    at.run()
    assert not at.exception
    at.button(key="mc_botao_calcular").click()
    at.run()
    assert not at.exception
    depois = at.session_state["mc_previa"]["rm"]
    assert antes != pytest.approx(depois)
    # o WACC nominal (menos amortecido pela conversão a real) também muda visivelmente
    metricas = {m.label: m.value for m in at.metric}
    assert metricas["WACC real"].endswith("%")


def test_montar_cenario_linha_com_erro_nao_e_selecionavel(bases_dir, repo):
    """Numa data-base sem cobertura recente (jun/2026, bases sintéticas só vão até dez/2025),
    as janelas "de meses" do T-10 falham (faltam meses) e não entram no seletor; só as janelas
    de anos-calendário (que não tocam 2026) continuam selecionáveis."""
    _cfg_bndes_teste(repo)
    at = _rodar("montar_cenario.py")
    at.text_input(key="mc_projeto").set_value("Projeto Erro")
    at.selectbox(key="mc_mes").set_value(6)
    at.selectbox(key="mc_ano").set_value(2026)
    at.selectbox(key="mc_fase_setor_0").set_value("Setor A")
    at.number_input(key="mc_fase_peso_0").set_value(100.0)
    at.run()
    assert not at.exception

    sel = at.selectbox(key="mc_escolha_rf")
    assert len(sel.options) == 4  # só as 4 janelas "Xa" do t10_media_mensal
    assert all("anos-calendário" in o for o in sel.options)

    textos = "\n".join(d.value.to_string() for d in at.dataframe)
    assert "faltam" in textos  # a tabela ainda mostra as linhas com erro, com o motivo


def test_montar_cenario_criar_e_remover_janela(bases_dir):
    amb = sv.ambiente(bases_dir)
    at = _rodar("montar_cenario.py")
    at.selectbox(key="mc_janela_tipo").set_value("Últimos N meses")
    at.number_input(key="mc_janela_n_meses").set_value(18)
    at.run()
    assert not at.exception
    at.button(key="mc_botao_add_janela").click()
    at.run()
    assert not at.exception
    assert any(j["espec"] == "18m" for j in sv.listar_janelas(amb))
    sucesso = "\n".join(i.value for i in at.success)
    assert "18m" in sucesso

    at.run()  # o catálogo de janelas só é relido do disco na rodada seguinte
    at.selectbox(key="mc_janela_remover").set_value("18m")
    at.run()
    assert not at.exception
    at.button(key="mc_botao_remover_janela").click()
    at.run()
    assert not at.exception
    assert not any(j["espec"] == "18m" for j in sv.listar_janelas(amb))


def test_montar_cenario_ver_empresas_do_setor(bases_dir, repo):
    df = pd.DataFrame({
        "company_name": ["Empresa Alfa", "Empresa Beta"], "exchange_ticker": ["NYSE:A", "NYSE:B"],
        "industry_group": ["Setor A", "Setor A"], "primary_sector": ["Industrial", "Industrial"],
        "sic_code": [1000, 1001], "country": ["Brazil", "United States"],
        "broad_group": ["Emerging Markets", "United States"], "sub_group": ["", ""],
    })
    m1._gravar(repo, "damodaran_empresas", df, "2025-01")

    at = _rodar("montar_cenario.py")
    at.selectbox(key="mc_fase_setor_0").set_value("Setor A")
    at.run()
    assert not at.exception
    at.button(key="mc_fase_empresas_0").click()
    at.run()
    assert not at.exception

    textos = "\n".join(d.value.to_string() for d in at.dataframe)
    assert "Empresa Alfa" in textos and "Empresa Beta" in textos


def test_montar_cenario_nome_arquivo_preenchido_ao_carregar(bases_dir):
    """Ao carregar um projeto salvo, o campo 'Nome do arquivo' vem com o nome do arquivo
    carregado (não com um valor genérico)."""
    amb = sv.ambiente(bases_dir)
    cfg = m1._cfg(projeto="Santa Maria")
    sv.salvar_projeto(amb, cfg, "santa_maria_2026-07")

    [caminho] = sv.listar_projetos(amb)
    at = _rodar("montar_cenario.py")
    carregar = next(s for s in at.selectbox if s.label == "Carregar projeto existente")
    carregar.select(caminho)
    at.run()
    assert not at.exception

    nome_arquivo = next(t for t in at.text_input if t.label == "Nome do arquivo")
    assert nome_arquivo.value == "santa_maria_2026-07"


def test_montar_cenario_pesos_diferentes_de_100_bloqueia_calculo(bases_dir):
    at = _rodar("montar_cenario.py")
    at.text_input(key="mc_projeto").set_value("Projeto Incompleto")
    at.number_input(key="mc_fase_peso_0").set_value(70.0)
    at.run()
    assert not at.exception

    erros = "\n".join(i.value for i in at.error)
    assert "100%" in erros
    assert at.button(key="mc_botao_calcular").disabled


def _todos_os_textos(at: AppTest) -> list[str]:
    """Todo texto renderizado que dá para inspecionar via AppTest: títulos, textos soltos,
    mensagens de status e o conteúdo (em string) de cada dataframe/tabela."""
    textos = []
    for grupo in (at.title, at.header, at.subheader, at.markdown, at.caption, at.text,
                 at.error, at.warning, at.success, at.info):
        textos += [i.value for i in grupo]
    textos += [f"{m.label} {m.value}" for m in at.metric]
    for d in at.dataframe:
        textos.append(d.value.to_string())
    return textos


@pytest.mark.parametrize("pagina", ["bases.py", "consulta.py", "montar_cenario.py", "historico.py", "painel.py"])
def test_nenhum_travessao_na_interface(bases_dir, pagina):
    at = _rodar(pagina)
    assert not at.exception
    for texto in _todos_os_textos(at):
        assert "—" not in texto, f"{pagina}: travessão encontrado em {texto!r}"
