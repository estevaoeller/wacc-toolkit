"""Utilidades compartilhadas pelas páginas da interface Streamlit.

Só orquestra chamadas a :mod:`wacc_toolkit.servicos` e formata valores para exibição;
nenhuma regra de cálculo, validação ou gravação vive aqui.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st

from wacc_toolkit import servicos as sv
from wacc_toolkit.config import ConfiguracaoAusente

FORMATO_DATA = "DD/MM/YYYY"  # usado em todo st.date_input da interface

# ------------------------------------------------------------------ ambiente
def obter_ambiente() -> sv.Ambiente | None:
    """Devolve o ambiente (pastas de bases/projetos/cálculos), com cache em ``session_state``.

    Mostra um erro e devolve ``None`` se as bases não estiverem configuradas.
    """
    if "amb" in st.session_state:
        return st.session_state.amb
    try:
        amb = sv.ambiente()
    except ConfiguracaoAusente as e:
        st.error(str(e))
        return None
    st.session_state.amb = amb
    return amb


# ------------------------------------------------------------------ formatação de números (pt-BR)
# a formatação em si (vírgula decimal) é regra de apresentação pura, sem cálculo: delega para
# wacc_toolkit.servicos, que é quem também formata a tabela Custo de Capital.
def fmt_pct(valor, casas: int = 2) -> str:
    return sv.formatar_percentual_pt(valor, casas) or "-"


def fmt_num(valor, casas: int = 2) -> str:
    return sv.formatar_numero_pt(valor, casas) or "-"


def formatar_valor(id_componente: str, valor: float) -> str:
    return sv.formatar_valor_componente(id_componente, valor) or "-"


def fmt_num_sinal_pt(valor, casas: int = 2) -> str:
    """Número com sinal explícito e vírgula decimal (ex.: +12,34 / -5,00), para diferenças."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    sinal = "+" if valor >= 0 else "-"
    return f"{sinal}{fmt_num(abs(valor), casas)}"


def formatar_df_numerico_pt(df: pd.DataFrame, casas: int = 2, exceto: tuple[str, ...] = ()) -> pd.DataFrame:
    """Cópia de ``df`` com as colunas numéricas (exceto as em ``exceto``) formatadas em pt-BR,
    para exibição em ``st.dataframe`` (a tabela original, para gráfico/download, não é alterada)."""
    saida = df.copy()
    for col in saida.columns:
        if col in exceto or not pd.api.types.is_numeric_dtype(saida[col]):
            continue
        inteira = pd.api.types.is_integer_dtype(saida[col])
        saida[col] = saida[col].map(lambda v: fmt_num(v, 0 if inteira else casas))
    return saida


# ------------------------------------------------------------------ formatação de datas (pt-BR)
def fmt_data_pt(valor) -> str:
    """Data como dd/mm/aaaa. Aceita ``date``/``datetime``/``Timestamp`` ou string ISO."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    if isinstance(valor, str):
        if not valor:
            return "-"
        valor = date.fromisoformat(valor[:10])
    return f"{valor.day:02d}/{valor.month:02d}/{valor.year:04d}"


def fmt_mes_ano_pt(valor) -> str:
    """Data-base como mm/aaaa. Aceita ``date`` ou string ISO ('AAAA-MM-DD')."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    if isinstance(valor, str):
        if not valor:
            return "-"
        valor = date.fromisoformat(valor[:10])
    return f"{valor.month:02d}/{valor.year:04d}"


