"""``wacc-app``: sobe a interface Streamlit (``streamlit run principal.py``).

Aceita ``--bases <diretorio>`` (define ``WACC_BASES_DIR`` para o processo do Streamlit,
sem alterar o ambiente do chamador) e repassa todos os demais argumentos ao
``streamlit run`` (ex.: ``--server.port``, ``--server.headless``).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="wacc-app", add_help=False)
    p.add_argument("--bases", help="diretório das bases (sobrepõe WACC_BASES_DIR / wacc.local.toml)")
    ns, resto = p.parse_known_args(argv)

    env = os.environ.copy()
    if ns.bases:
        env["WACC_BASES_DIR"] = str(Path(ns.bases).expanduser().resolve())

    principal = Path(__file__).resolve().parent / "principal.py"
    comando = [sys.executable, "-m", "streamlit", "run", str(principal), *resto]
    return subprocess.run(comando, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main())
