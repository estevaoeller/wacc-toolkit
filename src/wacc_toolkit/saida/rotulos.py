"""Rótulos e descrições da tabela "Custo de Capital" (aba do Excel e tela da interface).

Um único lugar para os nomes de item e as descrições por componente, para que o Excel
auditável e a interface Streamlit mostrem exatamente o mesmo texto. Não faz nenhum
cálculo: só formata texto a partir de um :class:`~wacc_toolkit.calc.modo1.ResultadoWACC`
já pronto.
"""

from __future__ import annotations

from dataclasses import asdict

from ..calc.modo1 import ResultadoWACC

# ------------------------------------------------------------------ ordem/seções
KE_ITENS = ["rf", "rm", "rf_estrutural", "erp", "risco_brasil", "beta_u", "d_v", "t", "beta_l",
            "ke_nominal", "inflacao_us", "ke_real"]
KD_ITENS = ["tlp", "remuneracao_bndes", "spread_credito", "ipca", "kd_nominal", "kd_real"]
WACC_ITENS = ["wacc_real", "wacc_nominal"]

# ------------------------------------------------------------------ nomes de item
ROTULOS = {
    "rf": "Taxa Livre de Riscos (Rf)", "rm": "Risco de Mercado",
    "rf_estrutural": "Taxa Livre de Riscos Estrutural (R'f)",
    "erp": "Prêmio de Risco de Mercado (Equity Risk Premium)", "risco_brasil": "Prêmio de Risco Brasil",
    "beta_u": "Beta desalavancado", "d_v": "D/(D+E)", "t": "T", "beta_l": "Beta re-alavancado",
    "ke_nominal": "Ke (US$ nominal)", "inflacao_us": "Inflação US$", "ke_real": "Ke (real)",
    "tlp": "Valor da TLP", "remuneracao_bndes": "Remuneração BNDES", "spread_credito": "Taxa de Risco de Crédito",
    "ipca": "Taxa de Inflação", "kd_nominal": "Kd (nominal)", "kd_real": "Kd (real)",
    "wacc_real": "WACC (real)", "wacc_nominal": "WACC (nominal)",
}

# linhas cujo valor vem de uma fórmula de composição (não de uma base/parâmetro isolado):
# na tela e no Excel, a descrição dessas linhas fica vazia.
COMPOSTOS = {"erp", "beta_l", "ke_nominal", "ke_real", "kd_nominal", "kd_real", "wacc_real", "wacc_nominal"}

# ------------------------------------------------------------------ esquema Variável × Janela
# grupos preenchidos pelo catálogo de variáveis (ver calc/variaveis.py) e a(s) variável(is) que
# reproduzem literalmente a planilha original: só para essas o Excel usa a fórmula "clássica"
# (fixa, célula a célula); qualquer outra variável usa o caminho genérico (valor + recortes
# genéricos), que nunca quebra, mesmo para variáveis criadas depois deste código.
VARS_PLANILHA: dict[str, set[str]] = {
    "rf": {"t10_media_mensal"},
    "rf_estrutural": {"t10_media_mensal"},
    "rm": {"sp500tr_ln_mensal", "sp500tr_retorno_anual"},
    "risco_brasil": {"cds10_vol_ibov_ntnb"},
    "d_v": {"damodaran_setores"},
    "inflacao_us": {"implicita_gs10_fii10"},
    "tlp": {"tlp_sgs27572"},
    "ipca": {"focus_ipca_mediana"},
}


def eh_variavel_planilha(grupo: str, variavel_id: str | None) -> bool:
    """``True`` só quando ``variavel_id`` é (uma d)a variável que reproduz a planilha para ``grupo``.

    ``variavel_id`` ausente (grupos que não vêm do catálogo: t, remuneração BNDES, spread) sempre
    devolve ``False`` sem erro - o chamador decide o que fazer nesse caso.
    """
    return variavel_id is not None and variavel_id in VARS_PLANILHA.get(grupo, set())


# ------------------------------------------------------------------ utilidades de texto
def meses_txt(espec: str) -> str:
    if espec.endswith("m") and espec[:-1].isdigit():
        return f"{espec[:-1]} meses"
    if espec.endswith("a") and espec[:-1].isdigit():
        return f"{espec[:-1]} anos"
    return espec


def anos_abrev(espec: str) -> str:
    if espec.endswith("m") and espec[:-1].isdigit():
        n = int(espec[:-1])
        return f"{n // 12}a" if n % 12 == 0 else f"{n}m"
    if espec.endswith("a") and espec[:-1].isdigit():
        return f"{espec[:-1]}a"
    return espec


