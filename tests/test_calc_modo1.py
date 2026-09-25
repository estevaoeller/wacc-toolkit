"""Motor do modo 1: fórmulas de composição e cálculo ponta a ponta em bases sintéticas."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from wacc_toolkit.calc.fontes import Bases
from wacc_toolkit.calc.modo1 import ConfigProjeto, Fase, calcular, compor
from wacc_toolkit.registry import carregar_todos


def test_compor_reproduz_formulas_da_planilha():
    """Insumos e resultados em cache da aba Custo de Capital de uma aplicação real do modo 1."""
    r = compor(rf=0.043000000000000003, rf_estrutural=0.035738564229998056, rm=0.1105043988779002,
               risco_brasil=0.0480001292530314, beta_u=0.6100684079065406, d_v=0.44549294340979884, t=0.34,
               inflacao_us=0.02281816583808825, tlp=0.07581666666666666, remuneracao=0.013,
               spread=0.013997704866725913, ipca=0.035820000000000005)
    assert r["beta_l"] == pytest.approx(0.9335549542779603, abs=1e-15)
    assert r["ke_nominal"] == pytest.approx(0.16079814459930725, abs=1e-15)
    assert r["kd_nominal"] == pytest.approx(0.14443737741034912, abs=1e-15)
    assert r["kd_real"] == pytest.approx(0.10486124752403803, abs=1e-15)
    assert r["wacc_nominal"] == pytest.approx(0.13163195525154017, abs=1e-15)


# ------------------------------------------------------------------ bases sintéticas
def _gravar(repo, serie, df, versao=None):
    spec = next(s for c in carregar_todos().values() for s in c.series if s.id == serie)
    repo.gravar_serie(spec, df, [], [], versao)


def _mensal(inicio, fim, valor):
    idx = pd.period_range(inicio, fim, freq="M").to_timestamp()
    return pd.DataFrame({"data": idx.date, "valor": valor})


@pytest.fixture
def bases_sinteticas(repo):
    dias = pd.bdate_range("1994-12-01", "2025-12-31")
    rng = np.random.default_rng(0)
    _gravar(repo, "fred_gs10", _mensal("1990-01", "2025-12", 4.0))
    _gravar(repo, "fred_fii10", _mensal("2003-01", "2025-12", 2.0))
    _gravar(repo, "yahoo_sp500tr", pd.DataFrame({"data": dias.date, "fechamento": 1000 * 1.0004 ** np.arange(len(dias)),
                                                 "fechamento_ajustado": np.nan}))
    ibov = 50000 * np.exp(np.cumsum(rng.normal(0, 0.012, len(dias))))
    _gravar(repo, "b3_ibov", pd.DataFrame({"data": dias.date, "fechamento": ibov}))
    pu = 4000 * np.exp(np.cumsum(rng.normal(0, 0.006, len(dias))))
    _gravar(repo, "tesouro_td_taxas", pd.DataFrame({
        "data": dias.date, "titulo": "Tesouro IPCA+ com Juros Semestrais", "vencimento": "2035-05-15",
        "taxa_compra": 6.0, "taxa_venda": 6.1, "pu_compra": pu, "pu_venda": pu, "pu_base": pu}))
    cds = _mensal("2010-01", "2025-12", 0.0).rename(columns={"valor": "ultimo"})
    cds["ultimo"], cds["abertura"], cds["maxima"], cds["minima"] = 250.0, 250.0, 250.0, 250.0
    _gravar(repo, "investing_cds10_brasil_mensal", cds)
    _gravar(repo, "bcb_tlp", _mensal("2018-01", "2025-12", 6.0))
    _gravar(repo, "bcb_focus_ipca_anual", pd.DataFrame({
        "data": [date(2026, 1, 16)] * 4, "ano_referencia": [2026, 2027, 2028, 2029], "base_calculo": 0,
        "mediana": [4.0, 3.5, 3.0, 3.0], "media": np.nan, "desvio_padrao": np.nan, "minimo": np.nan,
        "maximo": np.nan, "respondentes": 100}))
    setores = ["Setor A", "Setor B"]
    beta = pd.DataFrame({"industry_name": setores, "number_of_firms": 10, "beta": 1.0, "de_ratio": 0.5,
                         "effective_tax_rate": 0.2, "unlevered_beta": 0.7, "cash_to_firm_value": 0.05,
                         "unlevered_beta_corrected_for_cash": [0.8, 0.6]})
    _gravar(repo, "damodaran_beta_global", beta, "2026")
    spec_dbt = next(s for c in carregar_todos().values() for s in c.series if s.id == "damodaran_dbtfund_global")
    dbt = pd.DataFrame({c: 0.0 for c in spec_dbt.colunas}, index=[0, 1])
    dbt["industry_name"], dbt["market_de_unadjusted"] = setores, [1.0, 0.5]
    _gravar(repo, "damodaran_dbtfund_global", dbt, "2026")
    _gravar(repo, "parametros_manuais", pd.DataFrame({
        "parametro": ["ir_csll", "rem_x"], "valor": [34.0, 1.5], "unidade": "%", "fonte": "teste",
        "verificado_em": "2026-01-01", "responsavel": "", "notas": ""}))
    return Bases(repo)


def _cfg(**kw):
    base = dict(projeto="Teste", data_base=date(2026, 1, 16), fases=[Fase("Setor A", 0.4), Fase("Setor B", 0.6)],
                linha_bndes="rem_x", spread_credito=0.01)
    return ConfigProjeto(**{**base, **kw})


def test_calculo_ponta_a_ponta(bases_sinteticas):
    r = calcular(_cfg(), bases_sinteticas)
    assert r.corte == "2025-12"
    assert r["rf"] == pytest.approx(0.04) and r["rf_estrutural"] == pytest.approx(0.04)
    assert r["tlp"] == pytest.approx(0.06)
    assert r["beta_u"] == pytest.approx(0.4 * 0.8 + 0.6 * 0.6)
    assert r["d_v"] == pytest.approx(0.4 * 0.5 + 0.6 * (0.5 / 1.5))
    assert r["ipca"] == pytest.approx((4.0 + 3.5 + 3.0 * 8) / 10 / 100)  # 2030–2035 repetem 2029
    assert r["inflacao_us"] == pytest.approx(1.04 / 1.02 - 1)
    assert r.componentes["rf"].rotulo == "T-10 12m (jan/25 a dez/25)"
    rb = r.componentes["risco_brasil"].detalhes
    assert rb["cds_medio_bps"] == pytest.approx(250) and rb["n_cds"] == 120
    assert r["risco_brasil"] == pytest.approx(250 * rb["multiplicador"] / 1e4)
    assert all(rec.sha256_csv for c in r.componentes.values() for rec in c.recortes)


def test_pesos_devem_somar_um():
    with pytest.raises(ValueError, match="somar 1"):
        _cfg(fases=[Fase("Setor A", 0.5), Fase("Setor B", 0.6)])


def test_base_desatualizada_e_erro_claro(bases_sinteticas):
    with pytest.raises(ValueError, match="faltam"):
        calcular(_cfg(data_base=date(2026, 6, 1)), bases_sinteticas)


def test_setor_inexistente(bases_sinteticas):
    with pytest.raises(KeyError, match="Setor Z"):
        calcular(_cfg(fases=[Fase("Setor Z", 1.0)]), bases_sinteticas)


def test_cds_mensal_completado_pela_serie_diaria(repo, bases_sinteticas):
    """Meses sem CDS mensal usam o último pregão do mês da série diária (fonte manual do Investing)."""
    cds = _mensal("2010-01", "2025-06", 0.0).rename(columns={"valor": "ultimo"})
    cds["ultimo"], cds["abertura"], cds["maxima"], cds["minima"] = 250.0, 250.0, 250.0, 250.0
    _gravar(repo, "investing_cds10_brasil_mensal", cds)
    dias = pd.bdate_range("2025-06-01", "2025-12-31")
    d = pd.DataFrame({"data": dias.date, "ultimo": 100.0, "abertura": 1.0, "maxima": 1.0, "minima": 1.0})
    d.loc[d.groupby(pd.to_datetime(d["data"]).dt.to_period("M"))["data"].idxmax(), "ultimo"] = 310.0
    _gravar(repo, "investing_cds10_brasil", d)
    r = calcular(_cfg(), Bases(repo))
    rb = r.componentes["risco_brasil"]
    assert rb.detalhes["n_cds"] == 120
    assert rb.detalhes["cds_medio_bps"] == pytest.approx((114 * 250 + 6 * 310) / 120)  # jul–dez/25 do diário
    assert list(rb.recortes[0].df["origem"]).count("diário (último pregão)") == 6
    assert rb.recortes[-1].serie == "investing_cds10_brasil"
