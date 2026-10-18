# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `f215805f` em 2026-10-18 08:50:49 · alvo `http://localhost:8000/pix/transaction` · duração total 221 s
- Total: **26742** requisições, **120.9 req/s** médios, p95 867.2 ms, p99 1500.7 ms, erros inesperados 0 (0.0%)
- SLA usado: p95 ≤ 2000.0 ms e erros ≤ 1.0%


## Proximidade do critério SOLUÇÃO FUNCIONAL (visão do teste de carga)

| Dimensão | Nota | Situação | Itens |
|---|---|---|---|
| Corretude (idempotência, 409, lock, validação, GET, fluxo EPP) | 100.0% | pronto | 24/24 |
| Desempenho (SLA p95 ≤ 2000 ms, sem degradação) | 100.0% | pronto | 4/4 |

Este teste não valida se a decisão bate com as regras (isso é o `run_api_tests.py` / `audit_projeto.py --scenarios`) nem o padrão de código (`audit_projeto.py`). Passe o `summary.json` ao auditor com `--load-summary` para somar tudo em uma nota.

## O que falta ajustar

- Nada pendente nas fases executadas.

## Verificações de corretude: 28/28 passaram

| Fase | Verificação | Resultado | Detalhe |
|---|---|---|---|
| smoke | POST válido devolve 201 com key e status | ✅ | http 201 |
| smoke | reenvio idêntico devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET de id inexistente devolve 404 | ✅ | http 404 |
| ramp | existe ao menos um degrau dentro do SLA (p95 ≤ 2000.0 ms, erros ≤ 1.0%) | ✅ |  |
| idempotency | 50 rajadas: exatamente 1x 201, o resto 200, uma única key | ✅ | 0 violações |
| conflict | 1 vencedor; mesmo payload = 200; payload diferente = 409; uma key | ✅ | 0 violações |
| conflict | nenhum 5xx nem erro de rede (violação de UNIQUE não pode vazar) | ✅ | 0 erros |
| hot | todas as requisições da rajada retornam 201 | ✅ | 0 diferentes de 201 |
| hot | concorrente == sequencial em todos os pagadores (lock evita ler histórico incompleto) | ✅ | concorrente=[6] sequencial=[6] |
| hot | R2 acionado em 6 dos 10 Pix (do 5º em diante) | ✅ | observado=[6] |
| hot | contenção de um só pagador dentro do SLA (p95 ≤ 2000.0 ms) | ✅ | p95=1740.6ms, 19.0 req/s |
| destination | conta destino serializa o perfil: R9 dispara no quinto pagador | ✅ | concorrente=1, sequencial=1 |
| destination | todos os Pix da rajada são gravados | ✅ | {'conc': 0, 'seq': 0} |
| execution | uma execução passa e as outras quatro acionam C1 | ✅ | sem C1=1, com C1=4, HTTP=[201, 201, 201, 201, 201] |
| execution | todas as execuções duplicadas recebem resposta normal | ✅ | HTTP=[201, 201, 201, 201, 201] |
| validation | amount ausente → 422 | ✅ | 200 req, p95=10.7ms, códigos={422: 200} |
| validation | amount negativo → 422 | ✅ | 200 req, p95=11.8ms, códigos={422: 200} |
| validation | amount decimal → 422 | ✅ | 200 req, p95=18.5ms, códigos={422: 200} |
| validation | data sem fuso → 422 | ✅ | 200 req, p95=12.9ms, códigos={422: 200} |
| validation | documento com 10 dígitos → 422 | ✅ | 200 req, p95=17.9ms, códigos={422: 200} |
| validation | context com event inválido → 422 | ✅ | 200 req, p95=11.6ms, códigos={422: 200} |
| validation | vote sem request_id → 422 | ✅ | 200 req, p95=14.8ms, códigos={422: 200} |
| validation | JSON malformado → 400 | ✅ | 200 req, p95=11.6ms, códigos={400: 200} |
| get | todo GET devolve a mesma key do POST (200) ou 404 se inexistente | ✅ | 10898 req, erros=0, p95=168.7ms |
| mixed | mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo) | ✅ | 1187 req, erros=0, 73.8 req/s, p95=590.7ms |
| mixed | mistura dentro do SLA (p95 ≤ 2000.0 ms) | ✅ | p95=590.7ms, 73.8 req/s |
| soak | sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação) | ✅ | erros=0, p95 581.4→537.3 ms |