def desc_param(fonte: str) -> str:
    if fonte.startswith("Receita Federal"):
        return "Receita Federal do Brasil"
    if fonte.startswith("BNDES Finem:"):
        resto = fonte[len("BNDES Finem:"):].split(" (")[0].strip()
        return f"Finem - {resto}"
    return fonte.split(" (")[0]


def extrair_versao(rotulo: str) -> str:
    return rotulo.split(":")[0].strip().split()[-1]


# ------------------------------------------------------------------ descrições por componente
def _normalizar(fonte: ResultadoWACC | dict) -> tuple[dict, dict, dict[str, dict]]:
    """Aceita um :class:`ResultadoWACC` (cálculo recém-feito) ou o dict de um registro salvo
    (``servicos.ler_calculo``) e devolve ``(config, opcoes, componentes)`` como dicts simples,
    para que :func:`descricoes` trate os dois casos da mesma forma."""
    if isinstance(fonte, ResultadoWACC):
        cfg = asdict(fonte.config)
        cfg["data_base"] = str(fonte.config.data_base)
        componentes = {k: v.to_dict() for k, v in fonte.componentes.items()}
    else:
        cfg = fonte["config"]
        componentes = fonte["componentes"]
    return cfg, cfg["opcoes"], componentes


def descricoes(fonte: ResultadoWACC | dict) -> dict[str, str]:
    """Descrição de cada linha da tabela Custo de Capital (vazia para as linhas compostas).

    ``fonte`` pode ser um :class:`ResultadoWACC` (Excel, cálculo ao vivo na tela) ou o dict de
    um registro já salvo em disco (histórico), com a mesma estrutura de ``ResultadoWACC.to_dict``.
    """
    cfg, op, c = _normalizar(fonte)
    d: dict[str, str] = {}

    def _var(grupo: str) -> str | None:
        return (c.get(grupo) or {}).get("detalhes", {}).get("variavel")

    def _conhecida(grupo: str) -> bool:
        return eh_variavel_planilha(grupo, _var(grupo))

    def _rotulo(grupo: str) -> str:
        """Descrição de reserva: o rótulo que o próprio componente já traz (nunca quebra)."""
        return (c.get(grupo) or {}).get("rotulo") or ""

    if _conhecida("rf"):
        d["rf"] = f"T-10 {meses_txt(op['rf_janela'])} ({c['rf']['janela']['rotulo']})"
    else:
        d["rf"] = _rotulo("rf")

    if not _conhecida("rm"):
        d["rm"] = _rotulo("rm")
    elif "n_anos" in c["rm"]["detalhes"]:
        d["rm"] = f"Média SP500 Retornos Anuais ({c['rm']['janela']['rotulo']})"
    else:
        d["rm"] = f"Média SP500 Ln Mensal ({c['rm']['janela']['rotulo']})"

    if _conhecida("rf_estrutural"):
        d["rf_estrutural"] = f"T-10 {meses_txt(op['rf_estrutural_janela'])} ({c['rf_estrutural']['janela']['rotulo']})"
    else:
        d["rf_estrutural"] = _rotulo("rf_estrutural")

    if _conhecida("risco_brasil"):
        d["risco_brasil"] = f"CDS {anos_abrev(op['cds_janela'])} + Vol. {anos_abrev(op['vol_janela'])} (IBOV-NTNB)"
    else:
        d["risco_brasil"] = _rotulo("risco_brasil")

    desc_beta_dv = f"{cfg['regiao'].title()}/{' e '.join(f['setor'] for f in cfg['fases'])}"
    d["beta_u"] = desc_beta_dv  # beta_u nunca vem do catálogo de variáveis (sempre a mesma conta)
    d["d_v"] = desc_beta_dv if _conhecida("d_v") else _rotulo("d_v")

    d["t"] = desc_param(c["t"]["rotulo"])
    d["tlp"] = f"TLP {op['tlp_janela']} ({c['tlp']['janela']['rotulo']})" if _conhecida("tlp") else _rotulo("tlp")
    d["remuneracao_bndes"] = desc_param(c["remuneracao_bndes"]["rotulo"])
    d["spread_credito"] = cfg.get("spread_descricao") or "Spread de crédito do projeto"
    if _conhecida("inflacao_us"):
        d["inflacao_us"] = f"Implícita {meses_txt(op['inflacao_us_janela'])} ({c['inflacao_us']['janela']['rotulo']})"
    else:
        d["inflacao_us"] = _rotulo("inflacao_us")
    d["ipca"] = f"Projeção Focus - {op['ipca_anos']} anos" if _conhecida("ipca") else _rotulo("ipca")

    for cid in COMPOSTOS:
        d[cid] = ""
    return d
