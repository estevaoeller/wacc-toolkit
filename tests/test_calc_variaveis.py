"""Esquema Variável × Janela: registro, compatibilidade com o formato antigo e data-base mês/ano."""

from datetime import date

import pandas as pd
import pytest

import test_calc_modo1 as m1
from wacc_toolkit.calc.janelas import acompanha_data_base, descrever, interpretar
from wacc_toolkit.calc.modo1 import ConfigProjeto, Escolha, calcular
from wacc_toolkit.calc.variaveis import GRUPOS_VARIAVEIS, REGISTRO, variaveis_do_grupo
from wacc_toolkit.calc.fontes import Bases

bases_sinteticas = m1.bases_sinteticas


def test_intervalo_fixo_nao_acompanha_data_base_e_e_limitado_ao_corte():
    j = interpretar("intervalo:2016-01:2030-12", pd.Period("2025-12", "M"))
    assert j.rotulo() == "jan/16 a dez/25"
    assert not acompanha_data_base("intervalo:2016-01:2025-12") and acompanha_data_base("12m")
    assert descrever("120m") == "120 meses (10 anos)" and descrever("30a") == "30 anos-calendário"


def test_todo_grupo_tem_variavel_e_padroes_validos():
    for g in GRUPOS_VARIAVEIS:
        assert variaveis_do_grupo(g), g
    for d in REGISTRO.values():
        for esp in d.janelas.values():
            interpretar(esp, pd.Period("2025-12", "M"))


def test_data_base_vira_mes_e_dia_vira_relatorio_focus():
    cfg = m1._cfg(data_base=date(2026, 1, 16))
    assert cfg.data_base == date(2026, 1, 1) and cfg.focus_relatorio == date(2026, 1, 16)
    cfg2 = m1._cfg(data_base=date(2026, 7, 1))
    assert cfg2.focus_relatorio is None and cfg2.data_focus == date(2026, 7, 31)


def test_escolha_explicita_prevalece_sobre_opcoes(bases_sinteticas):
    cfg = m1._cfg(variaveis={"rf": Escolha("t10_media_mensal", {"janela": "24m"})})
    r = calcular(cfg, bases_sinteticas)
    assert r.componentes["rf"].janela["meses"] == 24
    assert r.componentes["rf"].detalhes["variavel"] == "t10_media_mensal"
    assert cfg.opcoes.rf_janela == "24m"  # opções antigas sincronizadas (usadas nos textos do Excel)


def test_variavel_incompativel_com_grupo(bases_sinteticas):
    cfg = m1._cfg(variaveis={"tlp": Escolha("t10_media_mensal", {"janela": "12m"})})
    with pytest.raises(ValueError, match="não serve ao grupo"):
        calcular(cfg, bases_sinteticas)


def test_toml_com_variaveis(tmp_path, bases_sinteticas):
    from wacc_toolkit import servicos as sv
    cfg = m1._cfg(variaveis={"risco_brasil": Escolha("cds10_vol_ibov_ntnb", {"janela_cds": "12m", "janela_vol": "60m"},
                                                      {"ntnb_vencimento": "2035-05-15"})})
    texto = sv.config_para_toml(cfg)
    assert "[variaveis.risco_brasil]" in texto
    assert ConfigProjeto.de_toml_texto(texto) == cfg
