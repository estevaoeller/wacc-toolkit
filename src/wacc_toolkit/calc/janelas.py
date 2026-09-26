"""Janelas temporais estruturadas.

Regra: a data-base define o **mês de corte** = último mês fechado antes da data-base.
Toda janela termina no mês de corte e é descrita por parâmetros (N meses, N anos,
desde um mês). O rótulo é gerado a partir dos mesmos parâmetros, então rótulo e
cálculo não podem divergir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

_MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _mmm_aa(p: pd.Period) -> str:
    return f"{_MESES[p.month - 1]}/{p.year % 100:02d}"


@dataclass(frozen=True)
class Janela:
    inicio: pd.Period  # mensal, inclusivo
    fim: pd.Period  # mensal, inclusivo

    def __post_init__(self):
        if self.inicio > self.fim:
            raise ValueError(f"janela inválida: {self.inicio} > {self.fim}")

    @property
    def n_meses(self) -> int:
        return (self.fim - self.inicio).n + 1

    @property
    def data_inicio(self) -> date:
        return self.inicio.start_time.date()

    @property
    def data_fim(self) -> date:
        return self.fim.end_time.date()

    def rotulo(self) -> str:
        return f"{_mmm_aa(self.inicio)} a {_mmm_aa(self.fim)}"

    def filtrar(self, df: pd.DataFrame, coluna: str = "data") -> pd.DataFrame:
        d = pd.to_datetime(df[coluna])
        return df[(d >= pd.Timestamp(self.data_inicio)) & (d <= pd.Timestamp(self.data_fim))]

    def to_dict(self) -> dict:
        return {"inicio": str(self.inicio), "fim": str(self.fim), "meses": self.n_meses, "rotulo": self.rotulo()}


def mes_corte(data_base: date) -> pd.Period:
    """Último mês fechado antes da data-base (data-base 16/01/2026 → dez/2025)."""
    return pd.Period(data_base, "M") - 1


def ultimos_meses(corte: pd.Period, n: int) -> Janela:
    return Janela(corte - (n - 1), corte)


def ultimos_anos(corte: pd.Period, n: int) -> Janela:
    """N anos-calendário completos terminando no último ano fechado até o corte."""
    ano_fim = corte.year if corte.month == 12 else corte.year - 1
    return Janela(pd.Period(f"{ano_fim - n + 1}-01", "M"), pd.Period(f"{ano_fim}-12", "M"))


def desde(inicio: str, corte: pd.Period) -> Janela:
    """Do mês ``inicio`` (``AAAA-MM``) até o corte."""
    return Janela(pd.Period(inicio, "M"), corte)


def interpretar(especificacao: str, corte: pd.Period) -> Janela:
    """Converte a especificação textual de uma opção em janela.

    - ``"12m"``: últimos 12 meses;
    - ``"30a"``: últimos 30 anos-calendário completos;
    - ``"desde:1995-01"``: de jan/1995 até o corte;
    - ``"intervalo:2016-01:2025-12"``: intervalo fixo, que **não** acompanha a data-base.
      O fim é limitado ao corte, porque não se usa dado posterior ao último mês fechado.
    """
    e = especificacao.strip().lower()
    if e.startswith("intervalo:"):
        _, ini, fim = e.split(":")
        j = Janela(pd.Period(ini, "M"), min(pd.Period(fim, "M"), corte))
        return j
    if e.startswith("desde:"):
        return desde(e.split(":", 1)[1], corte)
    if e.endswith("m") and e[:-1].isdigit():
        return ultimos_meses(corte, int(e[:-1]))
    if e.endswith("a") and e[:-1].isdigit():
        return ultimos_anos(corte, int(e[:-1]))
    raise ValueError(f"janela não reconhecida: {especificacao!r} "
                     "(use '12m', '30a', 'desde:AAAA-MM' ou 'intervalo:AAAA-MM:AAAA-MM')")


def acompanha_data_base(especificacao: str) -> bool:
    return not especificacao.strip().lower().startswith("intervalo:")


def descrever(especificacao: str) -> str:
    """Nome legível de uma especificação: '12m' → '12 meses', '30a' → '30 anos'."""
    e = especificacao.strip().lower()
    if e.startswith("intervalo:"):
        _, ini, fim = e.split(":")
        return f"de {_mmm_aa(pd.Period(ini, 'M'))} a {_mmm_aa(pd.Period(fim, 'M'))} (fixo)"
    if e.startswith("desde:"):
        return f"desde {_mmm_aa(pd.Period(e.split(':', 1)[1], 'M'))}"
    if e.endswith("m") and e[:-1].isdigit():
        n = int(e[:-1])
        return f"{n} meses" + (f" ({n // 12} anos)" if n >= 24 and n % 12 == 0 else "")
    if e.endswith("a") and e[:-1].isdigit():
        return f"{int(e[:-1])} anos-calendário"
    return especificacao


# Catálogo padrão de janelas. O usuário acrescenta as suas em Projetos/_janelas.toml.
JANELAS_PADRAO: tuple[str, ...] = ("12m", "24m", "60m", "120m", "10a", "26a", "28a", "30a", "desde:1995-01")
