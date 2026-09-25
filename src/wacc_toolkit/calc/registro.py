"""Registro reprodutível de um cálculo (JSON) e conferência contra valores esperados."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from .modo1 import ResultadoWACC

_RAIZ_REPO = Path(__file__).resolve().parents[3]


def versao_codigo() -> dict:
    info = {"pacote": __version__}
    try:
        info["git"] = subprocess.run(["git", "-C", str(_RAIZ_REPO), "rev-parse", "--short", "HEAD"],
                                     capture_output=True, text=True, timeout=5).stdout.strip() or None
        sujo = subprocess.run(["git", "-C", str(_RAIZ_REPO), "status", "--porcelain", "src"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
        info["alteracoes_nao_commitadas"] = bool(sujo)
    except (OSError, subprocess.SubprocessError):
        info["git"] = None
    return info


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", texto.lower()).strip("_")


def gravar_registro(resultado: ResultadoWACC, pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    agora = datetime.now(timezone.utc)
    dados = {"gerado_em": agora.isoformat(timespec="seconds"), "codigo": versao_codigo(), **resultado.to_dict()}
    base = f"{_slug(resultado.config.projeto)}_{resultado.config.data_base}_{agora:%Y%m%dT%H%M%S}"
    caminho, n = pasta / f"{base}.json", 2
    while caminho.exists() or caminho.with_suffix(".xlsx").exists():  # dois cálculos no mesmo segundo
        caminho, n = pasta / f"{base}_{n}.json", n + 1
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    return caminho


@dataclass
class LinhaConferencia:
    id: str
    calculado: float
    esperado: float | None
    dif_bp: float | None
    status: str  # ok | explicada | DIVERGE | sem_referencia
    explicacao: str = ""


def conferir(resultado: ResultadoWACC, arquivo_esperado: str | Path) -> list[LinhaConferencia]:
    """Compara com valores de referência. Formato TOML::

        tolerancia_bp = 1.0
        [esperado.rf]
        valor = 0.043
        explicacao = "planilha digitou jun/25 = 4,48 (fonte: 4,38)"   # opcional

    Diferença acima da tolerância com ``explicacao`` → "explicada"; sem → "DIVERGE".
    """
    d = tomllib.loads(Path(arquivo_esperado).read_text(encoding="utf-8"))
    tol = float(d.get("tolerancia_bp", 1.0))
    esperado = d.get("esperado", {})
    linhas = []
    for k, c in resultado.componentes.items():
        e = esperado.get(k)
        if e is None or e.get("valor") is None:
            linhas.append(LinhaConferencia(k, c.valor, None, None, "sem_referencia", (e or {}).get("explicacao", "")))
            continue
        dif = (c.valor - float(e["valor"])) * 1e4
        if abs(dif) <= tol:
            status = "ok"
        else:
            status = "explicada" if e.get("explicacao") else "DIVERGE"
        linhas.append(LinhaConferencia(k, c.valor, float(e["valor"]), dif, status, e.get("explicacao", "")))
    return linhas
