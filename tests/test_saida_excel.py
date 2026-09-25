"""Exportador Excel auditável: fórmulas vivas na aba "Custo de Capital" reproduzindo o motor Python."""

from __future__ import annotations

import pytest

import test_calc_modo1 as m1
from wacc_toolkit.calc.modo1 import Fase, beta_estrutura, calcular, compor
from wacc_toolkit.saida.excel import _layout_principal, exportar_excel

# reaproveita a fixture de bases sintéticas do motor (mesmo cenário validado em test_calc_modo1.py)
bases_sinteticas = m1.bases_sinteticas


def _com_disponivel() -> bool:
    try:
        import win32com.client
    except ImportError:
        return False
    try:
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
    assert nomes[0] == "Capa" and nomes[1] == "Custo de Capital"
    assert nomes[2] == "Parâmetros"
    assert nomes[-1] == "Registro"
    assert "Resumo" not in nomes and "Premissas" not in nomes
    esperadas = {"R_rf", "R_rf_estrutural", "R_rm", "R_cds10", "R_ibov", "R_ntnb", "R_beta", "R_de",
                 "R_treasury", "R_tips", "R_tlp", "R_focus"}
    assert esperadas <= set(nomes)


def test_nomes_definidos(resultado, caminho_xlsx):
    import openpyxl

    wb = openpyxl.load_workbook(caminho_xlsx)
    esperados = {"T", "remuneracao", "spread"} | {f"peso_{i}" for i in range(1, len(resultado.config.fases) + 1)}
    assert esperados <= set(wb.defined_names.keys())


def test_sem_travessao_gridlines_e_freeze(caminho_xlsx):
    import openpyxl

    wb = openpyxl.load_workbook(caminho_xlsx)
    for ws in wb.worksheets:
        assert ws.sheet_view.showGridLines is False, ws.title
        assert ws.freeze_panes is None, ws.title
        for row in ws.iter_rows():
            for cel in row:
                if isinstance(cel.value, str):
                    assert "—" not in cel.value and "–" not in cel.value, (ws.title, cel.coordinate, cel.value)
                if cel.comment is not None:
                    assert "—" not in cel.comment.text and "–" not in cel.comment.text


def test_sha256_so_no_registro(caminho_xlsx):
    import openpyxl

    wb = openpyxl.load_workbook(caminho_xlsx)
    for ws in wb.worksheets:
        if ws.title == "Registro":
            continue
        for row in ws.iter_rows():
            for cel in row:
                if isinstance(cel.value, str) and "SHA256" in cel.value.upper():
                    pytest.fail(f"SHA256 fora do Registro: {ws.title}!{cel.coordinate}")


def test_largura_colunas_recorte(caminho_xlsx):
    import openpyxl

    wb = openpyxl.load_workbook(caminho_xlsx)
    ws = wb["R_rf"]
    assert ws.column_dimensions["A"].width == pytest.approx(15.29, abs=0.01)
    assert ws.column_dimensions["B"].width == pytest.approx(15.29, abs=0.01)


def test_layout_tem_20_componentes(resultado):
    row_of = _layout_principal()
    assert len(row_of) == 20
    assert set(row_of) == set(resultado.componentes)


# ------------------------------------------------------------------ avaliação via Excel (COM)
def _abrir_com(caminho):
    import win32com.client

    app = win32com.client.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    wb = app.Workbooks.Open(str(caminho))
    wb.Application.CalculateFullRebuild()
    return app, wb


def _ler_custo_capital(wb, resultado):
    row_of = _layout_principal()
    ws = wb.Worksheets("Custo de Capital")
    return {cid: float(ws.Cells(r, 3).Value) for cid, r in row_of.items()}


@pytest.mark.excel
@pytest.mark.skipif(not COM_OK, reason="Excel não disponível via COM neste ambiente")
def test_formulas_batem_com_python_via_com(resultado, caminho_xlsx):
    app, wb = _abrir_com(caminho_xlsx)
    try:
        valores = _ler_custo_capital(wb, resultado)
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
        valores = _ler_custo_capital(wb, resultado)
        nota5 = wb.Worksheets("Custo de Capital").Cells(34, 2).Value
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
    # a nota (5) é uma fórmula de texto que também recalcula com o novo peso
    assert "50,00%" in nota5 or "50.00%" in nota5


def test_layout_custo_de_capital_e_capa(tmp_path, bases_sinteticas):
    """Coluna A vazia de 25 px, valores centralizados, capa com projeto/data-base/criação, datas em mês/ano."""
    from openpyxl import load_workbook

    from wacc_toolkit.calc.modo1 import calcular
    from wacc_toolkit.saida.excel import exportar_excel

    cfg = m1._cfg()
    r = calcular(cfg, bases_sinteticas)
    wb = load_workbook(exportar_excel(r, tmp_path / "x.xlsx"))
    cc = wb["Custo de Capital"]
    assert cc.column_dimensions["A"].width == pytest.approx(3.57, abs=0.01)
    assert all(cc.cell(row=i, column=1).value is None for i in range(1, cc.max_row + 1))
    assert cc["B3"].value == "Item" and cc["C3"].value == "Valor"
    assert cc["C5"].alignment.horizontal == "center"
    capa = {wb["Capa"].cell(row=i, column=2).value: wb["Capa"].cell(row=i, column=3).value for i in range(6, 9)}
    assert capa["Projeto:"] == "Teste" and capa["Data-base:"] == "01/2026" and capa["Data de criação:"]
    par = wb["Parâmetros"]
    assert par["B4"].value == "01/2026" and par["B4"].alignment.horizontal == "left"
