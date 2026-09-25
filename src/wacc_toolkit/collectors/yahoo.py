"""Yahoo Finance: S&P 500 Total Return e Ibovespa via endpoint não oficial de gráfico.

Endpoint (não documentado, mas estável e usado pelo yfinance por baixo dos panos):
    https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1=0&period2=<agora>&interval=1d&events=div,split

Séries (valores na unidade da fonte, sem ajuste metodológico):
- yahoo_sp500tr  diária  ^SP500TR  S&P 500 Total Return (dividendos reinvestidos), desde 1988
- yahoo_ibov     diária  ^BVSP     Ibovespa (pontos), como publicado pela Yahoo

O bloco ``meta`` de cada resposta traz ``gmtoffset`` (segundos) e ``timezone`` da bolsa.
Os timestamps do JSON são epoch UTC referentes ao horário de abertura do pregão; para obter
a data de pregão correta no fuso local (e não a data UTC, que pode cair um dia depois para
bolsas a oeste de Greenwich), somamos o ``gmtoffset`` ao timestamp antes de extrair a data.

Se a sessão padrão (User-Agent ``wacc-toolkit/...``) for rejeitada (401/403/429), o Yahoo
costuma exigir um User-Agent de navegador comum. Nesse caso, refazemos a mesma requisição
com um cabeçalho de navegador. Em testes manuais (2026-09), a sessão padrão funcionou sem
necessidade do fallback, mas o código o mantém por robustez.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import quote

import pandas as pd
import requests

from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?period1=0&period2={agora}&interval=1d&events=div,split"
)

# User-Agent de navegador comum, usado apenas como contingência caso a sessão padrão
# do wacc-toolkit (identificada como "wacc-toolkit/...") seja rejeitada pelo Yahoo.
_UA_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_TICKERS = {
    "^SP500TR": ("yahoo_sp500tr", "S&P 500 Total Return, diária", (100.0, 100000.0), 10, "SP500TR"),
    # faixa: o pedido original especificava (100, 1_000_000), mas os primeiros ~90
    # pregões que o Yahoo tem para ^BVSP (1993-04-27 a 1993-08-31, ainda no regime de
    # cruzeiro/cruzeiro real, antes do Plano Real "cortar zeros" do índice) ficam entre
    # 23,7 e 99,8 pontos: abaixo de 100. Para não rejeitar a série inteira por causa
    # desses ~90 pontos legítimos, o piso foi ajustado para 20. O teto permanece o
    # solicitado.
    "^BVSP": ("yahoo_ibov", "Ibovespa, diária", (20.0, 1000000.0), 15, "BVSP"),
}


def _baixar_com_fallback_ua(sessao: requests.Session, url: str) -> requests.Response:
    """Baixa ``url`` com a sessão padrão; se o Yahoo recusar (401/403/429), refaz a
    requisição com um User-Agent de navegador comum."""
    try:
        return baixar(sessao, url)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (401, 403, 429):
            return baixar(sessao, url, headers={"User-Agent": _UA_NAVEGADOR})
        raise


def interpretar_chart_json(conteudo: bytes, esperado_ticker: str) -> pd.DataFrame:
    """Interpreta o JSON do endpoint de gráfico do Yahoo Finance para um único ticker.

    Datas: cada timestamp (epoch UTC) é deslocado pelo ``gmtoffset`` (segundos) do bloco
    ``meta`` antes de extrair a data local do pregão. Linhas com ``close`` nulo (feriados
    que aparecem no calendário mas sem pregão) são descartadas. ``fechamento_ajustado``
    vem de ``indicators.adjclose`` quando presente; senão repete o ``close``.
    """
    import json

    dados = json.loads(conteudo)
    erro = dados.get("chart", {}).get("error")
    if erro:
        raise ValueError(f"Yahoo devolveu erro para {esperado_ticker}: {erro}")
    resultados = dados.get("chart", {}).get("result")
    if not resultados:
        raise ValueError(f"resposta do Yahoo sem 'chart.result' para {esperado_ticker}")
    bloco = resultados[0]

    meta = bloco.get("meta", {})
    simbolo = meta.get("symbol")
    if simbolo != esperado_ticker:
        raise ValueError(f"ticker inesperado na resposta do Yahoo: {simbolo!r} != {esperado_ticker!r}")
    gmtoffset = meta.get("gmtoffset")
    if gmtoffset is None:
        raise ValueError(f"meta.gmtoffset ausente na resposta do Yahoo para {esperado_ticker}")

    timestamps = bloco.get("timestamp")
    if not timestamps:
        raise ValueError(f"resposta do Yahoo sem 'timestamp' para {esperado_ticker}")

    indicadores = bloco.get("indicators", {})
    cotacoes = indicadores.get("quote")
    if not cotacoes or "close" not in cotacoes[0]:
        raise ValueError(f"resposta do Yahoo sem indicators.quote.close para {esperado_ticker}")
    close = cotacoes[0]["close"]

    adjclose_bloco = indicadores.get("adjclose")
    adjclose = adjclose_bloco[0]["adjclose"] if adjclose_bloco else close

    datas = [
        datetime.fromtimestamp(ts + gmtoffset, tz=timezone.utc).date()
        for ts in timestamps
    ]

    out = pd.DataFrame({
        "data": datas,
        "fechamento": pd.to_numeric(pd.Series(close), errors="coerce"),
        "fechamento_ajustado": pd.to_numeric(pd.Series(adjclose), errors="coerce"),
    })
    out = out.dropna(subset=["fechamento"]).reset_index(drop=True)
    out["fechamento_ajustado"] = out["fechamento_ajustado"].fillna(out["fechamento"])
    return out


@registrar
class Yahoo(Coletor):
    fonte = "yahoo"
    descricao = "Yahoo Finance: S&P 500 Total Return (^SP500TR) e Ibovespa (^BVSP), diárias"
    series = tuple(
        SerieSpec(
            id=sid,
            descricao=desc,
            unidade="pontos (índice)" if ticker == "^SP500TR" else "pontos",
            frequencia="D",
            colunas=("data", "fechamento", "fechamento_ajustado"),
            chave=("data",),
            valores=("fechamento",),
            modo="substituir",
            faixa=faixa,
            max_lacuna_dias=lac,
            extras={"ticker_yahoo": ticker},
        )
        for ticker, (sid, desc, faixa, lac, _rotulo) in _TICKERS.items()
    )

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        agora = int(time.time())
        out = []
        for ticker, (_sid, _desc, _faixa, _lac, rotulo) in _TICKERS.items():
            url = URL.format(ticker=quote(ticker, safe=""), agora=agora)
            r = _baixar_com_fallback_ua(ctx.sessao, url)
            out.append(ArquivoBruto(r.content, "json", url=url, rotulo=rotulo))
        return out

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        rotulo_para_ticker = {rotulo: ticker for ticker, (*_resto, rotulo) in _TICKERS.items()}
        saida = {}
        for reg in brutos:
            ticker = rotulo_para_ticker[reg.rotulo]
            sid = _TICKERS[ticker][0]
            saida[sid] = interpretar_chart_json(reg.caminho.read_bytes(), ticker)
        return saida
