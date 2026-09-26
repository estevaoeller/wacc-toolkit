"""Variáveis e WACC ao longo do tempo: recalcula, para cada data-base mensal, o que o modelo teria
dado naquela data com as mesmas escolhas (variável × janela), sem olhar para dados posteriores.

É a base da análise "rolling" (simulação histórica) e da análise de sensibilidade.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd

from .fontes import Bases
from .janelas import mes_corte
from .modo1 import ConfigProjeto, Escolha, calcular
from .variaveis import NOMES_GRUPOS, calcular_grupo


def meses(inicio: str | date, fim: str | date) -> list[date]:
    """Datas-base mensais (dia 1º) de ``inicio`` a ``fim``, inclusive."""
    return [p.start_time.date() for p in pd.period_range(pd.Period(inicio, "M"), pd.Period(fim, "M"), freq="M")]


def _cfg_na_data(cfg: ConfigProjeto, data_base: date) -> ConfigProjeto:
    # sem focus_relatorio fixo: em cada data-base usa o último relatório do mês
    return replace(cfg, data_base=data_base, focus_relatorio=None)


def serie_variavel(bases: Bases, cfg: ConfigProjeto, grupo: str, escolha: Escolha | None,
                   inicio: str | date, fim: str | date) -> pd.DataFrame:
    """Valor do ``grupo`` com a ``escolha`` (padrão: a do projeto) em cada data-base de ``inicio``
    a ``fim``. Colunas: data_base, mes_corte, valor, rotulo e erro. Meses sem dados trazem o erro,
    sem interromper a série."""
    escolha = escolha or cfg.variaveis[grupo]
    linhas = []
    for db in meses(inicio, fim):
        c = _cfg_na_data(cfg, db)
        try:
            comp = calcular_grupo(bases, c, mes_corte(db), grupo, escolha)
            linhas.append({"data_base": db, "mes_corte": str(mes_corte(db)), "valor": comp.valor,
                           "rotulo": comp.rotulo, "erro": None})
        except (ValueError, KeyError, FileNotFoundError) as e:
            linhas.append({"data_base": db, "mes_corte": str(mes_corte(db)), "valor": None, "rotulo": "",
                           "erro": str(e)})
    df = pd.DataFrame(linhas)
    df.attrs["grupo"], df.attrs["nome"], df.attrs["variavel"] = grupo, NOMES_GRUPOS.get(grupo, grupo), escolha.variavel
    return df


def serie_wacc(bases: Bases, cfg: ConfigProjeto, inicio: str | date, fim: str | date) -> pd.DataFrame:
    """WACC do cenário e todos os componentes em cada data-base (uma linha por mês e uma coluna
    por componente, em fração decimal). Meses sem cálculo trazem ``erro``."""
    linhas = []
    for db in meses(inicio, fim):
        try:
            r = calcular(_cfg_na_data(cfg, db), bases)
            linhas.append({"data_base": db, **{k: c.valor for k, c in r.componentes.items()}, "erro": None})
        except (ValueError, KeyError, FileNotFoundError) as e:
            linhas.append({"data_base": db, "erro": str(e)})
    return pd.DataFrame(linhas)
