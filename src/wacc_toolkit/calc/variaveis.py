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
    # conjuntos de parâmetros a exibir como alternativas (ex.: bases de cálculo do Focus); cada
    # item é sobreposto a `params` (ver `servicos.alternativas`)
    variantes_params: tuple[dict, ...] = ()


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


# ------------------------------------------------------------------ variáveis novas
def _t10_fechamento_mes(ctx: Ctx, grupo, j, p):
    df, meta = ctx.bases.ler("fred_dgs10")
    jan = interpretar(j["janela"], ctx.corte)
    s = m._na_janela(m._mensal_ultimo(df, "valor"), jan)
    m._exigir_cobertura(s, jan, NOMES_GRUPOS[grupo])
    rec = ctx.bases.recorte("t10_fechamento", "fred_dgs10", jan.filtrar(df), meta,
                            "US Treasury 10a, fechamento do último dia útil do mês (% a.a.)")
    return m.Componente(grupo, NOMES_GRUPOS[grupo], s.mean() / 100,
                        "média do fechamento do último dia útil de cada mês",
                        f"T-10 fechamento mensal ({jan.rotulo()})", jan.to_dict(), [rec], {"n_meses": len(s)})


def _retorno_anual_damodaran(ctx: Ctx, grupo, j, p, coluna: str, rotulo_instrumento: str):
    espec = j["janela"]
    jan = interpretar(espec, ctx.corte)
    versao = ctx.bases.versao_vigente("damodaran_histretsp", ctx.data_base)
    df, meta = ctx.bases.ler("damodaran_histretsp", versao)
    ini, fim = jan.inicio.year, jan.fim.year
    sub = df[(df["ano"] >= ini) & (df["ano"] <= fim)]
    anos_presentes = set(sub["ano"])
    faltando = sorted(set(range(ini, fim + 1)) - anos_presentes)
    if faltando:
        raise ValueError(f"{rotulo_instrumento} (Damodaran histretSP v{versao}): faltam os anos {faltando}")
    valor = float(sub[coluna].mean())
    rec = ctx.bases.recorte("damodaran_histretsp", "damodaran_histretsp", sub, meta,
                            f"Damodaran histretSP v{versao}: retorno anual {rotulo_instrumento} ({ini}-{fim})")
    return m.Componente(grupo, NOMES_GRUPOS[grupo], valor, f"média aritmética de {coluna} nos anos da janela",
                        f"Damodaran histretSP {rotulo_instrumento} ({jan.rotulo()})", jan.to_dict(), [rec],
                        {"n_anos": len(anos_presentes), "versao": versao})


def _tbond_retorno_anual_damodaran(ctx: Ctx, grupo, j, p):
    return _retorno_anual_damodaran(ctx, grupo, j, p, "tbond10_retorno", "T-Bond 10a")


def _sp500_retorno_anual_damodaran(ctx: Ctx, grupo, j, p):
    return _retorno_anual_damodaran(ctx, grupo, j, p, "sp500_retorno", "S&P 500")


def _cds10_sem_multiplicador(ctx: Ctx, grupo, j, p):
    mensal_cds, mc, dfd, md, completados = m._cds_mensal(ctx.bases, "investing_cds10_brasil_mensal",
                                                          "investing_cds10_brasil")
    jc = interpretar(j["janela_cds"], ctx.corte)
    cds = m._na_janela(mensal_cds, jc)
    m._exigir_cobertura(cds, jc, "CDS 10a (baixe o CSV do Investing para Bases/entrada/investing/)")
    meses_diario = [pp for pp in completados if jc.inicio <= pp <= jc.fim]
    cds_usado = pd.DataFrame({"data": cds.index.to_timestamp(), "ultimo": cds.values,
                              "origem": ["diário (último pregão)" if pp in meses_diario else "mensal"
                                        for pp in cds.index]})
    recs = [ctx.bases.recorte("cds10", "investing_cds10_brasil_mensal", cds_usado, mc,
                              "CDS Brasil 10a, média mensal (bps)" +
                              ("; meses completados pela série diária" if meses_diario else ""))]
    if meses_diario:
        usados_d = dfd[pd.to_datetime(dfd["data"]).dt.to_period("M").isin(meses_diario)]
        recs.append(ctx.bases.recorte("cds10_diario", "investing_cds10_brasil", usados_d, md,
                                      "CDS Brasil 10a, diário (meses sem dado mensal)",
                                      meses=[str(pp) for pp in meses_diario]))
    valor = cds.mean() / 10_000
    return m.Componente(grupo, NOMES_GRUPOS[grupo], valor, "média mensal do CDS 10a (bps) / 10.000, sem multiplicador",
                        f"CDS 10a {jc.rotulo()}", jc.to_dict(), recs, {"cds_medio_bps": cds.mean(), "n_cds": len(cds)})


