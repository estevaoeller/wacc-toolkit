from datetime import date

import pandas as pd
import pytest

from wacc_toolkit.calc.janelas import interpretar, mes_corte


def test_mes_corte_e_o_ultimo_mes_fechado():
    assert str(mes_corte(date(2026, 1, 16))) == "2025-12"
    assert str(mes_corte(date(2026, 1, 1))) == "2025-12"
    assert str(mes_corte(date(2026, 7, 31))) == "2026-06"


@pytest.mark.parametrize("espec,rotulo,meses", [
    ("12m", "jan/25 a dez/25", 12),
    ("120m", "jan/16 a dez/25", 120),
    ("60m", "jan/21 a dez/25", 60),
    ("30a", "jan/96 a dez/25", 360),
    ("desde:1995-01", "jan/95 a dez/25", 372),
])
def test_rotulo_gerado_pelos_mesmos_parametros(espec, rotulo, meses):
    j = interpretar(espec, pd.Period("2025-12", "M"))
    assert j.rotulo() == rotulo and j.n_meses == meses


def test_anos_usam_ultimo_ano_fechado():
    j = interpretar("10a", pd.Period("2026-06", "M"))
    assert j.rotulo() == "jan/16 a dez/25"


def test_especificacao_invalida():
    with pytest.raises(ValueError):
        interpretar("doze meses", pd.Period("2025-12", "M"))
