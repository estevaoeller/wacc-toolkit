"""Registro de variáveis: cada grupo do WACC × as variáveis (método + fonte) que podem ocupá-lo.

Separação pedida pelo usuário: **Variável** (o que se mede, como e de qual fonte) ×
**Janela** (o período). Uma escolha (:class:`~.modo1.Escolha`) = variável + janelas + parâmetros.

Para acrescentar uma variável:
1. escreva uma função ``fn(ctx: Ctx, grupo: str, janelas: dict, params: dict) -> Componente``;
2. registre com ``_registrar(DefVariavel(...))``, informando os grupos compatíveis, as chaves de
   janela (com padrão) e os parâmetros (com padrão);
3. o Componente deve trazer ``detalhes["variavel"]`` (preenchido por :func:`calcular_grupo`) e
   os recortes das bases usadas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Callable

import pandas as pd

from .fontes import Bases
from .janelas import JANELAS_PADRAO, descrever, interpretar
from . import modo1 as m

# grupos cujo insumo é escolhido no catálogo Variável × Janela (os demais vêm da configuração:
# beta/fases, T, remuneração BNDES e spread)
GRUPOS_VARIAVEIS: tuple[str, ...] = ("rf", "rf_estrutural", "rm", "risco_brasil", "d_v", "inflacao_us", "tlp", "ipca")

NOMES_GRUPOS = {
    "rf": "Taxa livre de risco (Rf)", "rf_estrutural": "Taxa livre de risco estrutural (R'f)",
    "rm": "Retorno de mercado (Rm)", "risco_brasil": "Prêmio de risco Brasil", "d_v": "D/(D+E)",
    "inflacao_us": "Inflação US$ (implícita)", "tlp": "TLP", "ipca": "IPCA (Focus)",
}


@dataclass(frozen=True)
class Ctx:
    bases: Bases
    cfg: "m.ConfigProjeto"
    corte: pd.Period

    @property
    def data_base(self) -> date:
        return self.cfg.data_base


@dataclass(frozen=True)
class DefVariavel:
    id: str
    nome: str                      # rótulo legível da variável (sem a janela)
    fonte: str                     # fonte dos dados, para a coluna "Fonte"
    grupos: tuple[str, ...]
    fn: Callable
    janelas: dict = field(default_factory=dict)     # chave -> janela padrão (ex.: {"janela": "12m"})
    params: dict = field(default_factory=dict)      # parâmetro -> padrão
    descricao: str = ""


REGISTRO: dict[str, DefVariavel] = {}


def _registrar(d: DefVariavel) -> DefVariavel:
    if d.id in REGISTRO:
        raise ValueError(f"variável duplicada: {d.id}")
    REGISTRO[d.id] = d
    return d


def variaveis_do_grupo(grupo: str) -> list[DefVariavel]:
    return [d for d in REGISTRO.values() if grupo in d.grupos]


def janelas_disponiveis(extras: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Janelas padrão + as criadas pelo usuário (sem repetir)."""
    vistos, out = set(), []
    for e in (*JANELAS_PADRAO, *extras):
        if e not in vistos:
            vistos.add(e)
            out.append(e)
    return out


def calcular_grupo(bases: Bases, cfg: "m.ConfigProjeto", corte: pd.Period, grupo: str,
                   escolha: "m.Escolha") -> "m.Componente":
    if escolha.variavel not in REGISTRO:
        raise KeyError(f"{grupo}: variável desconhecida {escolha.variavel!r}")
    d = REGISTRO[escolha.variavel]
    if grupo not in d.grupos:
        raise ValueError(f"a variável {d.id!r} não serve ao grupo {grupo!r} (serve a {d.grupos})")
    janelas = {**d.janelas, **(escolha.janelas or {})}
    params = {**d.params, **(escolha.params or {})}
    comp = d.fn(Ctx(bases, cfg, corte), grupo, janelas, params)
    comp.id, comp.nome = grupo, NOMES_GRUPOS.get(grupo, comp.nome)
    comp.detalhes = {**comp.detalhes, "variavel": d.id, "variavel_nome": d.nome, "fonte": d.fonte,
                     "janelas_escolhidas": janelas, "params": params,
                     "janelas_descricao": {k: descrever(v) for k, v in janelas.items()}}
    return comp


