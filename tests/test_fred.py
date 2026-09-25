import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.fred import FRED, interpretar_csv


def test_interpretar_csv_descarta_dias_sem_cotacao(fixtures):
    df = interpretar_csv((fixtures / "fred_DGS10.csv").read_bytes(), "DGS10")
    assert list(df.columns) == ["data", "valor"]
    assert df["valor"].notna().all()
    assert str(df["data"].iloc[0]) == "2025-01-02"
    assert len(df) == 4  # o feriado de 20/01 (vazio) é descartado


def test_formato_antigo_com_ponto(fixtures):
    df = interpretar_csv(b"DATE,DGS10\n2020-01-01,.\n2020-01-02,1.88\n", "DGS10")
    assert len(df) == 1 and df["valor"].iloc[0] == 1.88


@pytest.mark.online
def test_fred_online(ctx, repo):
    r = executar(FRED(), ctx)
    assert r.status == "ok", r
    assert {s.serie for s in r.series} == {s.id for s in FRED.series}
