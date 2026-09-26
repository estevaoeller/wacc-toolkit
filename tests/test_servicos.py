"""Camada de serviços usada pela interface."""

from datetime import date

import pandas as pd
import pytest

import test_calc_modo1 as m1
from wacc_toolkit import servicos as sv
from wacc_toolkit.calc.modo1 import ConfigProjeto, Escolha

bases_sinteticas = m1.bases_sinteticas


@pytest.fixture
def amb(tmp_path, bases_sinteticas):
    return sv.ambiente(tmp_path / "bases")


def test_ambiente_cria_projetos_e_calculos_ao_lado_das_bases(amb, tmp_path):
    assert amb.projetos == tmp_path / "Projetos" and amb.projetos.exists()
    assert amb.calculos == tmp_path / "Calculos" and amb.calculos.exists()


def test_toml_ida_e_volta(amb):
    cfg = m1._cfg(spread_descricao="Financ. BNDES", spread_fonte='texto com "aspas" e acentuação', notas="n")
    caminho = sv.salvar_projeto(amb, cfg, "teste")
    volta = sv.carregar_projeto(caminho)
    assert volta == cfg
    with pytest.raises(FileExistsError):
        sv.salvar_projeto(amb, cfg, "teste")
    assert sv.listar_projetos(amb) == [caminho]


def test_status_setores_linhas(amb):
    st = sv.status_bases(amb)
    assert {"serie", "fim", "linhas", "avisos"} <= set(st.columns)
    assert st.set_index("serie").loc["fred_gs10", "fim"] == "2025-12-01"
    assert sv.setores_damodaran(amb, "global", date(2026, 1, 16)) == ["Setor A", "Setor B"]
    assert sv.linhas_bndes(amb) == {}  # parâmetros sintéticos não têm linhas bndes_rem*


def test_calcular_listar_comparar(amb):
    c1 = sv.calcular_projeto(amb, m1._cfg(), excel=False)
    c2 = sv.calcular_projeto(amb, m1._cfg(spread_credito=0.02), excel=False)
    lista = sv.listar_calculos(amb)
    assert len(lista) == 2 and lista["wacc_real"].notna().all()
    comp = sv.comparar_calculos(amb, c1.registro.name, c2.registro.name).set_index("id")
    assert comp.loc["spread_credito", "dif_bp"] == pytest.approx(100)
    assert comp.loc["beta_u", "dif_bp"] == pytest.approx(0)
    assert list(sv.tabela_resultado(c1.resultado)["id"])[-1] == "wacc_nominal"


def test_importar_arquivos_so_fontes_manuais(amb):
    with pytest.raises(ValueError):
        sv.importar_arquivos(amb, "fred", [("x.csv", b"a")])
    csv = ('﻿"Data","Último","Abertura","Máxima","Mínima","Var%"\n'
           '"01.02.2026","210,0","210,0","210,0","210,0","0,00%"\n'
           '"01.01.2026","200,0","200,0","200,0","200,0","0,00%"\n').encode("utf-8")
    r = sv.importar_arquivos(amb, "investing", [("CDS Brasil 10 anos.csv", csv)])
    assert r.status == "ok"


def test_catalogo_cobre_padroes():
    from wacc_toolkit.calc.modo1 import Opcoes
    op = Opcoes()
    for campo, opcoes in sv.CATALOGO_OPCOES.items():
        assert getattr(op, campo) in opcoes, campo


def test_config_invalida_nao_e_gravada(amb):
    with pytest.raises(ValueError):
        sv.nova_config(projeto="x", data_base=date(2026, 1, 1), fases=[{"setor": "Setor A", "peso": 0.7}],
                       linha_bndes="rem_x", spread_credito=0.01)
    assert isinstance(sv.nova_config(projeto="x", data_base=date(2026, 1, 1),
                                     fases=[{"setor": "Setor A", "peso": 1.0}], linha_bndes="rem_x",
                                     spread_credito=0.01), ConfigProjeto)


def test_formatacao_pt_br():
    assert sv.formatar_numero_pt(1234.5, 2) == "1.234,50"
    assert sv.formatar_percentual_pt(0.105841, 2) == "10,58%"
    assert sv.formatar_valor_componente("beta_u", 0.61) == "0,61"
    assert sv.formatar_valor_componente("beta_l", 0.9336) == "0,934"
    assert sv.formatar_valor_componente("d_v", 0.4455) == "44,5%"
    assert sv.formatar_valor_componente("t", 0.34) == "34,0%"
    assert sv.formatar_valor_componente("wacc_real", 0.1058) == "10,58%"


