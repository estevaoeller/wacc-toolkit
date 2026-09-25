"""Exportador Excel auditável: fórmulas vivas reproduzindo os valores do motor Python."""

from __future__ import annotations

import pytest

import test_calc_modo1 as m1
from wacc_toolkit.calc.modo1 import Fase, beta_estrutura, calcular, compor
from wacc_toolkit.saida.excel import exportar_excel

# reaproveita a fixture de bases sintéticas do motor (mesmo cenário validado em test_calc_modo1.py)
bases_sinteticas = m1.bases_sinteticas


def _com_disponivel() -> bool:
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    try:
        import win32com.client
        app = win32com.client.DispatchEx("Excel.Application")
        app.Quit()
    except Exception:
        return False
    return True


COM_OK = _com_disponivel()


@pytest.fixture
def resultado(bases_sinteticas):
    return calcular(m1._cfg(), bases_sinteticas)


@pytest.fixture
def caminho_xlsx(resultado, tmp_path):
    return exportar_excel(resultado, tmp_path / "wacc_teste.xlsx")


def test_abas_presentes(caminho_xlsx):
    import openpyxl

    wb = openpyxl.load_workbook(caminho_xlsx)
    nomes = wb.sheetnames
    assert nomes[0] == "Premissas"
    assert nomes[1] == "Resumo"
    assert nomes[-1] == "Registro"
    assert any(n.startswith("R_") for n in nomes)
    # uma aba de recorte por série efetivamente usada
    esperadas = {"R_rf", "R_rf_estrutural", "R_rm", "R_cds10", "R_ibov", "R_ntnb", "R_beta", "R_de",
                 "R_treasury", "R_tips", "R_tlp", "R_focus"}
    assert esperadas <= set(nomes)


def test_nomes_definidos(resultado, caminho_xlsx):
    import openpyxl

    wb = openpyxl.load_workbook(caminho_xlsx)
    esperados = {"T", "remuneracao", "spread"} | {f"peso_{i}" for i in range(1, len(resultado.config.fases) + 1)}
    assert esperados <= set(wb.defined_names.keys())


def test_resumo_tem_uma_linha_por_componente(resultado, caminho_xlsx):
    import openpyxl

    wb = openpyxl.load_workbook(caminho_xlsx)
    ws = wb["Resumo"]
    nomes_planilha = [ws.cell(row=r, column=1).value for r in range(2, 2 + len(resultado.componentes))]
    nomes_esperados = [c.nome for c in resultado.componentes.values()]
    assert nomes_planilha == nomes_esperados


# ------------------------------------------------------------------ avaliação via Excel (COM)
def _abrir_com(caminho):
    import win32com.client

    app = win32com.client.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    wb = app.Workbooks.Open(str(caminho))
    wb.Application.CalculateFullRebuild()
    return app, wb


def _ler_resumo(wb, resultado):
    ws = wb.Worksheets("Resumo")
    valores = {}
    for i, comp_id in enumerate(resultado.componentes):
        valores[comp_id] = float(ws.Cells(2 + i, 2).Value)
    return valores


@pytest.mark.excel
@pytest.mark.skipif(not COM_OK, reason="Excel não disponível via COM neste ambiente")
def test_formulas_batem_com_python_via_com(resultado, caminho_xlsx):
    app, wb = _abrir_com(caminho_xlsx)
    try:
        valores = _ler_resumo(wb, resultado)
    finally:
        wb.Close(False)
        app.Quit()
    for comp_id, comp in resultado.componentes.items():
        assert valores[comp_id] == pytest.approx(comp.valor, abs=1e-9), comp_id


@pytest.mark.excel
@pytest.mark.skipif(not COM_OK, reason="Excel não disponível via COM neste ambiente")
def test_alterar_peso_recalcula_em_cascata(bases_sinteticas, resultado, caminho_xlsx):
    app, wb = _abrir_com(caminho_xlsx)
    try:
        wb.Names("peso_1").RefersToRange.Value = 0.5
        wb.Application.CalculateFullRebuild()
        valores = _ler_resumo(wb, resultado)
    finally:
        wb.Close(False)
        app.Quit()

    cfg = m1._cfg(fases=[Fase("Setor A", 0.5), Fase("Setor B", 0.5)])
    cb, cd = beta_estrutura(bases_sinteticas, cfg)
    comp = compor(
        rf=resultado["rf"], rf_estrutural=resultado["rf_estrutural"], rm=resultado["rm"],
        risco_brasil=resultado["risco_brasil"], beta_u=cb.valor, d_v=cd.valor, t=resultado["t"],
        inflacao_us=resultado["inflacao_us"], tlp=resultado["tlp"], remuneracao=resultado["remuneracao_bndes"],
        spread=resultado["spread_credito"], ipca=resultado["ipca"],
    )
    assert valores["beta_u"] == pytest.approx(cb.valor, abs=1e-9)
    assert valores["d_v"] == pytest.approx(cd.valor, abs=1e-9)
    assert valores["wacc_nominal"] == pytest.approx(comp["wacc_nominal"], abs=1e-9)
    assert valores["wacc_nominal"] != pytest.approx(resultado["wacc_nominal"], abs=1e-6)
