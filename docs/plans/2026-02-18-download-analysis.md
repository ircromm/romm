# Análise profunda: gargalos no download do app vs download direto do navegador

Data: 2026-02-18

## Contexto

Objetivo: entender por que o download no app parece "muito lento" e comparar com o comportamento de um download direto no navegador.

> Limitação deste ambiente: não foi possível executar medições reais contra Myrient/Archive.org por bloqueio de proxy (HTTP tunnel 403). A análise abaixo é baseada em inspeção de código e no fluxo de execução real do app.

## Comparação de fluxo: App vs Navegador

### Navegador (download direto)

Fluxo típico:
1. Usuário clica no arquivo.
2. Um único GET é iniciado imediatamente.
3. Sem delay artificial entre arquivos.
4. Se houver falha/transiente, navegador tende a reaproveitar conexão e pode retomar/repetir de forma eficiente.
5. UI do navegador atualiza progresso sem impactar muito o throughput.

### App (fluxo atual)

Fluxo no app (Myrient):
1. Resolver URLs de ROMs (inclui `HEAD` por item em `find_rom_url`).
2. Enfileirar tarefas.
3. Executar downloads sequenciais (`start_downloads`).
4. Fazer CRC durante streaming.
5. Atualizar UI por callback.

Diferenças-chave que impactam percepção de velocidade:
- Existia **delay padrão entre downloads** (5s) antes desta correção.
- Existe fase de **resolução por HEAD** antes de começar os GETs (para lote grande, soma latência relevante).
- Download é **sequencial por design** (bom para estabilidade, porém pior tempo total em lotes se comparado a múltiplos downloads concorrentes controlados).

## Gargalos identificados (por inspeção)

### 1) Delay artificial entre arquivos (impacto crítico em lote)

`start_downloads(..., download_delay=5)` aguardava 5 segundos entre cada arquivo por padrão.

Impacto estimado:
- 20 ROMs -> +95s de espera artificial (19 intervalos).
- 100 ROMs -> +495s (~8m15s) de espera artificial.

Este comportamento não existe no download direto do navegador.

## 2) Resolução de URL via HEAD por ROM antes de baixar

`find_rom_url` faz `HEAD` para cada ROM. Em lotes grandes, isso adiciona latência acumulada antes do primeiro byte útil de cada arquivo.

Risco adicional:
- Alguns servidores/CDNs tratam `HEAD` de forma diferente de `GET`.
- Sob rate-limit, `HEAD` pode piorar o tempo total sem aumentar taxa de download.

## 3) Estratégia sempre sequencial

O app está corretamente configurado para baixar 1 arquivo por vez (estilo navegador), mas isso não é sempre ideal para throughput total de lote.

Sugestão: manter default sequencial (seguro), mas permitir **concorrência opcional baixa** (2-3 workers) para links/servidores que performam melhor assim.

## 4) Sem retomada explícita (`Range`) no caminho principal

Se conexão cair no meio, o arquivo é refeito do zero (dependendo do estado). Navegadores normalmente oferecem retomada em mais cenários.

## Melhorias recomendadas

## A. Já aplicada nesta alteração

1. **Remover atraso padrão entre downloads** (default 0s):
   - `MyrientDownloader.start_downloads(..., download_delay=0)`
   - CLI também com `--download-delay` default 0.

Resultado esperado: ganho imediato de tempo em lotes, sem risco funcional alto.

## B. Próximas melhorias de alto impacto

1. **Modo de resolução sem HEAD para nomes já exatos**
   - Construir URL direta e tentar GET do arquivo na hora do download.
   - Em caso de 404, então fallback para busca/HEAD.

2. **Retomada de download com `Range` + arquivo `.part`**
   - Persistir progresso parcial e retomar após falha/reinício.
   - Aproxima comportamento de navegador para arquivos grandes.

3. **Retry com backoff por tipo de erro + timeouts diferenciados**
   - Timeout menor para connect, maior para read.
   - Retry mais agressivo apenas para erros transitórios.

4. **Concorrência opcional adaptativa (2-3 workers)**
   - Default continua 1 (estável).
   - Modo "rápido" habilita 2-3 downloads paralelos com limite por host.

5. **Telemetria por fase (resolução, TTFB, throughput, escrita em disco)**
   - Medir e exibir onde está o gargalo real por servidor/região.
   - Permite ajuste automático (delay/retry/concurrency) orientado por dados.

## C. Melhorias UX/Operacionais

1. Perfis de download:
   - `Conservador` (1 conexão, retries altos)
   - `Padrão` (1 conexão, sem delay)
   - `Rápido` (2-3 conexões)

2. Mostrar no progresso:
   - Velocidade instantânea e média (MB/s)
   - ETA real
   - Fase atual (resolvendo URL / baixando / verificando CRC)

3. Cache de resolução de URL por sessão:
   - Evita HEAD repetido para itens já validados.

## Conclusão

A maior diferença de percepção entre app e navegador, neste código, é o **tempo morto artificial entre arquivos** e o custo de pré-resolução por HEAD em lote. A correção do default para delay 0 elimina o principal desperdício previsível. Em seguida, o maior ganho tende a vir de **retomada com Range** e de um modo **rápido com concorrência baixa e controlada**.