## Capacidade (degraus de concorrência)

| Concorrência | req/s | p50 ms | p95 ms | p99 ms | máx ms | erros % | no SLA |
|---|---|---|---|---|---|---|---|
| 1 | 27.5 | 32.9 | 48.3 | 81.7 | 297.2 | 0.0 | sim |
| 5 | 97.7 | 46.7 | 76.0 | 119.9 | 200.3 | 0.0 | sim |
| 10 | 111.5 | 82.2 | 142.7 | 195.2 | 291.4 | 0.0 | sim |
| 25 | 95.6 | 234.1 | 454.7 | 750.4 | 941.3 | 0.0 | sim |
| 50 | 89.0 | 513.2 | 959.1 | 1220.2 | 1380.7 | 0.0 | sim |
| 100 | 89.0 | 1010.6 | 1857.0 | 2579.7 | 3772.0 | 0.0 | sim |

**Capacidade sustentada dentro do SLA: 111.5 req/s** (concorrência 10). Pico bruto: 111.5 req/s (concorrência 10).

## Idempotência sob concorrência

- 50 rajadas × 20 requisições idênticas simultâneas = 1000 requisições
- Violações (≠ 1× 201 + resto 200 + uma key): **0**; keys duplicadas: **0**
- Latência na rajada: p50 77.5 ms · p95 219.5 ms · máx 332.8 ms

## Conflito (mesmo id, payload diferente)

- 50 rajadas · violações: **0** · erros 5xx/rede: **0**

## Rajada do mesmo pagador (corrida de histórico)

- 10 pagadores × 10 Pix simultâneos; R2 esperado em 6 por pagador
- R2 acionado, concorrente: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]` · sequencial: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]`
- Contenção total (1 pagador, c=20): 19.0 req/s, p95 1740.6 ms

## Concorrência por conta destino (R9)

- Acionamentos R9: concorrente 1 · sequencial 1 · esperado 1
- Respostas diferentes de 201: {'conc': 0, 'seq': 0}

## Execuções repetidas do mesmo pedido (C1)

- Execuções sem C1: 1 · execuções rejeitadas por C1: 4
- Status HTTP: [201, 201, 201, 201, 201]

## Validação sob carga

| Caso | req | p95 ms | códigos |
|---|---|---|---|
| amount ausente → 422 | 200 | 10.7 | {422: 200} |
| amount negativo → 422 | 200 | 11.8 | {422: 200} |
| amount decimal → 422 | 200 | 18.5 | {422: 200} |
| data sem fuso → 422 | 200 | 12.9 | {422: 200} |
| documento com 10 dígitos → 422 | 200 | 17.9 | {422: 200} |
| context com event inválido → 422 | 200 | 11.6 | {422: 200} |
| vote sem request_id → 422 | 200 | 14.8 | {422: 200} |
| JSON malformado → 400 | 200 | 11.6 | {400: 200} |

## Leitura (GET)

- c=50: **725.1 req/s**, p50 63.1 ms, p95 168.7 ms, p99 252.5 ms, erros 0

## Mistura realista

- c=25: **73.8 req/s**, p95 590.7 ms, erros 0

| Operação | req | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| GET | 105 | 107.3 | 198.2 | 2987.6 |
| POST epp execution | 108 | 224.2 | 391.9 | 3092.1 |
| POST epp request | 108 | 390.7 | 713.7 | 3256.2 |
| POST inválido | 108 | 108.2 | 186.1 | 2941.4 |
| POST reenvio | 105 | 153.1 | 263.4 | 3070.3 |
| POST retail | 653 | 286.6 | 536.9 | 3188.1 |

## Estabilidade (soak)

- 60.18 s a c=25: **82.2 req/s**, p95 551.5 ms, erros 0, deriva do p95 (última/primeira janela) 0.92×