def test_tabela_custo_de_capital_mesmos_rotulos_do_excel(amb):
    """A tela usa exatamente os mesmos nomes de item e descrições da aba Custo de Capital."""
    from wacc_toolkit.saida.rotulos import ROTULOS

    calculo = sv.calcular_projeto(amb, m1._cfg(), excel=False)
    tabela = sv.tabela_custo_de_capital(calculo.resultado)
    assert list(tabela["secao"]) == ["KE"] * 12 + ["KD"] * 6 + ["WACC"] * 2
    assert list(tabela["item"])[:3] == [ROTULOS["rf"], ROTULOS["rm"], ROTULOS["rf_estrutural"]]
    assert "id" not in tabela.columns
    # linhas compostas (ERP, beta realavancado, Ke/Kd nominal e real) ficam sem descrição
    erp = tabela.set_index("item").loc[ROTULOS["erp"]]
    assert erp["descricao"] == ""
    rf = tabela.set_index("item").loc[ROTULOS["rf"]]
    assert rf["descricao"].startswith("T-10 12 meses")

    # o mesmo, a partir do registro salvo em disco (histórico) — sem recalcular
    import json
    dados = json.loads(calculo.registro.read_text(encoding="utf-8"))
    tabela_registro = sv.tabela_custo_de_capital_de_registro(dados)
    pd_testing_ok = tabela.reset_index(drop=True).equals(tabela_registro.reset_index(drop=True))
    assert pd_testing_ok


def test_series_opcionais_definidas():
    assert sv.SERIES_OPCIONAIS == {
        "investing_cds10_brasil", "investing_cds5_brasil", "investing_ibov_mensal", "investing_cds5_brasil_mensal",
    }


def test_linhas_bndes_sem_id_tecnico(amb, repo):
    import pandas as pd

    m1._gravar(repo, "parametros_manuais", pd.DataFrame({
        "parametro": ["ir_csll", "bndes_rem_teste"], "valor": [34.0, 1.3], "unidade": "%",
        "fonte": ["teste", "BNDES Finem: Água, esgoto e resíduos sólidos (página do produto: 'a partir de 1,3% a.a.')"],
        "verificado_em": "2026-01-01", "responsavel": "", "notas": ""}))
    linhas = sv.linhas_bndes(amb)
    assert linhas == {"bndes_rem_teste": "Finem: Água, esgoto e resíduos sólidos (1,30% a.a.)"}


def test_calcular_previa_nao_grava_e_e_identica_ao_gerado(amb):
    """calcular_previa não cria nenhum arquivo; o valor é idêntico ao de calcular_projeto."""
    cfg = m1._cfg()
    antes = list(amb.calculos.glob("*"))
    previa = sv.calcular_previa(amb, cfg)
    assert list(amb.calculos.glob("*")) == antes  # nada gravado

    gerado = sv.calcular_projeto(amb, cfg, excel=False)
    for cid, comp in previa.componentes.items():
        assert comp.valor == pytest.approx(gerado.resultado.componentes[cid].valor)
    assert previa["wacc_real"] == pytest.approx(gerado.resultado["wacc_real"])
    assert previa["wacc_nominal"] == pytest.approx(gerado.resultado["wacc_nominal"])


def test_ultimos_calculos_por_projeto(amb):
    import time

    sv.calcular_projeto(amb, m1._cfg(projeto="A"), excel=False)
    time.sleep(1.1)  # 'gerado_em' só tem precisão de segundo: garante que o 2º cálculo é "depois"
    ultimo_a = sv.calcular_projeto(amb, m1._cfg(projeto="A", spread_credito=0.02), excel=False)
    sv.calcular_projeto(amb, m1._cfg(projeto="B"), excel=False)
    ultimos = sv.ultimos_calculos_por_projeto(amb)
    assert sorted(ultimos["projeto"]) == ["A", "B"]
    # a linha de A deve ser a do cálculo mais recente (spread 2%), não o primeiro (spread 1%)
    linha_a = ultimos.set_index("projeto").loc["A"]
    assert linha_a["arquivo"] == ultimo_a.registro.name


def test_meta_serie_rapida(amb):
    meta = sv.meta_serie(amb, "fred_gs10")
    assert meta["linhas"] > 0 and "sha256_csv" in meta
    assert sv.meta_serie(amb, "damodaran_beta_global", "2026")["linhas"] == 2


def test_indicadores_painel_bases_sinteticas(amb):
    indicadores = sv.indicadores_painel(amb, meses=24)
    nomes = [i["nome"] for i in indicadores]
    assert "Treasury 10 anos" in nomes and "CDS Brasil 10 anos" in nomes and "TLP" in nomes
    assert all(i["status"] == "ok" for i in indicadores), [i["nome"] for i in indicadores if i["status"] != "ok"]
    treasury = next(i for i in indicadores if i["nome"] == "Treasury 10 anos")
    assert treasury["ultimo_valor"] == pytest.approx(4.0)
    assert treasury["tipo_variacao"] == "pb"
    assert list(treasury["serie"].columns) == ["data", "valor"]
    assert len(treasury["serie"]) <= 25  # ~24 meses + o mês corrente