def _cds5_vol(ctx: Ctx, grupo, j, p):
    op = SimpleNamespace(cds_janela=j["janela_cds"], vol_janela=j["janela_vol"], ntnb_vencimento=p["ntnb_vencimento"])
    return m.risco_brasil_com_series(ctx.bases, ctx.corte, op, "investing_cds5_brasil_mensal",
                                     "investing_cds5_brasil", "CDS 5a", "CDS Brasil 5a", "cds5")


def _damodaran_crp_brasil(ctx: Ctx, grupo, j, p):
    versao = ctx.bases.versao_vigente("damodaran_ctryprem", ctx.data_base)
    df, meta = ctx.bases.ler("damodaran_ctryprem", versao)
    linha = df[df["country"] == "Brazil"]
    if linha.empty:
        raise KeyError(f"Brazil não encontrado em damodaran_ctryprem v{versao}")
    valor = float(linha["country_risk_premium"].iloc[0])
    rec = ctx.bases.recorte("damodaran_crp_brasil", "damodaran_ctryprem", linha, meta,
                            f"Damodaran ctryprem v{versao}: country risk premium (Brasil)")
    return m.Componente(grupo, NOMES_GRUPOS[grupo], valor, "country_risk_premium (Brasil)",
                        f"Damodaran ctryprem {versao}", None, [rec], {"versao": versao})


def _t10yie_media(ctx: Ctx, grupo, j, p):
    df, meta = ctx.bases.ler("fred_t10yie")
    espec = j["janela"]
    jan = interpretar(espec, ctx.corte)
    s = m._na_janela(m._mensal(df, "valor"), jan)
    m._exigir_cobertura(s, jan, NOMES_GRUPOS[grupo])
    rec = ctx.bases.recorte("t10yie", "fred_t10yie", jan.filtrar(df), meta,
                            "Inflação implícita 10a (T10YIE, FRED), diária")
    return m.Componente(grupo, NOMES_GRUPOS[grupo], s.mean() / 100, "média do T10YIE na janela",
                        f"T10YIE {espec} ({jan.rotulo()})", jan.to_dict(), [rec], {"n_obs": len(s)})


def _dv_fixo(ctx: Ctx, grupo, j, p):
    valor = float(p["valor"])
    return m.Componente(grupo, NOMES_GRUPOS[grupo], valor, "parâmetro fixo (entrada do usuário)",
                        f"Fixo {valor * 100:.0f}%", None, [], {"valor": valor})


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
                       descricao="Média mensal do CDS 10a (p.b.) × σ(ln diário Ibov)/σ(ln diário PU NTN-B) / 10.000.",
                       variantes_params=({"ntnb_vencimento": "2035-05-15"},)))
_registrar(DefVariavel("implicita_gs10_fii10", "Implícita: Treasury nominal × TIPS (médias mensais)",
                       "Federal Reserve (FRED GS10 e FII10)", ("inflacao_us",), _implicita, {"janela": "12m"},
                       descricao="Média de (1 + nominal)/(1 + TIPS) − 1 mensal."))
