import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.b3 import B3, interpretar_b3_json


def test_interpretar_2024_datas_e_numero_br(fixtures):
    df = interpretar_b3_json((fixtures / "b3_2024.json").read_bytes(), 2024)
    assert list(df.columns) == ["data", "fechamento"]
    assert str(df["data"].iloc[0]) == "2024-01-02"
    assert str(df["data"].iloc[-1]) == "2024-12-30"
    # "132.696,63" -> 132696.63 (separador de milhar '.' e decimal ',')
    assert df.loc[df["data"].astype(str) == "2024-01-02", "fechamento"].iloc[0] == pytest.approx(132696.63)
    assert df["fechamento"].notna().all()


def test_interpretar_descarta_dia_31_de_mes_curto(fixtures):
    # a fixture de 2025 tem day=31 com rateValue4 (31 de abril, data inexistente) nulo;
    # a linha correspondente não deve aparecer na série.
    df = interpretar_b3_json((fixtures / "b3_2025.json").read_bytes(), 2025)
    assert "2025-04-31" not in df["data"].astype(str).values
    # mas 31 de janeiro (dia/mês válidos) deve estar presente
    assert "2025-01-31" in df["data"].astype(str).values


def test_interpretar_sem_results_falha():
    with pytest.raises(ValueError):
        interpretar_b3_json(b'{"min": {}, "max": {}, "results": []}', 2025)


@pytest.mark.online
def test_b3_online(ctx, repo):
    r = executar(B3(), ctx)
    assert r.status == "ok", r
    assert {s.serie for s in r.series} == {"b3_ibov"}


@pytest.mark.online
def test_b3_yahoo_validacao_cruzada(ctx, repo):
    from wacc_toolkit.collectors.yahoo import Yahoo

    r_b3 = executar(B3(), ctx)
    r_yahoo = executar(Yahoo(), ctx)
    assert r_b3.status == "ok", r_b3
    assert r_yahoo.status == "ok", r_yahoo

    df_b3 = ctx.repo.ler_serie(B3().spec("b3_ibov"))
    df_yahoo = ctx.repo.ler_serie(Yahoo().spec("yahoo_ibov"))

    m = df_b3.merge(df_yahoo, on="data", suffixes=("_b3", "_yahoo")).sort_values("data")
    m = m.tail(10)
    assert len(m) >= 5, "poucas datas em comum entre B3 e Yahoo para validar"

    diff_relativa = (m["fechamento_b3"] - m["fechamento_yahoo"]).abs() / m["fechamento_b3"]
    assert (diff_relativa < 0.005).all(), m.assign(diff=diff_relativa)
