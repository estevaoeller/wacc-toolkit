"""Repositório local das bases: bruto imutável, tratado e manifesto.

Estrutura em disco::

    <raiz>/
      bruto/<fonte>/<AAAAMMDDTHHMMSS>_<sha8>.<ext>   arquivos originais, nunca alterados
      tratado/<serie>.csv                            série vigente
      tratado/<serie>.meta.json                      metadados da série vigente
      tratado/<serie>/<versao>.csv                   tabelas versionadas (ex.: Damodaran)
      entrada/<fonte>/                               arquivos colocados à mão (fontes manuais)
      logs/atualizacao.log
      manifest.jsonl                                 trilha de auditoria (append-only)
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .series import SerieSpec


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def sha256_bytes(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


@dataclass(frozen=True)
class ArquivoBruto:
    """Arquivo obtido de uma fonte, ainda não gravado."""

    conteudo: bytes
    extensao: str  # sem ponto: "csv", "json", "xls"...
    url: str | None = None
    nome_original: str | None = None
    rotulo: str | None = None  # identifica o recurso dentro da fonte (ex.: "DGS10")


@dataclass(frozen=True)
class RegistroBruto:
    fonte: str
    caminho: Path
    sha256: str
    novo: bool
    rotulo: str | None
    url: str | None


class Repositorio:
    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)
        for sub in ("bruto", "tratado", "entrada", "logs"):
            (self.raiz / sub).mkdir(parents=True, exist_ok=True)
        self.manifest = self.raiz / "manifest.jsonl"

    # ---------- diretórios ----------
    def dir_bruto(self, fonte: str) -> Path:
        p = self.raiz / "bruto" / fonte
        p.mkdir(parents=True, exist_ok=True)
        return p

    def dir_entrada(self, fonte: str) -> Path:
        p = self.raiz / "entrada" / fonte
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def dir_tratado(self) -> Path:
        return self.raiz / "tratado"

    @property
    def dir_logs(self) -> Path:
        return self.raiz / "logs"

    # ---------- manifesto ----------
    def registrar(self, evento: dict) -> None:
        evento = {"registrado_em": _agora().isoformat(timespec="seconds"), **evento}
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False, default=str) + "\n")

    def eventos(self, tipo: str | None = None) -> list[dict]:
        if not self.manifest.exists():
            return []
        out = []
        with self.manifest.open(encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha:
                    continue
                ev = json.loads(linha)
                if tipo is None or ev.get("tipo") == tipo:
                    out.append(ev)
        return out

    # ---------- bruto ----------
    def gravar_bruto(self, fonte: str, arquivo: ArquivoBruto) -> RegistroBruto:
        """Grava o arquivo original. Se um arquivo idêntico (mesmo sha256) já existir
        para a fonte, não duplica: devolve o registro existente com ``novo=False``."""
        sha = sha256_bytes(arquivo.conteudo)
        for ev in self.eventos("bruto"):
            if ev["fonte"] == fonte and ev["sha256"] == sha:
                caminho = self.raiz / ev["arquivo"]
                if caminho.exists():
                    return RegistroBruto(fonte, caminho, sha, False, ev.get("rotulo"), ev.get("url"))
        carimbo = _agora().strftime("%Y%m%dT%H%M%S")
        prefixo = f"{arquivo.rotulo}_" if arquivo.rotulo else ""
        nome = f"{prefixo}{carimbo}_{sha[:8]}.{arquivo.extensao.lstrip('.')}"
        caminho = self.dir_bruto(fonte) / nome
        caminho.write_bytes(arquivo.conteudo)
        try:
            os.chmod(caminho, 0o444)  # somente leitura: o bruto é imutável
        except OSError:
            pass
        self.registrar(
            {
                "tipo": "bruto",
                "fonte": fonte,
                "rotulo": arquivo.rotulo,
                "arquivo": caminho.relative_to(self.raiz).as_posix(),
                "sha256": sha,
                "bytes": len(arquivo.conteudo),
                "url": arquivo.url,
                "nome_original": arquivo.nome_original,
            }
        )
        return RegistroBruto(fonte, caminho, sha, True, arquivo.rotulo, arquivo.url)

    # ---------- tratado ----------
    def caminho_serie(self, spec: SerieSpec, versao: str | None = None) -> Path:
        if spec.versionada:
            if not versao:
                raise ValueError(f"série versionada {spec.id} exige versão")
            return self.dir_tratado / spec.id / f"{versao}.csv"
        return self.dir_tratado / f"{spec.id}.csv"

    def ler_serie(self, spec: SerieSpec, versao: str | None = None) -> pd.DataFrame | None:
        caminho = self.caminho_serie(spec, versao)
        if not caminho.exists():
            return None
        df = pd.read_csv(caminho, encoding="utf-8")
        if "data" in df.columns:
            df["data"] = pd.to_datetime(df["data"]).dt.date
        return df

    def versoes(self, spec: SerieSpec) -> list[str]:
        pasta = self.dir_tratado / spec.id
        return sorted(p.stem for p in pasta.glob("*.csv")) if pasta.exists() else []

    def gravar_serie(
        self,
        spec: SerieSpec,
        df: pd.DataFrame,
        origem: list[RegistroBruto],
        avisos: list[str],
        versao: str | None = None,
    ) -> Path:
        caminho = self.caminho_serie(spec, versao)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        conteudo = df.to_csv(index=False, lineterminator="\n").encode("utf-8")
        _escrita_atomica(caminho, conteudo)
        meta = {
            "serie": spec.id,
            "descricao": spec.descricao,
            "unidade": spec.unidade,
            "frequencia": spec.frequencia,
            "versao": versao,
            "linhas": int(len(df)),
            "inicio": str(df["data"].min()) if "data" in df.columns and len(df) else None,
            "fim": str(df["data"].max()) if "data" in df.columns and len(df) else None,
            "sha256_csv": sha256_bytes(conteudo),
            "origem": [{"arquivo": r.caminho.relative_to(self.raiz).as_posix(), "sha256": r.sha256} for r in origem],
            "avisos": avisos,
            "atualizado_em": _agora().isoformat(timespec="seconds"),
        }
        caminho_meta = caminho.with_suffix(".meta.json")
        _escrita_atomica(caminho_meta, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
        self.registrar({"tipo": "serie", "status": "gravada", **{k: meta[k] for k in (
            "serie", "versao", "linhas", "inicio", "fim", "sha256_csv", "origem", "avisos")},
            "arquivo": caminho.relative_to(self.raiz).as_posix()})
        return caminho

    def meta_serie(self, spec: SerieSpec, versao: str | None = None) -> dict | None:
        caminho = self.caminho_serie(spec, versao).with_suffix(".meta.json")
        return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else None


def _escrita_atomica(destino: Path, conteudo: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=f".{destino.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(conteudo)
        os.replace(tmp, destino)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
