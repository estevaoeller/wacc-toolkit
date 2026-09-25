"""Interface Streamlit: cada página carrega sem exceção e os fluxos principais funcionam.

Upload de arquivo (``st.file_uploader``) não é simulável pelo ``AppTest`` desta versão do
Streamlit (não há como injetar o conteúdo de um arquivo enviado); a lógica de importação
em si já é testada diretamente em ``test_servicos.py::test_importar_arquivos_so_fontes_manuais``.
"""

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


def test_novo_wacc_calcula_e_aparece_no_historico(bases_dir, repo):
    """Preenche um projeto válido (mesmo cenário de test_calc_modo1._cfg) e calcula."""
    # As bases sintéticas não têm nenhuma linha "bndes_rem*"; acrescenta uma para o formulário
    # poder oferecer uma linha BNDES selecionável (linhas_bndes() filtra por esse prefixo).
    m1._gravar(repo, "parametros_manuais", pd.DataFrame({
        "parametro": ["ir_csll", "rem_x", "bndes_rem_teste"], "valor": [34.0, 1.5, 1.3],
        "unidade": "%", "fonte": "teste", "verificado_em": "2026-01-01", "responsavel": "", "notas": ""}))

    at = _rodar("novo_wacc.py")
    at.text_input(key="nw_projeto").set_value("Projeto Teste App")
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
    at.selectbox(key="nw_linha_bndes_sel").set_value("bndes_rem_teste")
    at.number_input(key="nw_spread").set_value(1.0)
    at.run()
    assert not at.exception

    soma = "\n".join([i.value for i in at.success] + [i.value for i in at.error])
    assert "100.00%" in soma

    at.button(key="nw_botao_calcular").click()
    at.run()
    assert not at.exception, at.exception[0].value if at.exception else None

    metricas = {m.label: m.value for m in at.metric}
    assert "WACC real" in metricas and metricas["WACC real"].endswith("%")

    # o cálculo foi gravado em disco; a página Histórico (nova sessão) deve listá-lo
    at_hist = _rodar("historico.py")
    assert not at_hist.exception
    tabela = at_hist.dataframe[0].value
    assert "Projeto Teste App" in list(tabela["projeto"])


def test_novo_wacc_pesos_diferentes_de_100_bloqueia_calculo(bases_dir):
    at = _rodar("novo_wacc.py")
    at.text_input(key="nw_projeto").set_value("Projeto Incompleto")
    at.number_input(key="nw_fase_peso_0").set_value(70.0)
    at.run()
    assert not at.exception

    erros = "\n".join(i.value for i in at.error)
    assert "100%" in erros
    assert at.button(key="nw_botao_calcular").disabled
