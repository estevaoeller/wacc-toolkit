"""BCB (Banco Central do Brasil): TLP, Selic e Focus.

Implementação do contrato de coletor para séries do Banco Central do Brasil.

Séries (valores em % a.a., como publicados):
- bcb_tlp: TLP: Taxa de Longo Prazo, série SGS 27572 (mensal)
- bcb_focus_ipca_anual: Focus: Expectativas de IPCA (mediana anual)
- bcb_selic_meta: Selic Meta (Copom), série SGS 432 (diária, desde mar/1999)
- bcb_selic_efetiva_mensal: Selic Efetiva acumulada no mês, série SGS 4189 (mensal, desde 1986)
- bcb_selic_efetiva_diaria: Selic Efetiva anualizada, série SGS 1178 (diária, desde 1995)
- bcb_focus_selic_anual: Focus: Expectativas de Selic para o ano (mediana anual, desde 2000)

Endpoints públicos, sem chave:
- TLP: https://api.bcb.gov.br/dados/serie/bcdata.sgs.27572/dados?formato=json
- Focus: https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta

import pandas as pd

from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

URL_TLP = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.27572/dados?formato=json"
URL_FOCUS_IPCA = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoAnuais?$filter=Indicador%20eq%20'IPCA'&$format=json&"
    "$select=Indicador,Data,DataReferencia,Media,Mediana,DesvioPadrao,Minimo,Maximo,"
    "numeroRespondentes,baseCalculo"
)
URL_FOCUS_SELIC = (
    "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/"
    "ExpectativasMercadoAnuais?$filter=Indicador%20eq%20'Selic'&$format=json&"
    "$select=Indicador,Data,DataReferencia,Media,Mediana,DesvioPadrao,Minimo,Maximo,"
    "numeroRespondentes,baseCalculo"
)


def interpretar_tlp(conteudo: bytes) -> pd.DataFrame:
    """Parse JSON da TLP.

    Formato: [{"data":"01/01/2018","valor":"4.74"}, ...]
    - data: string dd/mm/aaaa
    - valor: string com número decimal (ponto como separador)
    """
    dados = json.loads(conteudo)
    df = pd.DataFrame(dados)

    # Converter data de dd/mm/aaaa para datetime
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y").dt.date

    # Converter valor para float
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Descartar linhas com valor NaN
    out = df[["data", "valor"]].dropna(subset=["valor"]).reset_index(drop=True)

    return out


def interpretar_focus(conteudo: bytes) -> pd.DataFrame:
    """Parse JSON do Focus: Expectativas de IPCA anual.

    Formato: {"value": [{"Indicador":"IPCA","Data":"2018-01-22","DataReferencia":"2019", ...}, ...]}

    Colunas de saída:
    - data: Data de coleta (ISO format)
    - ano_referencia: DataReferencia como inteiro
    - base_calculo: baseCalculo (0 = últimos 30 dias, 1 = últimos 5 dias úteis)
    - mediana: Mediana (float)
    - media: Media (float)
    - desvio_padrao: DesvioPadrao (float)
    - minimo: Minimo (float)
    - maximo: Maximo (float)
    - respondentes: numeroRespondentes (int)
    """
    dados_json = json.loads(conteudo)
    items = dados_json.get("value", [])

    df = pd.DataFrame(items)

    # Converter Data (ISO) para date
    df["data"] = pd.to_datetime(df["Data"]).dt.date

    # Converter DataReferencia (string) para int
    df["ano_referencia"] = df["DataReferencia"].astype(int)

    # Renomear e manter colunas necessárias
    df_out = pd.DataFrame({
        "data": df["data"],
        "ano_referencia": df["ano_referencia"],
        "base_calculo": df["baseCalculo"].astype(int),
        "mediana": pd.to_numeric(df["Mediana"], errors="coerce"),
        "media": pd.to_numeric(df["Media"], errors="coerce"),
        "desvio_padrao": pd.to_numeric(df["DesvioPadrao"], errors="coerce"),
        "minimo": pd.to_numeric(df["Minimo"], errors="coerce"),
        "maximo": pd.to_numeric(df["Maximo"], errors="coerce"),
        "respondentes": pd.to_numeric(df["numeroRespondentes"], errors="coerce").astype("Int64"),
    })

    # Descartar linhas com NaN em colunas críticas
    df_out = df_out.dropna(subset=["data", "ano_referencia", "base_calculo", "mediana"]).reset_index(drop=True)

    return df_out


def interpretar_selic_meta(conteudo: bytes) -> pd.DataFrame:
    """Parse JSON da Selic Meta (SGS 432).

    Formato: [{"data":"01/01/2022","valor":"9.25"}, ...]
    - data: string dd/mm/aaaa
    - valor: string com número decimal (ponto como separador)

    Retorna DataFrame vazio se conteudo está vazio ou não é um array válido.
    """
    try:
        dados = json.loads(conteudo)
    except json.JSONDecodeError as e:
        # resposta não-JSON (ex.: página de erro HTML da API): erro explícito, nunca vazio silencioso
        raise ValueError(f"resposta da API SGS não é JSON: {conteudo[:80]!r}") from e

    # Se dados é vazio ou não é lista, retorna vazio
    if not dados or not isinstance(dados, list):
        return pd.DataFrame(columns=["data", "valor"])

    df = pd.DataFrame(dados)

    # Converter data de dd/mm/aaaa para date
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y").dt.date

    # Converter valor para float
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Descartar linhas com valor NaN
    out = df[["data", "valor"]].dropna(subset=["valor"]).reset_index(drop=True)

    return out


def interpretar_selic_efetiva_mensal(conteudo: bytes) -> pd.DataFrame:
    """Parse JSON da Selic Efetiva Mensal (SGS 4189).

    Formato: [{"data":"01/01/2020","valor":"4.40"}, ...]
    - data: string dd/mm/aaaa (primeiro dia do mês)
    - valor: string com número decimal (ponto como separador)
    """
    dados = json.loads(conteudo)
    df = pd.DataFrame(dados)

    # Converter data de dd/mm/aaaa para date
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y").dt.date

    # Converter valor para float
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Descartar linhas com valor NaN
    out = df[["data", "valor"]].dropna(subset=["valor"]).reset_index(drop=True)

    return out


def interpretar_selic_efetiva_diaria(conteudo: bytes) -> pd.DataFrame:
    """Parse JSON da Selic Efetiva Diária (SGS 1178).

    Formato: [{"data":"02/01/2023","valor":"13.65"}, ...]
    - data: string dd/mm/aaaa
    - valor: string com número decimal (ponto como separador)

    Retorna DataFrame vazio se conteudo está vazio ou não é um array válido.
    """
    try:
        dados = json.loads(conteudo)
    except json.JSONDecodeError as e:
        # resposta não-JSON (ex.: página de erro HTML da API): erro explícito, nunca vazio silencioso
        raise ValueError(f"resposta da API SGS não é JSON: {conteudo[:80]!r}") from e

    # Se dados é vazio ou não é lista, retorna vazio
    if not dados or not isinstance(dados, list):
        return pd.DataFrame(columns=["data", "valor"])

    df = pd.DataFrame(dados)

    # Converter data de dd/mm/aaaa para date
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y").dt.date

    # Converter valor para float
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")

    # Descartar linhas com valor NaN
    out = df[["data", "valor"]].dropna(subset=["valor"]).reset_index(drop=True)

    return out


def _baixar_json(sessao, url: str, tentativas: int = 3):
    """Baixa e valida que a resposta é JSON. A API SGS às vezes devolve uma página de erro
    HTML com status 200; nesse caso tenta de novo e, persistindo, falha com erro explícito."""
    import time
    ultimo = None
    for i in range(tentativas):
        r = baixar(sessao, url)
        try:
            json.loads(r.content)
            return r
        except json.JSONDecodeError:
            ultimo = r.content[:80]
            time.sleep(2 * (i + 1))
    raise ValueError(f"API SGS não devolveu JSON após {tentativas} tentativas ({url}): {ultimo!r}")


def _gerar_datas_paginacao(data_inicio: str, data_fim: str, anos_por_pagina: int = 10) -> list[tuple[str, str]]:
    """Gera lista de janelas (data_inicio, data_fim) para paginar requisições.

    Args:
        data_inicio: data em formato "dd/mm/aaaa"
        data_fim: data em formato "dd/mm/aaaa"
        anos_por_pagina: número de anos por página (padrão 10)

    Returns:
        Lista de tuplas (data_inicio_pagina, data_fim_pagina) em formato "dd/mm/aaaa"
    """
    start = datetime.strptime(data_inicio, "%d/%m/%Y")
    end = datetime.strptime(data_fim, "%d/%m/%Y")

    paginas = []
    current = start

    while current < end:
        # Calcula fim desta página (start + anos_por_pagina anos)
        page_end = current.replace(year=current.year + anos_por_pagina)
        # Mas não ultrapassa a data final total
        if page_end > end:
            page_end = end

        data_inicio_str = current.strftime("%d/%m/%Y")
        data_fim_str = page_end.strftime("%d/%m/%Y")
        paginas.append((data_inicio_str, data_fim_str))

        # Próxima página começa no dia seguinte
        current = page_end + timedelta(days=1)

    return paginas


@registrar
class BCB(Coletor):
    fonte = "bcb"
    descricao = "BCB: TLP, Selic (Meta, Efetiva) e Focus (IPCA, Selic)"
    series = (
        SerieSpec(
            id="bcb_tlp",
            descricao="TLP: Taxa de Longo Prazo para cálculo da TNLP (série SGS 27572), mensal",
            unidade="% a.a.",
            frequencia="M",
            faixa=(0.0, 30.0),
            max_lacuna_dias=35,
        ),
        SerieSpec(
            id="bcb_focus_ipca_anual",
            descricao="Focus: Expectativas de IPCA para o ano (mediana), por data de coleta",
            unidade="% a.a.",
            frequencia="D",  # diária, pois há múltiplos registros por data (por ano_referencia e base_calculo)
            colunas=("data", "ano_referencia", "base_calculo", "mediana", "media",
                    "desvio_padrao", "minimo", "maximo", "respondentes"),
            chave=("data", "ano_referencia", "base_calculo"),
            valores=("mediana", "media", "desvio_padrao", "minimo", "maximo"),
            faixa=(-5.0, 50.0),
            max_lacuna_dias=None,
            notas=("baseCalculo: 0 = expectativas informadas nos últimos 30 dias; 1 = nos últimos "
                   "5 dias úteis (conferido pelo nº de respondentes: base 1 ≈ metade da base 0). "
                   "A Metodologia do Tesouro (gross-up das debêntures) usa a base 1."),
            extras={"origem": "Olinda BCB"},
        ),
        SerieSpec(
            id="bcb_selic_meta",
            descricao="Selic Meta Copom (série SGS 432), diária, desde mar/1999",
            unidade="% a.a.",
            frequencia="D",
            faixa=(0.0, 50.0),
            max_lacuna_dias=10,
        ),
        SerieSpec(
            id="bcb_selic_efetiva_mensal",
            descricao="Selic Efetiva acumulada no mês, anualizada base 252 (série SGS 4189), mensal",
            unidade="% a.a.",
            frequencia="M",
            faixa=(0.0, 1000000.0),  # período hiper-inflacionário (1987-1990)
            max_lacuna_dias=35,
        ),
        SerieSpec(
            id="bcb_selic_efetiva_diaria",
            descricao="Selic Efetiva anualizada, base 252 (série SGS 1178), diária, desde 1995",
            unidade="% a.a.",
            frequencia="D",
            faixa=(0.0, 100.0),
            max_lacuna_dias=10,
        ),
        SerieSpec(
            id="bcb_focus_selic_anual",
            descricao="Focus: Expectativas de Selic para o ano (mediana), por data de coleta",
            unidade="% a.a.",
            frequencia="D",  # diária, pois há múltiplos registros por data
            colunas=("data", "ano_referencia", "base_calculo", "mediana", "media",
                    "desvio_padrao", "minimo", "maximo", "respondentes"),
            chave=("data", "ano_referencia", "base_calculo"),
            valores=("mediana", "media", "desvio_padrao", "minimo", "maximo"),
            faixa=(0.0, 60.0),
            max_lacuna_dias=None,
            notas=("baseCalculo: 0 = expectativas informadas nos últimos 30 dias; 1 = nos últimos "
                   "5 dias úteis. Indicador: 'Selic' (meta para taxa over-selic)."),
            extras={"origem": "Olinda BCB"},
        ),
    )

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        out = []

        # TLP
        r_tlp = baixar(ctx.sessao, URL_TLP)
        out.append(ArquivoBruto(r_tlp.content, "json", url=URL_TLP, rotulo="tlp"))

        # Focus IPCA
        r_focus_ipca = baixar(ctx.sessao, URL_FOCUS_IPCA)
        out.append(ArquivoBruto(r_focus_ipca.content, "json", url=URL_FOCUS_IPCA, rotulo="focus_ipca_anual"))

        # Selic Meta (SGS 432) - paginar de 10 em 10 anos desde mar/1999
        hoje = datetime.now()
        data_inicio_432 = "01/03/1999"  # meta Selic definida pelo Copom desde mar/1999
        data_fim_432 = hoje.strftime("%d/%m/%Y")
        paginas_432 = _gerar_datas_paginacao(data_inicio_432, data_fim_432, anos_por_pagina=10)

        for i, (di, df) in enumerate(paginas_432):
            url_432 = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial={di}&dataFinal={df}"
            r_432 = _baixar_json(ctx.sessao, url_432)
            ano_inicio = di.split("/")[2]
            out.append(ArquivoBruto(r_432.content, "json", url=url_432, rotulo=f"selic_meta_{ano_inicio}"))

        # Selic Efetiva Mensal (SGS 4189) - uma requisição só
        url_4189 = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.4189/dados?formato=json"
        r_4189 = baixar(ctx.sessao, url_4189)
        out.append(ArquivoBruto(r_4189.content, "json", url=url_4189, rotulo="selic_efetiva_mensal"))

        # Selic Efetiva Diária (SGS 1178) - paginar de 10 em 10 anos desde 1995
        data_inicio_1178 = "01/01/1995"
        data_fim_1178 = hoje.strftime("%d/%m/%Y")
        paginas_1178 = _gerar_datas_paginacao(data_inicio_1178, data_fim_1178, anos_por_pagina=10)

        for i, (di, df) in enumerate(paginas_1178):
            url_1178 = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.1178/dados?formato=json&dataInicial={di}&dataFinal={df}"
            r_1178 = _baixar_json(ctx.sessao, url_1178)
            ano_inicio = di.split("/")[2]
            out.append(ArquivoBruto(r_1178.content, "json", url=url_1178, rotulo=f"selic_efetiva_diaria_{ano_inicio}"))

        # Focus Selic
        r_focus_selic = baixar(ctx.sessao, URL_FOCUS_SELIC)
        out.append(ArquivoBruto(r_focus_selic.content, "json", url=URL_FOCUS_SELIC, rotulo="focus_selic_anual"))

        return out

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        saida = {}

        # Dicionários para acumular dados de séries paginadas
        dfs_selic_meta = []
        dfs_selic_efetiva_diaria = []

        for reg in brutos:
            conteudo = reg.caminho.read_bytes()

            if reg.rotulo == "tlp":
                saida["bcb_tlp"] = interpretar_tlp(conteudo)
            elif reg.rotulo == "focus_ipca_anual":
                saida["bcb_focus_ipca_anual"] = interpretar_focus(conteudo)
            elif reg.rotulo.startswith("selic_meta_"):
                df = interpretar_selic_meta(conteudo)
                dfs_selic_meta.append(df)
            elif reg.rotulo == "selic_efetiva_mensal":
                saida["bcb_selic_efetiva_mensal"] = interpretar_selic_efetiva_mensal(conteudo)
            elif reg.rotulo.startswith("selic_efetiva_diaria_"):
                df = interpretar_selic_efetiva_diaria(conteudo)
                dfs_selic_efetiva_diaria.append(df)
            elif reg.rotulo == "focus_selic_anual":
                saida["bcb_focus_selic_anual"] = interpretar_focus(conteudo)

        # Concatenar páginas de séries paginadas, removendo datas duplicadas (keep="last")
        if dfs_selic_meta:
            df_combined = pd.concat(dfs_selic_meta, ignore_index=True)
            # Remove duplicatas mantendo a última ocorrência
            df_combined = df_combined.drop_duplicates(subset=["data"], keep="last").reset_index(drop=True)
            if len(df_combined) > 0:
                saida["bcb_selic_meta"] = df_combined

        if dfs_selic_efetiva_diaria:
            df_combined = pd.concat(dfs_selic_efetiva_diaria, ignore_index=True)
            # Remove duplicatas mantendo a última ocorrência
            df_combined = df_combined.drop_duplicates(subset=["data"], keep="last").reset_index(drop=True)
            if len(df_combined) > 0:
                saida["bcb_selic_efetiva_diaria"] = df_combined

        return saida
