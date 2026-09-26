"""Damodaran: lista de empresas por setor.

Fonte: https://pages.stern.nyu.edu/~adamodar/pc/datasets/indname.xls
Aba: "By industry"

Colunas originais: Company Name, Exchange:Ticker, Industry Group, Primary Sector,
SIC Code, Country, Broad Group, Sub Group

O arquivo é atualizado in-place, então guardamos uma versão a cada atualização
observada (AAAA-MM do header Last-Modified).
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

log = logging.getLogger("wacc_toolkit")

URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/indname.xls"

# Colunas esperadas (normalizadas para snake_case)
COLUNAS_NORMALIZADAS = (
    "company_name",
    "exchange_ticker",
    "industry_group",
    "primary_sector",
    "sic_code",
    "country",
    "broad_group",
    "sub_group",
)

# Mapa de colunas do arquivo XLS para as colunas normalizadas
MAPA_COLUNAS = {
    "Company Name": "company_name",
    "Exchange:Ticker": "exchange_ticker",
    "Industry Group": "industry_group",
    "Primary Sector": "primary_sector",
    "SIC Code": "sic_code",
    "Country": "country",
    "Broad Group": "broad_group",
    "Sub Group": "sub_group",
}


def extrair_versao(response: requests.Response) -> str:
    """Extrai versão no formato AAAA-MM do header Last-Modified.

    Se não houver Last-Modified, usa o ano-mês da coleta e registra em log.
    """
    last_modified = response.headers.get("Last-Modified")
    if last_modified:
        try:
            # Formato: "Wed, 26 Feb 2025 10:30:00 GMT" (RFC 2822)
            dt = datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z")
            return dt.strftime("%Y-%m")
        except (ValueError, TypeError):
            log.warning("Last-Modified header inválido: %s", last_modified)

    # Fallback: usar data/hora de agora
    now = datetime.now(timezone.utc)
    versao = now.strftime("%Y-%m")
    log.info("damodaran_empresas: versão obtida do horário de coleta: %s", versao)
    return versao


def interpretar_excel(conteudo: bytes, versao: str | None = None) -> tuple[str, pd.DataFrame]:
    """Lê o arquivo XLS e retorna (versao, DataFrame normalizado).

    Processa:
    - Lê a aba "By industry"
    - Remove linhas vazias
    - Remove duplicatas (mantendo a primeira ocorrência de forma determinística)
    - Renormaliza colunas para snake_case
    """
    # Ler a aba "By industry"
    df = pd.read_excel(io.BytesIO(conteudo), sheet_name="By industry", engine="xlrd")

    # Remover linhas completamente vazias
    df = df.dropna(how="all").reset_index(drop=True)

    # Renomear colunas
    df = df.rename(columns=MAPA_COLUNAS)

    # Garantir que temos todas as colunas esperadas
    faltando = [c for c in COLUNAS_NORMALIZADAS if c not in df.columns]
    if faltando:
        raise ValueError(f"colunas ausentes no XLS: {faltando}")

    # Remover duplicatas pela chave (company_name, exchange_ticker, industry_group)
    chave = ["company_name", "exchange_ticker", "industry_group"]
    duplicatas_antes = len(df)
    df = df.drop_duplicates(subset=chave, keep="first").reset_index(drop=True)
    duplicatas_removidas = duplicatas_antes - len(df)
    if duplicatas_removidas:
        log.info("damodaran_empresas: removidas %d linhas com chave duplicada", duplicatas_removidas)

    # Selecionar e ordenar colunas conforme SerieSpec
    df = df[list(COLUNAS_NORMALIZADAS)].copy()

    return versao or "desconhecida", df


@registrar
class DamodaranEmpresas(Coletor):
    fonte = "damodaran_empresas"
    descricao = "Damodaran: lista de empresas por setor (atualizado in-place)"
    series = (
        SerieSpec(
            id="damodaran_empresas",
            descricao="Empresas por setor (Damodaran)",
            unidade="lista de empresas",
            frequencia="V",  # versionada
            colunas=COLUNAS_NORMALIZADAS,
            chave=("company_name", "exchange_ticker", "industry_group"),
            valores=(),  # sem colunas numéricas
            faixa=None,
            max_lacuna_dias=None,
            versionada=True,
        ),
    )

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        """Baixa o arquivo XLS e extrai a versão do Last-Modified."""
        # Timeout maior para arquivo de ~21 MB
        r = baixar(ctx.sessao, URL, timeout=180)
        versao = extrair_versao(r)
        rotulo = f"indname_{versao}"
        return [ArquivoBruto(r.content, "xls", url=URL, rotulo=rotulo)]

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        """Lê o arquivo XLS e retorna a série versionada."""
        saida = {}
        for reg in brutos:
            # Extrair versão do rótulo (ex.: "indname_2025-02" → "2025-02")
            versao = reg.rotulo.replace("indname_", "") if reg.rotulo else "desconhecida"
            _, df = interpretar_excel(reg.caminho.read_bytes(), versao)
            saida["damodaran_empresas"] = {versao: df}
        return saida
