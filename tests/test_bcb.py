import pytest

from wacc_toolkit.collector import executar
from wacc_toolkit.collectors.bcb import (
    BCB, interpretar_tlp, interpretar_focus, interpretar_selic_meta,
    interpretar_selic_efetiva_mensal, interpretar_selic_efetiva_diaria
)


def test_interpretar_tlp(fixtures):
    """Parse TLP com sucesso: colunas, tipos, datas e valores."""
    df = interpretar_tlp((fixtures / "bcb_tlp.json").read_bytes())

    # Verificar colunas
    assert list(df.columns) == ["data", "valor"]

    # Verificar tipos
    assert df["valor"].dtype == "float64"

    # Verificar que não há NaN em valores
    assert df["valor"].notna().all()

    # Verificar primeira data (01/01/2018)
    assert str(df["data"].iloc[0]) == "2018-01-01"

    # Verificar último item
    assert str(df["data"].iloc[-1]) == "2019-08-01"
    assert df["valor"].iloc[-1] == 3.41

    # Verificar um valor conhecido no meio (01/02/2018)
    assert df["valor"].iloc[1] == 4.81


def test_interpretar_tlp_formato_valores():
    """TLP: valores são strings decimais convertidas para float."""
    dados = b'[{"data":"01/01/2020","valor":"5.50"},{"data":"01/02/2020","valor":"5.75"}]'
    df = interpretar_tlp(dados)

    assert len(df) == 2
    assert df["valor"].iloc[0] == 5.50
    assert df["valor"].iloc[1] == 5.75


def test_interpretar_focus(fixtures):
    """Parse Focus com sucesso: colunas, tipos, chave composta."""
    df = interpretar_focus((fixtures / "bcb_focus_ipca_anual.json").read_bytes())

    # Verificar colunas
    expected_cols = ["data", "ano_referencia", "base_calculo", "mediana", "media",
                     "desvio_padrao", "minimo", "maximo", "respondentes"]
    assert list(df.columns) == expected_cols

    # Verificar tipos
    assert df["mediana"].dtype == "float64"
    assert df["ano_referencia"].dtype == "int64"
    assert df["base_calculo"].dtype == "int64"

    # Verificar que não há NaN nas colunas críticas
    assert df["data"].notna().all()
    assert df["ano_referencia"].notna().all()
    assert df["base_calculo"].notna().all()
    assert df["mediana"].notna().all()

    # Verificar primeira linha (2018-01-22, ano 2019, base 0)
    assert str(df["data"].iloc[0]) == "2018-01-22"
    assert df["ano_referencia"].iloc[0] == 2019
    assert df["base_calculo"].iloc[0] == 0
    assert df["mediana"].iloc[0] == 4.25

    # Verificar um valor conhecido (segundo item: ano 2020)
    assert df["ano_referencia"].iloc[1] == 2020
    assert df["mediana"].iloc[1] == 4.0


def test_interpretar_focus_múltiplas_bases():
    """Focus: dados com diferentes base_calculo."""
    dados = b'''{"value":[
        {"Indicador":"IPCA","Data":"2020-06-15","DataReferencia":"2021","Media":3.5,"Mediana":3.5,"DesvioPadrao":0.2,"Minimo":3.0,"Maximo":4.0,"numeroRespondentes":50,"baseCalculo":0},
        {"Indicador":"IPCA","Data":"2020-06-20","DataReferencia":"2021","Media":3.4,"Mediana":3.4,"DesvioPadrao":0.2,"Minimo":3.0,"Maximo":4.0,"numeroRespondentes":45,"baseCalculo":1}
    ]}'''
    df = interpretar_focus(dados)

    assert len(df) == 2
    assert df["base_calculo"].iloc[0] == 0
    assert df["base_calculo"].iloc[1] == 1
    assert df["mediana"].iloc[0] == 3.5
    assert df["mediana"].iloc[1] == 3.4


def test_interpretar_selic_meta(fixtures):
    """Parse Selic Meta com sucesso: colunas, tipos, datas e valores."""
    df = interpretar_selic_meta((fixtures / "bcb_selic_meta_2022.json").read_bytes())

    # Verificar colunas
    assert list(df.columns) == ["data", "valor"]

    # Verificar tipos
    assert df["valor"].dtype == "float64"

    # Verificar que não há NaN em valores
    assert df["valor"].notna().all()

    # Verificar primeira data
    assert str(df["data"].iloc[0]) == "2022-01-01"

    # Verificar último item
    assert str(df["data"].iloc[-1]) == "2022-03-29"
    assert df["valor"].iloc[-1] == 11.75