def fmt_datahora_local_pt(iso_utc: str | None) -> str:
    """Um "gerado_em" UTC ISO (``ResultadoWACC``/registro) como dd/mm/aaaa hh:mm no horário local."""
    if not iso_utc:
        return "-"
    dt = datetime.fromisoformat(iso_utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    return f"{local.day:02d}/{local.month:02d}/{local.year:04d} {local.hour:02d}:{local.minute:02d}"


def csv_excel_br(df: pd.DataFrame) -> bytes:
    """CSV com separador ';' e decimal ',', para abrir direto no Excel em pt-BR."""
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


# ------------------------------------------------------------------ cache de leitura das bases
# st.cache_data guarda o resultado por chave; usamos (série, versão, sha256_csv) - o sha vem de
# um metadado leve (sv.meta_serie não lê o CSV), então só relemos o CSV grande quando o conteúdo
# realmente mudou, mesmo que a página seja reaberta várias vezes na mesma sessão do servidor.
@st.cache_data(show_spinner=False)
def _ler_serie_no_cache(bases_dir: str, serie: str, versao: str | None, sha256_csv: str | None):
    amb = sv.ambiente(bases_dir)
    return sv.ler_serie(amb, serie, versao)


def ler_serie_cacheada(amb: sv.Ambiente, serie: str, versao: str | None = None) -> tuple[pd.DataFrame, dict]:
    meta = sv.meta_serie(amb, serie, versao)
    return _ler_serie_no_cache(str(amb.bases), serie, versao, meta.get("sha256_csv"))


@st.cache_data(show_spinner=False)
def _indicadores_painel_no_cache(bases_dir: str, meses: int, assinatura: tuple):
    amb = sv.ambiente(bases_dir)
    return sv.indicadores_painel(amb, meses)


def indicadores_painel_cacheados(amb: sv.Ambiente, meses: int = 24) -> list[dict]:
    """Como ``sv.indicadores_painel``, cacheado pela assinatura (sha256) dos metadados das
    séries envolvidas - recalcula só quando alguma base usada pelo painel muda."""
    series = ("fred_gs10", "fred_fii10", "investing_cds10_brasil_mensal", "b3_ibov", "yahoo_sp500tr",
             "tesouro_td_taxas", "bcb_tlp", "bcb_focus_ipca_anual")
    assinatura = tuple(sv.meta_serie(amb, s).get("sha256_csv") for s in series)
    return _indicadores_painel_no_cache(str(amb.bases), meses, assinatura)


# ------------------------------------------------------------------ alternativas (Montar cenário)
def _assinatura_bases(amb: sv.Ambiente) -> float:
    """Assinatura grosseira do conteúdo das bases tratadas (maior mtime dos CSVs): muda sempre que
    alguma base é atualizada, então basta para invalidar o cache de `alternativas` sem precisar
    descobrir, uma a uma, quais séries cada variável do catálogo usa."""
    pasta = amb.bases / "tratado"
    if not pasta.exists():
        return 0.0
    return max((p.stat().st_mtime for p in pasta.rglob("*.csv")), default=0.0)


def _chave_config_grupo(cfg: sv.ConfigProjeto, grupo: str) -> tuple:
    """Só as partes de ``cfg`` que afetam ``alternativas(grupo)``: a data-base/Focus (toda janela
    depende do corte), a região e as fases (usadas por d_v) e a escolha ATUAL do próprio grupo (a
    linha "ativa" da tabela) - nunca a escolha de outro grupo, para não invalidar o cache dos
    outros 7 grupos quando só este muda."""
    esc = cfg.variaveis.get(grupo)
    esc_chave = (esc.variavel, tuple(sorted((esc.janelas or {}).items())),
                tuple(sorted((esc.params or {}).items()))) if esc else None
    fases_chave = tuple((f.setor, f.peso, f.fase, f.base_peso) for f in cfg.fases)
    return (cfg.data_base, cfg.focus_relatorio, cfg.regiao, fases_chave, esc_chave)


@st.cache_data(show_spinner=False)
def _alternativas_no_cache(bases_dir: str, grupo: str, chave_grupo: tuple, assinatura_janelas: tuple,
                           assinatura_bases: float, _cfg, _bases) -> pd.DataFrame:
    amb = sv.ambiente(bases_dir)
    return sv.alternativas(amb, _cfg, grupo, bases=_bases)


def alternativas_cacheadas(amb: sv.Ambiente, cfg: sv.ConfigProjeto, grupo: str, bases=None) -> pd.DataFrame:
    """Como ``sv.alternativas``, cacheado por (bases, data-base/Focus/fases/escolha do grupo,
    catálogo de janelas, conteúdo das bases): mudar a escolha de só um grupo não invalida o cache
    dos outros 7. ``cfg``/``bases`` não entram na chave (prefixo ``_``): usadas só para reler de
    fato, em caso de cache miss, reaproveitando as séries já lidas por outros grupos na mesma tela."""
    chave_grupo = _chave_config_grupo(cfg, grupo)
    assinatura_janelas = tuple((j["espec"], j["nome"]) for j in sv.listar_janelas(amb))
    assinatura_bases = _assinatura_bases(amb)
    return _alternativas_no_cache(str(amb.bases), grupo, chave_grupo, assinatura_janelas, assinatura_bases, cfg, bases)


# ------------------------------------------------------------------ gráfico padrão (pt-BR)
_LOCALE_PT_BR = {
    "number": {"decimal": ",", "thousands": ".", "grouping": [3], "currency": ["R$ ", ""]},
    "time": {
        "dateTime": "%A, %e de %B de %Y. %X", "date": "%d/%m/%Y", "time": "%H:%M:%S",
        "periods": ["AM", "PM"],
        "days": ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"],
        "shortDays": ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"],
        "months": ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
                   "Setembro", "Outubro", "Novembro", "Dezembro"],
        "shortMonths": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    },
}


def grafico_linha(df, x: str = "data", y: str = "valor", altura: int = 260, titulo_y: str = ""):
    """Gráfico de linha com eixos em pt-BR (meses abreviados, vírgula decimal, ponto de milhar)
    e escala vertical ajustada aos dados (não começa em zero)."""
    import altair as alt

    dados = df[[x, y]].dropna().copy()
    dados[x] = pd.to_datetime(dados[x])
    return (
        alt.Chart(dados)
        .mark_line(strokeWidth=1.8)
        .encode(
            x=alt.X(f"{x}:T", title=None, axis=alt.Axis(format="%b/%y", labelAngle=0, tickCount=6)),
            y=alt.Y(f"{y}:Q", title=titulo_y or None, scale=alt.Scale(zero=False), axis=alt.Axis(format=",.2~f")),
            tooltip=[alt.Tooltip(f"{x}:T", title="Data", format="%d/%m/%Y"),
                     alt.Tooltip(f"{y}:Q", title=titulo_y or "Valor", format=",.2f")],
        )
        .properties(height=altura)
        .configure(locale=_LOCALE_PT_BR)
    )
