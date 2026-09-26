"""Modo de cálculo 1: prática da planilha Santa Maria (referência conceitual: MF/STN 2018).

Cada variável é uma função que devolve um :class:`Componente` com o valor (em fração
decimal: 0,043 = 4,3%), o rótulo da janela gerado pelos parâmetros, a fórmula aplicada e
os recortes das bases efetivamente usados. Opções = parâmetros de janela/método em
:class:`Opcoes`; o padrão reproduz a opção ativa na planilha.

Fórmulas (planilha Santa Maria, aba *Custo de Capital*):
    ERP        = Rm − R'f
    β_l        = β_u · [1 + (1 − T) · D/V / (1 − D/V)]
    Ke nominal = Rf + β_l · ERP + Risco Brasil
    Ke real    = (1 + Ke nominal) / (1 + π_US) − 1
    Kd nominal = (1 + TLP) · (1 + remuneração BNDES + spread) · (1 + IPCA) − 1
    Kd real    = (1 + Kd nominal) / (1 + IPCA) − 1
    WACC       = Ke · (1 − D/V) + Kd · D/V · (1 − T)          (real e nominal)
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .fontes import Bases, Recorte
from .janelas import Janela, interpretar, mes_corte

NTNB_TITULO = "Tesouro IPCA+ com Juros Semestrais"


# ---------------------------------------------------------------- configuração
@dataclass
class Fase:
    setor: str
    peso: float
    fase: str = ""        # ex.: "construção", "operação" (texto das fontes)
    base_peso: str = ""   # ex.: "CAPEX", "OPEX" (o peso é a proporção de ...)


@dataclass
class Opcoes:
    rf_janela: str = "12m"                 # 12m | 10a | 26a | 28a | 30a | desde:AAAA-MM
    rf_estrutural_janela: str = "30a"
    rm_metodo: str = "ln_mensal"           # ln_mensal: (1+média ln mensal)^12−1 | anual: média dos retornos anuais
    rm_janela: str = "desde:1995-01"
    cds_janela: str = "120m"               # 120m (10 anos) | 12m
    vol_janela: str = "60m"                # janela das volatilidades Ibovespa/NTN-B
    ntnb_vencimento: str = "2035-05-15"
    inflacao_us_janela: str = "12m"        # 12m | 120m
    tlp_janela: str = "12m"                # 12m | 24m | 1m
    ipca_anos: int = 10                    # anos de projeção Focus (t … t+n−1); faltantes repetem o último
    beta_coluna: str = "unlevered_beta_corrected_for_cash"
    de_coluna: str = "market_de_unadjusted"
    ir_parametro: str = "ir_csll"


@dataclass
class Escolha:
    """Escolha de um grupo do WACC: qual variável (método + fonte), com quais janelas e parâmetros.

    ``janelas`` usa as chaves da definição da variável (ex.: ``{"janela": "12m"}`` ou
    ``{"janela_cds": "120m", "janela_vol": "60m"}``). Ver ``calc/variaveis.py``.
    """

    variavel: str
    janelas: dict[str, str] = field(default_factory=dict)
    params: dict = field(default_factory=dict)


def escolhas_de_opcoes(op: Opcoes) -> dict[str, Escolha]:
    """Converte as opções no formato antigo (``[opcoes]``) nas escolhas por grupo."""
    return {
        "rf": Escolha("t10_media_mensal", {"janela": op.rf_janela}),
        "rf_estrutural": Escolha("t10_media_mensal", {"janela": op.rf_estrutural_janela}),
        "rm": Escolha("sp500tr_ln_mensal" if op.rm_metodo == "ln_mensal" else "sp500tr_retorno_anual",
                      {"janela": op.rm_janela}),
        "risco_brasil": Escolha("cds10_vol_ibov_ntnb", {"janela_cds": op.cds_janela, "janela_vol": op.vol_janela},
                                {"ntnb_vencimento": op.ntnb_vencimento}),
        "inflacao_us": Escolha("implicita_gs10_fii10", {"janela": op.inflacao_us_janela}),
        "tlp": Escolha("tlp_sgs27572", {"janela": op.tlp_janela}),
        "ipca": Escolha("focus_ipca_mediana", {}, {"anos": op.ipca_anos, "base_calculo": 0}),
        "d_v": Escolha("damodaran_setores", {}, {"coluna": op.de_coluna}),
    }


def _sincronizar_opcoes(op: Opcoes, esc: dict[str, Escolha]) -> Opcoes:
    """Mantém as opções no formato antigo coerentes com as escolhas. Usadas nos textos do Excel."""
    d = asdict(op)
    j = lambda g, k="janela": esc[g].janelas.get(k) if g in esc else None  # noqa: E731
    pares = {"rf_janela": j("rf"), "rf_estrutural_janela": j("rf_estrutural"), "rm_janela": j("rm"),
             "cds_janela": j("risco_brasil", "janela_cds"), "vol_janela": j("risco_brasil", "janela_vol"),
             "inflacao_us_janela": j("inflacao_us"), "tlp_janela": j("tlp")}
    d.update({k: v for k, v in pares.items() if v})
    if "rm" in esc:
        d["rm_metodo"] = "anual" if esc["rm"].variavel == "sp500tr_retorno_anual" else "ln_mensal"
    if "risco_brasil" in esc and esc["risco_brasil"].params.get("ntnb_vencimento"):
        d["ntnb_vencimento"] = esc["risco_brasil"].params["ntnb_vencimento"]
    if "ipca" in esc and "anos" in esc["ipca"].params:
        d["ipca_anos"] = int(esc["ipca"].params["anos"])
    return Opcoes(**d)


@dataclass
class ConfigProjeto:
    """Configuração de um projeto.

    ``data_base`` é um **mês/ano**, gravado como o dia 1º do mês. O dia importa só para o Focus,
    via ``focus_relatorio``: o último relatório até essa data. Se vazio, usa-se o último relatório
    até o fim do mês-base. Configurações antigas com dia ≠ 1 são convertidas: o mês vira a
    data-base e a data completa vira ``focus_relatorio``.
    """

    projeto: str
    data_base: date
    fases: list[Fase]
    linha_bndes: str                       # id em parametros_manuais (ex.: bndes_rem_finem_saneamento)
    spread_credito: float                  # fração decimal (entrada do projeto)
    regiao: str = "global"                 # global | emerging
    spread_descricao: str = ""             # rótulo curto (coluna Descrição), ex.: "Financ. BNDES"
    spread_fonte: str = ""                 # texto da nota de fonte do spread
    opcoes: Opcoes = field(default_factory=Opcoes)
    notas: str = ""
    variaveis: dict[str, Escolha] = field(default_factory=dict)
    focus_relatorio: date | None = None

    def __post_init__(self):
        soma = sum(f.peso for f in self.fases)
        if not self.fases or abs(soma - 1) > 1e-9:
            raise ValueError(f"pesos das fases devem somar 1 (soma = {soma})")
        if self.regiao not in ("global", "emerging"):
            raise ValueError("regiao deve ser 'global' ou 'emerging'")
        if self.data_base.day != 1:
            if self.focus_relatorio is None:
                self.focus_relatorio = self.data_base
            self.data_base = self.data_base.replace(day=1)
        base = escolhas_de_opcoes(self.opcoes)
        self.variaveis = {**base, **(self.variaveis or {})}
        self.opcoes = _sincronizar_opcoes(self.opcoes, self.variaveis)

    @property
    def data_focus(self) -> date:
        """Último dia considerado para o relatório Focus."""
        if self.focus_relatorio:
            return self.focus_relatorio
        return (pd.Timestamp(self.data_base) + pd.offsets.MonthEnd(0)).date()

    @classmethod
    def de_toml(cls, caminho: str | Path) -> "ConfigProjeto":
        return cls.de_toml_texto(Path(caminho).read_text(encoding="utf-8"))

    @classmethod
    def de_toml_texto(cls, texto: str) -> "ConfigProjeto":
        d = tomllib.loads(texto)
        variaveis = {}
        for grupo, bloco in (d.get("variaveis") or {}).items():
            bloco = dict(bloco)
            variavel = bloco.pop("variavel")
            janelas = {k: v for k, v in bloco.items() if k.startswith("janela")}
            params = {k: v for k, v in bloco.items() if not k.startswith("janela")}
            variaveis[grupo] = Escolha(variavel, janelas, params)
        fr = d.get("focus_relatorio")
        return cls(
            variaveis=variaveis,
            focus_relatorio=fr if isinstance(fr, date) or fr is None else date.fromisoformat(fr),
            projeto=d["projeto"],
            data_base=d["data_base"] if isinstance(d["data_base"], date) else date.fromisoformat(d["data_base"]),
            fases=[Fase(**f) for f in d["beta"]["fases"]],
            regiao=d["beta"].get("regiao", "global"),
            linha_bndes=d["kd"]["linha_bndes"],
            spread_credito=float(d["kd"]["spread_credito"]),
            spread_descricao=d["kd"].get("spread_descricao", ""),
            spread_fonte=d["kd"].get("spread_fonte", ""),
            opcoes=Opcoes(**d.get("opcoes", {})),
            notas=d.get("notas", ""),
        )


# ---------------------------------------------------------------- resultado
@dataclass
class Componente:
    id: str
    nome: str
    valor: float
    formula: str
    rotulo: str = ""
    janela: dict | None = None
    recortes: list[Recorte] = field(default_factory=list)
    detalhes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "nome": self.nome, "valor": self.valor, "formula": self.formula,
                "rotulo": self.rotulo, "janela": self.janela, "detalhes": self.detalhes,
                "recortes": [r.resumo() for r in self.recortes]}


@dataclass
class ResultadoWACC:
    config: ConfigProjeto
    corte: str
    componentes: dict[str, Componente]

    def __getitem__(self, k: str) -> float:
        return self.componentes[k].valor

    def to_dict(self) -> dict:
        cfg = asdict(self.config)
        cfg["data_base"] = str(self.config.data_base)
        return {"modo": "modo1_santa_maria", "config": cfg, "mes_corte": self.corte,
                "componentes": {k: c.to_dict() for k, c in self.componentes.items()}}


# ---------------------------------------------------------------- utilidades
def _mensal_ultimo(df: pd.DataFrame, col: str) -> pd.Series:
    """Série diária → valor do último pregão de cada mês, indexada por Period mensal."""
    s = df.set_index("data")[col].sort_index()
    return s.groupby(s.index.to_period("M")).last()


def _mensal(df: pd.DataFrame, col: str) -> pd.Series:
    s = df.set_index("data")[col].sort_index()
    s.index = s.index.to_period("M")
    return s


def _na_janela(s: pd.Series, j: Janela) -> pd.Series:
    return s[(s.index >= j.inicio) & (s.index <= j.fim)]


def _exigir_cobertura(s: pd.Series, j: Janela, nome: str) -> None:
    faltando = j.n_meses - s.index.nunique()
    if faltando > 0:
        raise ValueError(f"{nome}: faltam {faltando} meses na janela {j.rotulo()} (base desatualizada?)")


def _parametro(bases: Bases, pid: str) -> tuple[float, Recorte, dict]:
    df, meta = bases.ler("parametros_manuais")
    linha = df[df["parametro"] == pid]
    if linha.empty:
        raise KeyError(f"parâmetro {pid} ausente de parametros_manuais")
    rec = bases.recorte(pid, "parametros_manuais", linha, meta, "parâmetro manual")
    return float(linha["valor"].iloc[0]) / 100.0, rec, linha.iloc[0].to_dict()


# ---------------------------------------------------------------- variáveis
def rf(bases: Bases, corte: pd.Period, espec: str, id_: str = "rf", nome: str = "Taxa livre de risco (Rf)") -> Componente:
    df, meta = bases.ler("fred_gs10")
    j = interpretar(espec, corte)
    s = _na_janela(_mensal(df, "valor"), j)
    _exigir_cobertura(s, j, nome)
    rec = bases.recorte(id_, "fred_gs10", j.filtrar(df), meta, "US Treasury 10a, média mensal (% a.a.)")
    return Componente(id_, nome, s.mean() / 100, "média das médias mensais do T-10", f"T-10 {espec} ({j.rotulo()})",
                      j.to_dict(), [rec], {"n_meses": len(s)})


def rm(bases: Bases, corte: pd.Period, metodo: str, espec: str) -> Componente:
    df, meta = bases.ler("yahoo_sp500tr")
    j = interpretar(espec, corte)
    mensal = _mensal_ultimo(df, "fechamento")
    if metodo == "ln_mensal":
        r = np.log(mensal / mensal.shift(1))
        rj = _na_janela(r, j).dropna()
        _exigir_cobertura(rj, j, "Rm")
        valor = (1 + rj.mean()) ** 12 - 1
        formula = "(1 + média dos retornos ln mensais)^12 − 1"
        det = {"n_meses": len(rj), "media_ln_mensal": rj.mean()}
    elif metodo == "anual":
        anual = mensal[mensal.index.month == 12]
        anual.index = anual.index.year
        ra = (anual / anual.shift(1) - 1).loc[j.inicio.year:j.fim.year].dropna()
        if len(ra) != j.fim.year - j.inicio.year + 1:
            raise ValueError(f"Rm anual: anos faltando na janela {j.rotulo()}")
        valor, formula, det = ra.mean(), "média dos retornos anuais (dez/dez)", {"n_anos": len(ra)}
    else:
        raise ValueError(f"rm_metodo desconhecido: {metodo}")
    ini = pd.Timestamp((j.inicio - 1).start_time)  # inclui o fechamento anterior ao 1º retorno
    usados = df[(df["data"] >= ini) & (df["data"] <= pd.Timestamp(j.data_fim))]
    rec = bases.recorte("rm", "yahoo_sp500tr", usados, meta, "S&P 500 Total Return, fechamento diário (pontos)")
    return Componente("rm", "Retorno de mercado (Rm)", valor, formula, f"S&P 500 TR {metodo} ({j.rotulo()})",
                      j.to_dict(), [rec], det)


def risco_brasil(bases: Bases, corte: pd.Period, op: Opcoes) -> Componente:
    # CDS 10 anos, média mensal. Meses ausentes na série mensal são completados pela série
    # diária (último pregão do mês = "Último" do Investing mensal).
    dfc, mc = bases.ler("investing_cds10_brasil_mensal")
    jc = interpretar(op.cds_janela, corte)
    mensal_cds = _mensal(dfc, "ultimo")
    try:
        dfd, md = bases.ler("investing_cds10_brasil")
        do_diario = _mensal_ultimo(dfd, "ultimo")
        completados = do_diario.index.difference(mensal_cds.index)
        mensal_cds = pd.concat([mensal_cds, do_diario.loc[completados]]).sort_index()
    except FileNotFoundError:
        dfd, md, completados = None, None, pd.PeriodIndex([], freq="M")
    cds = _na_janela(mensal_cds, jc)
    _exigir_cobertura(cds, jc, "CDS 10a (baixe o CSV do Investing para Bases/entrada/investing/)")
    # Volatilidades diárias (retornos ln): Ibovespa (B3) e PU da NTN-B
    jv = interpretar(op.vol_janela, corte)
    dfi, mi = bases.ler("b3_ibov")
    ibov = dfi.set_index("data")["fechamento"].sort_index()
    ri = np.log(ibov / ibov.shift(1))
    ri_j = ri[(ri.index >= pd.Timestamp(jv.data_inicio)) & (ri.index <= pd.Timestamp(jv.data_fim))].dropna()
    if (ri_j.abs() > 0.5).any():
        raise ValueError("Ibovespa: retorno diário > 50% na janela (rebase de 1997?): ajuste a janela")
    dft, mt = bases.ler("tesouro_td_taxas")
    ntnb = dft[(dft["titulo"] == NTNB_TITULO) & (dft["vencimento"].astype(str) == op.ntnb_vencimento)]
    if ntnb.empty:
        raise ValueError(f"NTN-B {op.ntnb_vencimento} não encontrada em tesouro_td_taxas")
    pu = ntnb.set_index("data")["pu_base"].sort_index()
    rn = np.log(pu / pu.shift(1))
    rn_j = rn[(rn.index >= pd.Timestamp(jv.data_inicio)) & (rn.index <= pd.Timestamp(jv.data_fim))].dropna()
    s_ibov, s_ntnb = ri_j.std(ddof=1), rn_j.std(ddof=1)
    mult = s_ibov / s_ntnb
    valor = cds.mean() * mult / 10_000
    ini_v = pd.Timestamp(jv.data_inicio) - pd.Timedelta(days=10)
    # recorte do CDS = série mensal efetivamente usada (coluna "origem": mensal | diário)
    meses_diario = [p for p in completados if jc.inicio <= p <= jc.fim]
    cds_usado = pd.DataFrame({"data": cds.index.to_timestamp(), "ultimo": cds.values,
                              "origem": ["diário (último pregão)" if p in meses_diario else "mensal" for p in cds.index]})
    recs = [
        bases.recorte("cds10", "investing_cds10_brasil_mensal", cds_usado, mc,
                      "CDS Brasil 10a, média mensal (bps)" + ("; meses completados pela série diária" if meses_diario else "")),
    ]
    recs += [
        bases.recorte("ibov", "b3_ibov", dfi[(dfi["data"] >= ini_v) & (dfi["data"] <= pd.Timestamp(jv.data_fim))],
                      mi, "Ibovespa, fechamento diário (inclui o pregão anterior à janela)"),
        bases.recorte("ntnb", "tesouro_td_taxas",
                      ntnb[(ntnb["data"] >= ini_v) & (ntnb["data"] <= pd.Timestamp(jv.data_fim))], mt,
                      f"{NTNB_TITULO} {op.ntnb_vencimento}, PU base diário"),
    ]
    if meses_diario:  # rastreabilidade da base diária (hash no Registro); sempre após os 3 recortes principais
        usados_d = dfd[pd.to_datetime(dfd["data"]).dt.to_period("M").isin(meses_diario)]
        recs.append(bases.recorte("cds10_diario", "investing_cds10_brasil", usados_d, md,
                                  "CDS Brasil 10a, diário (meses sem dado mensal)",
                                  meses=[str(p) for p in meses_diario]))
    return Componente(
        "risco_brasil", "Prêmio de risco Brasil", valor, "média CDS 10a (bps) × σ(ln Ibov) / σ(ln PU NTN-B) / 10.000",
        f"CDS 10a {jc.rotulo()} × vol. {jv.rotulo()} (Ibov/NTN-B {op.ntnb_vencimento[:4]})",
        {"cds": jc.to_dict(), "volatilidade": jv.to_dict()}, recs,
        {"cds_medio_bps": cds.mean(), "sigma_ibov": s_ibov, "sigma_ntnb": s_ntnb, "multiplicador": mult,
         "n_cds": len(cds), "n_ibov": len(ri_j), "n_ntnb": len(rn_j)},
    )


def beta_estrutura(bases: Bases, cfg: ConfigProjeto) -> tuple[Componente, Componente]:
    sufixo = "global" if cfg.regiao == "global" else "emerg"
    sb, sd = f"damodaran_beta_{sufixo}", f"damodaran_dbtfund_{sufixo}"
    vb, vd = bases.versao_vigente(sb, cfg.data_base), bases.versao_vigente(sd, cfg.data_base)
    dfb, mb = bases.ler(sb, vb)
    dfd, md = bases.ler(sd, vd)
    op = cfg.opcoes
    linhas_b, linhas_d, betas, dvs = [], [], [], []
    for f in cfg.fases:
        lb, ld = dfb[dfb["industry_name"] == f.setor], dfd[dfd["industry_name"] == f.setor]
        if lb.empty or ld.empty:
            raise KeyError(f"setor Damodaran não encontrado: {f.setor!r} ({sb} v{vb} / {sd} v{vd})")
        de = float(ld[op.de_coluna].iloc[0])
        betas.append(float(lb[op.beta_coluna].iloc[0]))
        dvs.append(de / (1 + de))
        linhas_b.append(lb)
        linhas_d.append(ld)
    pesos = [f.peso for f in cfg.fases]
    beta_u = float(np.dot(pesos, betas))
    dv = float(np.dot(pesos, dvs))
    setores = " e ".join(f.setor for f in cfg.fases)
    det = {"fases": [{"setor": f.setor, "peso": f.peso, "beta_u": b, "d_v": d} for f, b, d in zip(cfg.fases, betas, dvs)]}
    cb = Componente("beta_u", "Beta desalavancado", beta_u, f"Σ peso × {op.beta_coluna}",
                    f"Damodaran {cfg.regiao.title()} {vb}: {setores}", None,
                    [bases.recorte("beta", sb, pd.concat(linhas_b), mb, f"Damodaran {sb} v{vb}")], det)
    cd = Componente("d_v", "D/(D+E)", dv, f"Σ peso × {op.de_coluna}/(1+{op.de_coluna})",
                    f"Damodaran {cfg.regiao.title()} {vd}: {setores}", None,
                    [bases.recorte("de", sd, pd.concat(linhas_d), md, f"Damodaran {sd} v{vd}")], det)
    return cb, cd


def inflacao_us(bases: Bases, corte: pd.Period, espec: str) -> Componente:
    dn, mn = bases.ler("fred_gs10")
    dr, mr = bases.ler("fred_fii10")
    j = interpretar(espec, corte)
    n, r = _na_janela(_mensal(dn, "valor"), j), _na_janela(_mensal(dr, "valor"), j)
    _exigir_cobertura(r, j, "TIPS 10a")
    implicita = ((1 + n / 100) / (1 + r / 100) - 1).dropna()
    recs = [bases.recorte("treasury", "fred_gs10", j.filtrar(dn), mn, "Treasury 10a nominal, média mensal"),
            bases.recorte("tips", "fred_fii10", j.filtrar(dr), mr, "TIPS 10a, média mensal")]
    return Componente("inflacao_us", "Inflação US$ (implícita)", implicita.mean(),
                      "média de (1 + nominal)/(1 + TIPS) − 1 mensal", f"Implícita {espec} ({j.rotulo()})",
                      j.to_dict(), recs, {"n_meses": len(implicita)})


def tlp(bases: Bases, corte: pd.Period, espec: str) -> Componente:
    df, meta = bases.ler("bcb_tlp")
    j = interpretar(espec, corte)
    s = _na_janela(_mensal(df, "valor"), j)
    _exigir_cobertura(s, j, "TLP")
    return Componente("tlp", "TLP", s.mean() / 100, "média mensal da TLP (SGS 27572)", f"TLP {espec} ({j.rotulo()})",
                      j.to_dict(), [bases.recorte("tlp", "bcb_tlp", j.filtrar(df), meta, "TLP, SGS 27572 (% a.a.)")],
                      {"n_meses": len(s)})


def ipca_focus(bases: Bases, data_base: date, anos: int, data_focus: date | None = None,
               base_calculo: int = 0) -> Componente:
    """Média das medianas Focus de ``anos`` anos a partir do ano da data-base, no último relatório
    até ``data_focus`` (padrão: a própria ``data_base``). ``base_calculo``: 0 = últimos 30 dias,
    1 = últimos 5 dias úteis."""
    data_focus = data_focus or data_base
    df, meta = bases.ler("bcb_focus_ipca_anual")
    df = df[(df["base_calculo"] == base_calculo) & (df["data"] <= pd.Timestamp(data_focus))]
    if df.empty:
        raise ValueError(f"Focus: nenhum relatório até {data_focus:%d/%m/%Y}")
    dia = df["data"].max()
    rel = df[df["data"] == dia].set_index("ano_referencia")["mediana"].sort_index()
    serie, ultimo = [], None
    for a in range(data_base.year, data_base.year + anos):
        if a in rel.index:
            ultimo = float(rel.loc[a])
        if ultimo is None:
            raise ValueError(f"Focus {dia.date()}: sem projeção para {a}")
        serie.append((a, ultimo, a in rel.index))
    valores = [v for _, v, _ in serie]
    usados = df[df["data"] == dia]
    return Componente("ipca", "IPCA (Focus)", float(np.mean(valores)) / 100,
                      f"média das medianas Focus {data_base.year}–{data_base.year + anos - 1} (anos sem projeção repetem o último)",
                      f"Focus de {dia.date():%d/%m/%Y}, {anos} anos", None,
                      [bases.recorte("focus", "bcb_focus_ipca_anual", usados, meta,
                                     f"Focus IPCA anual, mediana, base {base_calculo}")],
                      {"relatorio": str(dia.date()), "anos": [{"ano": a, "ipca": v, "projetado": p} for a, v, p in serie]})


# ---------------------------------------------------------------- composição
def compor(*, rf: float, rf_estrutural: float, rm: float, risco_brasil: float, beta_u: float, d_v: float,
           t: float, inflacao_us: float, tlp: float, remuneracao: float, spread: float, ipca: float) -> dict[str, float]:
    """Fórmulas da aba *Custo de Capital* (função pura; todas as taxas em fração decimal)."""
    erp = rm - rf_estrutural
    beta_l = beta_u * (1 + (1 - t) * d_v / (1 - d_v))
    ke_nominal = rf + erp * beta_l + risco_brasil
    ke_real = (1 + ke_nominal) / (1 + inflacao_us) - 1
    kd_nominal = (1 + tlp) * (1 + remuneracao + spread) * (1 + ipca) - 1
    kd_real = (1 + kd_nominal) / (1 + ipca) - 1
    return {
        "erp": erp, "beta_l": beta_l, "ke_nominal": ke_nominal, "ke_real": ke_real,
        "kd_nominal": kd_nominal, "kd_real": kd_real,
        "wacc_real": ke_real * (1 - d_v) + kd_real * d_v * (1 - t),
        "wacc_nominal": ke_nominal * (1 - d_v) + kd_nominal * d_v * (1 - t),
    }


FORMULAS = {
    "erp": "Rm − R'f",
    "beta_l": "β_u · [1 + (1 − T) · D/V / (1 − D/V)]",
    "ke_nominal": "Rf + β_l · ERP + Risco Brasil",
    "ke_real": "(1 + Ke nominal)/(1 + π_US) − 1",
    "kd_nominal": "(1 + TLP)(1 + remuneração + spread)(1 + IPCA) − 1",
    "kd_real": "(1 + Kd nominal)/(1 + IPCA) − 1",
    "wacc_real": "Ke real · (1 − D/V) + Kd real · D/V · (1 − T)",
    "wacc_nominal": "Ke nominal · (1 − D/V) + Kd nominal · D/V · (1 − T)",
}
NOMES = {
    "erp": "Prêmio de risco de mercado (ERP)", "beta_l": "Beta realavancado", "ke_nominal": "Ke (US$ nominal)",
    "ke_real": "Ke (real)", "kd_nominal": "Kd (nominal)", "kd_real": "Kd (real)",
    "wacc_real": "WACC (real)", "wacc_nominal": "WACC (nominal)",
}


def calcular(cfg: ConfigProjeto, bases: Bases) -> ResultadoWACC:
    from .variaveis import GRUPOS_VARIAVEIS, calcular_grupo

    op = cfg.opcoes
    corte = mes_corte(cfg.data_base)
    c: dict[str, Componente] = {}

    # insumos com variável × janela escolhidas (ver calc/variaveis.py)
    for grupo in GRUPOS_VARIAVEIS:
        c[grupo] = calcular_grupo(bases, cfg, corte, grupo, cfg.variaveis[grupo])
    c["beta_u"], _ = beta_estrutura(bases, cfg)
    t, rec_t, lt = _parametro(bases, op.ir_parametro)
    c["t"] = Componente("t", "Alíquota IR/CSLL (T)", t, "parâmetro manual", lt["fonte"], None, [rec_t])
    rem, rec_r, lr = _parametro(bases, cfg.linha_bndes)
    c["remuneracao_bndes"] = Componente("remuneracao_bndes", "Remuneração básica BNDES", rem, "parâmetro manual",
                                        lr["fonte"], None, [rec_r], {"linha": cfg.linha_bndes,
                                                                     "verificado_em": lr["verificado_em"]})
    c["spread_credito"] = Componente("spread_credito", "Taxa de risco de crédito", cfg.spread_credito,
                                     "entrada do projeto", cfg.spread_descricao or "informado pelo projeto",
                                     detalhes={"fonte": cfg.spread_fonte})

    # composição (fórmulas da planilha)
    comp = compor(rf=c["rf"].valor, rf_estrutural=c["rf_estrutural"].valor, rm=c["rm"].valor,
                  risco_brasil=c["risco_brasil"].valor, beta_u=c["beta_u"].valor, d_v=c["d_v"].valor, t=t,
                  inflacao_us=c["inflacao_us"].valor, tlp=c["tlp"].valor, remuneracao=rem,
                  spread=cfg.spread_credito, ipca=c["ipca"].valor)
    for k, v in comp.items():
        c[k] = Componente(k, NOMES[k], v, FORMULAS[k])
    ordem = ["rf", "rf_estrutural", "rm", "erp", "risco_brasil", "beta_u", "d_v", "t", "beta_l", "ke_nominal",
             "inflacao_us", "ke_real", "tlp", "remuneracao_bndes", "spread_credito", "ipca", "kd_nominal",
             "kd_real", "wacc_real", "wacc_nominal"]
    return ResultadoWACC(cfg, str(corte), {k: c[k] for k in ordem})