_registrar(DefVariavel("tlp_sgs27572", "TLP (média mensal)", "BCB, SGS 27572", ("tlp",), _tlp, {"janela": "12m"}))
_registrar(DefVariavel("focus_ipca_mediana", "Focus IPCA: média das medianas anuais", "BCB, Focus (Olinda)",
                       ("ipca",), _focus_ipca, {}, {"anos": 10, "base_calculo": 0},
                       descricao="Média das medianas anuais do Focus; anos sem projeção repetem o último.",
                       variantes_params=({"base_calculo": 0}, {"base_calculo": 1})))
_registrar(DefVariavel("damodaran_setores", "Damodaran: D/E de mercado dos setores, ponderado pelas fases",
                       "Damodaran Online (dbtfund)", ("d_v",), _dv_damodaran, {}, {"coluna": "market_de_unadjusted"}))

# ------------------------------------------------------------------ variáveis novas
_registrar(DefVariavel("t10_fechamento_mes", "T-10: fechamento do último dia útil do mês",
                       "Federal Reserve (FRED DGS10)", ("rf", "rf_estrutural"), _t10_fechamento_mes, {"janela": "12m"},
                       descricao="Média do fechamento diário do T-10 no último dia útil de cada mês."))
_registrar(DefVariavel("tbond_retorno_anual_damodaran", "T-Bond 10a: retorno anual histórico (Damodaran)",
                       "Damodaran Online (histretSP)", ("rf", "rf_estrutural"), _tbond_retorno_anual_damodaran,
                       {"janela": "intervalo:1995-01:2024-12"},
                       descricao="Média aritmética do retorno anual do T-Bond 10a (Damodaran histretSP) nos "
                                 "anos-calendário cobertos pela janela; exige anos completos."))
_registrar(DefVariavel("sp500_retorno_anual_damodaran", "S&P 500: retorno anual histórico (Damodaran)",
                       "Damodaran Online (histretSP)", ("rm",), _sp500_retorno_anual_damodaran,
                       {"janela": "intervalo:1995-01:2024-12"},
                       descricao="Média aritmética do retorno anual do S&P 500 (Damodaran histretSP) nos "
                                 "anos-calendário cobertos pela janela; exige anos completos."))
_registrar(DefVariavel("cds10_sem_multiplicador", "CDS 10a (sem multiplicador de volatilidade)",
                       "Investing.com (CDS Brasil 10a)", ("risco_brasil",), _cds10_sem_multiplicador,
                       {"janela_cds": "120m"},
                       descricao="Média mensal do CDS Brasil 10a (p.b.) / 10.000, sem o multiplicador de "
                                 "volatilidade Ibovespa/NTN-B."))
_registrar(DefVariavel("cds5_vol_ibov_ntnb", "CDS 5a × vol. Ibovespa/NTN-B",
                       "Investing.com (CDS) / B3 (Ibovespa) / Tesouro Nacional (NTN-B)", ("risco_brasil",), _cds5_vol,
                       {"janela_cds": "120m", "janela_vol": "60m"}, {"ntnb_vencimento": "2035-05-15"},
                       descricao="Como cds10_vol_ibov_ntnb, com o CDS Brasil 5a no lugar do 10a.",
                       variantes_params=({"ntnb_vencimento": "2035-05-15"},)))
_registrar(DefVariavel("damodaran_crp_brasil", "Damodaran: prêmio de risco-país (Brasil)",
                       "Damodaran Online (ctryprem)", ("risco_brasil",), _damodaran_crp_brasil,
                       descricao="country_risk_premium do Brasil, na edição vigente na data-base. Sem janela."))
_registrar(DefVariavel("t10yie_media", "T10YIE: inflação implícita 10a (média na janela)",
                       "Federal Reserve (FRED T10YIE)", ("inflacao_us",), _t10yie_media, {"janela": "12m"},
                       descricao="Média diária do breakeven de inflação 10 anos publicado pelo FRED (T10YIE)."))
_registrar(DefVariavel("dv_fixo", "D/(D+E): valor fixo", "Parâmetro do projeto", ("d_v",), _dv_fixo, {},
                       {"valor": 0.70}, descricao="Valor fixo informado (ex.: 'Fixo 70%' da planilha).",
                       variantes_params=({"valor": 0.70},)))
