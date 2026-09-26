"""Damodaran (NYU Stern): betas, fundamentos de dívida, risco-país e retornos históricos.

Fonte: planilhas anuais publicadas em
https://pages.stern.nyu.edu/~adamodar/pc/datasets/<arquivo>

Cada planilha é substituída inteiramente a cada atualização anual (normalmente em
janeiro). Por isso as séries são **versionadas** (``SerieSpec.versionada=True``):
cada edição vira ``tratado/<serie>/<versao>.csv`` e a edição anterior nunca é
sobrescrita. A versão é o ano de publicação, extraído da célula "Date updated"/
"Date of update" presente no topo de cada planilha: nunca a data de hoje. Se essa
célula não puder ser localizada, ``interpretar`` falha com ``ValueError`` (regra 9 do
contrato: nunca chutar a versão).

Origens de coleta (``coletar``):
  (a) web: download direto das URLs fixas acima;
  (b) importação local: arquivos com o mesmo nome colocados em
      ``entrada/damodaran/<qualquer subpasta>/`` (ex.: ``entrada/damodaran/2026/
      betaGlobal.xls``), útil para versões baixadas manualmente. O rótulo
      (``ArquivoBruto.rotulo``) é o mesmo nos dois casos (nome do arquivo sem
      extensão), então o núcleo deduplica automaticamente pelo sha256 do conteúdo.
      Se web e entrada trouxerem a mesma versão com conteúdos diferentes, a série
      dessa versão é regravada e ``validate`` emite aviso de "histórico revisado" -
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
  intervalo no ano seguinte): não são incluídas por não serem reproduzíveis de
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
  vez de "Region": por isso as colunas são nomeadas explicitamente por posição,
  não pelo texto do cabeçalho. A aba tem uma segunda tabela solta abaixo
  ("Frontier Markets (no sovereign ratings)", com colunas diferentes) que é
  descartada: a leitura para quando a coluna de região fica vazia, o que marca o
  fim da tabela principal.
- ``damodaran_histretsp`` (``histretSP.xls``, aba "Returns by year"): mantemos o
  retorno anual do S&P 500 (com dividendos) e do T.Bond de 10 anos; linhas de
  resumo no final da tabela ("Arithmetic Average...", "1928-2025" etc.) são
  descartadas pelo filtro "Year é um ano de 4 dígitos".

Unidade: os valores são preservados exatamente como a fonte publica: a maioria
já vem como fração decimal (ex.: 0.0425 representa 4,25% a.a.); nenhuma conversão
percentual é feita aqui.
"""

from __future__ import annotations

import io
import logging
import re
import time
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

# Edições arquivadas (histórico anual): mesmo nome de arquivo com um sufixo de 2
# dígitos ("AA") do exercício retratado, ex.: betaGlobal11.xls = dados de 2011,
# publicados em janeiro de 2012 (versão gravada "2012"). Ver ``Damodaran._coletar_historico``.
ARCHIVE_URL = "https://pages.stern.nyu.edu/~adamodar/pc/archives/{arquivo}"
PAUSA_ENTRE_DOWNLOADS_HISTORICO = 0.5  # segundos; sobrescrito por testes via monkeypatch

# variantes observadas do rótulo da 1a coluna que localiza a linha de cabeçalho
# das tabelas de beta e de fundamentos de dívida por setor, ao longo das edições
# desde 2011 (ex.: "Industry name" em 2011/2012, "Industry" isolado em 2014):
# comparado sempre sem diferenciar maiúsculas/minúsculas.
_INDUSTRIA_VARIANTES = (
    "Industry Name", "Industry Names", "Industry",
    "Induistry Name",  # erro de digitação real observado em dbtfundemerg18.xls
)

