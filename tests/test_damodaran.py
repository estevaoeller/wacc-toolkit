import pandas as pd
import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.damodaran import Damodaran, extrair_versao, interpretar_arquivo

from fixtures.damodaran_gerar import (
    planilha_beta_setor,
    planilha_beta_setor_legado_layout_invalido,
    planilha_beta_setor_legado_sheet1,
    planilha_beta_setor_sem_data,
    planilha_ctryprem,
    planilha_dbtfund_setor,
    planilha_dbtfund_setor_legado_13col,
    planilha_dbtfund_setor_legado_5col,
    planilha_histretsp,
    planilha_totalbeta_setor,
)


# ---------- parse offline sobre planilhas sintéticas ----------

def test_beta_setor_versao_colunas_e_valor():
    versao, df = interpretar_arquivo(planilha_beta_setor(), "betaGlobal")
    assert versao == "2026"
    assert list(df.columns) == [
        "industry_name", "number_of_firms", "beta", "de_ratio", "effective_tax_rate",
        "unlevered_beta", "cash_to_firm_value", "unlevered_beta_corrected_for_cash",
    ]
    assert len(df) == 3
    linha = df[df["industry_name"] == "Setor Alfa"].iloc[0]
    assert linha["unlevered_beta_corrected_for_cash"] == pytest.approx(0.82)
    assert linha["number_of_firms"] == 42


def test_beta_setor_ignora_colunas_extras_de_ano():
    # a fixture inclui "HiLo Risk", "2024", "2025" após a tabela estável — não
    # devem aparecer nas colunas tratadas.
    _, df = interpretar_arquivo(planilha_beta_setor(), "betaemerg")
    assert "HiLo Risk" not in df.columns
    assert "2024" not in df.columns


def test_totalbeta_setor():
    versao, df = interpretar_arquivo(planilha_totalbeta_setor(), "totalbetaGlobal")
    assert versao == "2026"
    assert list(df.columns) == [
        "industry_name", "number_of_firms", "average_unlevered_beta", "average_levered_beta",
        "average_correlation_with_market", "total_unlevered_beta", "total_levered_beta",
    ]
    linha = df[df["industry_name"] == "Setor Beta"].iloc[0]
    assert linha["total_unlevered_beta"] == pytest.approx(5.53)


def test_dbtfund_setor_debt_to_ebitda_extremo_preservado():
    # caso de borda da fonte: Debt to EBITDA pode divergir bastante quando o
    # EBITDA do setor está perto de zero — o parser deve preservar o valor tal
    # como publicado (sem faixa que rejeite outliers legítimos).
    versao, df = interpretar_arquivo(planilha_dbtfund_setor(), "dbtfundGlobal")
    assert versao == "2026"
    linha = df[df["industry_name"] == "Setor Beta"].iloc[0]
    assert linha["debt_to_ebitda"] == pytest.approx(-9000.0)
    assert Damodaran().spec("damodaran_dbtfund_global").faixa is None


def test_ctryprem_descarta_segunda_tabela_e_renomeia_coluna_de_regiao():
    # a 2a coluna real do Damodaran vem com o cabeçalho errado (nome de um
    # valor em vez de "Region"); nomeamos por posição. A tabela solta
    # "Frontier Markets..." abaixo deve ser descartada.
    versao, df = interpretar_arquivo(planilha_ctryprem(), "ctryprem")
    assert versao == "2026"
    assert list(df.columns) == [
        "country", "regiao", "moodys_rating", "default_spread_rating",
        "equity_risk_premium", "country_risk_premium",
    ]
    assert list(df["country"]) == ["Paisalandia", "Paisonia", "Terra do Nunca"]
    assert "Pais Fronteira" not in set(df["country"])
    linha = df[df["country"] == "Paisonia"].iloc[0]
    assert linha["country_risk_premium"] == pytest.approx(0.046)


def test_histretsp_descarta_linhas_de_resumo():
    versao, df = interpretar_arquivo(planilha_histretsp(), "histretSP")
    assert versao == "2026"
    assert list(df["ano"]) == [2023, 2024, 2025]
    linha = df[df["ano"] == 2024].iloc[0]
    assert linha["sp500_retorno"] == pytest.approx(-0.05)
    assert linha["tbond10_retorno"] == pytest.approx(-0.02)


def test_falha_clara_quando_nao_ha_data_de_atualizacao():
    import io

    import pandas as pd

    df0 = pd.read_excel(io.BytesIO(planilha_beta_setor_sem_data()), sheet_name="Industry Averages", header=None)
    with pytest.raises(ValueError, match="Date updated"):
        extrair_versao(df0)


