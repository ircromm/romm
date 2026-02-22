# Flet Agent Protocol (R0MM)

Este documento define instruções **obrigatórias** para qualquer agente (ou desenvolvedor) ao alterar `rommanager/gui_flet.py`.

Objetivo: evitar regressões recorrentes como a tela em branco + erro:

> `'Page' object has no attribute 'open'`

---

## 1) Regra de compatibilidade de API do Flet

O projeto usa APIs modernas (`page.open(...)` / `page.close(...)`) em alguns fluxos.
Esse padrão só funciona em versões mais novas do Flet.

### Regras práticas

1. **Nunca assumir API única sem checar versão alvo.**
2. Ao mexer com dialogs/snackbars/bottom sheets, confirmar se o código está:
   - no estilo novo (`page.open(control)` / `page.close(control)`), ou
   - no estilo legado (`control.open = True/False`, `page.dialog = control`, `page.update()`).
3. Se houver risco de ambiente desatualizado, implementar wrapper de compatibilidade (ver seção 4).

---

## 2) Checklist obrigatório antes de finalizar mudança em Flet

Sempre seguir esta ordem:

1. **Mapear pontos de UI afetados** em `rommanager/gui_flet.py`.
2. **Procurar chamadas sensíveis**: `page.open`, `page.close`, `SnackBar`, `AlertDialog`, `BottomSheet`, `FilePicker`.
3. **Validar coerência de padrão** (não misturar metade do fluxo no modo novo e metade no legado sem wrapper).
4. **Garantir fallback** para abertura/fechamento de overlays.
5. **Atualizar documentação** quando introduzir novo padrão de UI.

---

## 3) Padrões de mudança seguros em `gui_flet.py`

- Centralize comportamento em helpers (ex.: `_safe_open_overlay`, `_safe_close_overlay`).
- Evite espalhar chamadas diretas `page.open(...)` por múltiplos métodos.
- Para erros de execução, prefira fallback com `SnackBar` + log no painel de atividade.
- Não bloquear thread de UI; usar async e feedback visual de progresso quando aplicável.

---

## 4) Estratégia recomendada de fallback (compatibilidade)

Ao abrir/fechar dialog/overlay, usar política de fallback:

1. Tentar `page.open(control)` / `page.close(control)`.
2. Se falhar por atributo inexistente, usar fluxo legado:
   - `control.open = True/False`
   - se for `AlertDialog`, setar `page.dialog = control` quando abrir
   - chamar `page.update()`

Esse padrão elimina quebra quando o ambiente está com Flet mais antigo do que o esperado.

---

## 5) Diagnóstico rápido para erro de tela preta + snackbar vermelho

Quando aparecer algo como:

- `The application encountered an error: 'Page' object has no attribute 'open'`

seguir investigação mínima:

1. Confirmar versão instalada do Flet no ambiente.
2. Buscar em `rommanager/gui_flet.py` por `page.open(` e `page.close(`.
3. Verificar se o caminho de código executado depende exclusivamente dessas chamadas.
4. Aplicar wrapper/fallback de compatibilidade e registrar no changelog/docs.

---

## 6) Política de documentação para futuras alterações Flet

Sempre que alterar UX em Flet, incluir no PR:

1. **O que mudou** (componente/tela).
2. **Risco de compatibilidade** (sim/não).
3. **Como foi mitigado** (wrapper, fallback, pin de versão etc.).
4. **Como validar manualmente** (fluxo de cliques curto).

Sem esses quatro itens, a alteração deve ser considerada incompleta.

---

## 7) Decisão de stack para R0MM

- Requisito do projeto: `requirements.txt` mantém `flet>=0.80.0`.
- Mesmo assim, considerar cenários reais com ambiente divergente (venv antigo, cache local, instalação parcial).
- Portanto, mudanças em Flet devem ser **version-aware** e **defensivas**.

