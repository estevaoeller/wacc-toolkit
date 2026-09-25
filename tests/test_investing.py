import shutil

import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.investing import Investing, identificar_serie, interpretar_csv


# ---------- parse offline ----------

def test_interpretar_csv_cds10(fixtures):
    df = interpretar_csv((fixtures / "investing_cds10_brasil_2024.csv").read_bytes())
    assert list(df.columns) == ["data", "ultimo", "abertura", "maxima", "minima"]
    assert str(df["data"].iloc[0]) == "2024-01-05"  # arquivo vem do mais novo para o mais antigo
    assert str(df["data"].iloc[-1]) == "2024-01-02"
    assert len(df) == 4
    assert df["ultimo"].iloc[0] == 255.00


def test_interpretar_csv_descarta_linha_sem_ultimo(fixtures):
    # 03.01.2025 tem "-" em todas as colunas (feriado/erro de cotação) e deve ser descartada
    df = interpretar_csv((fixtures / "investing_cds10_brasil_2025.csv").read_bytes())
    assert len(df) == 3
    assert "2025-01-03" not in {str(d) for d in df["data"]}


def test_interpretar_csv_bom_milhar_e_sufixo_volume(fixtures):
    # BOM UTF-8, "1.234,56" com ponto de milhar, Vol. com sufixos B/M (ignorado), Var% ignorada
    df = interpretar_csv((fixtures / "investing_ibovespa_2025.csv").read_bytes())
    assert len(df) == 4
    assert list(df.columns) == ["data", "ultimo", "abertura", "maxima", "minima"]
    linha = df[df["data"].astype(str) == "2025-01-05"].iloc[0]
    assert linha["ultimo"] == 125432.10
    assert linha["abertura"] == 124980.50


# ---------- roteamento por nome de arquivo ----------

@pytest.mark.parametrize(
    "nome,esperado",
    [
        ("Dados Históricos - CDS Brasil 10 anos (2501 2509).csv", "cds10"),
        ("investing_cds10_brasil_2024.csv", "cds10"),
        ("cds5_2025.csv", "cds5"),
        ("Dados Históricos - CDS Brasil 5 Anos.csv", "cds5"),
        ("Dados Históricos - Ibovespa.csv", "ibov"),
        ("BOVESPA Historical Data.csv", "ibov"),
        ("taxa_selic.csv", None),
        ("qualquer_coisa.csv", None),
        # regressão: intervalo de datas no nome não deve ser confundido com "10 anos"
        ("cds5_planilha_20100101_20260101.csv", "cds5"),
        ("cds10_planilha_20100101_20260101.csv", "cds10"),
        ("Dados Históricos - CDS Brasil 5 Anos (2501 2510).csv", "cds5"),
    ],
)
def test_identificar_serie(nome, esperado):
    assert identificar_serie(nome) == esperado


def test_arquivo_nome_desconhecido_e_ignorado(ctx, repo, fixtures, caplog):
    entrada = ctx.entrada("investing")
    shutil.copy(fixtures / "investing_taxa_selic_2025.csv", entrada / "investing_taxa_selic_2025.csv")

    with caplog.at_level("WARNING"):
        r = executar(Investing(), ctx)

    # nenhum arquivo reconhecido -> coletar() devolve lista vazia -> falha "nenhum arquivo obtido"
    assert r.status == "falhou"
    assert any("não reconhecido" in m for m in caplog.messages)


# ---------- fluxo de acumulação ----------

def _copiar(fixtures, entrada, *nomes):
    for nome in nomes:
        shutil.copy(fixtures / nome, entrada / nome)


def test_primeira_carga(ctx, repo, fixtures):
    entrada = ctx.entrada("investing")
    _copiar(fixtures, entrada, "investing_cds10_brasil_2024.csv")

    r = executar(Investing(), ctx)
    assert r.status == "ok"
    serie = next(s for s in r.series if s.serie == "investing_cds10_brasil")
    assert serie.status == "gravada"
    assert serie.linhas == 4
    assert serie.fim == "2024-01-05"


def test_segunda_carga_com_janela_posterior_acumula(ctx, repo, fixtures):
    entrada = ctx.entrada("investing")
    _copiar(fixtures, entrada, "investing_cds10_brasil_2024.csv")
    executar(Investing(), ctx)

    _copiar(fixtures, entrada, "investing_cds10_brasil_2025.csv")
    r = executar(Investing(), ctx)

    serie = next(s for s in r.series if s.serie == "investing_cds10_brasil")
    assert serie.status == "gravada"
    # 4 linhas de 2024 + 3 válidas de 2025 (uma é descartada por não ter "ultimo")
    assert serie.linhas == 7
    assert serie.fim == "2025-01-05"


def test_mesmo_csv_de_novo_sem_novidade(ctx, repo, fixtures):
    # com as 3 séries do coletor já gravadas (cds10, cds5, ibov), repetir a coleta sem
    # adicionar arquivo novo deve resultar em "sem_novidade" (núcleo não chama interpretar).
    entrada = ctx.entrada("investing")
    _copiar(
        fixtures,
        entrada,
        "investing_cds10_brasil_2024.csv",
        "investing_cds5_brasil_2025.csv",
        "investing_ibovespa_2025.csv",
    )
    executar(Investing(), ctx)

    r = executar(Investing(), ctx)
    assert r.status == "sem_novidade"


def test_multiplas_series_na_mesma_coleta(ctx, repo, fixtures):
    entrada = ctx.entrada("investing")
    _copiar(
        fixtures,
        entrada,
        "investing_cds10_brasil_2025.csv",
        "investing_cds5_brasil_2025.csv",
        "investing_ibovespa_2025.csv",
    )

    r = executar(Investing(), ctx)
    assert r.status == "ok"
    gravadas = {s.serie: s.status for s in r.series}
    assert gravadas == {
        "investing_cds10_brasil": "gravada",
        "investing_cds5_brasil": "gravada",
        "investing_ibov": "gravada",
    }


def test_arquivo_mensal_vai_para_serie_mensal(ctx, repo):
    from wacc_toolkit.collector import executar
    from wacc_toolkit.collectors.investing import Investing

    mensal = ('﻿"Data","Último","Abertura","Máxima","Mínima","Vol.","Var%"\n'
              '"01.03.2025","150,0","150,0","150,0","150,0","","0,00%"\n'
              '"01.02.2025","140,0","140,0","140,0","140,0","","0,00%"\n'
              '"01.01.2025","130,0","130,0","130,0","130,0","","0,00%"\n')
    (ctx.entrada("investing") / "cds10_mensal_teste.csv").write_text(mensal, encoding="utf-8")
    r = executar(Investing(), ctx)
    gravadas = {s.serie for s in r.series if s.status == "gravada"}
    assert gravadas == {"investing_cds10_brasil_mensal"}