def test_listar_janelas_traz_as_padrao(amb):
    from wacc_toolkit.calc.janelas import JANELAS_PADRAO

    janelas = sv.listar_janelas(amb)
    especs = [j["espec"] for j in janelas]
    assert especs == list(JANELAS_PADRAO)
    assert all(j["padrao"] for j in janelas)
    intervalo = next(j for j in janelas if j["espec"] == "desde:1995-01")
    assert intervalo["acompanha_data_base"] is True


def test_salvar_listar_remover_janela(amb):
    nova = sv.salvar_janela(amb, "intervalo:2016-01:2025-12", "Santa Maria: jan/16 a dez/25")
    assert nova == {"espec": "intervalo:2016-01:2025-12", "nome": "Santa Maria: jan/16 a dez/25",
                    "padrao": False, "acompanha_data_base": False}
    janelas = sv.listar_janelas(amb)
    assert len(janelas) == len(sv.listar_janelas(amb))
    achada = next(j for j in janelas if j["espec"] == "intervalo:2016-01:2025-12")
    assert achada == nova

    with pytest.raises(ValueError, match="já existe"):
        sv.salvar_janela(amb, "intervalo:2016-01:2025-12")
    with pytest.raises(ValueError, match="já existe"):
        sv.salvar_janela(amb, "12m")  # já é padrão
    with pytest.raises(ValueError, match="janela não reconhecida"):
        sv.salvar_janela(amb, "espec-invalida")

    sv.remover_janela(amb, "intervalo:2016-01:2025-12")
    assert "intervalo:2016-01:2025-12" not in [j["espec"] for j in sv.listar_janelas(amb)]
    with pytest.raises(KeyError):
        sv.remover_janela(amb, "intervalo:2016-01:2025-12")
    with pytest.raises(ValueError, match="padrão"):
        sv.remover_janela(amb, "12m")


def test_arquivo_de_janelas_nao_aparece_em_listar_projetos(amb):
    cfg = m1._cfg()
    caminho = sv.salvar_projeto(amb, cfg, "meu_projeto")
    sv.salvar_janela(amb, "intervalo:2016-01:2025-12")
    assert sv.listar_projetos(amb) == [caminho]


def test_aplicar_escolha(amb):
    from wacc_toolkit.calc.modo1 import calcular

    cfg = m1._cfg()
    escolha_nova = Escolha("tlp_sgs27572", {"janela": "24m"})
    cfg2 = sv.aplicar_escolha(cfg, "tlp", escolha_nova)
    assert cfg2.variaveis["tlp"] == escolha_nova
    assert cfg2.variaveis["rf"] == cfg.variaveis["rf"]  # os demais grupos não mudam
    assert cfg.variaveis["tlp"].janelas["janela"] == "12m"  # cfg original intacto

    r2 = calcular(cfg2, sv.Bases(amb.repo))
    assert r2.componentes["tlp"].janela["meses"] == 24


def test_alternativas_grupo_sem_janela(amb):
    cfg = m1._cfg()
    tabela = sv.alternativas(amb, cfg, "d_v")
    assert set(tabela["variavel"]) == {"damodaran_setores", "dv_fixo"}
    assert (tabela["janela_chave"].isna()).all()
    ativa = tabela[tabela["ativa"]]
    assert len(ativa) == 1 and ativa.iloc[0]["variavel"] == "damodaran_setores"
    assert ativa.iloc[0]["valor"] == pytest.approx(0.4 * 0.5 + 0.6 * (0.5 / 1.5))
    fixo = tabela[tabela["variavel"] == "dv_fixo"].iloc[0]
    assert fixo["valor"] == pytest.approx(0.70) and fixo["erro"] is None


def test_alternativas_grupo_com_janela_e_erro_capturado(amb):
    from wacc_toolkit.calc.janelas import JANELAS_PADRAO

    cfg = m1._cfg()
    tabela = sv.alternativas(amb, cfg, "tlp")
    assert len(tabela) == len(JANELAS_PADRAO)  # 1 variável (tlp_sgs27572) x catálogo de janelas
    assert set(tabela["janela_espec"]) == set(JANELAS_PADRAO)
    ativa = tabela[tabela["ativa"]]
    assert len(ativa) == 1 and ativa.iloc[0]["janela_espec"] == "12m"
    assert ativa.iloc[0]["valor"] == pytest.approx(0.06)
    # janelas mais longas que a base sintética (2018-2025) faltam cobertura: erro capturado, não exceção
    com_erro = tabela[tabela["janela_espec"] == "30a"]
    assert len(com_erro) == 1
    assert pd.isna(com_erro.iloc[0]["valor"]) and "faltam" in com_erro.iloc[0]["erro"]


