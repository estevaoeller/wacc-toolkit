"""Validações aplicadas antes de aceitar uma nova versão de série.

Um problema de nível ``erro`` bloqueia a gravação: a última versão boa é mantida.
Um problema de nível ``aviso`` é registrado no manifesto e no meta da série, mas não
bloqueia a gravação.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from .series import SerieSpec


@dataclass(frozen=True)
class Problema:
    nivel: Literal["erro", "aviso"]
    mensagem: str

    def __str__(self) -> str:
        return f"[{self.nivel}] {self.mensagem}"


def normalizar(spec: SerieSpec, df: pd.DataFrame) -> pd.DataFrame:
    """Ordena as colunas do contrato e as linhas pela chave, e converte ``data`` em date."""
    faltando = [c for c in spec.colunas if c not in df.columns]
    if faltando:
        raise ValueError(f"{spec.id}: colunas ausentes {faltando}")
    out = df.loc[:, list(spec.colunas)].copy()
    if "data" in out.columns:
        out["data"] = pd.to_datetime(out["data"]).dt.date
    for c in spec.valores:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.sort_values(list(spec.chave), kind="stable").reset_index(drop=True)


def validar(spec: SerieSpec, novo: pd.DataFrame, anterior: pd.DataFrame | None) -> list[Problema]:
    p: list[Problema] = []
    if novo is None or len(novo) == 0:
        return [Problema("erro", "série vazia")]

    dup = novo.duplicated(subset=list(spec.chave)).sum()
    if dup:
        p.append(Problema("erro", f"{dup} linhas com chave duplicada {spec.chave}"))

    for c in spec.valores:
        nulos = int(novo[c].isna().sum())
        if nulos == len(novo):
            p.append(Problema("erro", f"coluna {c} inteiramente vazia/não numérica"))
        elif nulos:
            p.append(Problema("aviso", f"{nulos} valores nulos em {c}"))
        if spec.faixa is not None:
            lo, hi = spec.faixa
            fora = novo[(novo[c] < lo) | (novo[c] > hi)]
            if len(fora):
                exemplo = fora.iloc[0].to_dict()
                p.append(Problema("erro", f"{len(fora)} valores de {c} fora da faixa [{lo}, {hi}]; ex.: {exemplo}"))

    if "data" in novo.columns and spec.max_lacuna_dias:
        datas = pd.Series(sorted(set(novo["data"])))
        if len(datas) > 1:
            gaps = pd.to_datetime(datas).diff().dt.days
            maior = gaps.max()
            if maior > spec.max_lacuna_dias:
                i = int(gaps.idxmax())
                p.append(Problema("aviso", f"lacuna de {int(maior)} dias entre {datas[i-1]} e {datas[i]}"))

    if anterior is not None and len(anterior):
        p.extend(_comparar_com_anterior(spec, novo, anterior))
    return p


def _comparar_com_anterior(spec: SerieSpec, novo: pd.DataFrame, anterior: pd.DataFrame) -> list[Problema]:
    p: list[Problema] = []
    if "data" in novo.columns and "data" in anterior.columns:
        if max(novo["data"]) < max(anterior["data"]):
            p.append(Problema("erro", f"última data regrediu: {max(anterior['data'])} → {max(novo['data'])}"))

    chave = list(spec.chave)
    ant = anterior.copy()
    if "data" in ant.columns:
        ant["data"] = pd.to_datetime(ant["data"]).dt.date
    m = ant.merge(novo, on=chave, how="left", suffixes=("_ant", "_novo"), indicator=True)
    removidas = int((m["_merge"] == "left_only").sum())
    if removidas:
        p.append(Problema("aviso", f"{removidas} linhas do histórico anterior não vieram na nova coleta"))
    comuns = m[m["_merge"] == "both"]
    for c in spec.valores:
        a = pd.to_numeric(comuns[f"{c}_ant"], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(comuns[f"{c}_novo"], errors="coerce").to_numpy(dtype=float)
        mudou = ~np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True)
        n = int(mudou.sum())
        if n:
            linha = comuns.loc[comuns.index[mudou][0], chave].to_dict()
            p.append(Problema("aviso", f"histórico revisado: {n} valores de {c} mudaram (ex.: {linha})"))
    return p


def tem_erro(problemas: list[Problema]) -> bool:
    return any(x.nivel == "erro" for x in problemas)
