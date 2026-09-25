"""Camada de serviços usada pela interface."""

from datetime import date

import pytest

import test_calc_modo1 as m1
from wacc_toolkit import servicos as sv
from wacc_toolkit.calc.modo1 import ConfigProjeto

bases_sinteticas = m1.bases_sinteticas


@pytest.fixture
def amb(tmp_path, bases_sinteticas):
    return sv.ambiente(tmp_path / "bases")


def test_ambiente_cria_projetos_e_calculos_ao_lado_das_bases(amb, tmp_path):
    assert amb.projetos == tmp_path / "Projetos" and amb.projetos.exists()
    assert amb.calculos == tmp_path / "Calculos" and amb.calculos.exists()


def test_toml_ida_e_volta(amb):
    cfg = m1._cfg(spread_descricao="Financ. BNDES", spread_fonte='texto com "aspas" e acentuação', notas="n")
    caminho = sv.salvar_projeto(amb, cfg, "teste")
    volta = sv.carregar_projeto(caminho)
    assert volta == cfg
    with pytest.raises(FileExistsError):
        sv.salvar_projeto(amb, cfg, "teste")
    assert sv.listar_projetos(amb) == [caminho]


def test_status_setores_linhas(amb):
    st = sv.status_bases(amb)
    assert {"serie", "fim", "linhas", "avisos"} <= set(st.columns)
    assert st.set_index("serie").loc["fred_gs10", "fim"] == "2025-12-01"
    assert sv.setores_damodaran(amb, "global", date(2026, 1, 16)) == ["Setor A", "Setor B"]
    assert sv.linhas_bndes(amb) == {}  # parâmetros sintéticos não têm linhas bndes_rem*


def test_calcular_listar_comparar(amb):
    c1 = sv.calcular_projeto(amb, m1._cfg(), excel=False)
    c2 = sv.calcular_projeto(amb, m1._cfg(spread_credito=0.02), excel=False)
    lista = sv.listar_calculos(amb)
    assert len(lista) == 2 and lista["wacc_real"].notna().all()
    comp = sv.comparar_calculos(amb, c1.registro.name, c2.registro.name).set_index("id")
    assert comp.loc["spread_credito", "dif_bp"] == pytest.approx(100)
    assert comp.loc["beta_u", "dif_bp"] == pytest.approx(0)
    assert list(sv.tabela_resultado(c1.resultado)["id"])[-1] == "wacc_nominal"


def test_importar_arquivos_so_fontes_manuais(amb):
    with pytest.raises(ValueError):
        sv.importar_arquivos(amb, "fred", [("x.csv", b"a")])
    csv = ('﻿"Data","Último","Abertura","Máxima","Mínima","Var%"\n'
           '"01.02.2026","210,0","210,0","210,0","210,0","0,00%"\n'
           '"01.01.2026","200,0","200,0","200,0","200,0","0,00%"\n').encode("utf-8")
    r = sv.importar_arquivos(amb, "investing", [("CDS Brasil 10 anos.csv", csv)])
    assert r.status == "ok"


def test_catalogo_cobre_padroes():
    from wacc_toolkit.calc.modo1 import Opcoes
    op = Opcoes()
    for campo, opcoes in sv.CATALOGO_OPCOES.items():
        assert getattr(op, campo) in opcoes, campo


def test_config_invalida_nao_e_gravada(amb):
    with pytest.raises(ValueError):
        sv.nova_config(projeto="x", data_base=date(2026, 1, 1), fases=[{"setor": "Setor A", "peso": 0.7}],
                       linha_bndes="rem_x", spread_credito=0.01)
    assert isinstance(sv.nova_config(projeto="x", data_base=date(2026, 1, 1),
                                     fases=[{"setor": "Setor A", "peso": 1.0}], linha_bndes="rem_x",
                                     spread_credito=0.01), ConfigProjeto)


def test_formatacao_pt_br():
    assert sv.formatar_numero_pt(1234.5, 2) == "1.234,50"
    assert sv.formatar_percentual_pt(0.105841, 2) == "10,58%"
    assert sv.formatar_valor_componente("beta_u", 0.61) == "0,61"
    assert sv.formatar_valor_componente("beta_l", 0.9336) == "0,934"
    assert sv.formatar_valor_componente("d_v", 0.4455) == "44,5%"
    assert sv.formatar_valor_componente("t", 0.34) == "34,0%"
    assert sv.formatar_valor_componente("wacc_real", 0.1058) == "10,58%"


def test_tabela_custo_de_capital_mesmos_rotulos_do_excel(amb):
    """A tela usa exatamente os mesmos nomes de item e descrições da aba Custo de Capital."""
    from wacc_toolkit.saida.rotulos import ROTULOS

    calculo = sv.calcular_projeto(amb, m1._cfg(), excel=False)
    tabela = sv.tabela_custo_de_capital(calculo.resultado)
    assert list(tabela["secao"]) == ["KE"] * 12 + ["KD"] * 6 + ["WACC"] * 2
    assert list(tabela["item"])[:3] == [ROTULOS["rf"], ROTULOS["rm"], ROTULOS["rf_estrutural"]]
    assert "id" not in tabela.columns
    # linhas compostas (ERP, beta realavancado, Ke/Kd nominal e real) ficam sem descrição
    erp = tabela.set_index("item").loc[ROTULOS["erp"]]
    assert erp["descricao"] == ""
    rf = tabela.set_index("item").loc[ROTULOS["rf"]]
    assert rf["descricao"].startswith("T-10 12 meses")

    # o mesmo, a partir do registro salvo em disco (histórico) — sem recalcular
    import json
    dados = json.loads(calculo.registro.read_text(encoding="utf-8"))
    tabela_registro = sv.tabela_custo_de_capital_de_registro(dados)
    pd_testing_ok = tabela.reset_index(drop=True).equals(tabela_registro.reset_index(drop=True))
    assert pd_testing_ok


def test_series_opcionais_definidas():
    assert sv.SERIES_OPCIONAIS == {
        "investing_cds10_brasil", "investing_cds5_brasil", "investing_ibov_mensal", "investing_cds5_brasil_mensal",
    }


def test_linhas_bndes_sem_id_tecnico(amb, repo):
    import pandas as pd

    m1._gravar(repo, "parametros_manuais", pd.DataFrame({
        "parametro": ["ir_csll", "bndes_rem_teste"], "valor": [34.0, 1.3], "unidade": "%",
        "fonte": ["teste", "BNDES Finem: Água, esgoto e resíduos sólidos (página do produto: 'a partir de 1,3% a.a.')"],
        "verificado_em": "2026-01-01", "responsavel": "", "notas": ""}))
    linhas = sv.linhas_bndes(amb)
    assert linhas == {"bndes_rem_teste": "Finem: Água, esgoto e resíduos sólidos (1,30% a.a.)"}
