"""Testes do núcleo: bruto imutável e deduplicado, validação e manutenção da última versão boa."""

import pandas as pd

from wacc_toolkit.collector import Coletor, executar
from wacc_toolkit.series import SerieSpec
from wacc_toolkit.storage import ArquivoBruto


class Ficticio(Coletor):
    fonte = "ficticia"
    series = (SerieSpec("ficticia_x", "teste", "% a.a.", "D", faixa=(0, 100), max_lacuna_dias=10),)

    def __init__(self, linhas: str):
        self.linhas = linhas

    def coletar(self, ctx):
        return [ArquivoBruto(self.linhas.encode(), "csv", rotulo="X")]

    def interpretar(self, ctx, brutos):
        import io
        df = pd.read_csv(io.BytesIO(brutos[0].caminho.read_bytes()))
        return {"ficticia_x": df}


CSV1 = "data,valor\n2025-01-02,4.5\n2025-01-03,4.6\n"
CSV2 = "data,valor\n2025-01-02,4.5\n2025-01-03,4.6\n2025-01-06,4.7\n"


def test_primeira_carga_grava_bruto_tratado_e_manifesto(ctx, repo):
    r = executar(Ficticio(CSV1), ctx)
    assert r.status == "ok" and r.brutos_novos == 1
    assert r.series[0].status == "gravada"
    df = repo.ler_serie(Ficticio.series[0])
    assert list(df["valor"]) == [4.5, 4.6]
    meta = repo.meta_serie(Ficticio.series[0])
    assert meta["origem"][0]["sha256"]
    tipos = [e["tipo"] for e in repo.eventos()]
    assert tipos == ["bruto", "serie"]


def test_segunda_coleta_identica_nao_duplica(ctx, repo):
    executar(Ficticio(CSV1), ctx)
    r = executar(Ficticio(CSV1), ctx)
    assert r.status == "sem_novidade"
    assert len(list(repo.dir_bruto("ficticia").iterdir())) == 1


def test_coleta_nova_avanca_serie(ctx, repo):
    executar(Ficticio(CSV1), ctx)
    r = executar(Ficticio(CSV2), ctx)
    assert r.series[0].status == "gravada" and r.series[0].fim == "2025-01-06"


def test_valor_fora_da_faixa_mantem_versao_anterior(ctx, repo):
    executar(Ficticio(CSV1), ctx)
    r = executar(Ficticio(CSV1 + "2025-01-06,450\n"), ctx)
    assert r.status == "parcial" and r.series[0].status == "rejeitada"
    assert len(repo.ler_serie(Ficticio.series[0])) == 2  # última versão boa preservada


def test_regressao_de_data_e_erro(ctx, repo):
    executar(Ficticio(CSV2), ctx)
    r = executar(Ficticio(CSV1), ctx)
    assert r.series[0].status == "rejeitada"
    assert any("regrediu" in str(p) for p in r.series[0].problemas)


def test_revisao_de_historico_gera_aviso(ctx, repo):
    executar(Ficticio(CSV1), ctx)
    r = executar(Ficticio("data,valor\n2025-01-02,4.4\n2025-01-03,4.6\n2025-01-06,4.7\n"), ctx)
    assert r.series[0].status == "gravada"
    assert any("histórico revisado" in str(p) for p in r.series[0].problemas)


def test_falha_de_coleta_nao_propaga(ctx, repo):
    class Quebrado(Ficticio):
        def coletar(self, ctx):
            raise ConnectionError("fonte fora do ar")

    r = executar(Quebrado(CSV1), ctx)
    assert r.status == "falhou" and "fonte fora do ar" in r.erro
    assert repo.eventos("falha")


def test_bruto_e_somente_leitura(ctx, repo):
    executar(Ficticio(CSV1), ctx)
    arquivo = next(repo.dir_bruto("ficticia").iterdir())
    import os
    import stat
    assert not (os.stat(arquivo).st_mode & stat.S_IWRITE)
