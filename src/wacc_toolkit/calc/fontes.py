"""Leitura das bases tratadas com rastreabilidade (série, versão, hash do CSV)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ..registry import carregar_todos
from ..series import SerieSpec
from ..storage import Repositorio


@dataclass
class Recorte:
    """Observações efetivamente usadas num cálculo."""

    nome: str
    serie: str
    df: pd.DataFrame
    versao: str | None = None
    sha256_csv: str | None = None
    descricao: str = ""
    extras: dict = field(default_factory=dict)

    def resumo(self) -> dict:
        d = {"nome": self.nome, "serie": self.serie, "versao": self.versao, "sha256_csv": self.sha256_csv,
             "linhas": int(len(self.df)), "descricao": self.descricao}
        if "data" in self.df.columns and len(self.df):
            d["inicio"], d["fim"] = str(self.df["data"].min()), str(self.df["data"].max())
        return {**d, **self.extras}


class Bases:
    def __init__(self, repo: Repositorio):
        self.repo = repo
        self._specs: dict[str, SerieSpec] = {s.id: s for c in carregar_todos().values() for s in c.series}
        self._cache: dict[tuple, tuple[pd.DataFrame, dict]] = {}

    def spec(self, serie: str) -> SerieSpec:
        if serie not in self._specs:
            raise KeyError(f"série desconhecida: {serie}")
        return self._specs[serie]

    def ler(self, serie: str, versao: str | None = None) -> tuple[pd.DataFrame, dict]:
        chave = (serie, versao)
        if chave not in self._cache:
            spec = self.spec(serie)
            df = self.repo.ler_serie(spec, versao)
            if df is None:
                raise FileNotFoundError(f"base {serie}{' v' + versao if versao else ''} não encontrada; rode 'wacc atualizar'")
            meta = self.repo.meta_serie(spec, versao) or {}
            if "data" in df.columns:
                df["data"] = pd.to_datetime(df["data"])
            self._cache[chave] = (df, meta)
        df, meta = self._cache[chave]
        return df.copy(), meta

    def versao_vigente(self, serie: str, data_base: date) -> str:
        """Tabela versionada: a edição mais recente publicada até o ano da data-base."""
        versoes = [v for v in self.repo.versoes(self.spec(serie)) if v.isdigit() and int(v) <= data_base.year]
        if not versoes:
            raise FileNotFoundError(f"nenhuma versão de {serie} até {data_base.year}")
        return max(versoes, key=int)

    def recorte(self, nome: str, serie: str, df: pd.DataFrame, meta: dict, descricao: str = "", **extras) -> Recorte:
        return Recorte(nome, serie, df.reset_index(drop=True), meta.get("versao"), meta.get("sha256_csv"),
                       descricao, extras)
