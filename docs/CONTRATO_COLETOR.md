# Contrato de coletor

Cada fonte de dados é **um módulo** em `src/wacc_toolkit/collectors/<fonte>.py`, com uma subclasse de `Coletor` decorada com `@registrar`. A implementação de referência é [`collectors/fred.py`](../src/wacc_toolkit/collectors/fred.py).

## Regras

1. **Não altere o núcleo** (`collector.py`, `storage.py`, `validate.py`, `series.py`, `cli.py`, `registry.py`). Se o contrato não atende a um caso, pare e descreva a necessidade. Não contorne.
2. **`coletar(ctx)` só obtém bytes.** Devolve `list[ArquivoBruto]` sem interpretar nada. Use `ctx.sessao` e `http.baixar()` para a internet. Fontes manuais (`manual = True`) leem de `ctx.entrada(self.fonte)`.
3. **`interpretar(ctx, brutos)` lê apenas os arquivos gravados** (`reg.caminho`). Nunca use a memória da etapa anterior. Isso garante que o tratado seja reproduzível a partir do bruto.
4. **Saída:**
   - séries comuns: `{serie_id: DataFrame}`;
   - séries versionadas: `{serie_id: {versao: DataFrame}}`;
   - as colunas devem ser exatamente as de `SerieSpec.colunas`;
   - `data` deve ser convertível por `pd.to_datetime`.
5. **Valores na unidade da fonte** (ex.: % a.a. como publicado), declarada em `SerieSpec.unidade`. Conversões metodológicas (média 12m, anualização, retornos) **não** são feitas no coletor; pertencem ao motor de cálculo.
6. **`SerieSpec` realista:**
   - `faixa` plausível, que pegue erro de parsing (ex.: vírgula decimal virando 457 em vez de 4,57);
   - `max_lacuna_dias` compatível com a frequência;
   - `modo="acumular"` quando a fonte entrega só uma janela recente;
   - `chave` composta quando houver várias linhas por data (ex.: títulos).
7. **`rotulo` em `ArquivoBruto`** para distinguir arquivos da mesma fonte (ex.: código da série, ano).
8. **Identificação:** `id` de série em snake_case, prefixado pela fonte (`bcb_tlp`, `tesouro_ntnb`).
9. **Robustez:**
   - números no formato brasileiro (`1.234,56`), BOM no CSV e encoding latin-1 são comuns: trate-os;
   - falhe com mensagem clara (`ValueError`) se o layout mudar, sem devolver dados silenciosamente errados.
10. **Nada de dados no git.** Fixtures de teste são recortes pequenos (≤ 50 linhas) em `tests/fixtures/`.

## Testes obrigatórios (`tests/test_<fonte>.py`)
- **Parse offline** sobre uma fixture real recortada: colunas, tipos, primeira e última data, um valor conhecido.
- **Caso de borda da fonte:** feriado vazio, separador de milhar, linha de rodapé etc.
- **Teste `@pytest.mark.online`:** `executar(Coletor(), ctx)` retorna `status == "ok"` com todas as séries gravadas.

Para rodar:

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_<fonte>.py
.venv/Scripts/python.exe -m pytest -q -m online tests/test_<fonte>.py
```

## Esqueleto

```python
from ..collector import Coletor, Contexto
from ..http import baixar
from ..registry import registrar
from ..series import SerieSpec
from ..storage import ArquivoBruto, RegistroBruto

@registrar
class MinhaFonte(Coletor):
    fonte = "minhafonte"
    descricao = "..."
    series = (SerieSpec("minhafonte_x", "descrição", "% a.a.", "D", faixa=(0, 50), max_lacuna_dias=10),)

    def coletar(self, ctx: Contexto) -> list[ArquivoBruto]:
        r = baixar(ctx.sessao, URL)
        return [ArquivoBruto(r.content, "csv", url=URL, rotulo="x")]

    def interpretar(self, ctx: Contexto, brutos: list[RegistroBruto]) -> dict:
        ...
        return {"minhafonte_x": df}
```
