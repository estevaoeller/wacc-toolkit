from pathlib import Path

import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.parametros import Parametros, interpretar_toml

EXEMPLO = Path(__file__).parents[1] / "parametros_manuais.example.toml"


def test_exemplo_e_valido():
    df = interpretar_toml(EXEMPLO.read_bytes())
    assert df.set_index("parametro").loc["ir_csll", "valor"] == 34.0


def test_campo_obrigatorio_ausente():
    with pytest.raises(ValueError, match="verificado_em"):
        interpretar_toml(b'[[parametro]]\nid="x"\nvalor=1\nunidade="%"\nfonte="f"\n')


def test_sem_arquivo_falha_com_orientacao(ctx):
    r = executar(Parametros(), ctx)
    assert r.status == "falhou" and "entrada/parametros" in r.erro


def test_fluxo_com_arquivo(ctx, repo):
    (ctx.entrada("parametros") / "parametros_manuais.toml").write_bytes(EXEMPLO.read_bytes())
    r = executar(Parametros(), ctx)
    assert r.status == "ok", r
    assert repo.versoes(Parametros.series[0]) == []  # frequência V, mas não versionada por edição
    assert repo.ler_serie(Parametros.series[0]) is not None
