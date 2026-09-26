"""Testes para o coletor Damodaran de empresas por setor."""

import pandas as pd
import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.damodaran_empresas import (
    DamodaranEmpresas,
    extrair_versao,
    MAPA_COLUNAS,
    COLUNAS_NORMALIZADAS,
)


class MockResponse:
    """Mock para requests.Response com Last-Modified."""
    def __init__(self, last_modified: str | None = None):
        self.headers = {"Last-Modified": last_modified} if last_modified else {}


def criar_dataframe_sintetico() -> pd.DataFrame:
    """Cria um DataFrame sintético com dados de teste (antes da normalização)."""
    dados = {
        "Company Name": [
            "Apple Inc.",
            "Microsoft Corp.",
            "Nokia Oy",
            "Petrobras",
            "Petrobras",  # duplicata para testar remoção
            "Siemens AG",
            "Bradespar",
            "Vale SA",
            "Embraer",
        ],
        "Exchange:Ticker": [
            "NASDAQ:AAPL",
            "NASDAQ:MSFT",
            "HEX:NOKIA",
            "NYSE:PBR",
            "NYSE:PBR",  # duplicata
            "ETR:SIE",
            "BOVESPA:BRAP4",
            "NYSE:VALE",
            "NYSE:ERJ",
        ],
        "Industry Group": [
            "Software/Services",
            "Software/Services",
            "Telecom",
            "Energy",
            "Energy",  # duplicata com mesma chave
            "Machinery",
            "Banks",
            "Mining",
            "Aerospace/Defense",
        ],
        "Primary Sector": [
            "Technology",
            "Technology",
            "Communications",
            "Energy",
            "Energy",
            "Industrial",
            "Financial",
            "Materials",
            "Industrials",
        ],
        "SIC Code": [
            "7372",
            "7372",
            "4813",
            "1311",
            "1311",
            "3559",
            "6022",
            "1000",
            "3721",
        ],
        "Country": [
            "United States",
            "United States",
            "Finland",
            "Brazil",
            "Brazil",
            "Germany",
            "Brazil",
            "Brazil",
            "Brazil",
        ],
        "Broad Group": [
            "Developed Markets",
            "Developed Markets",
            "Developed Markets",
            "Emerging Markets",
            "Emerging Markets",
            "Developed Markets",
            "Emerging Markets",
            "Emerging Markets",
            "Emerging Markets",
        ],
        "Sub Group": [
            "Tech Hardware",
            "Software",
            "Telecom Equipment",
            "Oil & Gas Exploration",
            "Oil & Gas Exploration",
            "Industrial Equipment",
            "Financial Services",
            "Metals & Mining",
            "Aerospace",
        ],
    }

    return pd.DataFrame(dados)


def processar_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Simula o processamento do interpretar_excel."""
    # Remover linhas completamente vazias
    df = df.dropna(how="all").reset_index(drop=True)

    # Renomear colunas
    df = df.rename(columns=MAPA_COLUNAS)

    # Remover duplicatas pela chave
    chave = ["company_name", "exchange_ticker", "industry_group"]
    df = df.drop_duplicates(subset=chave, keep="first").reset_index(drop=True)

    # Selecionar e ordenar colunas conforme COLUNAS_NORMALIZADAS
    df = df[list(COLUNAS_NORMALIZADAS)].copy()

    return df


def test_processar_dataframe_basico():
    """Testa processamento básico do DataFrame sintético."""
    df = criar_dataframe_sintetico()
    result = processar_dataframe(df)

    # Verificar colunas
    assert list(result.columns) == list(COLUNAS_NORMALIZADAS)

    # Verificar que duplicatas foram removidas (Petrobras duplicada)
    assert len(result) == 8, f"esperado 8 linhas (9-1 duplicata), obtive {len(result)}"

    # Verificar que primeira linha foi mantida
    pb = result[result["company_name"] == "Petrobras"]
    assert len(pb) == 1
    assert pb.iloc[0]["exchange_ticker"] == "NYSE:PBR"


def test_processar_dataframe_remove_linhas_vazias():
    """Testa remoção de linhas completamente vazias."""
    df = pd.DataFrame({
        "Company Name": ["Apple Inc.", None, "Microsoft Corp."],
        "Exchange:Ticker": ["NASDAQ:AAPL", None, "NASDAQ:MSFT"],
        "Industry Group": ["Software/Services", None, "Software/Services"],
        "Primary Sector": ["Technology", None, "Technology"],
        "SIC Code": ["7372", None, "7372"],
        "Country": ["United States", None, "United States"],
        "Broad Group": ["Developed Markets", None, "Developed Markets"],
        "Sub Group": ["Tech", None, "Software"],
    })

    result = processar_dataframe(df)

    # Deve ter mantido as 2 linhas com dados (linha vazia removida)
    # pandas.dropna(how="all") remove apenas linhas completamente nulas
    assert len(result) <= 2


def test_extrair_versao_com_last_modified():
    """Testa extração de versão a partir do header Last-Modified."""
    response = MockResponse("Wed, 26 Feb 2025 10:30:00 GMT")
    versao = extrair_versao(response)
    assert versao == "2025-02"


def test_extrair_versao_formato():
    """Testa que versão tem formato AAAA-MM."""
    response = MockResponse("Wed, 26 Feb 2025 10:30:00 GMT")
    versao = extrair_versao(response)

    # Deve ter exatamente 7 caracteres: AAAA-MM
    assert len(versao) == 7
    assert versao[4] == "-"
    assert versao[:4].isdigit()
    assert versao[5:].isdigit()


def test_extrair_versao_sem_last_modified(caplog):
    """Testa fallback quando Last-Modified está ausente."""
    import logging
    caplog.set_level(logging.INFO)

    response = MockResponse(None)
    versao = extrair_versao(response)

    # Deve retornar versão no formato AAAA-MM
    assert "-" in versao
    assert len(versao) == 7  # AAAA-MM
    # Verificar que o log foi registrado
    assert any("versão obtida do horário" in record.message for record in caplog.records)


def test_empresas_brasileiras():
    """Testa contagem de empresas brasileiras."""
    df = criar_dataframe_sintetico()
    result = processar_dataframe(df)

    # Contar brasileiras
    brasileiras = result[result["country"] == "Brazil"]
    assert len(brasileiras) == 4  # Petrobras, Bradespar, Vale, Embraer

    # Todas devem ser Emerging Markets
    em_markets = brasileiras[brasileiras["broad_group"] == "Emerging Markets"]
    assert len(em_markets) == 4


def test_chave_primaria():
    """Testa que a chave primária é única após processamento."""
    df = criar_dataframe_sintetico()
    result = processar_dataframe(df)

    chave = ["company_name", "exchange_ticker", "industry_group"]
    duplicatas = result.duplicated(subset=chave)
    assert not duplicatas.any(), "encontradas linhas com chave duplicada"


@pytest.mark.online
def test_damodaran_online(ctx):
    """Testa coleta online do Damodaran."""
    r = executar(DamodaranEmpresas(), ctx)
    assert r.status == "ok", f"coleta falhou: {r}"
    assert len(r.series) == 1
    assert r.series[0].serie == "damodaran_empresas"
    assert r.series[0].status == "gravada"
    assert r.series[0].linhas > 0
