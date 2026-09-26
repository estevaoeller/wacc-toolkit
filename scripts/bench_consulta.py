"""Mede o tempo de abrir a página Consulta com b3_ibov e tesouro_td_taxas (bases reais).

Uso: .venv/Scripts/python.exe scripts/bench_consulta.py
Roda com o estado ATUAL de consulta.py/estado.py (script descartável, não faz parte da suíte).
"""

import os
import time
from pathlib import Path

os.environ["WACC_BASES_DIR"] = "C:/Users/estev/FGV/Núcleo Econômico-Financeiro - General/19_WACC/Bases"

from streamlit.testing.v1 import AppTest  # noqa: E402

CONSULTA = Path(__file__).resolve().parents[1] / "src" / "wacc_toolkit" / "app" / "paginas" / "consulta.py"


def _selecionar(at, rotulo_widget, valor):
    widget = next(s for s in at.selectbox if s.label == rotulo_widget)
    widget.set_value(valor)


def medir(fonte: str, serie: str) -> float:
    t0 = time.perf_counter()
    at = AppTest.from_file(str(CONSULTA), default_timeout=120)
    at.run()
    _selecionar(at, "Fonte", fonte)
    at.run()
    _selecionar(at, "Série", serie)
    at.run()
    if at.exception:
        raise RuntimeError(at.exception[0].value)
    return time.perf_counter() - t0


if __name__ == "__main__":
    for fonte, serie in (("b3", "b3_ibov"), ("tesouro", "tesouro_td_taxas")):
        primeira = medir(fonte, serie)
        segunda = medir(fonte, serie)  # 2ª leitura: st.cache_data já deve ter o conteúdo
        print(f"{serie}: 1ª abertura {primeira:.2f}s | 2ª abertura (cache) {segunda:.2f}s")