# rotulo -> (nome do arquivo na fonte, extensão, aba, id da série, rótulo(s) do
# cabeçalho na primeira coluna que localiza a linha de cabeçalho da tabela)
_ARQUIVOS: dict[str, tuple[str, str, str, str, str | tuple[str, ...]]] = {
    "betaGlobal": ("betaGlobal.xls", "xls", "Industry Averages", "damodaran_beta_global", _INDUSTRIA_VARIANTES),
    "betaemerg": ("betaemerg.xls", "xls", "Industry Averages", "damodaran_beta_emerg", _INDUSTRIA_VARIANTES),
    "betas": ("betas.xls", "xls", "Industry Averages", "damodaran_beta_us", _INDUSTRIA_VARIANTES),
    "totalbetaGlobal": ("totalbetaGlobal.xls", "xls", "Industry Averages", "damodaran_totalbeta_global", _INDUSTRIA_VARIANTES),
    "dbtfundGlobal": ("dbtfundGlobal.xls", "xls", "Industry Averages", "damodaran_dbtfund_global", _INDUSTRIA_VARIANTES),
    "dbtfundemerg": ("dbtfundemerg.xls", "xls", "Industry Averages", "damodaran_dbtfund_emerg", _INDUSTRIA_VARIANTES),
    "ctryprem": ("ctryprem.xlsx", "xlsx", "ERPs by country", "damodaran_ctryprem", "Country"),
    "histretSP": ("histretSP.xls", "xls", "Returns by year", "damodaran_histretsp", "Year"),
}

