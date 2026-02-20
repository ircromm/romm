# Investigação completa: app lento vs navegador rápido

Data: 2026-02-18

## Objetivo
Entender por que download via app pode parecer “internet discada” enquanto Edge/Chrome/Firefox entregam velocidade normal.

## O que foi investigado

### 1) Fluxo e implementação do app
- O downloader usa `requests.Session` (HTTP/1.1), download em streaming com chunk de 256KB, CRC em tempo real, e pode rodar em modo sequencial ou rápido (paralelo controlado).  
- A resolução de URL foi otimizada para evitar `HEAD` por padrão, reduzindo latência de pré-processamento em lote.
- Existe suporte a retomada com `.part` + `Range`.

### 2) Diferenças estruturais entre navegador e app (causas prováveis)

1. **Proxy/autoconfig aplicado ao Python, mas não igual no navegador**
   - `requests` usa variáveis de ambiente/proxy corporativo por padrão (`trust_env=True`).
   - Navegadores podem usar rota diferente (PAC, DoH, política local, exceções por domínio/processo).
   - Sintoma típico: app muito lento e navegador normal no mesmo host.

2. **Stack de transporte/protocolo**
   - Navegadores usam HTTP/2/HTTP/3 (QUIC) em muitos cenários.
   - `requests` padrão usa HTTP/1.1.
   - Em certas rotas/CDNs, isso muda bastante o throughput e TTFB.

3. **Inspeção/antivírus por processo**
   - Alguns antivírus/EDR escaneiam mais agressivamente processo Python que navegador.
   - Pode degradar escrita/stream e simular “discada”.

4. **Shaping por fingerprint TLS/cliente**
   - Mesmo User-Agent não replica exatamente o fingerprint TLS do navegador.
   - Alguns edges/CDNs priorizam perfis típicos de browser.

5. **Custos de aplicação (normalmente secundários)**
   - Callback/UI e CRC têm custo, mas raramente explicam queda para nível “discada” sozinhos.
   - Geralmente são responsáveis por degradação moderada, não extrema.

## Evidências no código
- Downloader usa `requests.Session` + adapter + keep-alive e timeout separado connect/read.
- Resolução de URL sem `HEAD` por padrão e com cache por sessão.
- Retomada via `Range` e `.part` implementada no pipeline.
- Web expõe modo `sequential`/`fast` com número de workers.

## Ferramenta de diagnóstico criada

Arquivo: `tools/investigate_download_gap.py`

Compara três caminhos para a **mesma URL direta**:
1. `requests(trust_env=True)`
2. `requests(trust_env=False)`
3. `curl`

Mede:
- MB/s
- TTFB
- tempo total
- contexto de proxy (`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`)

Uso:
```bash
python tools/investigate_download_gap.py --url "<URL-direta-do-arquivo>" --mb 100
```

## Interpretação prática dos resultados

- **Caso A**: `trust_env=False` muito mais rápido que `trust_env=True`  
  => gargalo principal é proxy/autoconfig.

- **Caso B**: `curl` muito mais rápido que ambos `requests`  
  => diferença de stack/protocolo/TLS (browser/curl path melhor).

- **Caso C**: todos lentos  
  => rota/ISP/servidor remoto limitando.

## Ações recomendadas (prioridade)

### P0 (imediato)
1. Rodar o script de diagnóstico com 2–3 URLs reais (Myrient e Archive).
2. Se `trust_env=False` ganhar, adicionar opção no app para desabilitar uso de proxy de ambiente.
3. Testar modo `fast` com 2–3 workers e comparar MB/s total.

## Workarounds já disponíveis no app

1. **Trocar backend para `curl`** no Myrient Browser (Backend: `cURL (fallback)`).
   - Mantém download no destino escolhido pelo app, mas usa stack de transporte do `curl`.

2. **Trocar backend para `browser`** (Backend: `Browser link only`).
   - O app abre o link direto no navegador padrão, usando exatamente o mesmo caminho de rede do browser.

3. **Desabilitar proxy/env no `requests` via variável de ambiente**:

```bash
ROMM_DOWNLOAD_TRUST_ENV=0 python main.py
```

Isso força `requests.Session.trust_env=False` e evita proxy/PAC herdado do ambiente quando ele é o gargalo.

### P1 (curto prazo)
1. Adicionar telemetria por arquivo no app:
   - DNS/connect/TLS/TTFB/throughput médio.
2. Expor no UI velocidade instantânea e média por arquivo.
3. Persistir resultados para comparar rotas/horários.

### P2 (médio prazo)
1. Implementar backend alternativo opcional via `curl` subprocess para ambientes onde `requests` performa pior.
2. Avaliar cliente com suporte HTTP/2 para downloads (quando estável no ambiente-alvo).
3. Adicionar política adaptativa:
   - detectar lentidão persistente e alternar automaticamente modo/worker/estratégia.

## Conclusão
Quando navegador está rápido e app está muito lento, a causa mais comum não é “chunk size” ou “CRC”, e sim **diferença de caminho de rede/proxy/protocolo**. O app já removeu atrasos artificiais e ganhou resume + modo rápido; o próximo passo decisivo é confirmar o gargalo com medição comparativa controlada (`trust_env`, `curl`, URL igual) e ajustar o transporte com base no resultado.
