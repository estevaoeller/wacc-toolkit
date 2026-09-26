"""Esquema Variável × Janela: registro, compatibilidade com o formato antigo e data-base mês/ano."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

import test_calc_modo1 as m1
from wacc_toolkit.calc.janelas import acompanha_data_base, descrever, interpretar
from wacc_toolkit.calc.modo1 import ConfigProjeto, Escolha, calcular, risco_brasil, risco_brasil_com_series
from wacc_toolkit.calc.variaveis import GRUPOS_VARIAVEIS, REGISTRO, calcular_grupo, variaveis_do_grupo
from wacc_toolkit.calc.fontes import Bases
from wacc_toolkit.registry import carregar_todos

bases_sinteticas = m1.bases_sinteticas


@pytest.fixture
def bases_sinteticas_novas(repo, bases_sinteticas):
    """Estende ``bases_sinteticas`` (sem alterá-la) com as séries das variáveis novas:
    fred_dgs10, fred_t10yie, damodaran_histretsp, damodaran_ctryprem e investing_cds5_brasil_mensal."""
    dias = pd.bdate_range("1996-01-01", "2025-12-31")
    m1._gravar(repo, "fred_dgs10", pd.DataFrame({"data": dias.date, "valor": 4.0}))
    dias_w = pd.bdate_range("2003-01-01", "2025-12-31")
    m1._gravar(repo, "fred_t10yie", pd.DataFrame({"data": dias_w.date, "valor": 2.3}))
    anos = list(range(1990, 2026))
    m1._gravar(repo, "damodaran_histretsp", pd.DataFrame({
        "ano": anos, "sp500_retorno": 0.10, "tbond10_retorno": 0.05}), "2026")
    m1._gravar(repo, "damodaran_ctryprem", pd.DataFrame({
        "country": ["Brazil"], "regiao": ["Latin America"], "moodys_rating": ["Ba1"],
        "default_spread_rating": [2.0], "equity_risk_premium": [0.09], "country_risk_premium": [0.03]}), "2026")
    cds5 = m1._mensal("2010-01", "2025-12", 0.0).rename(columns={"valor": "ultimo"})
    cds5["ultimo"], cds5["abertura"], cds5["maxima"], cds5["minima"] = 150.0, 150.0, 150.0, 150.0
    m1._gravar(repo, "investing_cds5_brasil_mensal", cds5)
    return Bases(repo)


def test_intervalo_fixo_nao_acompanha_data_base_e_e_limitado_ao_corte():
    j = interpretar("intervalo:2016-01:2030-12", pd.Period("2025-12", "M"))
    assert j.rotulo() == "jan/16 a dez/25"
    assert not acompanha_data_base("intervalo:2016-01:2025-12") and acompanha_data_base("12m")
    assert descrever("120m") == "120 meses (10 anos)" and descrever("30a") == "30 anos-calendário"


def test_todo_grupo_tem_variavel_e_padroes_validos():
    for g in GRUPOS_VARIAVEIS:
        assert variaveis_do_grupo(g), g
    for d in REGISTRO.values():
        for esp in d.janelas.values():
            interpretar(esp, pd.Period("2025-12", "M"))


def test_data_base_vira_mes_e_dia_vira_relatorio_focus():
    cfg = m1._cfg(data_base=date(2026, 1, 16))
    assert cfg.data_base == date(2026, 1, 1) and cfg.focus_relatorio == date(2026, 1, 16)
    cfg2 = m1._cfg(data_base=date(2026, 7, 1))
    assert cfg2.focus_relatorio is None and cfg2.data_focus == date(2026, 7, 31)


def test_escolha_explicita_prevalece_sobre_opcoes(bases_sinteticas):
    cfg = m1._cfg(variaveis={"rf": Escolha("t10_media_mensal", {"janela": "24m"})})
    r = calcular(cfg, bases_sinteticas)
    assert r.componentes["rf"].janela["meses"] == 24
    assert r.componentes["rf"].detalhes["variavel"] == "t10_media_mensal"
    assert cfg.opcoes.rf_janela == "24m"  # opções antigas sincronizadas (usadas nos textos do Excel)


def test_variavel_incompativel_com_grupo(bases_sinteticas):
    cfg = m1._cfg(variaveis={"tlp": Escolha("t10_media_mensal", {"janela": "12m"})})
    with pytest.raises(ValueError, match="não serve ao grupo"):
        calcular(cfg, bases_sinteticas)


def test_toml_com_variaveis(tmp_path, bases_sinteticas):
    from wacc_toolkit import servicos as sv
    cfg = m1._cfg(variaveis={"risco_brasil": Escolha("cds10_vol_ibov_ntnb", {"janela_cds": "12m", "janela_vol": "60m"},
                                                      {"ntnb_vencimento": "2035-05-15"})})
    texto = sv.config_para_toml(cfg)
    assert "[variaveis.risco_brasil]" in texto
    assert ConfigProjeto.de_toml_texto(texto) == cfg


# ------------------------------------------------------------------ variáveis novas
def _corte(cfg):
    from wacc_toolkit.calc.janelas import mes_corte
    return mes_corte(cfg.data_base)


def test_variantes_params_das_variaveis_existentes_e_novas():
    assert REGISTRO["focus_ipca_mediana"].variantes_params == ({"base_calculo": 0}, {"base_calculo": 1})
    assert REGISTRO["cds10_vol_ibov_ntnb"].variantes_params == ({"ntnb_vencimento": "2035-05-15"},)
    assert REGISTRO["dv_fixo"].variantes_params == ({"valor": 0.70},)
    for id_ in ("t10_fechamento_mes", "tbond_retorno_anual_damodaran", "sp500_retorno_anual_damodaran",
               "cds10_sem_multiplicador", "cds5_vol_ibov_ntnb", "damodaran_crp_brasil", "t10yie_media", "dv_fixo"):
        assert id_ in REGISTRO, id_


def test_t10_fechamento_mes(bases_sinteticas_novas):
    cfg = m1._cfg()
    comp = calcular_grupo(bases_sinteticas_novas, cfg, _corte(cfg), "rf", Escolha("t10_fechamento_mes", {"janela": "12m"}))
    assert comp.valor == pytest.approx(0.04)
    assert comp.detalhes["n_meses"] == 12


def test_tbond_retorno_anual_damodaran(bases_sinteticas_novas):
    cfg = m1._cfg()
    esc = Escolha("tbond_retorno_anual_damodaran", {"janela": "intervalo:1995-01:2024-12"})
    comp = calcular_grupo(bases_sinteticas_novas, cfg, _corte(cfg), "rf", esc)
    assert comp.valor == pytest.approx(0.05)
    assert comp.detalhes["n_anos"] == 30


def test_tbond_retorno_anual_damodaran_exige_anos_completos(bases_sinteticas_novas):
    cfg = m1._cfg()
    esc = Escolha("tbond_retorno_anual_damodaran", {"janela": "intervalo:1900-01:1910-12"})
    with pytest.raises(ValueError, match="faltam os anos"):
        calcular_grupo(bases_sinteticas_novas, cfg, _corte(cfg), "rf", esc)


def test_sp500_retorno_anual_damodaran(bases_sinteticas_novas):
    cfg = m1._cfg()
    esc = Escolha("sp500_retorno_anual_damodaran", {"janela": "intervalo:1995-01:2024-12"})
    comp = calcular_grupo(bases_sinteticas_novas, cfg, _corte(cfg), "rm", esc)
    assert comp.valor == pytest.approx(0.10)


def test_cds10_sem_multiplicador(bases_sinteticas_novas):
    cfg = m1._cfg()
    esc = Escolha("cds10_sem_multiplicador", {"janela_cds": "120m"})
    comp = calcular_grupo(bases_sinteticas_novas, cfg, _corte(cfg), "risco_brasil", esc)
    assert comp.valor == pytest.approx(250 / 10_000)


def test_cds5_vol_ibov_ntnb_usa_multiplicador_igual_ao_cds10(bases_sinteticas_novas):
    cfg = m1._cfg()
    corte = _corte(cfg)
    esc = Escolha("cds5_vol_ibov_ntnb", {"janela_cds": "120m", "janela_vol": "60m"},
                 {"ntnb_vencimento": "2035-05-15"})
    comp5 = calcular_grupo(bases_sinteticas_novas, cfg, corte, "risco_brasil", esc)
    comp10 = risco_brasil(bases_sinteticas_novas, corte, cfg.opcoes)
    assert comp5.detalhes["multiplicador"] == pytest.approx(comp10.detalhes["multiplicador"])
    assert comp5.valor == pytest.approx(150 * comp10.detalhes["multiplicador"] / 10_000)


def test_damodaran_crp_brasil(bases_sinteticas_novas):
    cfg = m1._cfg()
    comp = calcular_grupo(bases_sinteticas_novas, cfg, _corte(cfg), "risco_brasil", Escolha("damodaran_crp_brasil"))
    assert comp.valor == pytest.approx(0.03)
    assert comp.janela is None and comp.recortes


def test_t10yie_media(bases_sinteticas_novas):
    cfg = m1._cfg()
    esc = Escolha("t10yie_media", {"janela": "12m"})
    comp = calcular_grupo(bases_sinteticas_novas, cfg, _corte(cfg), "inflacao_us", esc)
    assert comp.valor == pytest.approx(0.023)


def test_dv_fixo(bases_sinteticas):
    cfg = m1._cfg()
    comp_padrao = calcular_grupo(bases_sinteticas, cfg, _corte(cfg), "d_v", Escolha("dv_fixo"))
    assert comp_padrao.valor == pytest.approx(0.70)
    assert comp_padrao.recortes == []
    comp_custom = calcular_grupo(bases_sinteticas, cfg, _corte(cfg), "d_v", Escolha("dv_fixo", {}, {"valor": 0.65}))
    assert comp_custom.valor == pytest.approx(0.65)
