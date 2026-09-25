"""Registro dos coletores disponíveis."""

from __future__ import annotations

import importlib
import pkgutil

from .collector import Coletor

_COLETORES: dict[str, type[Coletor]] = {}


def registrar(cls: type[Coletor]) -> type[Coletor]:
    if not cls.fonte:
        raise ValueError(f"{cls.__name__} sem atributo 'fonte'")
    if cls.fonte in _COLETORES and _COLETORES[cls.fonte] is not cls:
        raise ValueError(f"fonte duplicada: {cls.fonte}")
    _COLETORES[cls.fonte] = cls
    return cls


def carregar_todos() -> dict[str, type[Coletor]]:
    from . import collectors  # noqa: F401

    for mod in pkgutil.iter_modules(collectors.__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"{collectors.__name__}.{mod.name}")
    return dict(sorted(_COLETORES.items()))