def test_interpretar_selic_efetiva_mensal(fixtures):
    """Parse Selic Efetiva Mensal com sucesso: colunas, tipos, datas e valores."""
    df = interpretar_selic_efetiva_mensal((fixtures / "bcb_selic_efetiva_mensal.json").read_bytes())

    # Verificar colunas
    assert list(df.columns) == ["data", "valor"]

    # Verificar tipos
    assert df["valor"].dtype == "float64"

    # Verificar que não há NaN em valores
    assert df["valor"].notna().all()

    # Verificar primeira data
    assert str(df["data"].iloc[0]) == "2020-01-01"

    # Verificar último item
    assert str(df["data"].iloc[-1]) == "2024-12-01"
    assert df["valor"].iloc[-1] == 11.77


def test_interpretar_selic_efetiva_diaria(fixtures):
    """Parse Selic Efetiva Diária com sucesso: colunas, tipos, datas e valores."""
    df = interpretar_selic_efetiva_diaria((fixtures / "bcb_selic_efetiva_diaria_2023.json").read_bytes())

    # Verificar colunas
    assert list(df.columns) == ["data", "valor"]

    # Verificar tipos
    assert df["valor"].dtype == "float64"

    # Verificar que não há NaN em valores
    assert df["valor"].notna().all()

    # Verificar primeira data (02/01/2023, pois 01/01 é feriado)
    assert str(df["data"].iloc[0]) == "2023-01-02"

    # Verificar último item
    assert str(df["data"].iloc[-1]) == "2023-03-29"
    assert df["valor"].iloc[-1] == 13.65


def test_interpretar_selic_meta_formato_valores():
    """Selic Meta: valores são strings decimais convertidas para float."""
    dados = b'[{"data":"01/01/2022","valor":"9.25"},{"data":"31/01/2022","valor":"9.75"}]'
    df = interpretar_selic_meta(dados)

    assert len(df) == 2
    assert df["valor"].iloc[0] == 9.25
    assert df["valor"].iloc[1] == 9.75


def test_interpretar_selic_meta_com_duplicatas():
    """Selic Meta: remove duplicatas mantendo a última ocorrência."""
    # Simula duas páginas com uma data repetida
    dados_pagina1 = b'[{"data":"01/01/2022","valor":"9.25"},{"data":"31/01/2022","valor":"9.75"}]'
    dados_pagina2 = b'[{"data":"31/01/2022","valor":"9.80"},{"data":"28/02/2022","valor":"10.00"}]'

    df1 = interpretar_selic_meta(dados_pagina1)
    df2 = interpretar_selic_meta(dados_pagina2)

    # Simula concatenação como feita no interpretar()
    import pandas as pd
    df_combined = pd.concat([df1, df2], ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=["data"], keep="last").reset_index(drop=True)

    assert len(df_combined) == 3
    # Verifica que a data duplicada tem o valor da última ocorrência
    data_duplicada = df_combined[df_combined["data"] == df_combined["data"].iloc[1]]
    assert data_duplicada["valor"].iloc[0] == 9.80


def test_interpretar_focus_selic(fixtures):
    """Parse Focus Selic com sucesso: colunas, tipos, chave composta."""
    df = interpretar_focus((fixtures / "bcb_focus_selic_anual.json").read_bytes())

    # Verificar colunas
    expected_cols = ["data", "ano_referencia", "base_calculo", "mediana", "media",
                     "desvio_padrao", "minimo", "maximo", "respondentes"]
    assert list(df.columns) == expected_cols

    # Verificar tipos
    assert df["mediana"].dtype == "float64"
    assert df["ano_referencia"].dtype == "int64"
    assert df["base_calculo"].dtype == "int64"

    # Verificar que não há NaN nas colunas críticas
    assert df["data"].notna().all()
    assert df["ano_referencia"].notna().all()
    assert df["base_calculo"].notna().all()
    assert df["mediana"].notna().all()

    # Verificar primeiro item
    assert len(df) >= 1


@pytest.mark.online
def test_bcb_online(ctx, repo):
    """Teste online: executar coleta completa e validar resultado."""
    r = executar(BCB(), ctx)

    # Verificar status
    assert r.status == "ok", f"Status {r.status}: {r.erro}"

    # Verificar que todas as séries foram gravadas
    assert {s.serie for s in r.series} == {s.id for s in BCB.series}

    # Verificar que o status de cada série é "gravada"
    for s in r.series:
        assert s.status == "gravada", f"Série {s.serie}: status {s.status}"


def test_pagina_nao_json_e_erro_explicito():
    import pytest
    from wacc_toolkit.collectors.bcb import interpretar_selic_meta
    with pytest.raises(ValueError, match="não é JSON"):
        interpretar_selic_meta(b'<?xml version="1.0"?><html>erro</html>')
