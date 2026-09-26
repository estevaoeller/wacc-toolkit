"""Variáveis e WACC ao longo do tempo."""

from datetime import date

import pytest

import test_calc_modo1 as m1
from wacc_toolkit.calc.fontes import Bases
from wacc_toolkit.calc.historico import meses, serie_variavel, serie_wacc
from wacc_toolkit.calc.modo1 import Escolha, calcular

bases_sinteticas = m1.bases_sinteticas


def test_meses_inclusivo():
    assert meses("2025-11", "2026-02") == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]


def test_serie_variavel_coincide_com_calculo_pontual(bases_sinteticas):
    cfg = m1._cfg()
    s = serie_variavel(bases_sinteticas, cfg, "tlp", None, "2025-06", "2026-01")
    assert len(s) == 8 and s["erro"].isna().all()
    ultimo = calcular(cfg, bases_sinteticas).componentes["tlp"].valor
    assert s.iloc[-1]["valor"] == pytest.approx(ultimo)
    assert s.iloc[-1]["mes_corte"] == "2025-12"


def test_serie_variavel_registra_meses_sem_dados(bases_sinteticas):
    # as bases sintéticas acabam em dez/2025: a data-base mar/2026 (corte fev/26) não tem cobertura
    s = serie_variavel(bases_sinteticas, m1._cfg(), "rf", Escolha("t10_media_mensal", {"janela": "12m"}),
                       "2026-01", "2026-03")
    assert s["erro"].isna().tolist() == [True, False, False]
    assert "faltam" in s.iloc[-1]["erro"]


def test_serie_wacc_ultima_linha_igual_ao_calculo(bases_sinteticas):
    cfg = m1._cfg()
    s = serie_wacc(bases_sinteticas, cfg, "2025-12", "2026-01")
    assert s.iloc[-1]["wacc_real"] == pytest.approx(calcular(cfg, bases_sinteticas)["wacc_real"])