def test_alternativas_reusa_bases_entre_grupos(amb):
    bases = sv.Bases(amb.repo)
    cfg = m1._cfg()
    for grupo in ("rf", "rf_estrutural", "rm", "risco_brasil", "d_v", "inflacao_us", "tlp", "ipca"):
        tabela = sv.alternativas(amb, cfg, grupo, bases=bases)
        assert not tabela.empty
    assert bases._cache  # o cache de séries foi de fato usado


def test_indicadores_painel_sem_dados_nao_quebra(amb, repo):
    """Removendo uma série da base, o indicador correspondente vem sem dados, sem quebrar o painel."""
    (amb.bases / "tratado" / "bcb_tlp.csv").unlink()
    (amb.bases / "tratado" / "bcb_tlp.meta.json").unlink()
    indicadores = sv.indicadores_painel(amb, meses=24)
    tlp = next(i for i in indicadores if i["nome"] == "TLP")
    assert tlp["status"] == "sem_dados"
    assert all(i["status"] == "ok" for i in indicadores if i["nome"] != "TLP")


def test_spreads_predefinidos():
    assert sv.SPREADS_PREDEFINIDOS["Financ. BNDES"] is None  # digitado à mão
    assert sv.formatar_percentual_pt(sv.SPREADS_PREDEFINIDOS["Outro"], 2) == "3,16%"
    assert sv.formatar_percentual_pt(sv.SPREADS_PREDEFINIDOS["Hipotético BB+"], 2) == "1,78%"
    assert sv.formatar_percentual_pt(sv.SPREADS_PREDEFINIDOS["Tx. Risco BNDES - Simulação"], 2) == "1,25%"
    assert sv.formatar_percentual_pt(sv.SPREADS_PREDEFINIDOS["Fixo"], 2) == "3,00%"


def test_empresas_do_setor(amb, repo):
    df = pd.DataFrame({
        "company_name": ["Empresa A", "Empresa B", "Empresa C"],
        "exchange_ticker": ["NYSE:A", "NYSE:B", "BOVESPA:C"],
        "industry_group": ["Setor A", "Setor A", "Setor B"],
        "primary_sector": ["Industrial", "Industrial", "Financials"],
        "sic_code": [1000, 1001, 6000],
        "country": ["United States", "Brazil", "Brazil"],
        "broad_group": ["United States", "Emerging Markets", "Emerging Markets"],
        "sub_group": ["", "", ""],
    })
    m1._gravar(repo, "damodaran_empresas", df, "2025-01")

    global_ = sv.empresas_do_setor(amb, "Setor A", "global")
    assert sorted(global_["company_name"]) == ["Empresa A", "Empresa B"]

    emerging = sv.empresas_do_setor(amb, "Setor A", "emerging")
    assert list(emerging["company_name"]) == ["Empresa B"]

    assert sv.empresas_do_setor(amb, "Setor B", "global")["company_name"].iloc[0] == "Empresa C"


def test_empresas_do_setor_sem_serie(amb):
    with pytest.raises(FileNotFoundError, match="Damodaran"):
        sv.empresas_do_setor(amb, "Setor A", "global")


def test_mes_corte_rotulo_e_janela_periodo(amb):
    cfg = m1._cfg()  # data_base = date(2026, 1, 16) -> corte = dez/25
    assert sv.mes_corte_rotulo(cfg.data_base) == "dez/25"
    assert sv.janela_periodo(cfg, "12m") == "jan/25 a dez/25"


def test_tabela_alternativas_exibicao_nan_nao_e_erro():
    """Regressão: com as bases reais, a coluna 'erro' mistura textos e NaN; NaN não é erro
    (antes, todas as linhas da tela Montar cenário mostravam "-" e "None")."""
    import numpy as np
    import pandas as pd

    cfg = m1._cfg(data_base=date(2026, 7, 1))
    tabela = pd.DataFrame({
        "variavel_nome": ["T-10", "T-10", "T-bond"], "fonte": ["FRED", "FRED", "Damodaran"],
        "janela_espec": ["12m", "24m", "12m"], "janela_nome": ["12 meses", "24 meses", "12 meses"],
        "rotulo": ["r1", "r2", np.nan], "valor": [0.0424, 0.0425, np.nan],
        "erro": [np.nan, np.nan, "faltam os anos [2026]"], "ativa": [True, False, False]})
    out = sv.tabela_alternativas_exibicao(cfg, "rf", tabela)
    assert list(out["Valor"]) == ["4,24%", "4,25%", "-"]
    assert out.loc[0, "Janela/Obs"] == "12 meses (jul/25 a jun/26)"
    assert out.loc[2, "Janela/Obs"].startswith("sem dados:")
    assert list(out["erro"]) == [False, False, True] and out.loc[0, "Ativa"] == "✓"
    assert not out["Janela/Obs"].str.contains("None").any()
