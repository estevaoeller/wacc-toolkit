"""Especificação das séries tratadas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Frequencia = Literal["D", "W", "M", "A", "V"]  # V = tabela por versão (ex.: Damodaran)
Modo = Literal["substituir", "acumular"]


@dataclass(frozen=True)
class SerieSpec:
    """Contrato de uma série tratada.

    - ``id``: nome do arquivo em ``tratado/`` (``<id>.csv``), em snake_case.
    - ``colunas``: colunas obrigatórias, na ordem de gravação. Deve incluir ``chave``.
    - ``chave``: colunas que identificam unicamente uma linha (padrão: ``data``).
    - ``valores``: colunas numéricas sujeitas à checagem de faixa e de revisão de histórico.
    - ``modo``: ``substituir`` quando a fonte entrega o histórico completo a cada coleta;
      ``acumular`` quando entrega só uma parte (a série nova é mesclada à anterior).
    - ``faixa``: (mínimo, máximo) plausível para as colunas de ``valores``.
    - ``max_lacuna_dias``: maior intervalo aceitável entre datas consecutivas (aviso).
    - ``versionada``: tabelas substituídas por edição (Damodaran). Gravadas em
      ``tratado/<id>/<versao>.csv`` e nunca sobrescritas.
    """

    id: str
    descricao: str
    unidade: str
    frequencia: Frequencia
    colunas: tuple[str, ...] = ("data", "valor")
    chave: tuple[str, ...] = ("data",)
    valores: tuple[str, ...] = ("valor",)
    modo: Modo = "substituir"
    faixa: tuple[float, float] | None = None
    max_lacuna_dias: int | None = None
    versionada: bool = False
    notas: str = ""
    extras: dict = field(default_factory=dict, hash=False, compare=False)
