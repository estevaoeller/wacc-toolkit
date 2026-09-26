"""Camada de serviços: tudo o que a interface (e a CLI) precisa, sem lógica na tela.

A interface Streamlit só chama estas funções. Nenhuma regra de cálculo, de validação ou
de gravação deve ficar na camada de apresentação.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from .calc.fontes import Bases
from .calc.modo1 import ConfigProjeto, Fase, Opcoes, ResultadoWACC, calcular
from .calc.registro import gravar_registro
from .collector import Contexto, ResultadoColeta, executar
from .config import resolver_bases_dir
from .registry import carregar_todos
from .saida.rotulos import KD_ITENS, KE_ITENS, ROTULOS, WACC_ITENS
from .saida.rotulos import descricoes as _descricoes_custo_de_capital
from .series import SerieSpec
from .storage import Repositorio

# séries opcionais: variantes de uma fonte manual que podem legitimamente não ter dados
# (ex.: o usuário só baixou o CSV mensal do Investing, não o diário). Sem dados nelas não é
# uma falha a ser alertada, ao contrário das demais séries.
SERIES_OPCIONAIS: set[str] = {
    "investing_cds10_brasil", "investing_cds5_brasil", "investing_ibov_mensal", "investing_cds5_brasil_mensal",
}

# ------------------------------------------------------------------ catálogo de opções (modo 1)
# valor gravado na configuração -> rótulo exibido
CATALOGO_OPCOES: dict[str, dict[str, str]] = {
    "rf_janela": {"12m": "12 meses", "10a": "10 anos", "26a": "26 anos", "28a": "28 anos", "30a": "30 anos"},
    "rf_estrutural_janela": {"30a": "30 anos", "10a": "10 anos", "26a": "26 anos", "28a": "28 anos"},
    "rm_metodo": {"ln_mensal": "Ln mensal, (1 + média)^12 − 1", "anual": "Média dos retornos anuais"},
    "rm_janela": {"desde:1995-01": "Desde jan/1995", "26a": "26 anos", "30a": "30 anos"},
    "cds_janela": {"120m": "10 anos", "12m": "12 meses"},
    "vol_janela": {"60m": "5 anos"},
    "inflacao_us_janela": {"12m": "12 meses", "120m": "10 anos"},
    "tlp_janela": {"12m": "12 meses", "24m": "24 meses", "1m": "Último mês"},
}
ROTULOS_OPCOES = {
    "rf_janela": "Rf: janela do T-10", "rf_estrutural_janela": "R'f estrutural: janela do T-10",
    "rm_metodo": "Rm: método", "rm_janela": "Rm: janela do S&P 500 TR", "cds_janela": "Risco Brasil: janela do CDS 10a",
    "vol_janela": "Risco Brasil: janela das volatilidades", "inflacao_us_janela": "Inflação US$: janela",
    "tlp_janela": "TLP: janela", "ntnb_vencimento": "NTN-B de referência (vencimento)", "ipca_anos": "IPCA Focus: anos",
}


# ------------------------------------------------------------------ ambiente (pastas)
@dataclass(frozen=True)
class Ambiente:
    bases: Path
    projetos: Path
    calculos: Path

    @property
    def repo(self) -> Repositorio:
        return Repositorio(self.bases)


def ambiente(bases_dir: str | Path | None = None) -> Ambiente:
    """Pastas do projeto: as bases e, ao lado delas, ``Projetos/`` e ``Calculos/``."""
    b = resolver_bases_dir(bases_dir)
    amb = Ambiente(b, b.parent / "Projetos", b.parent / "Calculos")
    amb.projetos.mkdir(parents=True, exist_ok=True)
    amb.calculos.mkdir(parents=True, exist_ok=True)
    return amb


# ------------------------------------------------------------------ bases
def fontes() -> list[dict]:
    return [{"fonte": n, "descricao": c.descricao, "manual": c.manual, "series": [s.id for s in c.series]}
            for n, c in carregar_todos().items()]


def status_bases(amb: Ambiente) -> pd.DataFrame:
    """Uma linha por série: fonte, período, linhas, última atualização, nº de avisos, versões."""
    repo = amb.repo
    linhas = []
    for nome, cls in carregar_todos().items():
        for s in cls.series:
            base = {"fonte": nome, "serie": s.id, "descricao": s.descricao, "frequencia": s.frequencia,
                    "manual": cls.manual}
            if s.versionada:
                vs = repo.versoes(s)
                m = repo.meta_serie(s, vs[-1]) if vs else None
                linhas.append({**base, "inicio": None, "fim": None, "linhas": m["linhas"] if m else 0,
                               "atualizado_em": m["atualizado_em"][:10] if m else None,
                               "avisos": len(m["avisos"]) if m else 0, "versoes": ", ".join(vs)})
            else:
                m = repo.meta_serie(s)
                linhas.append({**base, "inicio": m["inicio"] if m else None, "fim": m["fim"] if m else None,
                               "linhas": m["linhas"] if m else 0,
                               "atualizado_em": m["atualizado_em"][:10] if m else None,
                               "avisos": len(m["avisos"]) if m else 0, "versoes": ""})
    return pd.DataFrame(linhas)


def ultimas_falhas(amb: Ambiente, n: int = 10) -> list[dict]:
    return amb.repo.eventos("falha")[-n:]


def atualizar(amb: Ambiente, fontes_alvo: list[str] | None = None) -> list[ResultadoColeta]:
    coletores = carregar_todos()
    alvo = fontes_alvo or [n for n, c in coletores.items() if not c.manual]
    ctx = Contexto(amb.repo)
    return [executar(coletores[f](), ctx) for f in alvo]


def importar_arquivos(amb: Ambiente, fonte: str, arquivos: list[tuple[str, bytes]]) -> ResultadoColeta:
    """Grava arquivos enviados (nome, conteúdo) em entrada/<fonte>/importado_<data>/ e atualiza a fonte."""
    coletores = carregar_todos()
    if fonte not in coletores or not coletores[fonte].manual:
        raise ValueError(f"'{fonte}' não é uma fonte manual")
    destino = amb.repo.dir_entrada(fonte) / f"importado_{date.today():%Y-%m-%d}"
    destino.mkdir(parents=True, exist_ok=True)
    for nome, conteudo in arquivos:
        (destino / Path(nome).name).write_bytes(conteudo)
    return executar(coletores[fonte](), Contexto(amb.repo))


def importar_caminhos(amb: Ambiente, fonte: str, caminhos: list[str | Path]) -> ResultadoColeta:
    """Como :func:`importar_arquivos`, a partir de arquivos ou pastas no disco (originais intactos)."""
    arquivos = []
    for c in map(Path, caminhos):
        itens = sorted(p for p in c.iterdir() if p.suffix.lower() in (".csv", ".toml")) if c.is_dir() else [c]
        arquivos += [(p.name, p.read_bytes()) for p in itens]
    if not arquivos:
        raise FileNotFoundError("nenhum arquivo .csv/.toml encontrado")
    return importar_arquivos(amb, fonte, arquivos)


# ------------------------------------------------------------------ consulta
def _spec(serie: str) -> SerieSpec:
    for c in carregar_todos().values():
        for s in c.series:
            if s.id == serie:
                return s
    raise KeyError(serie)


def ler_serie(amb: Ambiente, serie: str, versao: str | None = None) -> tuple[pd.DataFrame, dict]:
    spec = _spec(serie)
    df = amb.repo.ler_serie(spec, versao)
    if df is None:
        raise FileNotFoundError(f"série {serie} sem dados")
    return df, (amb.repo.meta_serie(spec, versao) or {})


def versoes(amb: Ambiente, serie: str) -> list[str]:
    return amb.repo.versoes(_spec(serie))


def meta_serie(amb: Ambiente, serie: str, versao: str | None = None) -> dict:
    """Só os metadados (rápido: não lê o CSV da série), úteis como chave de cache - ex.:
    ``(serie, versao, meta["sha256_csv"])`` identifica de forma estável um conteúdo já lido."""
    return amb.repo.meta_serie(_spec(serie), versao) or {}


def setores_damodaran(amb: Ambiente, regiao: str, data_base: date) -> list[str]:
    serie = "damodaran_beta_global" if regiao == "global" else "damodaran_beta_emerg"
    b = Bases(amb.repo)
    df, _ = b.ler(serie, b.versao_vigente(serie, data_base))
    return sorted(df["industry_name"].dropna().astype(str).unique())


def _fonte_bndes_legivel(fonte: str) -> str:
    """Só a parte legível da fonte (sem o parenteses de detalhe nem o prefixo 'BNDES ')."""
    texto = fonte.split(" (")[0].strip()
    if texto.startswith("BNDES "):
        texto = texto[len("BNDES "):]
    return texto


def linhas_bndes(amb: Ambiente) -> dict[str, str]:
    """id do parâmetro -> descrição legível (sem o id técnico), para as linhas de remuneração BNDES."""
    df, _ = ler_serie(amb, "parametros_manuais")
    df = df[df["parametro"].str.startswith("bndes_rem")]
    return {r.parametro: f"{_fonte_bndes_legivel(r.fonte)} ({formatar_numero_pt(r.valor, 2)}% a.a.)"
            for r in df.itertuples()}


# ------------------------------------------------------------------ projetos (configuração)
def _toml_valor(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, date):
        return v.isoformat()
    return json.dumps(str(v), ensure_ascii=False)


def config_para_toml(cfg: ConfigProjeto) -> str:
    linhas = [f"projeto = {_toml_valor(cfg.projeto)}",
              f"data_base = {_toml_valor(cfg.data_base)}          # mês/ano (dia 1º)"]
    if cfg.focus_relatorio:
        linhas.append(f"focus_relatorio = {_toml_valor(cfg.focus_relatorio)}   # último relatório Focus considerado")
    if cfg.notas:
        linhas.append(f"notas = {_toml_valor(cfg.notas)}")
    linhas += ["", "[beta]", f"regiao = {_toml_valor(cfg.regiao)}", "fases = ["]
    for f in cfg.fases:
        campos = ", ".join(f"{k} = {_toml_valor(v)}" for k, v in asdict(f).items() if v != "")
        linhas.append(f"  {{ {campos} }},")
    linhas += ["]", "", "[kd]", f"linha_bndes = {_toml_valor(cfg.linha_bndes)}",
               f"spread_credito = {_toml_valor(cfg.spread_credito)}"]
    if cfg.spread_descricao:
        linhas.append(f"spread_descricao = {_toml_valor(cfg.spread_descricao)}")
    if cfg.spread_fonte:
        linhas.append(f"spread_fonte = {_toml_valor(cfg.spread_fonte)}")
    linhas += ["", "[opcoes]"] + [f"{k} = {_toml_valor(v)}" for k, v in asdict(cfg.opcoes).items()]
    # escolhas Variável × Janela por grupo (prevalecem sobre [opcoes] na leitura)
    for grupo, esc in cfg.variaveis.items():
        linhas += ["", f"[variaveis.{grupo}]", f"variavel = {_toml_valor(esc.variavel)}"]
        linhas += [f"{k} = {_toml_valor(v)}" for k, v in {**esc.janelas, **esc.params}.items()]
    return "\n".join(linhas) + "\n"


def listar_projetos(amb: Ambiente) -> list[Path]:
    return sorted(p for p in amb.projetos.glob("*.toml") if not p.name.endswith(".conferencia.toml"))


def carregar_projeto(caminho: str | Path) -> ConfigProjeto:
    return ConfigProjeto.de_toml(caminho)


def salvar_projeto(amb: Ambiente, cfg: ConfigProjeto, nome_arquivo: str, sobrescrever: bool = False) -> Path:
    nome = Path(nome_arquivo).stem + ".toml"
    caminho = amb.projetos / nome
    if caminho.exists() and not sobrescrever:
        raise FileExistsError(f"{caminho.name} já existe")
    texto = config_para_toml(cfg)
    ConfigProjeto.de_toml_texto(texto)  # valida antes de gravar
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def nova_config(**kw) -> ConfigProjeto:
    """Monta uma configuração a partir de campos simples (usado pelo formulário)."""
    fases = [f if isinstance(f, Fase) else Fase(**f) for f in kw.pop("fases")]
    opcoes = kw.pop("opcoes", None)
    op = opcoes if isinstance(opcoes, Opcoes) else Opcoes(**(opcoes or {}))
    return ConfigProjeto(fases=fases, opcoes=op, **kw)


# ------------------------------------------------------------------ cálculo e histórico
@dataclass
class Calculo:
    resultado: ResultadoWACC
    registro: Path
    excel: Path | None


def calcular_previa(amb: Ambiente, cfg: ConfigProjeto) -> ResultadoWACC:
    """Só calcula (``calc.modo1.calcular``), sem gravar registro nem Excel: para prévias que o
    usuário recalcula à vontade antes de decidir gerar a versão definitiva. O valor é idêntico
    ao que :func:`calcular_projeto` produziria para a mesma configuração e as mesmas bases."""
    return calcular(cfg, Bases(amb.repo))


def calcular_projeto(amb: Ambiente, cfg: ConfigProjeto, excel: bool = True) -> Calculo:
    resultado = calcular(cfg, Bases(amb.repo))
    registro = gravar_registro(resultado, amb.calculos)
    xlsx = None
    if excel:
        from .saida.excel import exportar_excel
        xlsx = exportar_excel(resultado, registro.with_suffix(".xlsx"))
    return Calculo(resultado, registro, xlsx)


def tabela_resultado(resultado: ResultadoWACC) -> pd.DataFrame:
    return pd.DataFrame([{"id": c.id, "item": c.nome, "valor": c.valor, "descricao": c.rotulo}
                         for c in resultado.componentes.values()])


# ------------------------------------------------------------------ formatação pt-BR
# id do componente -> ("pct" | "num", casas decimais); os demais são "pct" com 2 casas
_FORMATOS_COMPONENTE: dict[str, tuple[str, int]] = {
    "beta_u": ("num", 2), "beta_l": ("num", 3), "d_v": ("pct", 1), "t": ("pct", 1),
}


def formatar_numero_pt(valor: float | None, casas: int = 2) -> str:
    """Número com vírgula decimal (e ponto como separador de milhar), ex.: 1234.5 -> '1.234,50'."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def formatar_percentual_pt(valor: float | None, casas: int = 2) -> str:
    """Fração decimal (0,1058 = 10,58%) formatada como percentual em pt-BR."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return f"{formatar_numero_pt(valor * 100, casas)}%"


def formatar_valor_componente(id_componente: str, valor: float) -> str:
    """Formata o valor de um componente do WACC (fração decimal) segundo a convenção da
    tabela Custo de Capital: percentual com 2 casas, exceto beta_u/beta_l (número) e d_v/t
    (percentual com 1 casa)."""
    tipo, casas = _FORMATOS_COMPONENTE.get(id_componente, ("pct", 2))
    return formatar_numero_pt(valor, casas) if tipo == "num" else formatar_percentual_pt(valor, casas)


def _montar_tabela_custo_de_capital(valores: dict[str, float], descricoes_map: dict[str, str]) -> pd.DataFrame:
    linhas = [
        {"secao": secao, "item": ROTULOS[cid], "valor": formatar_valor_componente(cid, valores[cid]),
         "descricao": descricoes_map.get(cid, "")}
        for secao, ids in (("KE", KE_ITENS), ("KD", KD_ITENS), ("WACC", WACC_ITENS))
        for cid in ids
    ]
    return pd.DataFrame(linhas, columns=["secao", "item", "valor", "descricao"])


def tabela_custo_de_capital(resultado: ResultadoWACC) -> pd.DataFrame:
    """Tabela Seção | Item | Valor | Descrição (ordem KE/KD/WACC), com os mesmos nomes de item e
    descrições da aba "Custo de Capital" do Excel (:mod:`wacc_toolkit.saida.rotulos`)."""
    valores = {k: comp.valor for k, comp in resultado.componentes.items()}
    return _montar_tabela_custo_de_capital(valores, _descricoes_custo_de_capital(resultado))


def tabela_custo_de_capital_de_registro(dados: dict) -> pd.DataFrame:
    """Como :func:`tabela_custo_de_capital`, a partir do dict de um registro salvo (``ler_calculo``),
    sem precisar recalcular nem acessar as bases."""
    valores = {k: v["valor"] for k, v in dados["componentes"].items()}
    return _montar_tabela_custo_de_capital(valores, _descricoes_custo_de_capital(dados))


def listar_calculos(amb: Ambiente) -> pd.DataFrame:
    linhas = []
    for p in sorted(amb.calculos.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        comp = d.get("componentes", {})
        linhas.append({
            "arquivo": p.name, "projeto": d.get("config", {}).get("projeto"),
            "data_base": d.get("config", {}).get("data_base"), "gerado_em": d.get("gerado_em"),
            "wacc_real": comp.get("wacc_real", {}).get("valor"), "wacc_nominal": comp.get("wacc_nominal", {}).get("valor"),
            "excel": p.with_suffix(".xlsx").name if p.with_suffix(".xlsx").exists() else None,
        })
    return pd.DataFrame(linhas)


def ultimos_calculos_por_projeto(amb: Ambiente) -> pd.DataFrame:
    """Uma linha por projeto: o cálculo mais recente (maior ``gerado_em``)."""
    lista = listar_calculos(amb)
    if lista.empty:
        return lista
    return lista.sort_values("gerado_em").groupby("projeto", as_index=False).last()


def ler_calculo(amb: Ambiente, arquivo: str) -> dict:
    return json.loads((amb.calculos / Path(arquivo).name).read_text(encoding="utf-8"))


def comparar_calculos(amb: Ambiente, arquivo_a: str, arquivo_b: str) -> pd.DataFrame:
    """Componente a componente: valor em A, valor em B e diferença em pontos-base."""
    a, b = ler_calculo(amb, arquivo_a)["componentes"], ler_calculo(amb, arquivo_b)["componentes"]
    linhas = []
    for k in a:
        if k not in b:
            continue
        va, vb = a[k]["valor"], b[k]["valor"]
        linhas.append({"id": k, "item": a[k]["nome"], "a": va, "b": vb, "dif_bp": (vb - va) * 1e4,
                       "descricao_a": a[k].get("rotulo", ""), "descricao_b": b[k].get("rotulo", "")})
    return pd.DataFrame(linhas)


def copiar_excel(amb: Ambiente, arquivo_json: str, destino: str | Path) -> Path:
    origem = (amb.calculos / Path(arquivo_json).name).with_suffix(".xlsx")
    return Path(shutil.copy2(origem, destino))


# ------------------------------------------------------------------ painel de indicadores
def _serie_coluna(amb: Ambiente, serie: str, coluna: str) -> pd.DataFrame:
    df, _ = ler_serie(amb, serie)
    return df[["data", coluna]].rename(columns={coluna: "valor"})


def _serie_inflacao_us(amb: Ambiente) -> pd.DataFrame:
    dn, _ = ler_serie(amb, "fred_gs10")
    dr, _ = ler_serie(amb, "fred_fii10")
    m = dn.rename(columns={"valor": "nominal"})[["data", "nominal"]].merge(
        dr.rename(columns={"valor": "real"})[["data", "real"]], on="data", how="inner")
    m["valor"] = ((1 + m["nominal"] / 100) / (1 + m["real"] / 100) - 1) * 100
    return m[["data", "valor"]]


def _serie_ntnb(amb: Ambiente, vencimento: str = "2035-05-15") -> pd.DataFrame:
    from .calc.modo1 import NTNB_TITULO

    df, _ = ler_serie(amb, "tesouro_td_taxas")
    d = df[(df["titulo"] == NTNB_TITULO) & (df["vencimento"].astype(str) == vencimento)]
    return d[["data", "taxa_compra"]].rename(columns={"taxa_compra": "valor"})


def _serie_ipca_focus(amb: Ambiente, ano: int) -> pd.DataFrame:
    df, _ = ler_serie(amb, "bcb_focus_ipca_anual")
    d = df[(df["base_calculo"] == 0) & (df["ano_referencia"] == ano)]
    return d[["data", "mediana"]].rename(columns={"mediana": "valor"})


def _indicador(nome: str, unidade: str, fonte: str, tipo_variacao: str, fator_pb: float, meses: int, obter) -> dict:
    """``tipo_variacao``: "pb" (a variação de 12 meses é dada em pontos-base, valor já em
    pontos percentuais × ``fator_pb``) ou "pct" (variação percentual, para índices)."""
    item: dict = {
        "nome": nome, "unidade": unidade, "fonte": fonte, "tipo_variacao": tipo_variacao, "status": "ok",
        "ultimo_valor": None, "data_ultimo": None, "valor_12m_atras": None, "variacao": None,
        "serie": pd.DataFrame(columns=["data", "valor"]),
    }
    try:
        df = obter()
    except (FileNotFoundError, KeyError, ValueError):
        item["status"] = "sem_dados"
        return item
    df = df.dropna(subset=["valor"])
    if df.empty:
        item["status"] = "sem_dados"
        return item
    df = df.assign(_data=pd.to_datetime(df["data"])).sort_values("_data")
    data_ultimo = df["_data"].iloc[-1]
    ultimo_valor = float(df["valor"].iloc[-1])
    limite_12m = data_ultimo - pd.DateOffset(months=12)
    anteriores = df[df["_data"] <= limite_12m]
    valor_12m = float(anteriores["valor"].iloc[-1]) if not anteriores.empty else None
    variacao = None
    if valor_12m is not None:
        variacao = (ultimo_valor - valor_12m) * fator_pb if tipo_variacao == "pb" else \
            ((ultimo_valor / valor_12m - 1) * 100 if valor_12m else None)
    limite_serie = data_ultimo - pd.DateOffset(months=meses)
    serie = df[df["_data"] >= limite_serie][["data", "valor"]].reset_index(drop=True)
    item.update(ultimo_valor=ultimo_valor, data_ultimo=str(pd.Timestamp(data_ultimo).date()),
               valor_12m_atras=valor_12m, variacao=variacao, serie=serie)
    return item


def indicadores_painel(amb: Ambiente, meses: int = 24) -> list[dict]:
    """As variáveis mais relevantes para acompanhamento, cada uma com o último valor, o valor de
    12 meses atrás, a variação (pontos-base para taxas, percentual para índices) e a série dos
    últimos ``meses`` meses. Uma série ausente não interrompe o painel: o indicador correspondente
    vem com ``status="sem_dados"``."""
    ano_atual = date.today().year
    especificacoes = [
        ("Treasury 10 anos", "% a.a.", "FRED (GS10)", "pb", 100.0, lambda: _serie_coluna(amb, "fred_gs10", "valor")),
        ("Inflação implícita EUA", "% a.a.", "FRED (GS10 e FII10)", "pb", 100.0, lambda: _serie_inflacao_us(amb)),
        ("CDS Brasil 10 anos", "p.b.", "Investing.com", "pb", 1.0,
         lambda: _serie_coluna(amb, "investing_cds10_brasil_mensal", "ultimo")),
        ("Ibovespa", "pontos", "B3", "pct", 0.0, lambda: _serie_coluna(amb, "b3_ibov", "fechamento")),
        ("S&P 500 Total Return", "pontos", "Yahoo Finance", "pct", 0.0,
         lambda: _serie_coluna(amb, "yahoo_sp500tr", "fechamento")),
        ("NTN-B 2035", "% a.a.", "Tesouro Transparente", "pb", 100.0, lambda: _serie_ntnb(amb)),
        ("TLP", "% a.a.", "BCB (SGS 27572)", "pb", 100.0, lambda: _serie_coluna(amb, "bcb_tlp", "valor")),
        (f"IPCA Focus {ano_atual}", "% a.a.", "BCB (Focus)", "pb", 100.0,
         lambda: _serie_ipca_focus(amb, ano_atual)),
        (f"IPCA Focus {ano_atual + 1}", "% a.a.", "BCB (Focus)", "pb", 100.0,
         lambda: _serie_ipca_focus(amb, ano_atual + 1)),
    ]
    return [_indicador(nome, unidade, fonte, tipo, fator, meses, obter)
            for nome, unidade, fonte, tipo, fator, obter in especificacoes]
