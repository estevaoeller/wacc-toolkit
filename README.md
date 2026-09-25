# wacc-toolkit

Atualizador e repositório versionado das bases de dados usadas no cálculo do WACC (custo médio ponderado de capital) de projetos de infraestrutura no Brasil.

O foco é a camada de dados. A ferramenta baixa as séries de fontes públicas, guarda o arquivo original sem alterá-lo (com data e sha256), gera uma série tratada padronizada e valida cada atualização antes de aceitá-la. O manifesto registra tudo. Cálculos de WACC, exportações para Excel e a interface são consumidores dessas bases.

A metodologia de referência é a *Metodologia de Cálculo do WACC* do Ministério da Fazenda/STN (2018).

## Instalação

```bash
uv venv .venv
uv pip install -e ".[dev]"
cp wacc.local.toml.example wacc.local.toml   # ajuste bases_dir
```

## Uso

```bash
wacc fontes                 # lista fontes e séries
wacc atualizar              # atualiza todas as fontes
wacc atualizar --fonte fred # atualiza uma fonte
wacc status                 # situação de cada série
```

## Estrutura das bases

```
<bases>/
  bruto/<fonte>/...        originais imutáveis (nome com carimbo e hash)
  tratado/<serie>.csv      série vigente (+ .meta.json com a origem)
  tratado/<serie>/<v>.csv  tabelas versionadas (ex.: Damodaran por ano)
  entrada/<fonte>/         arquivos colocados à mão (fontes manuais, ex.: CDS)
  manifest.jsonl           trilha de auditoria
  logs/
```

As bases **não** fazem parte deste repositório.

## Desenvolvimento

- Contrato dos coletores: [docs/CONTRATO_COLETOR.md](docs/CONTRATO_COLETOR.md)
- `pytest` roda os testes offline; `pytest -m online` roda os testes que acessam as fontes.
