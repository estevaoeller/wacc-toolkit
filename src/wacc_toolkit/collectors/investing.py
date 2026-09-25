"""Investing.com — CDS Brasil (5 e 10 anos) e Ibovespa. Coleta MANUAL.

O CDS soberano do Brasil (5 e 10 anos) só está disponível, de forma acessível, no
Investing.com — que bloqueia acesso automatizado (robôs). Por isso esta fonte é
``manual = True``: o usuário baixa, pelo site, o CSV "Dados Históricos" de cada
instrumento e copia o arquivo para ``<bases>/entrada/investing/`` (pode usar
subpastas; a busca é recursiva). A cada coleta, ``coletar()`` relê *todos* os
``*.csv`` presentes nessa pasta — os arquivos não são removidos depois de
processados — e ``interpretar()`` reconstrói a série a partir de todos eles.

Formato esperado do CSV (exportação em português do Investing.com):
colunas ``"Data","Último","Abertura","Máxima","Mínima","Vol.","Var%"``,
datas ``dd.mm.aaaa``, números no formato brasileiro (``1.234,56``), possível
BOM UTF-8 e aspas envolvendo os campos. Apenas ``Data``, ``Último``,
``Abertura``, ``Máxima`` e ``Mínima`` são usados; ``Vol.`` (sufixos K/M/B) e
``Var%`` são ignorados.

Convenção de nomes de arquivo (é assim que a série é identificada — o
conteúdo do CSV não traz o nome do instrumento):

- token ``cds10`` (fundido) ou token ``cds`` seguido de perto por um token ``10``
  → CDS Brasil 10 anos (``investing_cds10_brasil``);
- token ``cds5`` (fundido) ou token ``cds`` seguido de perto por um token ``5``
  (e não ``10``) → CDS Brasil 5 anos (``investing_cds5_brasil``);
- contém ``ibovespa`` ou ``bovespa`` → Ibovespa (``investing_ibov``).

Ver ``identificar_serie()`` para o algoritmo exato (por que não é uma simples
checagem de substring no nome inteiro).

Ex.: ``Dados Históricos - CDS Brasil 10 anos (2501 2509).csv``,
``cds5_2025.csv``, ``Dados Históricos - Ibovespa.csv``. Arquivos cujo nome não
bate com nenhum desses padrões são ignorados (aviso no log) — não é possível
adivinhar a série pelo conteúdo, então um nome fora do padrão não interrompe a
coleta dos demais arquivos.

Frequência: cada arquivo é classificado como diário ou mensal pelos próprios dados
(ver ``eh_mensal``); os mensais vão para as séries ``*_mensal``. Diário e mensal
nunca se misturam na mesma série.

Cada arquivo do Investing.com cobre só uma janela de datas (o usuário baixa
recortes), por isso as três séries usam ``modo="acumular"``: o núcleo mescla o
que vier nesta coleta com o que já estava salvo. Quando, numa mesma coleta,
chegam vários arquivos da mesma série com datas sobrepostas, eles são
concatenados em ordem de "chegada" — ``st_mtime`` do bruto já gravado e, em
empate, nome do arquivo — e a data repetida fica com o valor do arquivo mais
recente nessa ordem (é o comportamento de ``drop_duplicates(keep="last")``
aplicado pelo núcleo).
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata

import pandas as pd

from ..collector import Coletor, Contexto
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

log = logging.getLogger("wacc_toolkit")

_COLUNAS = ("data", "ultimo", "abertura", "maxima", "minima")

# chave de roteamento -> (serie_id, descrição, unidade, faixa plausível, lacuna máx. em dias)
_SERIES = {
    "cds10": ("investing_cds10_brasil", "CDS Brasil 10 anos (Investing.com)", "pontos-base", (10.0, 2000.0), 15),
    "cds5": ("investing_cds5_brasil", "CDS Brasil 5 anos (Investing.com)", "pontos-base", (10.0, 2000.0), 15),
    "ibov": ("investing_ibov", "Ibovespa — fechamento diário (Investing.com)", "pontos", (100.0, 1_000_000.0), 15),
}


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def identificar_serie(nome_arquivo: str) -> str | None:
    """Deduz a série (``cds10``/``cds5``/``ibov``) pelo nome do arquivo. ``None`` se não reconhecer.

    Trabalha por tokens (separados por qualquer caractere não alfanumérico), não por
    substring bruta do nome inteiro: uma checagem de "contém 'cds' e contém '10'" no
    nome completo é ingênua demais — nomes com intervalo de datas (ex.:
    ``cds5_planilha_20100101_20260101.csv``, ou ``(2501 2509)`` de exports do
    Investing.com) quase sempre têm um "10" em algum lugar da data, o que faria um
    arquivo de CDS 5 anos ser confundido com CDS 10 anos. Por isso: ``cds10``/``cds5``
    fundidos num só token casam direto; senão, a partir de um token ``cds`` isolado,
    procura-se ``10``/``5`` como token isolado nos poucos tokens seguintes, parando ao
    encontrar um token puramente numérico de 4+ dígitos (ano/intervalo de datas, não
    faz parte do nome do instrumento).
    """
    n = _sem_acento(nome_arquivo).lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", n) if t]

    if "cds10" in tokens:
        return "cds10"
    if "cds5" in tokens:
        return "cds5"
    if "cds" in tokens:
        i = tokens.index("cds")
        for t in tokens[i + 1 : i + 5]:
            if t.isdigit() and len(t) >= 4:
                break  # ano/intervalo de datas: não é o descritor do instrumento
            if t == "10":
                return "cds10"
            if t == "5":
                return "cds5"

    if "ibovespa" in n or "bovespa" in n:
        return "ibov"
    return None


def _parse_numero_br(valor: object) -> float:
    """Converte número em formato brasileiro (``1.234,56``) para float. Vazio/'-' -> NaN."""
    s = "" if valor is None else str(valor).strip()
    if not s or s in {"-", "—", "n/a", "N/A"}:
        return float("nan")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def _normalizar_cabecalho(coluna: str) -> str:
    return _sem_acento(str(coluna)).strip().lower().rstrip(".")


def interpretar_csv(conteudo: bytes) -> pd.DataFrame:
    """Lê um CSV "Dados Históricos" do Investing.com (BOM UTF-8 opcional, aspas,
    dd.mm.aaaa, números BR). Devolve colunas ``data,ultimo,abertura,maxima,minima``.
    ``Vol.`` e ``Var%`` são ignorados. Linhas sem ``Último`` (feriado/erro) são descartadas.
    """
    texto = conteudo.decode("utf-8-sig")
    df = pd.read_csv(io.StringIO(texto), dtype=str)

    mapa = {_normalizar_cabecalho(c): c for c in df.columns}
    obrigatorias = {"data", "ultimo", "abertura", "maxima", "minima"}
    faltando = sorted(obrigatorias - mapa.keys())
    if faltando:
        raise ValueError(f"investing: colunas ausentes {faltando} (colunas encontradas: {list(df.columns)})")

    out = pd.DataFrame(
        {
            "data": pd.to_datetime(df[mapa["data"]].str.strip(), format="%d.%m.%Y").dt.date,
            "ultimo": df[mapa["ultimo"]].map(_parse_numero_br),
            "abertura": df[mapa["abertura"]].map(_parse_numero_br),
            "maxima": df[mapa["maxima"]].map(_parse_numero_br),
            "minima": df[mapa["minima"]].map(_parse_numero_br),
        }
    )
    return out.dropna(subset=["ultimo"]).reset_index(drop=True)


def eh_mensal(df: pd.DataFrame) -> bool:
    """Arquivo com granularidade mensal (Investing permite exportar "Mensal"; o histórico
    extraído da planilha Santa Maria também é mensal). Critério: mediana do intervalo
    entre datas consecutivas ≥ 25 dias. Séries diárias e mensais nunca são misturadas."""
    datas = pd.Series(sorted(set(df["data"])))
    if len(datas) < 2:
        return False
    return pd.to_datetime(datas).diff().dt.days.median() >= 25


def _specs():
    for sid, desc, unidade, faixa, lacuna in _SERIES.values():
        base = dict(unidade=unidade, colunas=_COLUNAS, chave=("data",), valores=("ultimo",),
                    modo="acumular", faixa=faixa)
        yield SerieSpec(id=sid, descricao=desc, frequencia="D", max_lacuna_dias=lacuna, **base)
        yield SerieSpec(id=f"{sid}_mensal", descricao=f"{desc} — mensal (data = 1º dia do mês)",
                        frequencia="M", max_lacuna_dias=35, **base)


@registrar
class Investing(Coletor):
    fonte = "investing"
    descricao = "Investing.com — CDS Brasil 5a/10a e Ibovespa (coleta manual: CSV 'Dados Históricos')"
    manual = True
    series = tuple(_specs())

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        pasta = ctx.entrada(self.fonte)
        out: list[ArquivoBruto] = []
        for caminho in sorted(pasta.rglob("*.csv")):
            chave = identificar_serie(caminho.name)
            if chave is None:
                log.warning("investing: arquivo com nome não reconhecido, ignorado: %s", caminho.name)
                continue
            out.append(ArquivoBruto(caminho.read_bytes(), "csv", nome_original=caminho.name, rotulo=chave))
        return out

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        grupos: dict[str, list[RegistroBruto]] = {}
        for reg in brutos:
            grupos.setdefault(reg.rotulo, []).append(reg)

        saida: dict[str, pd.DataFrame] = {}
        for chave, regs in grupos.items():
            if chave not in _SERIES:
                continue  # defensivo: não deveria ocorrer, rotulo vem de identificar_serie
            regs_ordenados = sorted(regs, key=lambda r: (r.caminho.stat().st_mtime, r.caminho.name))
            partes: dict[str, list[pd.DataFrame]] = {}
            for r in regs_ordenados:
                df = interpretar_csv(r.caminho.read_bytes())
                sid = _SERIES[chave][0] + ("_mensal" if eh_mensal(df) else "")
                partes.setdefault(sid, []).append(df)
            for sid, dfs in partes.items():
                df = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]
                # sobreposição entre arquivos: prevalece o mais recente na ordem acima
                saida[sid] = df.drop_duplicates(subset=["data"], keep="last").reset_index(drop=True)
        return saida
