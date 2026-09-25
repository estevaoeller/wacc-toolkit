import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.tesouro import Tesouro, interpretar_csv


def test_interpretar_csv_colunas_e_tipos(fixtures):
    df = interpretar_csv((fixtures / "tesouro_td.csv").read_bytes())
    assert list(df.columns) == [
        "data", "titulo", "vencimento", "taxa_compra", "taxa_venda", "pu_compra", "pu_venda", "pu_base",
    ]
    assert len(df) == 25  # 26 linhas na fixture menos o cabeçalho
    assert df["taxa_compra"].dtype.kind == "f"
    assert df["pu_compra"].dtype.kind == "f"


def test_conversao_decimal_com_virgula(fixtures):
    df = interpretar_csv((fixtures / "tesouro_td.csv").read_bytes())
    linha = df[(df["titulo"] == "Tesouro Selic") & (df["vencimento"] == "2028-03-01")].iloc[0]
    assert linha["taxa_compra"] == 0.02
    assert linha["taxa_venda"] == 0.03
    assert linha["pu_compra"] == 19950.41
    assert linha["pu_venda"] == 19937.36


def test_datas_iso(fixtures):
    df = interpretar_csv((fixtures / "tesouro_td.csv").read_bytes())
    # data (Data Base) permanece como date (não string); vencimento é string ISO
    assert str(df["data"].iloc[0]) == "2026-09-24"
    assert df["vencimento"].iloc[0] == "2028-03-01"
    assert all(isinstance(v, str) for v in df["vencimento"])


def test_valor_conhecido_ntnb_juros_semestrais(fixtures):
    df = interpretar_csv((fixtures / "tesouro_td.csv").read_bytes())
    linha = df[
        (df["titulo"] == "Tesouro IPCA+ com Juros Semestrais") & (df["vencimento"] == "2045-05-15")
    ].iloc[0]
    assert linha["taxa_compra"] == 7.35
    assert linha["taxa_venda"] == 7.47
    assert linha["pu_compra"] == 4230.32
    assert linha["pu_venda"] == 4178.38


def test_taxa_negativa_legitima_preservada(fixtures):
    """Taxas negativas (deságio) ocorrem de fato na Tesouro Selic em janelas de juros
    baixos; não devem ser descartadas nem confundidas com erro de parsing."""
    df = interpretar_csv((fixtures / "tesouro_td.csv").read_bytes())
    negativas = df[df["taxa_compra"] < 0]
    assert len(negativas) == 3
    assert set(negativas["titulo"]) == {"Tesouro Selic"}
    assert negativas["taxa_compra"].iloc[0] == -0.01


def test_todos_titulos_presentes_sem_filtro(fixtures):
    """O coletor não filtra por tipo de título — isso é responsabilidade do motor de
    cálculo (ex.: selecionar apenas NTN-B / IPCA+ para o WACC)."""
    df = interpretar_csv((fixtures / "tesouro_td.csv").read_bytes())
    esperados = {
        "Tesouro Selic",
        "Tesouro Prefixado",
        "Tesouro IPCA+ com Juros Semestrais",
        "Tesouro IPCA+",
        "Tesouro IGPM+ com Juros Semestrais",
        "Tesouro Prefixado com Juros Semestrais",
        "Tesouro Renda+ Aposentadoria Extra",
        "Tesouro Educa+",
    }
    assert esperados <= set(df["titulo"])


def test_sem_duplicatas_na_chave(fixtures):
    df = interpretar_csv((fixtures / "tesouro_td.csv").read_bytes())
    assert not df.duplicated(subset=["data", "titulo", "vencimento"]).any()


@pytest.mark.online
def test_tesouro_online(ctx, repo):
    r = executar(Tesouro(), ctx)
    assert r.status == "ok", r
    assert {s.serie for s in r.series} == {s.id for s in Tesouro.series}
