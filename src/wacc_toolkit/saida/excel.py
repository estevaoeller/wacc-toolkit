"""Exportador do Excel auditável do cálculo de WACC (modo 1).

Gera um ``.xlsx`` em que o WACC é recalculado por fórmulas vivas do Excel a partir de:

* uma aba **Premissas** com as entradas editáveis (pesos das fases, T, remuneração
  BNDES, spread de crédito) — expostas como nomes definidos (``peso_1``, ``peso_2``…,
  ``T``, ``remuneracao``, ``spread``);
* uma aba por recorte de dados efetivamente usado (``R_<nome>``), com metadados de
  rastreabilidade (série, versão, sha256 do CSV) e a tabela de dados;
* uma aba **Resumo** com uma linha por componente, cuja coluna "Valor" é uma fórmula
  do Excel que referencia as abas de recorte e as premissas — não um valor fixo;
* uma aba **Registro** com a configuração completa e a lista de bases usadas.

Este módulo NÃO altera o motor de cálculo (``wacc_toolkit.calc``): ele apenas lê o
:class:`~wacc_toolkit.calc.modo1.ResultadoWACC` já calculado e monta uma representação
equivalente em fórmulas de planilha. Onde a seleção de linhas depende de uma janela
temporal (ex.: quais retornos diários do Ibovespa entram na janela de volatilidade), a
seleção é decidida aqui, em Python, a partir de ``Componente.janela`` — a fórmula viva
cobre exatamente o intervalo de linhas correspondente. Isso é suficiente para o
critério de "recálculo por link" pedido: mudar uma premissa (peso, T, remuneração,
spread) propaga por fórmula até o WACC; mudar a janela/dados exigiria novo cálculo em
Python (as opções de janela não são premissas editáveis do Excel).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName

from ..calc.modo1 import ResultadoWACC
from ..calc.registro import versao_codigo

# ------------------------------------------------------------------ estilos
NEGRITO = Font(bold=True)
TITULO = Font(bold=True, size=13)
FUNDO_CABECALHO = PatternFill("solid", fgColor="D9D9D9")
FUNDO_ENTRADA = PatternFill("solid", fgColor="FFF2CC")
BORDA_FINA = Side(style="thin", color="BFBFBF")
BORDA = Border(left=BORDA_FINA, right=BORDA_FINA, top=BORDA_FINA, bottom=BORDA_FINA)
FMT_PCT = "0.0000%"
FMT_NUM = "0.000000"
FMT_DATA = "DD/MM/YYYY"


def _cab(ws, row, col, texto, largura=None):
    c = ws.cell(row=row, column=col, value=texto)
    c.font = NEGRITO
    c.fill = FUNDO_CABECALHO
    c.border = BORDA
    if largura:
        ws.column_dimensions[get_column_letter(col)].width = largura
    return c


def _entrada(ws, row, col, valor, nota="entrada"):
    c = ws.cell(row=row, column=col, value=valor)
    c.fill = FUNDO_ENTRADA
    c.comment = Comment(nota, "wacc-toolkit")
    return c


def _largura_auto(ws, col, valores, minimo=10, maximo=42):
    largura = max([minimo] + [len(str(v)) + 2 for v in valores if v is not None])
    ws.column_dimensions[get_column_letter(col)].width = min(largura, maximo)


def _nome_aba(base: str, usados: set[str]) -> str:
    nome = f"R_{base}"[:31]
    if nome not in usados:
        usados.add(nome)
        return nome
    i = 2
    while f"{nome[:28]}_{i}" in usados:
        i += 1
    nome2 = f"{nome[:28]}_{i}"
    usados.add(nome2)
    return nome2


def _def_nome(wb: Workbook, nome: str, ref: str) -> None:
    wb.defined_names[nome] = DefinedName(nome, attr_text=ref)


def _to_pydate(v):
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime().date()
    return v


# ------------------------------------------------------------------ recortes (genérico)
def _meta_recorte(ws, rec, row: int) -> int:
    for rot, val in (("Série:", rec.serie), ("Versão:", rec.versao or "—"),
                     ("SHA256 (CSV):", rec.sha256_csv or "—"), ("Descrição:", rec.descricao),
                     ("Nº de linhas:", len(rec.df))):
        ws.cell(row=row, column=1, value=rot).font = NEGRITO
        ws.cell(row=row, column=2, value=val)
        row += 1
    return row + 1


def _tabela(ws, df: pd.DataFrame, row: int) -> tuple[dict[str, int], int, int]:
    """Escreve cabeçalho + dados a partir de ``row``. Devolve {coluna: índice}, 1ª e última linha de dados."""
    col_idx = {}
    for j, col in enumerate(df.columns, start=1):
        _cab(ws, row, j, col)
        col_idx[col] = j
    r0 = row + 1
    for i, (_, linha) in enumerate(df.iterrows()):
        r = r0 + i
        for col in df.columns:
            v = linha[col]
            v = _to_pydate(v) if col == "data" else (None if pd.isna(v) else v)
            cel = ws.cell(row=r, column=col_idx[col], value=v)
            cel.border = BORDA
            if col == "data":
                cel.number_format = FMT_DATA
            elif isinstance(v, float):
                cel.number_format = FMT_NUM
    r1 = r0 + len(df) - 1 if len(df) else r0 - 1
    ws.freeze_panes = ws.cell(row=r0, column=1).coordinate
    for col, j in col_idx.items():
        _largura_auto(ws, j, [col] + list(df[col].astype(str)))
    return col_idx, r0, r1


def _col_letra(col_idx: dict[str, int], nome: str) -> str:
    return get_column_letter(col_idx[nome])


def _sheet_basico(wb: Workbook, usados: set[str], nome: str, rec) -> tuple:
    ws = wb.create_sheet(_nome_aba(nome, usados))
    row = _meta_recorte(ws, rec, 1)
    df = rec.df.sort_values("data") if "data" in rec.df.columns else rec.df
    col_idx, r0, r1 = _tabela(ws, df, row)
    return ws, col_idx, r0, r1


# ------------------------------------------------------------------ exportação
def exportar_excel(resultado: ResultadoWACC, caminho: str | Path) -> Path:
    cfg = resultado.config
    c = resultado.componentes
    wb = Workbook()
    wb.remove(wb.active)
    abas_usadas: set[str] = set()

    # ============================================================ Premissas
    pre = wb.create_sheet("Premissas")
    pre.sheet_view.showGridLines = False
    pre.cell(row=1, column=1, value="Premissas — WACC").font = TITULO
    linha = 3
    for rot, val in (
        ("Projeto:", cfg.projeto), ("Data-base:", cfg.data_base), ("Mês de corte:", resultado.corte),
        ("Modo:", "modo1_santa_maria"), ("Região Damodaran:", cfg.regiao),
    ):
        pre.cell(row=linha, column=1, value=rot).font = NEGRITO
        v = _to_pydate(val)
        cel = pre.cell(row=linha, column=2, value=v)
        if isinstance(val, __import__("datetime").date):
            cel.number_format = FMT_DATA
        linha += 1
    op = cfg.opcoes
    pre.cell(row=linha, column=1, value="Opções de janela:").font = NEGRITO
    linha += 1
    for rot, val in (
        ("Rf:", op.rf_janela), ("Rf estrutural:", op.rf_estrutural_janela), ("Rm (método):", op.rm_metodo),
        ("Rm (janela):", op.rm_janela), ("CDS 10a:", op.cds_janela), ("Volatilidade:", op.vol_janela),
        ("NTN-B (vencimento):", op.ntnb_vencimento), ("Inflação US$:", op.inflacao_us_janela),
        ("TLP:", op.tlp_janela), ("IPCA (anos Focus):", op.ipca_anos),
    ):
        pre.cell(row=linha, column=1, value=f"   {rot}")
        pre.cell(row=linha, column=2, value=val)
        linha += 1

    linha += 1
    _cab(pre, linha, 1, "Fase / setor", 26)
    _cab(pre, linha, 2, "Peso", 12)
    linha_pesos0 = linha + 1
    n_fases = len(cfg.fases)
    peso_refs: list[str] = []
    for i, f in enumerate(cfg.fases, start=1):
        r = linha_pesos0 + i - 1
        pre.cell(row=r, column=1, value=f.setor).border = BORDA
        if i < n_fases:
            cel = _entrada(pre, r, 2, f.peso)
        elif n_fases == 2:
            cel = pre.cell(row=r, column=2, value=f"=1-B{linha_pesos0}")
        else:
            cel = _entrada(pre, r, 2, f.peso)
        cel.number_format = FMT_PCT
        cel.border = BORDA
        _def_nome(wb, f"peso_{i}", f"Premissas!$B${r}")
        peso_refs.append(f"$B${r}")
    linha_pesos1 = linha_pesos0 + n_fases - 1
    linha = linha_pesos1 + 1
    if n_fases > 2:
        pre.cell(row=linha, column=1, value="Soma dos pesos (deve ser 100%):").font = NEGRITO
        soma = pre.cell(row=linha, column=2, value=f"=SUM(B{linha_pesos0}:B{linha_pesos1})")
        soma.number_format = FMT_PCT
        linha += 1
    linha += 1

    def _premissa(rotulo, valor, fmt=FMT_PCT, extra=None):
        nonlocal linha
        pre.cell(row=linha, column=1, value=rotulo).font = NEGRITO
        if extra is not None:
            pre.cell(row=linha, column=2, value=extra)
            r_valor = linha + 1
            cel = _entrada(pre, r_valor, 2, valor)
        else:
            r_valor = linha
            cel = _entrada(pre, r_valor, 2, valor)
        cel.number_format = fmt
        linha = r_valor + 1
        return r_valor

    r_t = _premissa("Alíquota IR/CSLL (T):", c["t"].valor)
    _def_nome(wb, "T", f"Premissas!$B${r_t}")
    r_rem = _premissa("Remuneração básica BNDES:", c["remuneracao_bndes"].valor, extra=f"linha: {cfg.linha_bndes}")
    _def_nome(wb, "remuneracao", f"Premissas!$B${r_rem}")
    r_spr = _premissa("Spread de crédito:", c["spread_credito"].valor)
    _def_nome(wb, "spread", f"Premissas!$B${r_spr}")
    pre.column_dimensions["A"].width = 30
    pre.column_dimensions["B"].width = 20

    # ============================================================ Resumo (criado agora, preenchido depois)
    res = wb.create_sheet("Resumo")
    cab_res = ["Nome", "Valor", "Rótulo / janela", "Fórmula", "Valor (Python)", "Diferença"]
    for j, t in enumerate(cab_res, start=1):
        _cab(res, 1, j, t, 22 if j in (1, 3, 4) else 16)
    res.freeze_panes = "A2"
    linha_res: dict[str, int] = {}

    def _linha_resumo(comp_id: str, formula_excel: str) -> int:
        r = 2 + len(linha_res)
        comp = c[comp_id]
        res.cell(row=r, column=1, value=comp.nome).border = BORDA
        cv = res.cell(row=r, column=2, value=formula_excel)
        cv.number_format = FMT_PCT
        cv.border = BORDA
        res.cell(row=r, column=3, value=comp.rotulo).border = BORDA
        res.cell(row=r, column=4, value=comp.formula).border = BORDA
        cp = res.cell(row=r, column=5, value=comp.valor)
        cp.number_format = FMT_PCT
        cp.border = BORDA
        cd = res.cell(row=r, column=6, value=f"=B{r}-E{r}")
        cd.number_format = "0.00000000%"
        cd.border = BORDA
        linha_res[comp_id] = r
        return r

    def _cel_valor(comp_id: str) -> str:
        return f"Resumo!$B${linha_res[comp_id]}"

    # ------------------------------------------------------------ rf / rf_estrutural
    def _serie_media(comp_id: str) -> str:
        comp = c[comp_id]
        rec = comp.recortes[0]
        _, col_idx, r0, r1 = _sheet_basico(wb, abas_usadas, rec.nome, rec)
        col = _col_letra(col_idx, "valor")
        aba = wb.sheetnames[-1]
        return f"=AVERAGE('{aba}'!{col}{r0}:{col}{r1})/100"

    _linha_resumo("rf", _serie_media("rf"))
    _linha_resumo("rf_estrutural", _serie_media("rf_estrutural"))

    # ------------------------------------------------------------ rm
    def _rm_formula() -> str:
        comp = c["rm"]
        rec = comp.recortes[0]
        ws = wb.create_sheet(_nome_aba(rec.nome, abas_usadas))
        row = _meta_recorte(ws, rec, 1)
        ws.cell(row=row, column=1, value="Tabela auxiliar mensal").font = NEGRITO
        row += 1
        anual = "n_anos" in comp.detalhes
        j = comp.janela
        ini_p, fim_p = pd.Period(j["inicio"], "M"), pd.Period(j["fim"], "M")
        df = rec.df.sort_values("data")
        if not anual:
            fechos = df.set_index("data")["fechamento"].sort_index()
            fechos = fechos.groupby(fechos.index.to_period("M")).last()
            fechos = fechos[(fechos.index >= ini_p - 1) & (fechos.index <= fim_p)]
        else:
            fechos = df.set_index("data")["fechamento"].sort_index()
            fechos = fechos.groupby(fechos.index.to_period("M")).last()
            fechos = fechos[fechos.index.month == 12]
            fechos = fechos[(fechos.index.year >= ini_p.year - 1) & (fechos.index.year <= fim_p.year)]
        _cab(ws, row, 1, "Mês", 14)
        _cab(ws, row, 2, "Fechamento (último pregão)", 24)
        _cab(ws, row, 3, "Retorno" + (" simples" if anual else " ln"), 14)
        r0 = row + 1
        for i, (per, val) in enumerate(fechos.items()):
            r = r0 + i
            ws.cell(row=r, column=1, value=str(per)).border = BORDA
            ws.cell(row=r, column=2, value=float(val)).border = BORDA
            if i > 0:
                if anual:
                    f = f"=B{r}/B{r-1}-1"
                else:
                    f = f"=LN(B{r}/B{r-1})"
                cel = ws.cell(row=r, column=3, value=f)
                cel.number_format = FMT_NUM
                cel.border = BORDA
        r_ini = r0 + 1  # 1º retorno útil (row of ini_p, i.e. index 1)
        r_fim = r0 + len(fechos) - 1
        ws.freeze_panes = ws.cell(row=r0, column=1).coordinate
        # tabela bruta abaixo
        row2 = r_fim + 3
        ws.cell(row=row2 - 1, column=1, value="Recorte bruto usado").font = NEGRITO
        _tabela(ws, df, row2)
        aba = ws.title
        if anual:
            return f"=AVERAGE('{aba}'!C{r_ini}:C{r_fim})"
        return f"=(1+AVERAGE('{aba}'!C{r_ini}:C{r_fim}))^12-1"

    _linha_resumo("rm", _rm_formula())

    # ------------------------------------------------------------ erp
    _linha_resumo("erp", f"={_cel_valor('rm')}-{_cel_valor('rf_estrutural')}")

    # ------------------------------------------------------------ risco_brasil
    def _risco_brasil_formula() -> str:
        comp = c["risco_brasil"]
        rec_cds, rec_ibov, rec_ntnb = comp.recortes
        _, ci, r0c, r1c = _sheet_basico(wb, abas_usadas, rec_cds.nome, rec_cds)
        col_cds = _col_letra(ci, "ultimo")
        aba_cds = wb.sheetnames[-1]

        jv = comp.janela["volatilidade"]
        d_ini, d_fim = pd.Period(jv["inicio"], "M").start_time, pd.Period(jv["fim"], "M").end_time

        def _serie_vol(rec, coluna) -> tuple[str, str, int, int]:
            ws = wb.create_sheet(_nome_aba(rec.nome, abas_usadas))
            row = _meta_recorte(ws, rec, 1)
            df = rec.df.sort_values("data").reset_index(drop=True)
            col_idx, r0, r1 = _tabela(ws, df, row)
            col_val = _col_letra(col_idx, coluna)
            col_ret = get_column_letter(len(col_idx) + 1)
            _cab(ws, row, len(col_idx) + 1, "Retorno ln")
            datas = pd.to_datetime(df["data"])
            r_ini_marker, r_fim_marker = None, None
            for i in range(len(df)):
                r = r0 + i
                if i > 0:
                    f = f"=LN({col_val}{r}/{col_val}{r-1})"
                    cel = ws.cell(row=r, column=len(col_idx) + 1, value=f)
                    cel.number_format = FMT_NUM
                    cel.border = BORDA
                    if datas.iloc[i] >= d_ini and datas.iloc[i] <= d_fim and r_ini_marker is None:
                        r_ini_marker = r
                    if datas.iloc[i] >= d_ini and datas.iloc[i] <= d_fim:
                        r_fim_marker = r
            return ws.title, col_ret, r_ini_marker, r_fim_marker

        aba_ibov, col_ret_ibov, ri0, ri1 = _serie_vol(rec_ibov, "fechamento")
        aba_ntnb, col_ret_ntnb, rn0, rn1 = _serie_vol(rec_ntnb, "pu_base")
        # STDEV.S é pós-2007: o XML precisa do prefixo _xlfn. quando a fórmula é escrita
        # diretamente (fora da UI do Excel), senão o Excel devolve #NOME?.
        return (f"=AVERAGE('{aba_cds}'!{col_cds}{r0c}:{col_cds}{r1c})"
                f"*_xlfn.STDEV.S('{aba_ibov}'!{col_ret_ibov}{ri0}:{col_ret_ibov}{ri1})"
                f"/_xlfn.STDEV.S('{aba_ntnb}'!{col_ret_ntnb}{rn0}:{col_ret_ntnb}{rn1})/10000")

    _linha_resumo("risco_brasil", _risco_brasil_formula())

    # ------------------------------------------------------------ beta_u / d_v
    def _beta_dv_formulas() -> tuple[str, str]:
        rec_beta = c["beta_u"].recortes[0]
        _, cib, r0b, r1b = _sheet_basico(wb, abas_usadas, rec_beta.nome, rec_beta)
        col_beta = _col_letra(cib, op.beta_coluna)
        aba_beta = wb.sheetnames[-1]

        rec_de = c["d_v"].recortes[0]
        ws_de = wb.create_sheet(_nome_aba(rec_de.nome, abas_usadas))
        row = _meta_recorte(ws_de, rec_de, 1)
        col_idx, r0d, r1d = _tabela(ws_de, rec_de.df, row)
        col_de = _col_letra(col_idx, op.de_coluna)
        col_dv_idx = len(col_idx) + 1
        col_dv = get_column_letter(col_dv_idx)
        _cab(ws_de, row, col_dv_idx, "D/V")
        for i in range(len(rec_de.df)):
            r = r0d + i
            cel = ws_de.cell(row=r, column=col_dv_idx, value=f"={col_de}{r}/(1+{col_de}{r})")
            cel.number_format = FMT_NUM
            cel.border = BORDA
        aba_de = ws_de.title

        peso_range = f"Premissas!$B${linha_pesos0}:$B${linha_pesos1}"
        f_beta = f"=SUMPRODUCT({peso_range},'{aba_beta}'!{col_beta}{r0b}:{col_beta}{r1b})"
        f_dv = f"=SUMPRODUCT({peso_range},'{aba_de}'!{col_dv}{r0d}:{col_dv}{r1d})"
        return f_beta, f_dv

    f_beta_u, f_dv = _beta_dv_formulas()
    _linha_resumo("beta_u", f_beta_u)
    _linha_resumo("d_v", f_dv)

    # ------------------------------------------------------------ t
    _sheet_basico(wb, abas_usadas, c["t"].recortes[0].nome, c["t"].recortes[0])
    _linha_resumo("t", "=T")

    # ------------------------------------------------------------ beta_l
    _linha_resumo("beta_l", f"={_cel_valor('beta_u')}*(1+(1-T)*{_cel_valor('d_v')}/(1-{_cel_valor('d_v')}))")

    # ------------------------------------------------------------ ke_nominal
    _linha_resumo(
        "ke_nominal",
        f"={_cel_valor('rf')}+{_cel_valor('erp')}*{_cel_valor('beta_l')}+{_cel_valor('risco_brasil')}",
    )

    # ------------------------------------------------------------ inflacao_us
    def _inflacao_formula() -> str:
        comp = c["inflacao_us"]
        rec_treasury, rec_tips = comp.recortes
        _, cit, r0t, r1t = _sheet_basico(wb, abas_usadas, rec_treasury.nome, rec_treasury)
        col_t = _col_letra(cit, "valor")
        aba_treasury = wb.sheetnames[-1]

        ws_tips = wb.create_sheet(_nome_aba(rec_tips.nome, abas_usadas))
        row = _meta_recorte(ws_tips, rec_tips, 1)
        df_tips = rec_tips.df.sort_values("data").reset_index(drop=True)
        col_idx, r0r, r1r = _tabela(ws_tips, df_tips, row)
        col_r = _col_letra(col_idx, "valor")
        col_imp_idx = len(col_idx) + 1
        col_imp = get_column_letter(col_imp_idx)
        _cab(ws_tips, row, col_imp_idx, "Implícita")
        for i in range(len(df_tips)):
            r = r0r + i
            r_treasury_row = r0t + i
            f = f"=(1+'{aba_treasury}'!{col_t}{r_treasury_row}/100)/(1+{col_r}{r}/100)-1"
            cel = ws_tips.cell(row=r, column=col_imp_idx, value=f)
            cel.number_format = FMT_NUM
            cel.border = BORDA
        aba_tips = ws_tips.title
        return f"=AVERAGE('{aba_tips}'!{col_imp}{r0r}:{col_imp}{r1r})"

    _linha_resumo("inflacao_us", _inflacao_formula())

    # ------------------------------------------------------------ ke_real
    _linha_resumo("ke_real", f"=(1+{_cel_valor('ke_nominal')})/(1+{_cel_valor('inflacao_us')})-1")

    # ------------------------------------------------------------ tlp
    _linha_resumo("tlp", _serie_media("tlp"))

    # ------------------------------------------------------------ remuneracao_bndes / spread_credito
    def _param_manual(comp_id, nome_defn):
        comp = c[comp_id]
        rec = comp.recortes[0]
        _sheet_basico(wb, abas_usadas, rec.nome, rec)
        return f"={nome_defn}"

    _linha_resumo("remuneracao_bndes", _param_manual("remuneracao_bndes", "remuneracao"))
    _linha_resumo("spread_credito", "=spread")

    # ------------------------------------------------------------ ipca
    def _ipca_formula() -> str:
        comp = c["ipca"]
        rec = comp.recortes[0]
        ws = wb.create_sheet(_nome_aba(rec.nome, abas_usadas))
        row = _meta_recorte(ws, rec, 1)
        ws.cell(row=row, column=1, value="Projeção usada (Focus)").font = NEGRITO
        row += 1
        _cab(ws, row, 1, "Ano", 10)
        _cab(ws, row, 2, "IPCA (%)", 12)
        _cab(ws, row, 3, "Projetado", 12)
        r0 = row + 1
        anos = comp.detalhes["anos"]
        for i, item in enumerate(anos):
            r = r0 + i
            ws.cell(row=r, column=1, value=item["ano"]).border = BORDA
            if item["projetado"] or i == 0:
                cel = ws.cell(row=r, column=2, value=item["ipca"])
            else:
                cel = ws.cell(row=r, column=2, value=f"=B{r-1}")
            cel.number_format = "0.00"
            cel.border = BORDA
            ws.cell(row=r, column=3, value="S" if item["projetado"] else "N").border = BORDA
        r1 = r0 + len(anos) - 1
        row2 = r1 + 3
        ws.cell(row=row2 - 1, column=1, value="Recorte bruto do relatório Focus usado").font = NEGRITO
        _tabela(ws, rec.df, row2)
        aba = ws.title
        return f"=AVERAGE('{aba}'!B{r0}:B{r1})/100"

    _linha_resumo("ipca", _ipca_formula())

    # ------------------------------------------------------------ kd_nominal / kd_real
    _linha_resumo(
        "kd_nominal",
        f"=(1+{_cel_valor('tlp')})*(1+remuneracao+spread)*(1+{_cel_valor('ipca')})-1",
    )
    _linha_resumo("kd_real", f"=(1+{_cel_valor('kd_nominal')})/(1+{_cel_valor('ipca')})-1")

    # ------------------------------------------------------------ wacc_real / wacc_nominal
    _linha_resumo(
        "wacc_real",
        f"={_cel_valor('ke_real')}*(1-{_cel_valor('d_v')})+{_cel_valor('kd_real')}*{_cel_valor('d_v')}*(1-T)",
    )
    _linha_resumo(
        "wacc_nominal",
        f"={_cel_valor('ke_nominal')}*(1-{_cel_valor('d_v')})+{_cel_valor('kd_nominal')}*{_cel_valor('d_v')}*(1-T)",
    )

    # ============================================================ Registro
    reg = wb.create_sheet("Registro")
    reg.cell(row=1, column=1, value="Registro").font = TITULO
    r = 3
    dados = resultado.to_dict()
    reg.cell(row=r, column=1, value="Versão do código:").font = NEGRITO
    reg.cell(row=r, column=2, value=str(versao_codigo()))
    r += 2
    reg.cell(row=r, column=1, value="Configuração completa:").font = NEGRITO
    r += 1
    for k, v in dados["config"].items():
        reg.cell(row=r, column=1, value=f"   {k}")
        reg.cell(row=r, column=2, value=str(v))
        r += 1
    r += 1
    reg.cell(row=r, column=1, value="Bases usadas (série, versão, sha256):").font = NEGRITO
    r += 1
    _cab(reg, r, 1, "Série", 30)
    _cab(reg, r, 2, "Versão", 12)
    _cab(reg, r, 3, "SHA256 (CSV)", 68)
    r += 1
    vistos = set()
    for comp in c.values():
        for rc in comp.recortes:
            chave = (rc.serie, rc.versao, rc.sha256_csv)
            if chave in vistos:
                continue
            vistos.add(chave)
            reg.cell(row=r, column=1, value=rc.serie).border = BORDA
            reg.cell(row=r, column=2, value=rc.versao or "—").border = BORDA
            reg.cell(row=r, column=3, value=rc.sha256_csv or "—").border = BORDA
            r += 1
    reg.column_dimensions["A"].width = 30
    reg.column_dimensions["B"].width = 40

    # ============================================================ ordem final das abas
    ordem_abas = ["Premissas", "Resumo"] + [n for n in wb.sheetnames if n.startswith("R_")] + ["Registro"]
    wb._sheets = [wb[n] for n in ordem_abas]
    wb.active = 1

    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)
    return caminho