# Histórico anual arquivado (origem (c) de ``Damodaran.coletar``): apenas as 5
# séries com histórico multi-ano tratado por este módulo. "AA" varre os anos
# disponíveis no arquivo (ver ``_ano_do_codigo``): 11..25 para as séries
# globais/emergentes (arquivo existe desde 2011; falhas de download, ex.: ainda
# sem edição arquivada do ano corrente, são um 404 tratado como aviso) e
# 98..25 para a série dos EUA (arquivo existe desde 1998). O arquivo "dbtfund.xls"
# (fundamentos de dívida dos EUA) também tem histórico arquivado na fonte, mas
# não incluímos aqui porque não existe hoje uma série ``damodaran_dbtfund_us``
# neste coletor: criar essa série é uma decisão em aberto, fora do escopo desta
# extensão (ver nota em ``Damodaran._coletar_historico``).
_ANOS_GLOBAL_EMERG = tuple(f"{n:02d}" for n in range(11, 26))
_ANOS_US = tuple(f"{n:02d}" for n in range(98, 100)) + tuple(f"{n:02d}" for n in range(0, 26))
_HISTORICO: dict[str, tuple[str, tuple[str, ...]]] = {
    "betaGlobal": ("betaGlobal{aa}.xls", _ANOS_GLOBAL_EMERG),
    "betaemerg": ("betaemerg{aa}.xls", _ANOS_GLOBAL_EMERG),
    "betas": ("betas{aa}.xls", _ANOS_US),
    "dbtfundGlobal": ("dbtfundGlobal{aa}.xls", _ANOS_GLOBAL_EMERG),
    "dbtfundemerg": ("dbtfundemerg{aa}.xls", _ANOS_GLOBAL_EMERG),
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
# subconjunto de _COLUNAS_DBTFUND validado (faixa/coluna-inteiramente-vazia) pelo
# núcleo (``validate.validar``): só as 3 colunas presentes em TODAS as edições
# desde 2011 (ver ``_parse_dbtfund_historico``). As demais 10 colunas do layout
# atual só existem a partir de ~2013 (8 delas) ou ~2022 (interest_coverage_ratio,
# debt_to_ebitda): incluí-las em ``valores`` faria ``validar`` rejeitar (erro
# "coluna inteiramente vazia") toda edição arquivada anterior a essas datas, o
# que inviabilizaria justamente o histórico que esta série existe para guardar.
# Ficam gravadas como NaN nessas edições, só não fazem parte da validação.
_COLUNAS_DBTFUND_VALORES_VALIDADAS = ("market_debt_to_capital_unadjusted", "market_de_unadjusted", "effective_tax_rate")
_COLUNAS_CTRYPREM = (
    "country", "regiao", "moodys_rating", "default_spread_rating",
    "equity_risk_premium", "country_risk_premium",
)
_COLUNAS_HISTRETSP = ("ano", "sp500_retorno", "tbond10_retorno")

def _normalizar_cabecalho(valor: object) -> str:
    if not isinstance(valor, str):
        return ""
    return re.sub(r"\s+", " ", valor.strip().lower()).rstrip(":")


# mapeamento por nome (não por posição) dos cabeçalhos de fundamentos de dívida
# por setor: o número e a ordem das colunas mudou várias vezes desde 2011 (ex.:
# 5 colunas em 2011/2012, 13 a partir de ~2013 sem "Interest Coverage Ratio" nem
# "Debt to EBITDA", 15 a partir de ~2022, iguais às atuais). Usado só pelo
# histórico e pela versão corrente de dbtfundGlobal/dbtfundemerg (produz o
# mesmo resultado que a fatia posicional antiga para o layout atual).
_DBTFUND_ALIASES: dict[str, str] = {
    # variantes de "industry name" (inclui a de _INDUSTRIA_VARIANTES, mesma
    # constante usada por _achar_linha_cabecalho, para não duplicar a lista de
    # grafias/typos observados, ex.: "Induistry Name" em dbtfundemerg18.xls)
    **{_normalizar_cabecalho(v): "industry_name" for v in _INDUSTRIA_VARIANTES},
    "number of firms": "number_of_firms",
    "book debt to capital": "book_debt_to_capital",
    "interest coverage ratio": "interest_coverage_ratio",
    "debt to ebitda": "debt_to_ebitda",
    "tax rate": "effective_tax_rate",
    "effective tax rate": "effective_tax_rate",
    "institutional holdings": "institutional_holdings",
    "std dev in stock prices": "std_dev_stock_prices",
    "ebitda/value": "ebitda_ev",
    "ebitda/ev": "ebitda_ev",
    "fixed assets/total assets": "net_ppe_total_assets",
    "net pp&e/total assets": "net_ppe_total_assets",
    "capital spending/total assets": "capex_total_assets",
}


def _mapear_coluna_dbtfund(cabecalho_norm: str) -> str | None:
    if cabecalho_norm in _DBTFUND_ALIASES:
        return _DBTFUND_ALIASES[cabecalho_norm]
    if cabecalho_norm.startswith("market debt to capital"):
        return ("market_debt_to_capital_adjusted_leases" if "adjusted for leases" in cabecalho_norm
                else "market_debt_to_capital_unadjusted")
    if cabecalho_norm.startswith("market d/e"):
        return "market_de_adjusted_leases" if "adjusted for leases" in cabecalho_norm else "market_de_unadjusted"
    return None


def _ano_do_codigo(codigo: str) -> int:
    """Converte o sufixo de 2 dígitos do arquivo arquivado ("AA") no ano de 4
    dígitos do exercício retratado: >=90 é 19xx (arquivos desde 1998, só para a
    série dos EUA), caso contrário 20xx (ex.: "11" -> 2011, "24" -> 2024)."""
    n = int(codigo)
    return (1900 if n >= 90 else 2000) + n


def _ler_planilha(caminho: Path, aba: str) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(caminho.read_bytes()), sheet_name=aba, header=None)


