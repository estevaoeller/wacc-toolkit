"""Exportador do Excel auditável do cálculo de WACC (modo 1).

Gera um ``.xlsx`` em que o WACC é recalculado por fórmulas vivas do Excel, no layout da
planilha original Santa Maria:

* **Custo de Capital** (1ª aba): a tabela Item | Valor | Descrição onde o cálculo
  acontece de fato - Rf, Rm, ERP, Beta, D/(D+E), T, Ke, TLP, Kd, WACC (real e nominal) -
  todas como fórmulas do Excel; abaixo, as notas de fonte (1)-(10) e, quando há mais de
  uma fase, o bloco de ponderação dos betas/D/(D+E) por fase (pesos editáveis);
* **Parâmetros** (2ª aba): metadados informativos do projeto (sem entradas);
* uma aba por recorte de dados efetivamente usado (``R_<nome>``): metadados de
  rastreabilidade (série, versão, descrição, janela, nº de linhas, link da fonte) e a
  tabela de dados;
* **Registro** (última aba): configuração completa, lista de bases usadas (série,
  versão, sha256 - único lugar com o hash) e a conferência valor-Python × fórmula.

Este módulo NÃO altera o motor de cálculo (``wacc_toolkit.calc``): lê o
:class:`~wacc_toolkit.calc.modo1.ResultadoWACC` já calculado e monta uma representação
equivalente em fórmulas de planilha. As janelas temporais (quais linhas entram em cada
cálculo) são decididas aqui, em Python, a partir de ``Componente.janela`` - a fórmula
viva cobre exatamente essas linhas. Isso é suficiente para o recálculo em cascata
pedido: mudar uma entrada editável (peso, T, remuneração BNDES, spread) propaga por
fórmula até o WACC; mudar a janela/dados exigiria novo cálculo em Python.
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
ITALICO = Font(italic=True)
TITULO = Font(bold=True, size=13)
BRANCO_NEGRITO = Font(bold=True, color="FFFFFF")
FUNDO_SECAO = PatternFill("solid", fgColor="D9D9D9")
FUNDO_ENTRADA = PatternFill("solid", fgColor="FFF2CC")
FUNDO_CABECALHO_TABELA = PatternFill("solid", fgColor="1F4E78")
FUNDO_WACC = PatternFill("solid", fgColor="375623")
FUNDO_HACHURA = PatternFill(fill_type="lightUp", fgColor="BFBFBF", bgColor="FFFFFF")
BORDA_FINA = Side(style="thin", color="BFBFBF")
BORDA = Border(left=BORDA_FINA, right=BORDA_FINA, top=BORDA_FINA, bottom=BORDA_FINA)
BORDA_TOPO = Border(top=Side(style="thin", color="595959"))
CENTRO = Alignment(horizontal="center", vertical="center")
FMT_PCT = "0.00%"
FMT_NUM = "0.000000"
FMT_DATA = "DD/MM/YYYY"
LARGURA_R = 15.29  # 107 px no Excel (o arquivo guarda a largura com ~0,71 de preenchimento)
LARGURA_MARGEM = 3.57  # 25 px no Excel (coluna A vazia)
ESQUERDA = Alignment(horizontal="left", vertical="center")


def _mes_ano(d) -> str:
    """Data-base exibida como mês/ano (ex.: 01/2026)."""
    return f"{d.month:02d}/{d.year}"

# séries -> página pública da fonte (para o link nas abas de recorte)
URLS_SERIE = {
    "fred_gs10": "https://fred.stlouisfed.org/series/GS10",
    "fred_fii10": "https://fred.stlouisfed.org/series/FII10",
    "yahoo_sp500tr": "https://finance.yahoo.com/quote/%5ESP500TR/history",
    "investing_cds10_brasil_mensal": "https://br.investing.com/rates-bonds/brazil-cds-10-years-usd-historical-data",
    "investing_cds10_brasil": "https://br.investing.com/rates-bonds/brazil-cds-10-years-usd-historical-data",
    "b3_ibov": "https://www.b3.com.br/pt_br/market-data-e-indices/indices/indices-amplos/"
               "indice-ibovespa-ibovespa-estatisticas-historicas.htm",
    "tesouro_td_taxas": "https://www.tesourotransparente.gov.br/ckan/dataset/"
                         "taxas-dos-titulos-ofertados-pelo-tesouro-direto",
    "bcb_tlp": "https://www.bndes.gov.br/wps/portal/site/home/financiamento/guia/"
               "custos-financeiros/tlp-taxa-de-longo-prazo",
    "bcb_focus_ipca_anual": "https://www.bcb.gov.br/publicacoes/focus",
    "ir_csll": "https://www.gov.br/receitafederal/pt-br/assuntos/orientacao-tributaria/tributos/IRPJ",
}
ENDPOINT_SERIE = {
    "bcb_tlp": "https://api.bcb.gov.br/dados/serie/bcdata.sgs.27572/dados?formato=json",
}
URL_DAMODARAN = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datacurrent.html"
URL_BNDES_PRODUTO = "https://www.bndes.gov.br/wps/portal/site/home/financiamento/produto/bndes-finem-saneamento"


def _url_para(rec) -> str | None:
    if rec.serie.startswith("damodaran_"):
        return URL_DAMODARAN
    if rec.serie == "parametros_manuais":
        if rec.nome.startswith("bndes_"):
            return URL_BNDES_PRODUTO
        return URLS_SERIE.get(rec.nome)
    return URLS_SERIE.get(rec.serie)


# ------------------------------------------------------------------ utilidades de texto
def _sanitizar(texto: str) -> str:
    return texto.replace("—", "-").replace("–", "-")


def _meses_txt(espec: str) -> str:
    if espec.endswith("m") and espec[:-1].isdigit():
        return f"{espec[:-1]} meses"
    if espec.endswith("a") and espec[:-1].isdigit():
        return f"{espec[:-1]} anos"
    return espec


def _anos_abrev(espec: str) -> str:
    if espec.endswith("m") and espec[:-1].isdigit():
        n = int(espec[:-1])
        return f"{n // 12}a" if n % 12 == 0 else f"{n}m"
    if espec.endswith("a") and espec[:-1].isdigit():
        return f"{espec[:-1]}a"
    return espec


def _desc_param(fonte: str) -> str:
    if fonte.startswith("Receita Federal"):
        return "Receita Federal do Brasil"
    if fonte.startswith("BNDES Finem:"):
        resto = fonte[len("BNDES Finem:"):].split(" (")[0].strip()
        return f"Finem - {resto}"
    return fonte.split(" (")[0]


# ------------------------------------------------------------------ helpers de planilha
def _cab(ws, row, col, texto, largura=None):
    c = ws.cell(row=row, column=col, value=_sanitizar(str(texto)))
    c.font = NEGRITO
    c.fill = FUNDO_SECAO
    c.border = BORDA
    if largura:
        ws.column_dimensions[get_column_letter(col)].width = largura
    return c


def _entrada(ws, row, col, valor, nota="entrada"):
    c = ws.cell(row=row, column=col, value=valor)
    c.fill = FUNDO_ENTRADA
    c.comment = Comment(nota, "wacc-toolkit")
    return c


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


def _col_letra(col_idx: dict[str, int], nome: str) -> str:
    return get_column_letter(col_idx[nome])


# ------------------------------------------------------------------ abas de recorte (genérico)
def _meta_recorte(ws, rec, row: int) -> int:
    itens = [("Série:", rec.serie), ("Versão:", rec.versao or "-"), ("Descrição:", rec.descricao),
             ("Nº de linhas:", len(rec.df))]
    url = _url_para(rec)
    for rot, val in itens:
        ws.cell(row=row, column=1, value=rot).font = NEGRITO
        ws.cell(row=row, column=2, value=_sanitizar(str(val)) if isinstance(val, str) else val)
        row += 1
    ws.cell(row=row, column=1, value="Fonte (link):").font = NEGRITO
    cel = ws.cell(row=row, column=2, value=url or "-")
    if url:
        cel.hyperlink = url
        cel.font = Font(color="0563C1", underline="single")
    row += 1
    endpoint = ENDPOINT_SERIE.get(rec.serie)
    if endpoint:
        ws.cell(row=row, column=1, value="Endpoint:").font = NEGRITO
        cele = ws.cell(row=row, column=2, value=endpoint)
        cele.hyperlink = endpoint
        cele.font = Font(color="0563C1", underline="single")
        row += 1
    return row + 1


def _tabela(ws, df: pd.DataFrame, row: int) -> tuple[dict[str, int], int, int]:
    """Escreve cabeçalho + dados a partir de ``row``. Devolve {coluna: índice}, 1ª e última linha de dados."""
    col_idx = {}
    for j, col in enumerate(df.columns, start=1):
        cel = _cab(ws, row, j, col)
        cel.alignment = CENTRO
        col_idx[col] = j
    r0 = row + 1
    for i, (_, linha) in enumerate(df.iterrows()):
        r = r0 + i
        for col in df.columns:
            v = linha[col]
            v = _to_pydate(v) if col == "data" else (None if pd.isna(v) else v)
            v = _sanitizar(v) if isinstance(v, str) else v
            cel = ws.cell(row=r, column=col_idx[col], value=v)
            cel.border = BORDA
            cel.alignment = CENTRO
            if col == "data":
                cel.number_format = FMT_DATA
            elif isinstance(v, float):
                cel.number_format = FMT_NUM
    r1 = r0 + len(df) - 1 if len(df) else r0 - 1
    for j in range(1, len(col_idx) + 1):
        ws.column_dimensions[get_column_letter(j)].width = LARGURA_R
    return col_idx, r0, r1


def _sheet_basico(wb: Workbook, usados: set[str], nome: str, rec) -> tuple:
    ws = wb.create_sheet(_nome_aba(nome, usados))
    row = _meta_recorte(ws, rec, 1)
    df = rec.df.sort_values("data") if "data" in rec.df.columns else rec.df
    col_idx, r0, r1 = _tabela(ws, df, row)
    return ws, col_idx, r0, r1


# ------------------------------------------------------------------ ordem/layout da aba Custo de Capital
_KE_ITENS = ["rf", "rm", "rf_estrutural", "erp", "risco_brasil", "beta_u", "d_v", "t", "beta_l",
             "ke_nominal", "inflacao_us", "ke_real"]
_KD_ITENS = ["tlp", "remuneracao_bndes", "spread_credito", "ipca", "kd_nominal", "kd_real"]

_ROTULOS = {
    "rf": "Taxa Livre de Riscos (Rf)", "rm": "Risco de Mercado",
    "rf_estrutural": "Taxa Livre de Riscos Estrutural (R'f)",
    "erp": "Prêmio de Risco de Mercado (Equity Risk Premium)", "risco_brasil": "Prêmio de Risco Brasil",
    "beta_u": "Beta desalavancado", "d_v": "D/(D+E)", "t": "T", "beta_l": "Beta re-alavancado",
    "ke_nominal": "Ke (US$ nominal)", "inflacao_us": "Inflação US$", "ke_real": "Ke (real)",
    "tlp": "Valor da TLP", "remuneracao_bndes": "Remuneração BNDES", "spread_credito": "Taxa de Risco de Crédito",
    "ipca": "Taxa de Inflação", "kd_nominal": "Kd (nominal)", "kd_real": "Kd (real)",
    "wacc_real": "WACC (real)", "wacc_nominal": "WACC (nominal)",
}
_FMT_VALOR = {
    "beta_u": "0.00", "d_v": "0.0%", "t": "0.0%", "beta_l": "0.000",
}
_COMPOSTOS = {"erp", "beta_l", "ke_nominal", "ke_real", "kd_nominal", "kd_real", "wacc_real", "wacc_nominal"}


def _layout_principal() -> dict[str, int]:
    row_of: dict[str, int] = {}
    for i, cid in enumerate(_KE_ITENS):
        row_of[cid] = 5 + i
    for i, cid in enumerate(_KD_ITENS):
        row_of[cid] = 19 + i
    row_of["wacc_real"] = 26
    row_of["wacc_nominal"] = 27
    return row_of


def _layout_ponderacao(n_fases: int, linha0: int) -> dict:
    beta_r, dv_r, peso_r = [], [], []
    r = linha0
    for _ in range(n_fases):
        beta_r.append(r)
        dv_r.append(r + 1)
        peso_r.append(r + 2)
        r += 3
    row_soma = r if n_fases > 2 else None
    if row_soma:
        r += 1
    row_media_beta, row_media_dv = r, r + 1
    return {"beta": beta_r, "dv": dv_r, "peso": peso_r, "soma": row_soma,
            "media_beta": row_media_beta, "media_dv": row_media_dv, "fim": row_media_dv}


# ------------------------------------------------------------------ exportação
def exportar_excel(resultado: ResultadoWACC, caminho: str | Path) -> Path:
    cfg = resultado.config
    op = cfg.opcoes
    c = resultado.componentes
    n_fases = len(cfg.fases)
    wb = Workbook()
    wb.remove(wb.active)
    abas_usadas: set[str] = set()

    # ============================================================ Custo de Capital
    # colunas: A = margem vazia, B = Item, C = Valor, D = Descrição
    CI, CV, CD = 2, 3, 4
    VL = get_column_letter(CV)
    cc = wb.create_sheet("Custo de Capital")
    row_of = _layout_principal()
    linha_pond0 = 42
    pond = _layout_ponderacao(n_fases, linha_pond0) if n_fases > 1 else None

    cc.cell(row=1, column=CI, value=_sanitizar(f"Custo de Capital - {cfg.projeto}")).font = TITULO
    for j, t in enumerate(("Item", "Valor", "Descrição"), start=CI):
        cel = cc.cell(row=3, column=j, value=t)
        cel.font = BRANCO_NEGRITO
        cel.fill = FUNDO_CABECALHO_TABELA
        cel.alignment = CENTRO
        cel.border = BORDA
    cc.column_dimensions["A"].width = LARGURA_MARGEM  # coluna A vazia (25 px)
    cc.column_dimensions["B"].width = 45
    cc.column_dimensions["C"].width = 12
    cc.column_dimensions["D"].width = 70

    def _secao(row, texto):
        for col in (CI, CV, CD):
            cel = cc.cell(row=row, column=col, value=texto if col == CI else None)
            cel.font = NEGRITO
            cel.fill = FUNDO_SECAO
            cel.border = BORDA

    _secao(4, "KE")
    _secao(18, "KD")

    def _linha(cid, formula_ou_valor, descricao, *, editable=False, italico=False, total=False, wacc=False):
        r = row_of[cid]
        item = cc.cell(row=r, column=CI, value=_sanitizar(_ROTULOS[cid]))
        item.border = BORDA
        val = cc.cell(row=r, column=CV, value=formula_ou_valor)
        val.number_format = _FMT_VALOR.get(cid, FMT_PCT)
        val.border = BORDA
        val.alignment = CENTRO
        desc_cel = cc.cell(row=r, column=CD)
        desc_cel.border = BORDA
        if cid in _COMPOSTOS:
            desc_cel.fill = FUNDO_HACHURA
        else:
            desc_cel.value = _sanitizar(descricao)
        if editable:
            val.fill = FUNDO_ENTRADA
            val.comment = Comment("entrada", "wacc-toolkit")
        if italico:
            item.font = ITALICO
            val.font = ITALICO
        if total:
            item.font = NEGRITO
            val.font = NEGRITO
            item.border = BORDA_TOPO
            val.border = BORDA_TOPO
        if wacc:
            item.font = BRANCO_NEGRITO if wacc == "verde" else NEGRITO
            val.font = BRANCO_NEGRITO if wacc == "verde" else NEGRITO
            if wacc == "verde":
                item.fill = FUNDO_WACC
                val.fill = FUNDO_WACC
        return r

    def _ref(cid: str) -> str:
        return f"{VL}{row_of[cid]}"

    # ---- Rf / Rf estrutural
    def _serie_media(comp_id: str) -> str:
        comp = c[comp_id]
        rec = comp.recortes[0]
        _, col_idx, r0, r1 = _sheet_basico(wb, abas_usadas, rec.nome, rec)
        col = _col_letra(col_idx, "valor")
        aba = wb.sheetnames[-1]
        return f"=AVERAGE('{aba}'!{col}{r0}:{col}{r1})/100"

    f_rf = _serie_media("rf")
    desc_rf = f"T-10 {_meses_txt(op.rf_janela)} ({c['rf'].janela['rotulo']})"
    _linha("rf", f_rf, desc_rf)

    # ---- Rm
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
        fechos = df.set_index("data")["fechamento"].sort_index()
        fechos = fechos.groupby(fechos.index.to_period("M")).last()
        if not anual:
            fechos = fechos[(fechos.index >= ini_p - 1) & (fechos.index <= fim_p)]
        else:
            fechos = fechos[fechos.index.month == 12]
            fechos = fechos[(fechos.index.year >= ini_p.year - 1) & (fechos.index.year <= fim_p.year)]
        _cab(ws, row, 1, "Mês", 14).alignment = CENTRO
        _cab(ws, row, 2, "Fechamento (último pregão)", 24).alignment = CENTRO
        _cab(ws, row, 3, "Retorno" + (" simples" if anual else " ln"), 14).alignment = CENTRO
        r0 = row + 1
        for i, (per, val) in enumerate(fechos.items()):
            r = r0 + i
            cp = ws.cell(row=r, column=1, value=str(per))
            cp.border = BORDA
            cp.alignment = CENTRO
            cv = ws.cell(row=r, column=2, value=float(val))
            cv.border = BORDA
            cv.alignment = CENTRO
            if i > 0:
                f = f"=B{r}/B{r-1}-1" if anual else f"=LN(B{r}/B{r-1})"
                cel = ws.cell(row=r, column=3, value=f)
                cel.number_format = FMT_NUM
                cel.border = BORDA
                cel.alignment = CENTRO
        r_ini = r0 + 1
        r_fim = r0 + len(fechos) - 1
        for j2 in range(1, 4):
            ws.column_dimensions[get_column_letter(j2)].width = LARGURA_R
        row2 = r_fim + 3
        ws.cell(row=row2 - 1, column=1, value="Recorte bruto usado").font = NEGRITO
        _tabela(ws, df, row2)
        aba = ws.title
        if anual:
            return f"=AVERAGE('{aba}'!C{r_ini}:C{r_fim})", aba
        return f"=(1+AVERAGE('{aba}'!C{r_ini}:C{r_fim}))^12-1", aba

    f_rm, _ = _rm_formula()
    if "n_anos" in c["rm"].detalhes:
        desc_rm = f"Média SP500 Retornos Anuais ({c['rm'].janela['rotulo']})"
    else:
        desc_rm = f"Média SP500 Ln Mensal ({c['rm'].janela['rotulo']})"
    _linha("rm", f_rm, desc_rm)

    # ---- Rf estrutural
    f_rfe = _serie_media("rf_estrutural")
    desc_rfe = f"T-10 {_meses_txt(op.rf_estrutural_janela)} ({c['rf_estrutural'].janela['rotulo']})"
    _linha("rf_estrutural", f_rfe, desc_rfe)

    # ---- ERP
    _linha("erp", f"={_ref('rm')}-{_ref('rf_estrutural')}", "")

    # ---- Risco Brasil
    def _risco_brasil_formula() -> str:
        comp = c["risco_brasil"]
        rec_cds, rec_ibov, rec_ntnb = comp.recortes[:3]
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
            cel = _cab(ws, row, len(col_idx) + 1, "Retorno ln")
            cel.alignment = CENTRO
            ws.column_dimensions[col_ret].width = LARGURA_R
            datas = pd.to_datetime(df["data"])
            r_ini_marker, r_fim_marker = None, None
            for i in range(len(df)):
                r = r0 + i
                if i > 0:
                    f = f"=LN({col_val}{r}/{col_val}{r-1})"
                    cel = ws.cell(row=r, column=len(col_idx) + 1, value=f)
                    cel.number_format = FMT_NUM
                    cel.border = BORDA
                    cel.alignment = CENTRO
                    if d_ini <= datas.iloc[i] <= d_fim:
                        if r_ini_marker is None:
                            r_ini_marker = r
                        r_fim_marker = r
            return ws.title, col_ret, r_ini_marker, r_fim_marker

        aba_ibov, col_ret_ibov, ri0, ri1 = _serie_vol(rec_ibov, "fechamento")
        aba_ntnb, col_ret_ntnb, rn0, rn1 = _serie_vol(rec_ntnb, "pu_base")
        # STDEV.S é pós-2007: o XML precisa do prefixo _xlfn. quando a fórmula é escrita
        # diretamente (fora da UI do Excel), senão o Excel devolve #NOME?.
        return (f"=AVERAGE('{aba_cds}'!{col_cds}{r0c}:{col_cds}{r1c})"
                f"*_xlfn.STDEV.S('{aba_ibov}'!{col_ret_ibov}{ri0}:{col_ret_ibov}{ri1})"
                f"/_xlfn.STDEV.S('{aba_ntnb}'!{col_ret_ntnb}{rn0}:{col_ret_ntnb}{rn1})/10000")

    f_rb = _risco_brasil_formula()
    desc_rb = f"CDS {_anos_abrev(op.cds_janela)} + Vol. {_anos_abrev(op.vol_janela)} (IBOV-NTNB)"
    _linha("risco_brasil", f_rb, desc_rb)

    # ---- beta_u / d_v (recortes sempre; fórmula depende de haver bloco de ponderação)
    rec_beta = c["beta_u"].recortes[0]
    _, cib, r0b, r1b = _sheet_basico(wb, abas_usadas, rec_beta.nome, rec_beta)
    col_beta = _col_letra(cib, op.beta_coluna)
    aba_beta = wb.sheetnames[-1]

    rec_de = c["d_v"].recortes[0]
    ws_de = wb.create_sheet(_nome_aba(rec_de.nome, abas_usadas))
    row = _meta_recorte(ws_de, rec_de, 1)
    col_idx_de, r0d, r1d = _tabela(ws_de, rec_de.df, row)
    col_de = _col_letra(col_idx_de, op.de_coluna)
    col_dv_idx = len(col_idx_de) + 1
    col_dv = get_column_letter(col_dv_idx)
    cel_dv = _cab(ws_de, row, col_dv_idx, "D/V")
    cel_dv.alignment = CENTRO
    ws_de.column_dimensions[col_dv].width = LARGURA_R
    for i in range(len(rec_de.df)):
        r = r0d + i
        cel = ws_de.cell(row=r, column=col_dv_idx, value=f"={col_de}{r}/(1+{col_de}{r})")
        cel.number_format = FMT_NUM
        cel.border = BORDA
        cel.alignment = CENTRO
    aba_de = ws_de.title

    def _extrair_versao(rotulo: str) -> str:
        return rotulo.split(":")[0].strip().split()[-1]

    vb = _extrair_versao(c["beta_u"].rotulo)
    vd = _extrair_versao(c["d_v"].rotulo)
    desc_beta_dv = f"{cfg.regiao.title()}/{' e '.join(f.setor for f in cfg.fases)}"

    if pond:
        _def_nome(wb, "peso_1", f"'Custo de Capital'!${VL}${pond['peso'][0]}")
        for i in range(2, n_fases + 1):
            _def_nome(wb, f"peso_{i}", f"'Custo de Capital'!${VL}${pond['peso'][i-1]}")
        f_beta_u = f"={VL}{pond['media_beta']}"
        f_dv = f"={VL}{pond['media_dv']}"
    else:
        ws_de["Z1"] = 1.0  # fase única: peso fixo (100%), sem bloco de ponderação visível
        _def_nome(wb, "peso_1", f"'{aba_de}'!$Z$1")
        f_beta_u = f"='{aba_beta}'!{col_beta}{r0b}"
        f_dv = f"='{aba_de}'!{col_dv}{r0d}"

    _linha("beta_u", f_beta_u, desc_beta_dv)
    _linha("d_v", f_dv, desc_beta_dv)

    # ---- T (entrada editável)
    rec_t = c["t"].recortes[0]
    _sheet_basico(wb, abas_usadas, rec_t.nome, rec_t)
    desc_t = _desc_param(c["t"].rotulo)
    r_t = _linha("t", c["t"].valor, desc_t, editable=True)
    _def_nome(wb, "T", f"'Custo de Capital'!${VL}${r_t}")

    # ---- beta_l
    _linha("beta_l", f"={_ref('beta_u')}*(1+(1-T)*{_ref('d_v')}/(1-{_ref('d_v')}))", "")

    # ---- Ke nominal
    _linha("ke_nominal", f"={_ref('rf')}+{_ref('erp')}*{_ref('beta_l')}+{_ref('risco_brasil')}", "",
           italico=True)

    # ---- Inflação US$
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
        cel = _cab(ws_tips, row, col_imp_idx, "Implícita")
        cel.alignment = CENTRO
        ws_tips.column_dimensions[col_imp].width = LARGURA_R
        for i in range(len(df_tips)):
            r = r0r + i
            r_treasury_row = r0t + i
            f = f"=(1+'{aba_treasury}'!{col_t}{r_treasury_row}/100)/(1+{col_r}{r}/100)-1"
            cel = ws_tips.cell(row=r, column=col_imp_idx, value=f)
            cel.number_format = FMT_NUM
            cel.border = BORDA
            cel.alignment = CENTRO
        aba_tips = ws_tips.title
        return f"=AVERAGE('{aba_tips}'!{col_imp}{r0r}:{col_imp}{r1r})"

    f_inf = _inflacao_formula()
    desc_inf = f"Implícita {_meses_txt(op.inflacao_us_janela)} ({c['inflacao_us'].janela['rotulo']})"
    _linha("inflacao_us", f_inf, desc_inf)

    # ---- Ke real (total)
    _linha("ke_real", f"=(1+{_ref('ke_nominal')})/(1+{_ref('inflacao_us')})-1", "", total=True)

    # ---- TLP
    f_tlp = _serie_media("tlp")
    desc_tlp = f"TLP {op.tlp_janela} ({c['tlp'].janela['rotulo']})"
    _linha("tlp", f_tlp, desc_tlp)

    # ---- Remuneração BNDES (entrada editável)
    rec_r = c["remuneracao_bndes"].recortes[0]
    _sheet_basico(wb, abas_usadas, rec_r.nome, rec_r)
    desc_rem = _desc_param(c["remuneracao_bndes"].rotulo)
    r_rem = _linha("remuneracao_bndes", c["remuneracao_bndes"].valor, desc_rem, editable=True)
    _def_nome(wb, "remuneracao", f"'Custo de Capital'!${VL}${r_rem}")

    # ---- Taxa de risco de crédito (entrada editável)
    desc_spread = cfg.spread_descricao or "Spread de crédito do projeto"
    r_spr = _linha("spread_credito", cfg.spread_credito, desc_spread, editable=True)
    _def_nome(wb, "spread", f"'Custo de Capital'!${VL}${r_spr}")

    # ---- IPCA (Focus)
    def _ipca_formula() -> str:
        comp = c["ipca"]
        rec = comp.recortes[0]
        ws = wb.create_sheet(_nome_aba(rec.nome, abas_usadas))
        row = _meta_recorte(ws, rec, 1)
        ws.cell(row=row, column=1, value="Projeção usada (Focus)").font = NEGRITO
        row += 1
        for j2, t2 in enumerate(("Ano", "IPCA (%)", "Projetado"), start=1):
            _cab(ws, row, j2, t2).alignment = CENTRO
        r0 = row + 1
        anos = comp.detalhes["anos"]
        for i, item in enumerate(anos):
            r = r0 + i
            cel_a = ws.cell(row=r, column=1, value=item["ano"])
            cel_a.border = BORDA
            cel_a.alignment = CENTRO
            if item["projetado"] or i == 0:
                cel = ws.cell(row=r, column=2, value=item["ipca"])
            else:
                cel = ws.cell(row=r, column=2, value=f"=B{r-1}")
            cel.number_format = "0.00"
            cel.border = BORDA
            cel.alignment = CENTRO
            cel_p = ws.cell(row=r, column=3, value="S" if item["projetado"] else "N")
            cel_p.border = BORDA
            cel_p.alignment = CENTRO
        r1 = r0 + len(anos) - 1
        for j2 in range(1, 4):
            ws.column_dimensions[get_column_letter(j2)].width = LARGURA_R
        row2 = r1 + 3
        ws.cell(row=row2 - 1, column=1, value="Recorte bruto do relatório Focus usado").font = NEGRITO
        _tabela(ws, rec.df, row2)
        aba = ws.title
        return f"=AVERAGE('{aba}'!B{r0}:B{r1})/100", aba, r0, r1

    f_ipca, aba_focus, r0_ipca, r1_ipca = _ipca_formula()
    _linha("ipca", f_ipca, f"Projeção Focus - {op.ipca_anos} anos")

    # ---- Kd nominal
    _linha("kd_nominal", f"=(1+{_ref('tlp')})*(1+remuneracao+spread)*(1+{_ref('ipca')})-1", "", italico=True)

    # ---- Kd real (total)
    _linha("kd_real", f"=(1+{_ref('kd_nominal')})/(1+{_ref('ipca')})-1", "", total=True)

    # ---- WACC
    _linha("wacc_real", f"={_ref('ke_real')}*(1-{_ref('d_v')})+{_ref('kd_real')}*{_ref('d_v')}*(1-T)", "",
           wacc="verde")
    _linha("wacc_nominal", f"={_ref('ke_nominal')}*(1-{_ref('d_v')})+{_ref('kd_nominal')}*{_ref('d_v')}*(1-T)",
           "", wacc=True)

    # ============================================================ Fonte (notas 1-10)
    cc.cell(row=29, column=CI, value="Fonte:").font = NEGRITO
    notas = []
    notas.append(f"(1) Federal Reserve (FRED GS10) - T-10 {_meses_txt(op.rf_janela)} ({c['rf'].janela['rotulo']}).")
    notas.append(f"(2) S&P 500 Total Return, Yahoo Finance - {desc_rm}.")
    notas.append(f"(3) Federal Reserve (FRED GS10) - T-10 {_meses_txt(op.rf_estrutural_janela)} "
                 f"({c['rf_estrutural'].janela['rotulo']}).")
    jv = c["risco_brasil"].janela
    notas.append("(4) Investing.com (CDS Brasil 10 anos) / B3 (Ibovespa) / Tesouro Nacional "
                 f"(Tesouro IPCA+ com Juros Semestrais {op.ntnb_vencimento[:4]}) - "
                 f"CDS {jv['cds']['rotulo']}; volatilidade {jv['volatilidade']['rotulo']}.")
    notas.append(None)  # nota (5): fórmula, tratada abaixo
    notas.append(f"(6) Federal Reserve (FRED GS10 e FII10) - Inflação implícita, a partir da rentabilidade "
                 f"da Treasury nominal de 10 anos e da Treasury real de 10 anos (TIPS); "
                 f"Implícita {_meses_txt(op.inflacao_us_janela)} ({c['inflacao_us'].janela['rotulo']}).")
    notas.append(f"(7) BCB, SGS 27572 (TLP divulgada pelo BNDES) - TLP {op.tlp_janela} "
                 f"({c['tlp'].janela['rotulo']}).")
    verificado = c["remuneracao_bndes"].detalhes.get("verificado_em", "")
    try:
        verificado = pd.Timestamp(verificado).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        pass
    notas.append(f"(8) BNDES - {_desc_param(c['remuneracao_bndes'].rotulo)} (verificado em {verificado}).")
    notas.append(f"(9) {cfg.spread_fonte or 'Spread de crédito informado pelo projeto.'}")
    rel = c["ipca"].detalhes.get("relatorio", "")
    try:
        rel_fmt = pd.Timestamp(rel).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        rel_fmt = str(rel)
    notas.append(f"(10) BCB - Pesquisa Focus (relatório de {rel_fmt}), mediana, média de {op.ipca_anos} anos.")

    # pontuação como na planilha: cada nota termina em ";" e a última em "."
    notas = [None if t is None else t.rstrip(" .;") + (";" if i < len(notas) - 1 else ".")
             for i, t in enumerate(notas)]

    def _nota(r: int, valor: str, n_caracteres: int) -> None:
        """Nota ocupa a largura da tabela (A:C), com quebra de linha e altura estimada."""
        cc.merge_cells(start_row=r, start_column=CI, end_row=r, end_column=CD)
        cel = cc.cell(row=r, column=CI, value=valor)
        cel.font = Font(size=9)
        cel.alignment = Alignment(wrap_text=True, vertical="top")
        linhas = max(1, -(-n_caracteres // 210))
        cc.row_dimensions[r].height = 12 * linhas

    for i, texto in enumerate(notas):
        if texto is not None:
            _nota(30 + i, _sanitizar(texto), len(texto))

    # ---- nota (5), fórmula (acompanha o bloco de ponderação)
    def _texto(expr: str) -> tuple:
        return ("ref", expr)

    pecas: list = [f"(5) Damodaran Online (atualizado em jan/{vb}, região {cfg.regiao.title()}): "]
    if n_fases == 1:
        f0 = cfg.fases[0]
        pecas += [f"utilizou-se o setor {cfg.regiao.title()} - {f0.setor}, com um beta desalavancado de ",
                  _texto(f'TEXT({_ref("beta_u")},"0,000")'), " e alavancagem (D/(D+E)) de ",
                  _texto(f'TEXT({_ref("d_v")},"0,00%")'), "."]
    else:
        pecas.append("Uma média de betas desalavancados foi utilizada para refletir as particularidades "
                      "do projeto.")
        for j2, f in enumerate(cfg.fases):
            rb, rd, rp = pond["beta"][j2], pond["dv"][j2], pond["peso"][j2]
            if j2 == 0:
                pecas += [f" Para a fase de {f.fase}, adotou-se o setor {cfg.regiao.title()} - {f.setor}, "
                          f"com um beta desalavancado de ", _texto(f'TEXT({VL}{rb},"0,000")'),
                          " e alavancagem (D/(D+E)) de ", _texto(f'TEXT({VL}{rd},"0,00%")'),
                          f", ponderado pela proporção do {f.base_peso} (", _texto(f'TEXT({VL}{rp},"0,00%")'), ")."]
            else:
                pecas += [f" Já para a fase de {f.fase}, utilizou-se o setor {cfg.regiao.title()} - {f.setor}, "
                          f"com um beta desalavancado de ", _texto(f'TEXT({VL}{rb},"0,000")'), " e alavancagem de ",
                          _texto(f'TEXT({VL}{rd},"0,00%")'),
                          f", ponderado pela proporção do {f.base_peso} (", _texto(f'TEXT({VL}{rp},"0,00%")'), ")."]

    def _monta_concat(pecas) -> str:
        partes = []
        for p in pecas:
            if isinstance(p, tuple):
                partes.append(p[1])
            else:
                partes.append('"' + _sanitizar(p).replace('"', '""') + '"')
        return "=" + "&".join(partes)

    if isinstance(pecas[-1], str):
        pecas[-1] = pecas[-1].rstrip(" .;") + ";"
    tamanho_5 = sum(len(p) if isinstance(p, str) else 6 for p in pecas)
    _nota(34, _monta_concat(pecas), tamanho_5)

    # ============================================================ bloco de ponderação
    if pond:
        cc.cell(row=41, column=CI, value="Ponderação dos betas e do D/(D+E) por fase").font = NEGRITO
        for j2, f in enumerate(cfg.fases):
            rb, rd, rp = pond["beta"][j2], pond["dv"][j2], pond["peso"][j2]
            cc.cell(row=rb, column=CI, value="Beta desalavancado").border = BORDA
            vb_cel = cc.cell(row=rb, column=CV, value=f"='{aba_beta}'!{col_beta}{r0b + j2}")
            vb_cel.alignment = CENTRO
            vb_cel.number_format = "0.000"
            vb_cel.border = BORDA
            cc.cell(row=rb, column=CD, value=_sanitizar(f.setor)).border = BORDA

            cc.cell(row=rd, column=CI, value="D/(D+E)").border = BORDA
            vd_cel = cc.cell(row=rd, column=CV, value=f"='{aba_de}'!{col_dv}{r0d + j2}")
            vd_cel.alignment = CENTRO
            vd_cel.number_format = FMT_PCT
            vd_cel.border = BORDA
            cc.cell(row=rd, column=CD, value=_sanitizar(f"{cfg.regiao.title()} ({vb})")).border = BORDA

            cc.cell(row=rp, column=CI, value="Peso").border = BORDA
            if n_fases == 2 and j2 == 1:
                vp_cel = cc.cell(row=rp, column=CV, value=f"=1-{VL}{pond['peso'][0]}")
            else:
                vp_cel = _entrada(cc, rp, CV, f.peso)
            vp_cel.alignment = CENTRO
            vp_cel.number_format = FMT_PCT
            vp_cel.border = BORDA
            cc.cell(row=rp, column=CD, value=_sanitizar(f"Proporção do {f.base_peso}")).border = BORDA

        if pond["soma"]:
            r = pond["soma"]
            cc.cell(row=r, column=CI, value="Soma dos pesos (deve ser 100%)").font = NEGRITO
            soma_cel = cc.cell(row=r, column=CV, value="=" + "+".join(f"{VL}{p}" for p in pond["peso"]))
            soma_cel.alignment = CENTRO
            soma_cel.number_format = FMT_PCT

        prod_beta = "+".join(f"{VL}{b}*{VL}{p}" for b, p in zip(pond["beta"], pond["peso"]))
        prod_dv = "+".join(f"{VL}{d}*{VL}{p}" for d, p in zip(pond["dv"], pond["peso"]))
        rmb, rmd = pond["media_beta"], pond["media_dv"]
        cc.cell(row=rmb, column=CI, value=_sanitizar(f"{cfg.regiao.title()} - Média Setores")).font = NEGRITO
        c_mb = cc.cell(row=rmb, column=CV, value=f"={prod_beta}")
        c_mb.alignment = CENTRO
        c_mb.number_format = "0.000"
        c_mb.font = NEGRITO
        cc.cell(row=rmb, column=CD, value=_sanitizar(f"{cfg.regiao.title()} - Média Setores"))
        cc.cell(row=rmd, column=CI, value=_sanitizar(f"{cfg.regiao.title()} - Média Setores")).font = NEGRITO
        c_md = cc.cell(row=rmd, column=CV, value=f"={prod_dv}")
        c_md.alignment = CENTRO
        c_md.number_format = FMT_PCT
        c_md.font = NEGRITO
        cc.cell(row=rmd, column=CD, value=_sanitizar(f"{cfg.regiao.title()} - Média Setores"))

    # ============================================================ Parâmetros
    par = wb.create_sheet("Parâmetros")
    par.cell(row=1, column=1, value="Parâmetros").font = TITULO
    linha = 3
    corte = pd.Period(resultado.corte, "M")
    for rot, val in (
        ("Projeto:", cfg.projeto), ("Data-base:", _mes_ano(cfg.data_base)),
        ("Mês de corte:", f"{corte.month:02d}/{corte.year}"),
        ("Modo:", "modo1_santa_maria"), ("Região Damodaran:", cfg.regiao),
    ):
        par.cell(row=linha, column=1, value=rot).font = NEGRITO
        par.cell(row=linha, column=2, value=_sanitizar(val)).alignment = ESQUERDA
        linha += 1
    par.cell(row=linha, column=1, value="Opções de janela:").font = NEGRITO
    linha += 1
    for rot, val in (
        ("Rf:", op.rf_janela), ("Rf estrutural:", op.rf_estrutural_janela), ("Rm (método):", op.rm_metodo),
        ("Rm (janela):", op.rm_janela), ("CDS 10a:", op.cds_janela), ("Volatilidade:", op.vol_janela),
        ("NTN-B (vencimento):", op.ntnb_vencimento), ("Inflação US$:", op.inflacao_us_janela),
        ("TLP:", op.tlp_janela), ("IPCA (anos Focus):", op.ipca_anos),
    ):
        par.cell(row=linha, column=1, value=f"   {rot}")
        par.cell(row=linha, column=2, value=val).alignment = ESQUERDA
        linha += 1
    par.column_dimensions["A"].width = 30
    par.column_dimensions["B"].width = 24

    # ============================================================ Registro
    reg = wb.create_sheet("Registro")
    reg.cell(row=1, column=1, value="Registro").font = TITULO
    r = 3
    dados = resultado.to_dict()
    reg.cell(row=r, column=1, value="Gerado em:").font = NEGRITO
    from datetime import datetime, timezone
    reg.cell(row=r, column=2, value=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    r += 1
    reg.cell(row=r, column=1, value="Versão do código:").font = NEGRITO
    reg.cell(row=r, column=2, value=_sanitizar(str(versao_codigo())))
    r += 2
    reg.cell(row=r, column=1, value="Configuração completa:").font = NEGRITO
    r += 1
    for k, v in dados["config"].items():
        reg.cell(row=r, column=1, value=f"   {k}")
        reg.cell(row=r, column=2, value=_sanitizar(str(v)))
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
            reg.cell(row=r, column=2, value=rc.versao or "-").border = BORDA
            reg.cell(row=r, column=3, value=rc.sha256_csv or "-").border = BORDA
            r += 1
    r += 1
    reg.cell(row=r, column=1, value="Conferência (valor Python x fórmula da aba Custo de Capital):").font = NEGRITO
    r += 1
    _cab(reg, r, 1, "Componente", 22)
    _cab(reg, r, 2, "Valor (Python)", 16)
    _cab(reg, r, 3, "Fórmula (Custo de Capital)", 16)
    _cab(reg, r, 4, "Diferença", 14)
    r += 1
    for cid, comp in c.items():
        reg.cell(row=r, column=1, value=comp.nome).border = BORDA
        cp = reg.cell(row=r, column=2, value=comp.valor)
        cp.number_format = FMT_PCT
        cp.border = BORDA
        cf = reg.cell(row=r, column=3, value=f"='Custo de Capital'!{VL}{row_of[cid]}")
        cf.number_format = FMT_PCT
        cf.border = BORDA
        cd = reg.cell(row=r, column=4, value=f"=B{r}-C{r}")
        cd.number_format = "0.00000000%"
        cd.border = BORDA
        r += 1
    reg.column_dimensions["A"].width = 30
    reg.column_dimensions["B"].width = 40

    # ============================================================ Capa
    capa = wb.create_sheet("Capa")
    capa.column_dimensions["A"].width = LARGURA_MARGEM
    capa.column_dimensions["B"].width = 22
    capa.column_dimensions["C"].width = 60
    capa.cell(row=3, column=2, value="Custo Médio Ponderado de Capital (WACC)").font = Font(bold=True, size=16)
    for i, (rot, val) in enumerate((
        ("Projeto:", cfg.projeto),
        ("Data-base:", _mes_ano(cfg.data_base)),
        ("Data de criação:", datetime.now().strftime("%d/%m/%Y %H:%M")),
    )):
        capa.cell(row=6 + i, column=2, value=rot).font = NEGRITO
        capa.cell(row=6 + i, column=3, value=_sanitizar(val)).alignment = ESQUERDA

    # ============================================================ ordem final e ajustes gerais
    ordem_abas = (["Capa", "Custo de Capital", "Parâmetros"] + [n for n in wb.sheetnames if n.startswith("R_")]
                  + ["Registro"])
    wb._sheets = [wb[n] for n in ordem_abas]
    wb.active = 0

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = False
        ws.freeze_panes = None

    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)
    return caminho
