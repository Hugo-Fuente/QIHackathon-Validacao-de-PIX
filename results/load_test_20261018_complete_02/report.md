# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `92777724` em 2026-10-18 08:42:07 · alvo `http://localhost:8000/pix/transaction` · duração total 225 s
- Total: **26401** requisições, **117.5 req/s** médios, p95 836.4 ms, p99 1467.5 ms, erros inesperados 0 (0.0%)
- SLA usado: p95 ≤ 2000 ms e erros ≤ 1.0%


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
| ramp | existe ao menos um degrau dentro do SLA (p95 ≤ 2000 ms, erros ≤ 1.0%) | ✅ |  |
| idempotency | 50 rajadas: exatamente 1x 201, o resto 200, uma única key | ✅ | 0 violações |
| conflict | 1 vencedor; mesmo payload = 200; payload diferente = 409; uma key | ✅ | 0 violações |
| conflict | nenhum 5xx nem erro de rede (violação de UNIQUE não pode vazar) | ✅ | 0 erros |
| hot | todas as requisições da rajada retornam 201 | ✅ | 0 diferentes de 201 |
| hot | concorrente == sequencial em todos os pagadores (lock evita ler histórico incompleto) | ✅ | concorrente=[6] sequencial=[6] |
| hot | R2 acionado em 6 dos 10 Pix (do 5º em diante) | ✅ | observado=[6] |
| hot | contenção de um só pagador dentro do SLA (p95 ≤ 2000 ms) | ✅ | p95=1082.2ms, 26.2 req/s |
| destination | conta destino serializa o perfil: R9 dispara no quinto pagador | ✅ | concorrente=1, sequencial=1 |
| destination | todos os Pix da rajada são gravados | ✅ | {'conc': 0, 'seq': 0} |
| execution | uma execução passa e as outras quatro acionam C1 | ✅ | sem C1=1, com C1=4, HTTP=[201, 201, 201, 201, 201] |
| execution | todas as execuções duplicadas recebem resposta normal | ✅ | HTTP=[201, 201, 201, 201, 201] |
| validation | amount ausente → 422 | ✅ | 200 req, p95=19.8ms, códigos={422: 200} |
| validation | amount negativo → 422 | ✅ | 200 req, p95=18.2ms, códigos={422: 200} |
| validation | amount decimal → 422 | ✅ | 200 req, p95=19.0ms, códigos={422: 200} |
| validation | data sem fuso → 422 | ✅ | 200 req, p95=33.6ms, códigos={422: 200} |
| validation | documento com 10 dígitos → 422 | ✅ | 200 req, p95=52.0ms, códigos={422: 200} |
| validation | context com event inválido → 422 | ✅ | 200 req, p95=17.6ms, códigos={422: 200} |
| validation | vote sem request_id → 422 | ✅ | 200 req, p95=13.4ms, códigos={422: 200} |
| validation | JSON malformado → 400 | ✅ | 200 req, p95=18.0ms, códigos={400: 200} |
| get | todo GET devolve a mesma key do POST (200) ou 404 se inexistente | ✅ | 9308 req, erros=0, p95=169.5ms |
| mixed | mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo) | ✅ | 1730 req, erros=0, 112.9 req/s, p95=596.7ms |
| mixed | mistura dentro do SLA (p95 ≤ 2000 ms) | ✅ | p95=596.7ms, 112.9 req/s |
| soak | sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação) | ✅ | erros=0, p95 2013.6→470.9 ms |

## Capacidade (degraus de concorrência)

| Concorrência | req/s | p50 ms | p95 ms | p99 ms | máx ms | erros % | no SLA |
|---|---|---|---|---|---|---|---|
| 1 | 51.9 | 16.9 | 27.7 | 49.2 | 135.1 | 0.0 | sim |
| 5 | 102.6 | 40.6 | 94.9 | 182.0 | 343.8 | 0.0 | sim |
| 10 | 94.3 | 87.4 | 207.8 | 474.9 | 795.2 | 0.0 | sim |
| 25 | 117.9 | 187.4 | 388.7 | 541.9 | 735.5 | 0.0 | sim |
| 50 | 104.5 | 433.5 | 838.3 | 1091.6 | 1361.7 | 0.0 | sim |
| 100 | 65.1 | 1101.2 | 5098.0 | 5706.0 | 6374.4 | 0.0 | não |

**Capacidade sustentada dentro do SLA: 117.9 req/s** (concorrência 25). Pico bruto: 117.9 req/s (concorrência 25).

## Idempotência sob concorrência

- 50 rajadas × 20 requisições idênticas simultâneas = 1000 requisições
- Violações (≠ 1× 201 + resto 200 + uma key): **0**; keys duplicadas: **0**
- Latência na rajada: p50 69.1 ms · p95 144.9 ms · máx 404.9 ms

## Conflito (mesmo id, payload diferente)

- 50 rajadas · violações: **0** · erros 5xx/rede: **0**

## Rajada do mesmo pagador (corrida de histórico)

- 10 pagadores × 10 Pix simultâneos; R2 esperado em 6 por pagador
- R2 acionado, concorrente: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]` · sequencial: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]`
- Contenção total (1 pagador, c=20): 26.2 req/s, p95 1082.2 ms

## Concorrência por conta destino (R9)

- Acionamentos R9: concorrente 1 · sequencial 1 · esperado 1
- Respostas diferentes de 201: {'conc': 0, 'seq': 0}

## Execuções repetidas do mesmo pedido (C1)

- Execuções sem C1: 1 · execuções rejeitadas por C1: 4
- Status HTTP: [201, 201, 201, 201, 201]

## Validação sob carga

| Caso | req | p95 ms | códigos |
|---|---|---|---|
| amount ausente → 422 | 200 | 19.8 | {422: 200} |
| amount negativo → 422 | 200 | 18.2 | {422: 200} |
| amount decimal → 422 | 200 | 19.0 | {422: 200} |
| data sem fuso → 422 | 200 | 33.6 | {422: 200} |
| documento com 10 dígitos → 422 | 200 | 52.0 | {422: 200} |
| context com event inválido → 422 | 200 | 17.6 | {422: 200} |
| vote sem request_id → 422 | 200 | 13.4 | {422: 200} |
| JSON malformado → 400 | 200 | 18.0 | {400: 200} |

## Leitura (GET)

- c=50: **615.8 req/s**, p50 67.5 ms, p95 169.5 ms, p99 227.6 ms, erros 0

## Mistura realista

- c=25: **112.9 req/s**, p95 596.7 ms, erros 0

| Operação | req | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| GET | 154 | 50.2 | 101.1 | 147.6 |
| POST epp execution | 158 | 214.1 | 367.7 | 618.1 |
| POST epp request | 158 | 597.1 | 925.5 | 1056.1 |
| POST inválido | 157 | 45.5 | 112.4 | 141.7 |
| POST reenvio | 155 | 70.7 | 151.9 | 196.0 |
| POST retail | 948 | 210.4 | 377.0 | 531.0 |

## Estabilidade (soak)

- 60.21 s a c=25: **85.4 req/s**, p95 530.2 ms, erros 0, deriva do p95 (última/primeira janela) 0.23×
