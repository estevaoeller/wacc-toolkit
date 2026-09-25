"""Linha de comando: ``wacc atualizar``, ``wacc status``, ``wacc fontes``."""

from __future__ import annotations

import argparse
import logging
import sys

from .collector import Contexto, executar
from .config import resolver_bases_dir
from .registry import carregar_todos
from .storage import Repositorio


def _configurar_log(repo: Repositorio, verboso: bool) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    raiz = logging.getLogger("wacc_toolkit")
    raiz.setLevel(logging.DEBUG if verboso else logging.INFO)
    arq = logging.FileHandler(repo.dir_logs / "atualizacao.log", encoding="utf-8")
    arq.setFormatter(fmt)
    tela = logging.StreamHandler(sys.stdout)
    tela.setFormatter(fmt)
    raiz.handlers[:] = [arq, tela]


def cmd_fontes(_args) -> int:
    for nome, cls in carregar_todos().items():
        tipo = "manual" if cls.manual else "auto"
        print(f"{nome:<14} {tipo:<6} {cls.descricao}")
        for s in cls.series:
            print(f"    - {s.id:<32} {s.frequencia}  {s.unidade}")
    return 0


def cmd_atualizar(args) -> int:
    repo = Repositorio(resolver_bases_dir(args.bases))
    _configurar_log(repo, args.verboso)
    coletores = carregar_todos()
    alvo = args.fonte or list(coletores)
    desconhecidas = [f for f in alvo if f not in coletores]
    if desconhecidas:
        print(f"Fontes desconhecidas: {desconhecidas}. Use 'wacc fontes'.", file=sys.stderr)
        return 2
    ctx = Contexto(repo)
    log = logging.getLogger("wacc_toolkit")
    falhas = 0
    for nome in alvo:
        log.info("== %s ==", nome)
        r = executar(coletores[nome](), ctx, reprocessar=args.reprocessar)
        if r.status in ("falhou", "parcial"):
            falhas += 1
        log.info("%s: %s (brutos novos: %d)%s", nome, r.status, r.brutos_novos, f" — {r.erro}" if r.erro else "")
        for s in r.series:
            v = f" v{s.versao}" if s.versao else ""
            log.info("   %s%s: %s, %d linhas, fim %s", s.serie, v, s.status, s.linhas, s.fim)
            for p in s.problemas:
                log.info("      %s", p)
    return 1 if falhas else 0


def cmd_status(args) -> int:
    repo = Repositorio(resolver_bases_dir(args.bases))
    for nome, cls in carregar_todos().items():
        for s in cls.series:
            if s.versionada:
                vs = repo.versoes(s)
                print(f"{s.id:<34} versões: {', '.join(vs) if vs else '—'}")
            else:
                m = repo.meta_serie(s)
                if m:
                    aviso = f"  ({len(m['avisos'])} avisos)" if m.get("avisos") else ""
                    print(f"{s.id:<34} {m['inicio']} → {m['fim']}  {m['linhas']:>7} linhas  "
                          f"atualizada {m['atualizado_em'][:10]}{aviso}")
                else:
                    print(f"{s.id:<34} — sem dados")
    falhas = [e for e in repo.eventos("falha")][-5:]
    if falhas:
        print("\nÚltimas falhas:")
        for e in falhas:
            print(f"  {e['registrado_em']} {e['fonte']} [{e['etapa']}] {e['erro'][:120]}")
    return 0


def cmd_calcular(args) -> int:
    from pathlib import Path

    from .calc.fontes import Bases
    from .calc.modo1 import ConfigProjeto, calcular
    from .calc.registro import conferir, gravar_registro

    bases_dir = resolver_bases_dir(args.bases)
    cfg = ConfigProjeto.de_toml(args.projeto)
    resultado = calcular(cfg, Bases(Repositorio(bases_dir)))
    print(f"{cfg.projeto} — data-base {cfg.data_base} (mês de corte {resultado.corte})\n")
    for c in resultado.componentes.values():
        print(f"  {c.nome:<36} {c.valor * 100:9.4f}%   {c.rotulo}")
    saida = Path(args.saida) if args.saida else bases_dir.parent / "Calculos"
    caminho = gravar_registro(resultado, saida)
    print(f"\nRegistro: {caminho}")
    if args.excel:
        from .saida.excel import exportar_excel
        xlsx = exportar_excel(resultado, caminho.with_suffix(".xlsx"))
        print(f"Excel:    {xlsx}")
    if args.conferir:
        linhas = conferir(resultado, args.conferir)
        print(f"\nConferência contra {args.conferir}:")
        for ln in linhas:
            esp = "   —    " if ln.esperado is None else f"{ln.esperado * 100:8.4f}%"
            dif = "" if ln.dif_bp is None else f"{ln.dif_bp:+7.2f} p.b."
            print(f"  {ln.id:<18} {ln.calculado * 100:8.4f}%  {esp}  {dif:>12}  {ln.status:<14} {ln.explicacao}")
        if any(ln.status == "DIVERGE" for ln in linhas):
            print("\nHá divergências não explicadas.")
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    for fluxo in (sys.stdout, sys.stderr):  # console do Windows (cp1252) não tem "→", acentos etc.
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="wacc", description="Atualizador das bases de WACC")
    p.add_argument("--bases", help="diretório das bases (sobrepõe WACC_BASES_DIR / wacc.local.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("atualizar", help="coleta e atualiza as bases")
    a.add_argument("--fonte", nargs="*", help="fontes específicas (padrão: todas)")
    a.add_argument("--reprocessar", action="store_true", help="reinterpreta mesmo sem bruto novo")
    a.add_argument("-v", "--verboso", action="store_true")
    a.set_defaults(func=cmd_atualizar)
    sub.add_parser("status", help="situação de cada série").set_defaults(func=cmd_status)
    sub.add_parser("fontes", help="lista fontes e séries").set_defaults(func=cmd_fontes)
    c = sub.add_parser("calcular", help="calcula o WACC de um projeto (modo 1)")
    c.add_argument("--projeto", required=True, help="arquivo TOML de configuração do projeto")
    c.add_argument("--saida", help="pasta dos registros (padrão: <bases>/../Calculos)")
    c.add_argument("--conferir", help="TOML com valores esperados para conferência")
    c.add_argument("--excel", action="store_true", help="gera também o Excel auditável")
    c.set_defaults(func=cmd_calcular)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
