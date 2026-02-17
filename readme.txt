# ROM Collection Manager v2

Sistema para identificação e organização de ROMs com DATs (No-Intro, Redump, TOSEC e formatos Logiqx compatíveis).

---

## 1. Visão geral

O projeto atualmente oferece **três interfaces sobre o mesmo núcleo**:

1. **CLI** (automação e scripts)
2. **Desktop GUI (tkinter)**
3. **Web UI (Flask API + React embutido no template HTML)**

O fluxo principal é o mesmo em todas as interfaces:

1. Carregar um ou mais DATs
2. Escanear pasta de ROMs (com suporte a ZIP)
3. Fazer matching por hash
4. Visualizar identificados / não identificados / faltantes
5. Organizar (copy/move) com estratégia
6. (Opcional) gerar relatório e salvar coleção

---

## 2. Estado atual da arquitetura

### Núcleo de domínio (reutilizado por CLI/GUI/Web)

- `rommanager/models.py` → dataclasses principais (`ROMInfo`, `ScannedFile`, `DATInfo`, `Collection`, etc.)
- `rommanager/parser.py` → parser DAT/XML (`.dat`, `.xml`, `.gz`, `.zip`)
- `rommanager/scanner.py` → scan de arquivos + CRC32 (MD5/SHA1 opcionais)
- `rommanager/matcher.py` → matching por CRC+size, MD5, SHA1; suporte multi-DAT
- `rommanager/organizer.py` → preview, organização e undo
- `rommanager/reporter.py` → relatório de ROMs faltantes (TXT/CSV/JSON)

### Interfaces

- `rommanager/cli.py` → execução via terminal
- `rommanager/gui.py` → app desktop tkinter
- `rommanager/web.py` → backend Flask + frontend React em `HTML_TEMPLATE`
- `rommanager/launcher.py` → launcher gráfico para escolher Desktop/Web

### Persistência e biblioteca

- `rommanager/collection.py` → save/load de sessões (`.romcol.json`)
- `rommanager/dat_library.py` → biblioteca local de DATs
- `rommanager/dat_sources.py` → fontes conhecidas de DAT e download direto (quando `requests` disponível)
- `rommanager/shared_config.py` → configurações compartilhadas (colunas, cores, estratégias e paths)

---

## 3. Entradas e execução

### Opções principais

```bash
python main.py                 # GUI desktop (fallback para help/aviso se tkinter indisponível)
python main.py --web           # Web UI local (Flask)
python main.py --dat ...       # CLI
python -m rommanager           # launcher/modo automático
python -m rommanager --help    # ajuda CLI
```

### Requisitos práticos

- Python 3.10+
- Flask para modo web
- tkinter para GUI desktop
- `requests` para alguns recursos de download de DAT

Instalação rápida:

```bash
pip install -r requirements.txt
```

---

## 4. Estratégias de organização

Suportadas hoje:

- `system`
- `1g1r`
- `region`
- `alphabetical`
- `emulationstation`
- `flat`

Também é possível compor estratégias com `+` (ex.: `system+region`).

---

## 5. Pontos importantes para desenvolvimento

1. **Single source of truth**: regras de negócio estão no núcleo (`parser/scanner/matcher/organizer`) e não nas interfaces.
2. **Multi-DAT first**: `MultiROMMatcher` é a base para estatísticas por sistema e matching simultâneo.
3. **Config compartilhada**: ajuste colunas/estratégias em `shared_config.py` para manter GUI/Web coerentes.
4. **Web atual é monolítico**: API Flask e frontend React estão no mesmo arquivo (`web.py`). Funciona, mas dificulta manutenção de longo prazo.

---

## 6. Podemos começar uma versão mais limpa?

Sim. Não precisa ser “só atualizar documentação”. A atualização de docs é importante, mas já dá para iniciar uma base mais limpa em paralelo com baixo risco.

### Proposta incremental (v3 clean foundation)

#### Fase 1 — limpeza sem quebrar funcionalidades

- Extrair regras de estado global do `web.py` para um módulo de serviço (`services/app_state.py`)
- Separar rotas Flask por domínio (`routes/scan.py`, `routes/organize.py`, `routes/library.py`, ...)
- Criar camada de casos de uso (`use_cases/scan_and_match.py`, `use_cases/organize.py`)
- Padronizar erros/retornos de API (schema simples e consistente)

#### Fase 2 — desacoplamento do frontend web

- Migrar React embutido para frontend separado (`frontend/`) com build estático
- Manter Flask servindo API e assets compilados
- Ganhar versionamento de UI, testes unitários de frontend e PRs mais focados

#### Fase 3 — qualidade e governança

- Adicionar suíte mínima de testes por domínio (parser/scanner/matcher/organizer)
- Lint/format/type check no CI
- Definir convenções de evolução de schema de coleção (`version` + migrações)

### Resultado esperado

- Mudanças menores e mais previsíveis
- Menor risco de regressão
- Melhor onboarding para novos contribuidores
- Base pronta para crescer sem ampliar dívida técnica no mesmo ritmo

---

## 7. Recomendação prática imediata

**Fazer os dois em paralelo:**

1. **Atualizar documentação** (este arquivo + docs técnicas principais)
2. **Abrir um “v3 foundation” pequeno** com extração inicial de módulos de serviço/rotas

Isso evita “big-bang rewrite” e melhora a qualidade já no curto prazo.

---


## 8. Monitor de atividades (novo)

O app agora possui um monitor central (`rommanager/monitor.py`) para registrar tudo que está acontecendo:

- início/fim de parsing DAT
- início/fim de scan e erros de arquivos
- início/fim de organização e undo
- downloads (início/fim/falhas)
- operações de coleção e biblioteca

### Onde ver o monitor

- **Desktop GUI**: nova aba **Monitor** com atualização automática em tempo real.
- **Web**: endpoint `GET /api/monitor?limit=200` e limpeza em `POST /api/monitor/clear`.

Objetivo: evitar falhas silenciosas e dar visibilidade das operações em andamento.

---
