"""Interface Streamlit: cada página carrega sem exceção e os fluxos principais funcionam.

Upload de arquivo (``st.file_uploader``) não é simulável pelo ``AppTest`` desta versão do
Streamlit (não há como injetar o conteúdo de um arquivo enviado); a lógica de importação
em si já é testada diretamente em ``test_servicos.py::test_importar_arquivos_so_fontes_manuais``.
"""

import re
from datetime import date
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


def test_pagina_novo_wacc_carrega(bases_dir):
    at = _rodar("novo_wacc.py")
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


def _preencher_projeto_valido(at: AppTest, projeto: str = "Projeto Teste App") -> AppTest:
    at.text_input(key="nw_projeto").set_value(projeto)
    at.date_input(key="nw_data_base").set_value(date(2026, 1, 16))
    at.run()
    assert not at.exception

    at.selectbox(key="nw_fase_setor_0").set_value("Setor A")
    at.number_input(key="nw_fase_peso_0").set_value(40.0)
    at.run()
    assert not at.exception

    at.button(key="nw_botao_add_fase").click()
    at.run()
    assert not at.exception

    at.selectbox(key="nw_fase_setor_1").set_value("Setor B")
    at.number_input(key="nw_fase_peso_1").set_value(60.0)
    at.selectbox(key="nw_linha_bndes_sel").set_value("teste (1,30% a.a.)")
    at.number_input(key="nw_spread").set_value(1.0)
    at.run()
    assert not at.exception
    return at


def test_novo_wacc_previa_nao_grava_e_gerar_versao_grava(bases_dir, repo):
    """'Calcular' é só uma prévia (não cria arquivo nenhum); 'Gerar versão' grava o JSON e o
    Excel, com o mesmo valor da prévia, e o cálculo passa a aparecer no Histórico."""
    # As bases sintéticas não têm nenhuma linha "bndes_rem*"; acrescenta uma para o formulário
    # poder oferecer uma linha BNDES selecionável (linhas_bndes() filtra por esse prefixo).
    m1._gravar(repo, "parametros_manuais", pd.DataFrame({
        "parametro": ["ir_csll", "rem_x", "bndes_rem_teste"], "valor": [34.0, 1.5, 1.3],
        "unidade": "%", "fonte": "teste", "verificado_em": "2026-01-01", "responsavel": "", "notas": ""}))

    amb = sv.ambiente(bases_dir)
    at = _preencher_projeto_valido(_rodar("novo_wacc.py"))

    soma = "\n".join([i.value for i in at.success] + [i.value for i in at.error])
    assert "100,00%" in soma

    # "Gerar versão" começa desabilitado: ainda não há prévia
    assert at.button(key="nw_botao_gerar").disabled
    assert list(amb.calculos.glob("*")) == []

    at.button(key="nw_botao_calcular").click()
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else None

    metricas = {m.label: m.value for m in at.metric}
    assert "WACC real" in metricas and metricas["WACC real"].endswith("%")
    # a prévia não grava nada em Calculos/
    assert list(amb.calculos.glob("*")) == []
    assert not at.button(key="nw_botao_gerar").disabled

    at.button(key="nw_botao_gerar").click()
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else None
    assert len(list(amb.calculos.glob("*.json"))) == 1
    assert len(list(amb.calculos.glob("*.xlsx"))) == 1

    # o valor gravado é idêntico ao da prévia
    [arquivo_json] = amb.calculos.glob("*.json")
    dados = sv.ler_calculo(amb, arquivo_json.name)
    assert dados["componentes"]["wacc_real"]["valor"] == pytest.approx(
        float(metricas["WACC real"].rstrip("%").replace(".", "").replace(",", ".")) / 100, abs=1e-3)

    # o cálculo foi gravado em disco; a página Histórico (nova sessão) deve listá-lo
    at_hist = _rodar("historico.py")
    assert not at_hist.exception
    tabela = at_hist.dataframe[0].value
    assert "Projeto Teste App" in list(tabela["Projeto"])


def test_novo_wacc_mudar_campo_desatualiza_previa(bases_dir, repo):
    """Mudar um campo depois da prévia mostra o aviso e desabilita 'Gerar versão' até recalcular."""
    m1._gravar(repo, "parametros_manuais", pd.DataFrame({
        "parametro": ["ir_csll", "rem_x", "bndes_rem_teste"], "valor": [34.0, 1.5, 1.3],
        "unidade": "%", "fonte": "teste", "verificado_em": "2026-01-01", "responsavel": "", "notas": ""}))

    at = _preencher_projeto_valido(_rodar("novo_wacc.py"))
    at.button(key="nw_botao_calcular").click()
    at.run()
    assert not at.exception
    assert not at.button(key="nw_botao_gerar").disabled

    at.number_input(key="nw_spread").set_value(2.0)
    at.run()
    assert not at.exception

    avisos = "\n".join(i.value for i in at.warning)
    assert "desatualizada" in avisos
    assert at.button(key="nw_botao_gerar").disabled

    at.button(key="nw_botao_calcular").click()
    at.run()
    assert not at.exception
    assert not at.button(key="nw_botao_gerar").disabled


def test_novo_wacc_nome_arquivo_preenchido_ao_carregar(bases_dir):
    """Ao carregar um projeto salvo, o campo 'Nome do arquivo' vem com o nome do arquivo
    carregado (não com um valor genérico)."""
    amb = sv.ambiente(bases_dir)
    cfg = m1._cfg(projeto="Santa Maria")
    sv.salvar_projeto(amb, cfg, "santa_maria_2026-07")

    [caminho] = sv.listar_projetos(amb)
    at = _rodar("novo_wacc.py")
    carregar = next(s for s in at.selectbox if s.label == "Carregar projeto existente")
    carregar.select(caminho)
    at.run()
    assert not at.exception

    nome_arquivo = next(t for t in at.text_input if t.label == "Nome do arquivo")
    assert nome_arquivo.value == "santa_maria_2026-07"


def test_novo_wacc_pesos_diferentes_de_100_bloqueia_calculo(bases_dir):
    at = _rodar("novo_wacc.py")
    at.text_input(key="nw_projeto").set_value("Projeto Incompleto")
    at.number_input(key="nw_fase_peso_0").set_value(70.0)
    at.run()
    assert not at.exception

    erros = "\n".join(i.value for i in at.error)
    assert "100%" in erros
    assert at.button(key="nw_botao_calcular").disabled


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


@pytest.mark.parametrize("pagina", ["bases.py", "consulta.py", "novo_wacc.py", "historico.py", "painel.py"])
def test_nenhum_travessao_na_interface(bases_dir, pagina):
    at = _rodar(pagina)
    assert not at.exception
    for texto in _todos_os_textos(at):
        assert "—" not in texto, f"{pagina}: travessão encontrado em {texto!r}"
