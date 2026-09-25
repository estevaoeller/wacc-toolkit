import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.yahoo import Yahoo, interpretar_chart_json


def test_interpretar_bvsp_datas_e_fechamento_ajustado(fixtures):
    df = interpretar_chart_json((fixtures / "yahoo_bvsp.json").read_bytes(), "^BVSP")
    assert list(df.columns) == ["data", "fechamento", "fechamento_ajustado"]
    # primeiro pregão: timestamp 735915600 (UTC) + gmtoffset -10800 -> 1993-04-27 local,
    # não 1993-04-28 (o que aconteceria se usássemos a data em UTC puro).
    assert str(df["data"].iloc[0]) == "1993-04-27"
    assert str(df["data"].iloc[-1]) == "2026-09-25"
    assert df["fechamento"].iloc[0] == pytest.approx(24.5)
    # fechamento_ajustado == fechamento quando não há adjclose diferente
    assert (df["fechamento_ajustado"] == df["fechamento"]).all()


def test_interpretar_descarta_linha_com_close_nulo(fixtures):
    df = interpretar_chart_json((fixtures / "yahoo_bvsp.json").read_bytes(), "^BVSP")
    assert df["fechamento"].notna().all()
    # a fixture inclui um timestamp com close nulo (739717200); confirma que foi descartado
    assert 9 <= len(df) <= 14  # 15 timestamps na fixture, 1 nulo descartado


def test_interpretar_ticker_inesperado_falha(fixtures):
    with pytest.raises(ValueError):
        interpretar_chart_json((fixtures / "yahoo_bvsp.json").read_bytes(), "^SP500TR")


def test_interpretar_sp500tr(fixtures):
    df = interpretar_chart_json((fixtures / "yahoo_sp500tr.json").read_bytes(), "^SP500TR")
    assert str(df["data"].iloc[0]) == "1988-01-04"
    assert df["fechamento"].notna().all()


@pytest.mark.online
def test_yahoo_online(ctx, repo):
    r = executar(Yahoo(), ctx)
    assert r.status == "ok", r
    assert {s.serie for s in r.series} == {s.id for s in Yahoo.series}
