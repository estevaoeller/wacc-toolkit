"""Damodaran (NYU Stern) — betas, fundamentos de dívida, risco-país e retornos históricos.

Fonte: planilhas anuais publicadas em
https://pages.stern.nyu.edu/~adamodar/pc/datasets/<arquivo>

Cada planilha é substituída inteiramente a cada atualização anual (normalmente em
janeiro). Por isso as séries são **versionadas** (``SerieSpec.versionada=True``):
cada edição vira ``tratado/<serie>/<versao>.csv`` e a edição anterior nunca é
sobrescrita. A versão é o ano de publicação, extraído da célula "Date updated"/
"Date of update" presente no topo de cada planilha — nunca a data de hoje. Se essa
célula não puder ser localizada, ``interpretar`` falha com ``ValueError`` (regra 9 do
contrato: nunca chutar a versão).

Origens de coleta (``coletar``):
  (a) web — download direto das URLs fixas acima;
  (b) importação local — arquivos com o mesmo nome colocados em
      ``entrada/damodaran/<qualquer subpasta>/`` (ex.: ``entrada/damodaran/2026/
      betaGlobal.xls``), útil para versões baixadas manualmente. O rótulo
      (``ArquivoBruto.rotulo``) é o mesmo nos dois casos (nome do arquivo sem
      extensão), então o núcleo deduplica automaticamente pelo sha256 do conteúdo.
      Se web e entrada trouxerem a mesma versão com conteúdos diferentes, a série
      dessa versão é regravada e ``validate`` emite aviso de "histórico revisado" —
      isso é aceitável e esperado (ex.: Damodaran corrige a planilha após publicar).
Falha de download de um arquivo (ex.: 404, rate limit) não interrompe os demais:
é capturada e registrada via ``logging.getLogger("wacc_toolkit").warning``.

Séries e decisões de layout (planilhas de jan/2026 inspecionadas para desenhar o
parser; o parser localiza a linha de cabeçalho pelo texto da primeira coluna, não
por índice fixo, para tolerar pequenos deslocamentos entre edições):

- ``damodaran_beta_global`` / ``damodaran_beta_emerg`` / ``damodaran_beta_us``
  (arquivos ``betaGlobal.xls``, ``betaemerg.xls``, ``betas.xls``, aba
  "Industry Averages"): mantemos as 8 colunas centrais e estáveis da tabela
  (Industry Name .. Unlevered beta corrected for cash). As colunas seguintes
  ("HiLo Risk", desvios-padrão, betas anuais por ano civil) mudam de nome e de
  quantidade a cada edição (ex.: "2022,2023,2024,2025,Average(2020-24)" vira outro
  intervalo no ano seguinte) — não são incluídas por não serem reproduzíveis de
  forma estável ano a ano.
- ``damodaran_totalbeta_global`` (``totalbetaGlobal.xls``, aba "Industry
  Averages"): "Total Beta by Industry Sector" citado na Metodologia do Tesouro.
- ``damodaran_dbtfund_global`` / ``damodaran_dbtfund_emerg`` (``dbtfundGlobal.xls``,
  ``dbtfundemerg.xls``, aba "Industry Averages"): todas as 15 colunas da tabela.
  ``faixa=None`` propositalmente: "Debt to EBITDA" diverge para setores com EBITDA
  perto de zero (observado de -23714 a 2713 nos dados de jan/2026), incompatível
  com uma faixa única plausível junto das demais colunas em fração (0-1) ou razão
  pequena (0-5).
- ``damodaran_ctryprem`` (``ctryprem.xlsx``, aba "ERPs by country"): a segunda
  coluna da tabela real é a região (ex.: "Middle East"), mas o cabeçalho da
  planilha traz nela, por erro do autor, o nome do primeiro valor ("Africa") em
  vez de "Region" — por isso as colunas são nomeadas explicitamente por posição,
  não pelo texto do cabeçalho. A aba tem uma segunda tabela solta abaixo
  ("Frontier Markets (no sovereign ratings)", com colunas diferentes) que é
  descartada: a leitura para quando a coluna de região fica vazia, o que marca o
  fim da tabela principal.
- ``damodaran_histretsp`` (``histretSP.xls``, aba "Returns by year"): mantemos o
  retorno anual do S&P 500 (com dividendos) e do T.Bond de 10 anos; linhas de
  resumo no final da tabela ("Arithmetic Average...", "1928-2025" etc.) são
  descartadas pelo filtro "Year é um ano de 4 dígitos".

Unidade: os valores são preservados exatamente como a fonte publica — a maioria
já vem como fração decimal (ex.: 0.0425 representa 4,25% a.a.); nenhuma conversão
percentual é feita aqui.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

log = logging.getLogger("wacc_toolkit")

BASE_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/{arquivo}"

# rotulo -> (nome do arquivo na fonte, extensão, aba, id da série, rótulo do
# cabeçalho na primeira coluna que localiza a linha de cabeçalho da tabela)
_ARQUIVOS: dict[str, tuple[str, str, str, str, str]] = {
    "betaGlobal": ("betaGlobal.xls", "xls", "Industry Averages", "damodaran_beta_global", "Industry Name"),
    "betaemerg": ("betaemerg.xls", "xls", "Industry Averages", "damodaran_beta_emerg", "Industry Name"),
    "betas": ("betas.xls", "xls", "Industry Averages", "damodaran_beta_us", "Industry Name"),
    "totalbetaGlobal": ("totalbetaGlobal.xls", "xls", "Industry Averages", "damodaran_totalbeta_global", "Industry Name"),
    "dbtfundGlobal": ("dbtfundGlobal.xls", "xls", "Industry Averages", "damodaran_dbtfund_global", "Industry Name"),
    "dbtfundemerg": ("dbtfundemerg.xls", "xls", "Industry Averages", "damodaran_dbtfund_emerg", "Industry Name"),
    "ctryprem": ("ctryprem.xlsx", "xlsx", "ERPs by country", "damodaran_ctryprem", "Country"),
    "histretSP": ("histretSP.xls", "xls", "Returns by year", "damodaran_histretsp", "Year"),
}

_COLUNAS_BETA_SETOR = (
    "industry_name", "number_of_firms", "beta", "de_ratio", "effective_tax_rate",
    "unlevered_beta", "cash_to_firm_value", "unlevered_beta_corrected_for_cash",
)
_COLUNAS_TOTALBETA = (
    "industry_name", "number_of_firms", "average_unlevered_beta", "average_levered_beta",
    "average_correlation_with_market", "total_unlevered_beta", "total_levered_beta",
)
_COLUNAS_DBTFUND = (
    "industry_name", "number_of_firms", "book_debt_to_capital",
    "market_debt_to_capital_unadjusted", "market_de_unadjusted",
    "market_debt_to_capital_adjusted_leases", "market_de_adjusted_leases",
    "interest_coverage_ratio", "debt_to_ebitda", "effective_tax_rate",
    "institutional_holdings", "std_dev_stock_prices", "ebitda_ev",
    "net_ppe_total_assets", "capex_total_assets",
)
_COLUNAS_CTRYPREM = (
    "country", "regiao", "moodys_rating", "default_spread_rating",
    "equity_risk_premium", "country_risk_premium",
)
_COLUNAS_HISTRETSP = ("ano", "sp500_retorno", "tbond10_retorno")


def _ler_planilha(caminho: Path, aba: str) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(caminho.read_bytes()), sheet_name=aba, header=None)


def extrair_versao(df0: pd.DataFrame) -> str:
    """Procura, nas primeiras linhas, uma célula da coluna A contendo "date"
    (case-insensitive — cobre "Date updated:" e "Date of update:") e devolve o
    ano da primeira data encontrada na mesma linha, como string "AAAA".

    Levanta ``ValueError`` se não encontrar — nunca usamos a data de hoje como
    substituto, para não gravar uma versão errada silenciosamente."""
    limite = min(15, len(df0))
    for i in range(limite):
        rotulo = df0.iat[i, 0]
        if isinstance(rotulo, str) and "date" in rotulo.lower():
            for j in range(1, df0.shape[1]):
                valor = df0.iat[i, j]
                if isinstance(valor, (pd.Timestamp, datetime)):
                    return f"{valor.year:04d}"
    raise ValueError(
        "damodaran: não encontrei a célula 'Date updated'/'Date of update' com uma "
        "data válida nas primeiras linhas da planilha; o layout pode ter mudado"
    )


def _achar_linha_cabecalho(df0: pd.DataFrame, rotulo: str) -> int:
    limite = min(30, len(df0))
    for i in range(limite):
        valor = df0.iat[i, 0]
        if isinstance(valor, str) and valor.strip() == rotulo:
            return i
    raise ValueError(f"damodaran: linha de cabeçalho '{rotulo}' não encontrada; o layout pode ter mudado")


def _parse_tabela_setor(df0: pd.DataFrame, header_idx: int, colunas: tuple[str, ...]) -> pd.DataFrame:
    n = len(colunas)
    dados = df0.iloc[header_idx + 1:, :n].copy()
    dados.columns = list(colunas)
    dados = dados[dados[colunas[0]].notna()].reset_index(drop=True)
    if dados.empty:
        raise ValueError("damodaran: nenhuma linha de setor encontrada após o cabeçalho")
    for c in colunas[1:]:
        dados[c] = pd.to_numeric(dados[c], errors="coerce")
    return dados


def _parse_ctryprem(df0: pd.DataFrame, header_idx: int) -> pd.DataFrame:
    colunas = _COLUNAS_CTRYPREM
    dados = df0.iloc[header_idx + 1:, :6].copy()
    dados.columns = list(colunas)
    dados = dados.reset_index(drop=True)
    # a coluna de região fica vazia exatamente na linha em que a tabela principal
    # termina (antes da segunda tabela solta "Frontier Markets..."); usamos isso
    # como sentinela de fim de tabela.
    vazio = dados["regiao"].isna()
    if vazio.any():
        dados = dados.iloc[: vazio.idxmax()]
    dados = dados[dados["country"].notna()].reset_index(drop=True)
    if dados.empty:
        raise ValueError("damodaran: nenhuma linha de país encontrada em ctryprem")
    for c in ("default_spread_rating", "equity_risk_premium", "country_risk_premium"):
        dados[c] = pd.to_numeric(dados[c], errors="coerce")
    return dados


def _parse_histretsp(df0: pd.DataFrame, header_idx: int) -> pd.DataFrame:
    dados = df0.iloc[header_idx + 1:, [0, 1, 4]].copy()
    dados.columns = list(_COLUNAS_HISTRETSP)
    dados = dados.reset_index(drop=True)

    def _e_ano(v: object) -> bool:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return not pd.isna(v) and float(v).is_integer() and 1800 < float(v) < 2200
        if isinstance(v, str):
            return bool(re.fullmatch(r"\d{4}", v.strip()))
        return False

    dados = dados[dados["ano"].apply(_e_ano)].reset_index(drop=True)
    if dados.empty:
        raise ValueError("damodaran: nenhuma linha anual encontrada em histretSP")
    dados["ano"] = dados["ano"].astype(float).astype(int)
    for c in ("sp500_retorno", "tbond10_retorno"):
        dados[c] = pd.to_numeric(dados[c], errors="coerce")
    return dados


def interpretar_arquivo(conteudo: bytes, rotulo: str) -> tuple[str, pd.DataFrame]:
    """Lê um dos arquivos Damodaran e devolve ``(versao, DataFrame)`` já no formato
    da série correspondente. Usado por ``Damodaran.interpretar`` e disponível para
    testes/verificação manual."""
    _, _, aba, _, cabecalho = _ARQUIVOS[rotulo]
    df0 = pd.read_excel(io.BytesIO(conteudo), sheet_name=aba, header=None)
    versao = extrair_versao(df0)
    header_idx = _achar_linha_cabecalho(df0, cabecalho)

    if rotulo in ("betaGlobal", "betaemerg", "betas"):
        df = _parse_tabela_setor(df0, header_idx, _COLUNAS_BETA_SETOR)
    elif rotulo == "totalbetaGlobal":
        df = _parse_tabela_setor(df0, header_idx, _COLUNAS_TOTALBETA)
    elif rotulo in ("dbtfundGlobal", "dbtfundemerg"):
        df = _parse_tabela_setor(df0, header_idx, _COLUNAS_DBTFUND)
    elif rotulo == "ctryprem":
        df = _parse_ctryprem(df0, header_idx)
    elif rotulo == "histretSP":
        df = _parse_histretsp(df0, header_idx)
    else:  # pragma: no cover — não deveria acontecer, _ARQUIVOS é fechado
        raise ValueError(f"damodaran: rótulo desconhecido {rotulo!r}")
    return versao, df


@registrar
class Damodaran(Coletor):
    fonte = "damodaran"
    descricao = (
        "Damodaran (NYU Stern) — betas por setor, fundamentos de dívida, "
        "prêmio de risco-país e retornos históricos S&P/T-Bond (edições anuais)"
    )
    series = (
        SerieSpec(
            id="damodaran_beta_global", descricao="Beta por setor — empresas globais (ex-EUA)",
            unidade="adimensional (beta, D/E) e fração 0-1 (tax rate, cash/firm value)",
            frequencia="V", colunas=_COLUNAS_BETA_SETOR, chave=("industry_name",),
            valores=("beta", "de_ratio", "effective_tax_rate", "unlevered_beta",
                      "cash_to_firm_value", "unlevered_beta_corrected_for_cash"),
            faixa=(-1.0, 10.0), versionada=True,
        ),
        SerieSpec(
            id="damodaran_beta_emerg", descricao="Beta por setor — mercados emergentes",
            unidade="adimensional (beta, D/E) e fração 0-1 (tax rate, cash/firm value)",
            frequencia="V", colunas=_COLUNAS_BETA_SETOR, chave=("industry_name",),
            valores=("beta", "de_ratio", "effective_tax_rate", "unlevered_beta",
                      "cash_to_firm_value", "unlevered_beta_corrected_for_cash"),
            faixa=(-1.0, 10.0), versionada=True,
        ),
        SerieSpec(
            id="damodaran_beta_us", descricao="Beta por setor — empresas dos EUA",
            unidade="adimensional (beta, D/E) e fração 0-1 (tax rate, cash/firm value)",
            frequencia="V", colunas=_COLUNAS_BETA_SETOR, chave=("industry_name",),
            valores=("beta", "de_ratio", "effective_tax_rate", "unlevered_beta",
                      "cash_to_firm_value", "unlevered_beta_corrected_for_cash"),
            faixa=(-1.0, 10.0), versionada=True,
        ),
        SerieSpec(
            id="damodaran_totalbeta_global", descricao="Total beta por setor (investidor não diversificado)",
            unidade="adimensional (beta) e fração 0-1 (correlação)",
            frequencia="V", colunas=_COLUNAS_TOTALBETA, chave=("industry_name",),
            valores=("average_unlevered_beta", "average_levered_beta", "average_correlation_with_market",
                      "total_unlevered_beta", "total_levered_beta"),
            faixa=(-2.0, 15.0), versionada=True,
        ),
        SerieSpec(
            id="damodaran_dbtfund_global", descricao="Fundamentos de dívida por setor — global",
            unidade="fração 0-1 (endividamento, tax rate) e razões (ver notas)",
            frequencia="V", colunas=_COLUNAS_DBTFUND, chave=("industry_name",),
            valores=_COLUNAS_DBTFUND[2:], faixa=None, versionada=True,
            notas="faixa=None: 'Debt to EBITDA' diverge para setores com EBITDA perto de "
                  "zero (observado -23714 a 2713 em jan/2026); incompatível com faixa única "
                  "junto das demais colunas em fração 0-1.",
        ),
        SerieSpec(
            id="damodaran_dbtfund_emerg", descricao="Fundamentos de dívida por setor — mercados emergentes",
            unidade="fração 0-1 (endividamento, tax rate) e razões (ver notas)",
            frequencia="V", colunas=_COLUNAS_DBTFUND, chave=("industry_name",),
            valores=_COLUNAS_DBTFUND[2:], faixa=None, versionada=True,
            notas="faixa=None: mesma razão de damodaran_dbtfund_global (Debt to EBITDA diverge "
                  "para setores com EBITDA perto de zero).",
        ),
        SerieSpec(
            id="damodaran_ctryprem", descricao="Prêmio de risco de país e prêmio de risco de capital, por país",
            unidade="fração (ex.: 0.0425 = 4,25% a.a.)",
            frequencia="V", colunas=_COLUNAS_CTRYPREM, chave=("country",),
            valores=("default_spread_rating", "equity_risk_premium", "country_risk_premium"),
            faixa=(-0.05, 0.5), versionada=True,
        ),
        SerieSpec(
            id="damodaran_histretsp", descricao="Retornos anuais históricos: S&P 500 e T-Bond de 10 anos",
            unidade="fração (ex.: 0.05 = 5% a.a.)",
            frequencia="V", colunas=_COLUNAS_HISTRETSP, chave=("ano",),
            valores=("sp500_retorno", "tbond10_retorno"),
            faixa=(-0.8, 0.8), versionada=True,
        ),
    )

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        return self._coletar_web(ctx) + self._coletar_entrada(ctx)

    def _coletar_web(self, ctx: Contexto) -> list[ArquivoBruto]:
        """Origem (a): download direto das URLs fixas do Damodaran. Uma falha em um
        arquivo (404, timeout etc.) é registrada e não impede os demais."""
        out: list[ArquivoBruto] = []
        for rotulo, (arquivo_nome, ext, _, _, _) in _ARQUIVOS.items():
            url = BASE_URL.format(arquivo=arquivo_nome)
            try:
                r = baixar(ctx.sessao, url)
                out.append(ArquivoBruto(r.content, ext, url=url, nome_original=arquivo_nome, rotulo=rotulo))
            except Exception as e:  # noqa: BLE001 — uma fonte fora do ar não derruba as demais
                log.warning("damodaran: falha ao baixar %s: %r", arquivo_nome, e)
        return out

    def _coletar_entrada(self, ctx: Contexto) -> list[ArquivoBruto]:
        """Origem (b): arquivos com o mesmo nome colocados manualmente em
        ``entrada/damodaran/<qualquer subpasta>/`` (ex.: versões baixadas à mão)."""
        out: list[ArquivoBruto] = []
        entrada = ctx.entrada(self.fonte)
        for rotulo, (arquivo_nome, ext, _, _, _) in _ARQUIVOS.items():
            for caminho in sorted(entrada.rglob(arquivo_nome)):
                if caminho.is_file():
                    out.append(ArquivoBruto(caminho.read_bytes(), ext, url=None,
                                             nome_original=str(caminho), rotulo=rotulo))
        return out

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        saida: dict[str, dict[str, pd.DataFrame]] = {}
        for reg in brutos:
            if reg.rotulo not in _ARQUIVOS:
                continue
            serie_id = _ARQUIVOS[reg.rotulo][3]
            try:
                versao, df = interpretar_arquivo(reg.caminho.read_bytes(), reg.rotulo)
            except Exception as e:
                log.warning("damodaran: falha ao interpretar %s (%s): %r", reg.rotulo, reg.caminho, e)
                continue
            saida.setdefault(serie_id, {})[versao] = df
        return saida