# ------------------------------------------------------------------ variáveis que reproduzem a planilha
def _t10_media_mensal(ctx: Ctx, grupo, j, p):
    return m.rf(ctx.bases, ctx.corte, j["janela"], grupo, NOMES_GRUPOS[grupo])


def _sp500_ln(ctx: Ctx, grupo, j, p):
    return m.rm(ctx.bases, ctx.corte, "ln_mensal", j["janela"])


def _sp500_anual(ctx: Ctx, grupo, j, p):
    return m.rm(ctx.bases, ctx.corte, "anual", j["janela"])


def _cds10_vol(ctx: Ctx, grupo, j, p):
    op = SimpleNamespace(cds_janela=j["janela_cds"], vol_janela=j["janela_vol"], ntnb_vencimento=p["ntnb_vencimento"])
    return m.risco_brasil(ctx.bases, ctx.corte, op)


def _implicita(ctx: Ctx, grupo, j, p):
    return m.inflacao_us(ctx.bases, ctx.corte, j["janela"])


def _tlp(ctx: Ctx, grupo, j, p):
    return m.tlp(ctx.bases, ctx.corte, j["janela"])


def _focus_ipca(ctx: Ctx, grupo, j, p):
    return m.ipca_focus(ctx.bases, ctx.data_base, int(p["anos"]), ctx.cfg.data_focus, int(p["base_calculo"]))


def _dv_damodaran(ctx: Ctx, grupo, j, p):
    cfg = ctx.cfg
    if p.get("coluna") and p["coluna"] != cfg.opcoes.de_coluna:
        from dataclasses import replace
        cfg = replace(cfg, opcoes=replace(cfg.opcoes, de_coluna=p["coluna"]))
    _, dv = m.beta_estrutura(ctx.bases, cfg)
    return dv


_registrar(DefVariavel("t10_media_mensal", "T-10: média das médias mensais", "Federal Reserve (FRED GS10)",
                       ("rf", "rf_estrutural"), _t10_media_mensal, {"janela": "12m"},
                       descricao="Média das médias mensais do US Treasury 10 anos (constant maturity)."))
_registrar(DefVariavel("sp500tr_ln_mensal", "S&P 500 TR: média do retorno ln mensal, anualizada",
                       "Yahoo Finance (^SP500TR)", ("rm",), _sp500_ln, {"janela": "desde:1995-01"},
                       descricao="(1 + média dos retornos ln mensais)^12 − 1, com fechamentos de fim de mês."))
_registrar(DefVariavel("sp500tr_retorno_anual", "S&P 500 TR: média dos retornos anuais", "Yahoo Finance (^SP500TR)",
                       ("rm",), _sp500_anual, {"janela": "30a"},
                       descricao="Média aritmética dos retornos anuais dez/dez."))
_registrar(DefVariavel("cds10_vol_ibov_ntnb", "CDS 10a × vol. Ibovespa/NTN-B",
                       "Investing.com (CDS) / B3 (Ibovespa) / Tesouro Nacional (NTN-B)", ("risco_brasil",), _cds10_vol,
                       {"janela_cds": "120m", "janela_vol": "60m"}, {"ntnb_vencimento": "2035-05-15"},
                       descricao="Média mensal do CDS 10a (p.b.) × σ(ln diário Ibov)/σ(ln diário PU NTN-B) / 10.000."))
_registrar(DefVariavel("implicita_gs10_fii10", "Implícita: Treasury nominal × TIPS (médias mensais)",
                       "Federal Reserve (FRED GS10 e FII10)", ("inflacao_us",), _implicita, {"janela": "12m"},
                       descricao="Média de (1 + nominal)/(1 + TIPS) − 1 mensal."))
_registrar(DefVariavel("tlp_sgs27572", "TLP (média mensal)", "BCB, SGS 27572", ("tlp",), _tlp, {"janela": "12m"}))
_registrar(DefVariavel("focus_ipca_mediana", "Focus IPCA: média das medianas anuais", "BCB, Focus (Olinda)",
                       ("ipca",), _focus_ipca, {}, {"anos": 10, "base_calculo": 0},
                       descricao="Média das medianas anuais do Focus; anos sem projeção repetem o último."))
_registrar(DefVariavel("damodaran_setores", "Damodaran: D/E de mercado dos setores, ponderado pelas fases",
                       "Damodaran Online (dbtfund)", ("d_v",), _dv_damodaran, {}, {"coluna": "market_de_unadjusted"}))