def test_interpretar_arquivo_falha_clara_sem_data():
    with pytest.raises(ValueError):
        interpretar_arquivo(planilha_beta_setor_sem_data(), "betaGlobal")


# ---------- parse de edições históricas (arquivadas) sintéticas ----------

def test_beta_setor_legado_sheet1_sem_data_usa_fallback_ano_arquivo():
    # betaGlobal11.xls: sem "Date updated", cabeçalho em caixa baixa ("Industry
    # name") na 1a linha da única aba ("Sheet1"). ano_arquivo_fallback=2011
    # (do nome do arquivo) -> versão publicada = 2012.
    versao, df = interpretar_arquivo(
        planilha_beta_setor_legado_sheet1(), "betaGlobal", ano_arquivo_fallback=2011,
    )
    assert versao == "2012"
    assert list(df.columns) == [
        "industry_name", "number_of_firms", "beta", "de_ratio", "effective_tax_rate",
        "unlevered_beta", "cash_to_firm_value", "unlevered_beta_corrected_for_cash",
    ]
    linha = df[df["industry_name"] == "Setor Alfa"].iloc[0]
    assert linha["unlevered_beta_corrected_for_cash"] == pytest.approx(0.82)


def test_beta_setor_legado_layout_invalido_falha_claro():
    # betas98.xls: layout de colunas totalmente diferente nas posições das
    # colunas obrigatórias — deve falhar claro, não interpretar a coluna errada.
    with pytest.raises(ValueError, match="layout de beta por setor inesperado"):
        interpretar_arquivo(
            planilha_beta_setor_legado_layout_invalido(), "betas", ano_arquivo_fallback=1998,
        )


def test_dbtfund_legado_5col_colunas_ausentes_viram_nan():
    # dbtfundGlobal11.xls: só 5 das 15 colunas atuais existem.
    versao, df = interpretar_arquivo(
        planilha_dbtfund_setor_legado_5col(), "dbtfundGlobal", ano_arquivo_fallback=2011,
    )
    assert versao == "2012"
    assert list(df.columns) == list(
        (
            "industry_name", "number_of_firms", "book_debt_to_capital",
            "market_debt_to_capital_unadjusted", "market_de_unadjusted",
            "market_debt_to_capital_adjusted_leases", "market_de_adjusted_leases",
            "interest_coverage_ratio", "debt_to_ebitda", "effective_tax_rate",
            "institutional_holdings", "std_dev_stock_prices", "ebitda_ev",
            "net_ppe_total_assets", "capex_total_assets",
        )
    )
    linha = df[df["industry_name"] == "Setor Beta"].iloc[0]
    assert linha["market_de_unadjusted"] == pytest.approx(0.18)
    assert linha["effective_tax_rate"] == pytest.approx(0.19)
    assert pd.isna(linha["book_debt_to_capital"])
    assert pd.isna(linha["interest_coverage_ratio"])
    assert pd.isna(linha["debt_to_ebitda"])


def test_dbtfund_legado_13col_sem_interest_coverage_nem_debt_to_ebitda():
    # dbtfundGlobal19.xls: aba "Variables & FAQ" (sem tabela) + "Industry
    # Averages" com 13 colunas (falta Interest Coverage Ratio e Debt to EBITDA,
    # que só existem a partir de ~2022).
    versao, df = interpretar_arquivo(planilha_dbtfund_setor_legado_13col(), "dbtfundGlobal")
    assert versao == "2019"
    linha = df[df["industry_name"] == "Setor Alfa"].iloc[0]
    assert linha["book_debt_to_capital"] == pytest.approx(0.40)
    assert linha["ebitda_ev"] == pytest.approx(0.12)
    assert linha["capex_total_assets"] == pytest.approx(0.05)
    assert pd.isna(linha["interest_coverage_ratio"])
    assert pd.isna(linha["debt_to_ebitda"])


def test_ano_do_codigo_mapeia_aa_para_ano_de_4_digitos():
    from wacc_toolkit.collectors.damodaran import _ano_do_codigo

    assert _ano_do_codigo("11") == 2011
    assert _ano_do_codigo("24") == 2024
    assert _ano_do_codigo("00") == 2000
    assert _ano_do_codigo("98") == 1998
    assert _ano_do_codigo("99") == 1999


# ---------- coleta do histórico arquivado (_coletar_historico) ----------

