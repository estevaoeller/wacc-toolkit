"""Resolução do diretório das bases.

Ordem de precedência: argumento explícito > variável WACC_BASES_DIR > wacc.local.toml
(procurado no diretório corrente e na raiz do repositório).
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

ENV_VAR = "WACC_BASES_DIR"
ARQUIVO_LOCAL = "wacc.local.toml"
_RAIZ_REPO = Path(__file__).resolve().parents[2]


class ConfiguracaoAusente(RuntimeError):
    pass


def resolver_bases_dir(explicito: str | Path | None = None) -> Path:
    if explicito:
        return Path(explicito).expanduser().resolve()
    if os.environ.get(ENV_VAR):
        return Path(os.environ[ENV_VAR]).expanduser().resolve()
    for pasta in (Path.cwd(), _RAIZ_REPO):
        arquivo = pasta / ARQUIVO_LOCAL
        if arquivo.exists():
            dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
            if "bases_dir" in dados:
                return Path(dados["bases_dir"]).expanduser().resolve()
    raise ConfiguracaoAusente(
        f"Diretório das bases não configurado. Use --bases, a variável {ENV_VAR} "
        f"ou crie {ARQUIVO_LOCAL} (veja wacc.local.toml.example)."
    )
