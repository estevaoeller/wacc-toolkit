"""Sessão HTTP padrão: identificação, timeout e novas tentativas."""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "wacc-toolkit/0.1 (+https://github.com/estevaoeller/wacc-toolkit)"
TIMEOUT = 60


def nova_sessao(user_agent: str = USER_AGENT) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept": "*/*"})
    retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def baixar(sessao: requests.Session, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT)
    r = sessao.get(url, **kwargs)
    r.raise_for_status()
    return r