def test_coletar_historico_nao_baixa_anos_ja_existentes(ctx, repo, monkeypatch):
    import wacc_toolkit.collectors.damodaran as mod

    monkeypatch.setattr(mod, "_HISTORICO", {"betaGlobal": ("betaGlobal{aa}.xls", ("11", "12"))})
    monkeypatch.setattr(mod, "PAUSA_ENTRE_DOWNLOADS_HISTORICO", 0)

    # pré-grava a versão "2012" (AA=11 -> 2011+1) para o repositório já ter essa
    # edição; só "2013" (AA=12) deveria ser considerada faltante.
    spec = Damodaran().spec("damodaran_beta_global")
    caminho = repo.caminho_serie(spec, "2012")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("industry_name,number_of_firms,beta,de_ratio,effective_tax_rate,"
                        "unlevered_beta,cash_to_firm_value,unlevered_beta_corrected_for_cash\n")

    pedidos = []

    def baixar_espiao(sessao, url, **kwargs):
        pedidos.append(url)
        raise ConnectionError("nao deveria ser chamado para a versao ja existente")

    monkeypatch.setattr(mod, "baixar", baixar_espiao)

    arquivos = Damodaran()._coletar_historico(ctx)
    assert arquivos == []  # baixar sempre falha neste teste, mas o importante é o que foi pedido
    assert all("betaGlobal11.xls" not in u for u in pedidos)
    assert any("betaGlobal12.xls" in u for u in pedidos)


def test_coletar_historico_404_nao_derruba_a_coleta(ctx, monkeypatch):
    import requests

    import wacc_toolkit.collectors.damodaran as mod

    monkeypatch.setattr(mod, "_HISTORICO", {"betaGlobal": ("betaGlobal{aa}.xls", ("11", "12"))})
    monkeypatch.setattr(mod, "PAUSA_ENTRE_DOWNLOADS_HISTORICO", 0)

    def baixar_falso(sessao, url, **kwargs):
        if "betaGlobal11.xls" in url:
            raise requests.HTTPError("404 simulado")
        class Resp:
            content = planilha_beta_setor_legado_sheet1()
        return Resp()

    monkeypatch.setattr(mod, "baixar", baixar_falso)

    arquivos = Damodaran()._coletar_historico(ctx)
    rotulos = {a.rotulo for a in arquivos}
    assert rotulos == {"betaGlobal_12"}


# ---------- importação local via entrada/damodaran/ ----------

def test_importacao_local_mesmo_rotulo_que_web(ctx, repo, monkeypatch):
    import wacc_toolkit.collectors.damodaran as mod

    # este teste roda executar() por completo (não só _coletar_entrada), então sem
    # mockar baixar()/esvaziar o histórico ele bateria na rede de verdade para os
    # arquivos correntes e para ~15 anos x 5 arquivos do histórico: mantém offline
    # e rápido, sem mudar o que o teste verifica (import local prevalece).
    monkeypatch.setattr(mod, "_HISTORICO", {})

    def baixar_falso(sessao, url, **kwargs):
        raise ConnectionError("sem rede neste teste")

    monkeypatch.setattr(mod, "baixar", baixar_falso)

    entrada = ctx.entrada("damodaran") / "2026"
    entrada.mkdir(parents=True, exist_ok=True)
    (entrada / "betaGlobal.xls").write_bytes(planilha_beta_setor())

    arquivos = Damodaran()._coletar_entrada(ctx)
    assert len(arquivos) == 1
    assert arquivos[0].rotulo == "betaGlobal"
    assert arquivos[0].extensao == "xls"

    r = executar(Damodaran(), ctx)
    assert r.status == "ok", r
    df = repo.ler_serie(Damodaran().spec("damodaran_beta_global"), "2026")
    assert len(df) == 3


def test_coletar_entrada_ignora_quando_pasta_vazia(ctx):
    assert Damodaran()._coletar_entrada(ctx) == []


def test_coletar_web_nao_derruba_as_demais_quando_uma_url_falha(ctx, monkeypatch):
    import wacc_toolkit.collectors.damodaran as mod

    def baixar_falso(sessao, url, **kwargs):
        class Resp:
            content = planilha_beta_setor()
        if "betas.xls" in url:
            raise ConnectionError("404 simulado")
        return Resp()

    monkeypatch.setattr(mod, "baixar", baixar_falso)
    arquivos = Damodaran()._coletar_web(ctx)
    rotulos = {a.rotulo for a in arquivos}
    assert "betas" not in rotulos
    assert "betaGlobal" in rotulos
    assert len(arquivos) == len(mod._ARQUIVOS) - 1


# ---------- coleta online completa ----------

@pytest.mark.online
def test_damodaran_online(ctx, repo):
    r = executar(Damodaran(), ctx)
    assert r.status in ("ok", "parcial"), r
    gravadas = {s.serie for s in r.series if s.status in ("gravada", "sem_mudanca")}
    assert "damodaran_beta_global" in gravadas