def extrair_versao(df0: pd.DataFrame) -> str:
    """Procura, nas primeiras linhas, uma célula da coluna A contendo "date"
    (case-insensitive: cobre "Date updated:" e "Date of update:") e devolve o
    ano da primeira data encontrada na mesma linha, como string "AAAA".

    Levanta ``ValueError`` se não encontrar: nunca usamos a data de hoje como
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


def _achar_linha_cabecalho(df0: pd.DataFrame, rotulo: str | tuple[str, ...]) -> int:
    # normaliza espaços (algumas edições têm espaço duplo, ex.: "Industry  Name"
    # em betas19.xls) além de maiúsculas/minúsculas.
    aceitos = {_normalizar_cabecalho(rotulo)} if isinstance(rotulo, str) else {_normalizar_cabecalho(r) for r in rotulo}
    limite = min(30, len(df0))
    for i in range(limite):
        valor = df0.iat[i, 0]
        if isinstance(valor, str) and _normalizar_cabecalho(valor) in aceitos:
            return i
    raise ValueError(f"damodaran: linha de cabeçalho '{rotulo}' não encontrada; o layout pode ter mudado")


def _validar_cabecalho_beta_setor(df0: pd.DataFrame, header_idx: int) -> None:
    """Confere, além da posição, que as colunas 7 e 8 (0-indexadas 6 e 7) da
    tabela de beta por setor são mesmo "Cash/Firm value" e "Unlevered beta
    corrected for cash": edições muito antigas (ex.: betas98.xls, o primeiro
    arquivo da série dos EUA) têm um layout totalmente diferente nessas
    posições, e a fatia posicional silenciosamente leria outra coisa como se
    fosse essas colunas obrigatórias. Preferimos falhar claro (regra 9 do
    contrato) a gravar um valor errado."""
    esperado = ("cash/firm value", "unlevered beta corrected for cash")
    for pos, alvo in zip((6, 7), esperado):
        valor = df0.iat[header_idx, pos] if pos < df0.shape[1] else None
        texto = valor.strip().lower() if isinstance(valor, str) else ""
        if alvo not in texto:
            raise ValueError(
                f"damodaran: layout de beta por setor inesperado (coluna {pos} = {valor!r}, "
                f"esperava algo como {alvo!r}); provavelmente uma edição muito antiga sem essa coluna"
            )


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


def _parse_dbtfund_historico(df0: pd.DataFrame, header_idx: int) -> pd.DataFrame:
    """Monta a tabela de fundamentos de dívida por setor mapeando cada coluna
    pelo NOME do cabeçalho (via ``_mapear_coluna_dbtfund``), não pela posição:
    o número e a ordem das colunas mudou várias vezes entre 2011 e hoje (ver
    comentário de ``_DBTFUND_ALIASES``). Colunas do layout atual ausentes na
    edição em questão ficam ``NaN``; a linha é considerada dado até a coluna
    ``industry_name`` (mapeada por nome) ficar vazia."""
    cabecalhos = df0.iloc[header_idx].tolist()
    posicoes: dict[str, int] = {}
    for pos, bruto in enumerate(cabecalhos):
        alvo = _mapear_coluna_dbtfund(_normalizar_cabecalho(bruto))
        if alvo and alvo not in posicoes:
            posicoes[alvo] = pos

    faltantes = [c for c in ("industry_name", "market_de_unadjusted") if c not in posicoes]
    if faltantes:
        raise ValueError(
            f"damodaran: colunas obrigatórias ausentes no layout de dívida por setor: {faltantes}"
        )

    bruto_nome = df0.iloc[header_idx + 1:, posicoes["industry_name"]]
    linhas_validas = bruto_nome.notna()
    n = int(linhas_validas.sum())
    dados: dict[str, object] = {}
    for coluna in _COLUNAS_DBTFUND:
        if coluna in posicoes:
            serie = df0.iloc[header_idx + 1:, posicoes[coluna]][linhas_validas].reset_index(drop=True)
        else:
            serie = pd.Series([pd.NA] * n)
        dados[coluna] = serie
    dados_df = pd.DataFrame(dados)
    if dados_df.empty:
        raise ValueError("damodaran: nenhuma linha de setor encontrada após o cabeçalho")
    for c in _COLUNAS_DBTFUND[1:]:
        dados_df[c] = pd.to_numeric(dados_df[c], errors="coerce")
    return dados_df


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


def interpretar_arquivo(
    conteudo: bytes, rotulo: str, ano_arquivo_fallback: int | None = None,
) -> tuple[str, pd.DataFrame]:
    """Lê um dos arquivos Damodaran e devolve ``(versao, DataFrame)`` já no formato
    da série correspondente. Usado por ``Damodaran.interpretar`` e disponível para
    testes/verificação manual.

    ``ano_arquivo_fallback``: só usado pelas edições ARQUIVADAS do histórico (ver
    ``Damodaran._coletar_historico``), que às vezes não têm a célula "Date
    updated" (edições antigas, ~2011/2012 e antes). Nesse caso a versão vira
    ``str(ano_arquivo_fallback + 1)`` (o ano de publicação, um a mais que o
    exercício retratado pelo nome do arquivo), e o fallback é registrado via
    ``logging.info``. Para os arquivos correntes/de entrada (``ano_arquivo_fallback=None``,
    o padrão), o comportamento é o mesmo de sempre: falha com ``ValueError`` se
    não achar a célula."""
    _, _, aba, _, cabecalho = _ARQUIVOS[rotulo]
    try:
        df0 = pd.read_excel(io.BytesIO(conteudo), sheet_name=aba, header=None)
    except ValueError:
        # edições antigas (ex.: até ~2018) não têm aba "Industry Averages": é a
        # única aba de dados, ou a 1a aba de fato ("Sheet1"/"Variables & FAQ" +
        # dados na 2a). Cai para a 1a aba nesses casos.
        df0 = pd.read_excel(io.BytesIO(conteudo), sheet_name=0, header=None)

    try:
        versao = extrair_versao(df0)
    except ValueError:
        if ano_arquivo_fallback is None:
            raise
        versao = str(ano_arquivo_fallback + 1)
        log.info(
            "damodaran: %s sem célula 'Date updated'/'Date of update'; usando o ano do nome "
            "do arquivo (%d) + 1 = %s", rotulo, ano_arquivo_fallback, versao,
        )

    header_idx = _achar_linha_cabecalho(df0, cabecalho)

    if rotulo in ("betaGlobal", "betaemerg", "betas"):
        _validar_cabecalho_beta_setor(df0, header_idx)
        df = _parse_tabela_setor(df0, header_idx, _COLUNAS_BETA_SETOR)
    elif rotulo == "totalbetaGlobal":
        df = _parse_tabela_setor(df0, header_idx, _COLUNAS_TOTALBETA)
    elif rotulo in ("dbtfundGlobal", "dbtfundemerg"):
        df = _parse_dbtfund_historico(df0, header_idx)
    elif rotulo == "ctryprem":
        df = _parse_ctryprem(df0, header_idx)
    elif rotulo == "histretSP":
        df = _parse_histretsp(df0, header_idx)
    else:  # pragma: no cover: não deveria acontecer, _ARQUIVOS é fechado
        raise ValueError(f"damodaran: rótulo desconhecido {rotulo!r}")
    return versao, df


def _resolver_rotulo(rotulo: str | None) -> tuple[str, str, int | None] | None:
    """Identifica a série e o arquivo-base de um ``RegistroBruto.rotulo``, e o
    ano do arquivo (fallback de versão) quando é uma edição histórica.
    Rótulos correntes/de entrada usam a chave direta de ``_ARQUIVOS`` (ex.:
    "betaGlobal"); rótulos do histórico usam ``"{arquivo}_{AA}"`` (ex.:
    "betaGlobal_11", ver ``Damodaran._coletar_historico``). Devolve ``None``
    para rótulos desconhecidos (ignorados por ``Damodaran.interpretar``)."""
    if rotulo is None:
        return None
    if rotulo in _ARQUIVOS:
        return _ARQUIVOS[rotulo][3], rotulo, None
    for base in _HISTORICO:
        prefixo = f"{base}_"
        if rotulo.startswith(prefixo):
            codigo = rotulo[len(prefixo):]
            return _ARQUIVOS[base][3], base, _ano_do_codigo(codigo)
    return None


@registrar
class Damodaran(Coletor):
    fonte = "damodaran"
    descricao = (
        "Damodaran (NYU Stern): betas por setor, fundamentos de dívida, "
        "prêmio de risco-país e retornos históricos S&P/T-Bond (edições anuais)"
    )
    series = (
        SerieSpec(
            id="damodaran_beta_global", descricao="Beta por setor: empresas globais (ex-EUA)",
            unidade="adimensional (beta, D/E) e fração 0-1 (tax rate, cash/firm value)",
            frequencia="V", colunas=_COLUNAS_BETA_SETOR, chave=("industry_name",),
            # de_ratio fica de fora de ``valores`` (mas continua uma coluna obrigatória,
            # sempre gravada, ver _validar_cabecalho_beta_setor/_ARQUIVOS): setores
            # financeiros muito alavancados (ex.: "Thrift", "Financial Svcs. (Non-bank
            # & Insurance)") têm de_ratio > 10 e observado até ~70 em edições
            # históricas (2011-2019) — mesma razão de "Debt to EBITDA" ficar fora de
            # ``valores`` em damodaran_dbtfund_global (ver nota lá).
            valores=("beta", "effective_tax_rate", "unlevered_beta",
                      "cash_to_firm_value", "unlevered_beta_corrected_for_cash"),
            faixa=(-1.0, 10.0), versionada=True,
        ),
        SerieSpec(
            id="damodaran_beta_emerg", descricao="Beta por setor: mercados emergentes",
            unidade="adimensional (beta, D/E) e fração 0-1 (tax rate, cash/firm value)",
            frequencia="V", colunas=_COLUNAS_BETA_SETOR, chave=("industry_name",),
            valores=("beta", "effective_tax_rate", "unlevered_beta",
                      "cash_to_firm_value", "unlevered_beta_corrected_for_cash"),
            faixa=(-1.0, 10.0), versionada=True,  # ver nota de damodaran_beta_global
        ),
        SerieSpec(
            id="damodaran_beta_us", descricao="Beta por setor: empresas dos EUA",
            unidade="adimensional (beta, D/E) e fração 0-1 (tax rate, cash/firm value)",
            frequencia="V", colunas=_COLUNAS_BETA_SETOR, chave=("industry_name",),
            valores=("beta", "effective_tax_rate", "unlevered_beta",
                      "cash_to_firm_value", "unlevered_beta_corrected_for_cash"),
            faixa=(-1.0, 10.0), versionada=True,  # ver nota de damodaran_beta_global
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
            id="damodaran_dbtfund_global", descricao="Fundamentos de dívida por setor: global",
            unidade="fração 0-1 (endividamento, tax rate) e razões (ver notas)",
            frequencia="V", colunas=_COLUNAS_DBTFUND, chave=("industry_name",),
            valores=_COLUNAS_DBTFUND_VALORES_VALIDADAS, faixa=None, versionada=True,
            notas="faixa=None: 'Debt to EBITDA' diverge para setores com EBITDA perto de "
                  "zero (observado -23714 a 2713 em jan/2026); incompatível com faixa única "
                  "junto das demais colunas em fração 0-1. valores restrito a 3 colunas: ver "
                  "comentário de _COLUNAS_DBTFUND_VALORES_VALIDADAS (histórico anual com "
                  "colunas que não existiam em edições antigas).",
        ),
        SerieSpec(
            id="damodaran_dbtfund_emerg", descricao="Fundamentos de dívida por setor: mercados emergentes",
            unidade="fração 0-1 (endividamento, tax rate) e razões (ver notas)",
            frequencia="V", colunas=_COLUNAS_DBTFUND, chave=("industry_name",),
            valores=_COLUNAS_DBTFUND_VALORES_VALIDADAS, faixa=None, versionada=True,
            notas="faixa=None: mesma razão de damodaran_dbtfund_global (Debt to EBITDA diverge "
                  "para setores com EBITDA perto de zero). valores restrito a 3 colunas: ver "
                  "comentário de _COLUNAS_DBTFUND_VALORES_VALIDADAS.",
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
        # ordem importa: quando uma edição arquivada e a versão corrente caem na
        # mesma versão (ex.: a versão corrente de hoje se torna, no futuro, a
        # edição arquivada "25"), ``interpretar`` grava por último quem vier
        # depois na lista — corrente prevalece sobre histórico, e entrada (local)
        # prevalece sobre os dois, documentado no módulo.
        return self._coletar_historico(ctx) + self._coletar_web(ctx) + self._coletar_entrada(ctx)

    def _coletar_web(self, ctx: Contexto) -> list[ArquivoBruto]:
        """Origem (a): download direto das URLs fixas do Damodaran. Uma falha em um
        arquivo (404, timeout etc.) é registrada e não impede os demais."""
        out: list[ArquivoBruto] = []
        for rotulo, (arquivo_nome, ext, _, _, _) in _ARQUIVOS.items():
            url = BASE_URL.format(arquivo=arquivo_nome)
            try:
                r = baixar(ctx.sessao, url)
                out.append(ArquivoBruto(r.content, ext, url=url, nome_original=arquivo_nome, rotulo=rotulo))
            except Exception as e:  # noqa: BLE001: uma fonte fora do ar não derruba as demais
                log.warning("damodaran: falha ao baixar %s: %r", arquivo_nome, e)
        return out

    def _coletar_historico(self, ctx: Contexto) -> list[ArquivoBruto]:
        """Origem (c): edições anteriores arquivadas em
        ``.../pc/archives/<arquivo><AA>.xls`` (ver ``_HISTORICO``/``ARCHIVE_URL``).
        Só baixa edições cuja versão (ano de publicação, ``_ano_do_codigo(AA) + 1``)
        ainda não está gravada no repositório (``ctx.repo.versoes``); a partir da
        2a execução isso normalmente não baixa nada. Uma edição inexistente
        (404, comum para o ano mais recente antes de ser arquivado) é avisada e
        ignorada, sem interromper as demais; pausa de
        ``PAUSA_ENTRE_DOWNLOADS_HISTORICO`` segundos entre cada tentativa."""
        out: list[ArquivoBruto] = []
        for base, (modelo, codigos) in _HISTORICO.items():
            spec = self.spec(_ARQUIVOS[base][3])
            existentes = set(ctx.repo.versoes(spec))
            for codigo in codigos:
                versao_esperada = str(_ano_do_codigo(codigo) + 1)
                if versao_esperada in existentes:
                    continue
                arquivo_nome = modelo.format(aa=codigo)
                url = ARCHIVE_URL.format(arquivo=arquivo_nome)
                try:
                    r = baixar(ctx.sessao, url)
                    out.append(ArquivoBruto(r.content, "xls", url=url, nome_original=arquivo_nome,
                                             rotulo=f"{base}_{codigo}"))
                except Exception as e:  # noqa: BLE001: uma edição fora do ar não derruba as demais
                    log.warning("damodaran: falha ao baixar arquivo histórico %s: %r", arquivo_nome, e)
                time.sleep(PAUSA_ENTRE_DOWNLOADS_HISTORICO)
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
            info = _resolver_rotulo(reg.rotulo)
            if info is None:
                continue
            serie_id, arquivo_base, ano_arquivo_fallback = info
            try:
                versao, df = interpretar_arquivo(reg.caminho.read_bytes(), arquivo_base, ano_arquivo_fallback)
            except Exception as e:
                log.warning("damodaran: falha ao interpretar %s (%s): %r", reg.rotulo, reg.caminho, e)
                continue
            # mesma versão de uma edição arquivada e da versão corrente: o último
            # processado nesta lista vence (ver ordem em ``coletar``).
            saida.setdefault(serie_id, {})[versao] = df
        return saida
