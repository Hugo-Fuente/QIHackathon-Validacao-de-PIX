# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `dce63cdc` em 2026-10-18 08:57:22 · alvo `http://localhost:8000/pix/transaction` · duração total 223 s
- Total: **26693** requisições, **119.6 req/s** médios, p95 926.4 ms, p99 1494.9 ms, erros inesperados 0 (0.0%)
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
| hot | contenção de um só pagador dentro do SLA (p95 ≤ 2000.0 ms) | ✅ | p95=1355.1ms, 18.4 req/s |
| destination | conta destino serializa o perfil: R9 dispara no quinto pagador | ✅ | concorrente=1, sequencial=1 |
| destination | todos os Pix da rajada são gravados | ✅ | {'conc': 0, 'seq': 0} |
| execution | uma execução passa e as outras quatro acionam C1 | ✅ | sem C1=1, com C1=4, HTTP=[201, 201, 201, 201, 201] |
| execution | todas as execuções duplicadas recebem resposta normal | ✅ | HTTP=[201, 201, 201, 201, 201] |
| validation | amount ausente → 422 | ✅ | 200 req, p95=13.4ms, códigos={422: 200} |
| validation | amount negativo → 422 | ✅ | 200 req, p95=11.3ms, códigos={422: 200} |
| validation | amount decimal → 422 | ✅ | 200 req, p95=19.7ms, códigos={422: 200} |
| validation | data sem fuso → 422 | ✅ | 200 req, p95=12.2ms, códigos={422: 200} |
| validation | documento com 10 dígitos → 422 | ✅ | 200 req, p95=10.3ms, códigos={422: 200} |
| validation | context com event inválido → 422 | ✅ | 200 req, p95=11.6ms, códigos={422: 200} |
| validation | vote sem request_id → 422 | ✅ | 200 req, p95=13.0ms, códigos={422: 200} |
| validation | JSON malformado → 400 | ✅ | 200 req, p95=53.7ms, códigos={400: 200} |
| get | todo GET devolve a mesma key do POST (200) ou 404 se inexistente | ✅ | 11989 req, erros=0, p95=115.3ms |
| mixed | mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo) | ✅ | 1516 req, erros=0, 99.1 req/s, p95=623.3ms |
| mixed | mistura dentro do SLA (p95 ≤ 2000.0 ms) | ✅ | p95=623.3ms, 99.1 req/s |
| soak | sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação) | ✅ | erros=0, p95 633.3→669.1 ms |

## Capacidade (degraus de concorrência)

| Concorrência | req/s | p50 ms | p95 ms | p99 ms | máx ms | erros % | no SLA |
|---|---|---|---|---|---|---|---|
| 1 | 23.1 | 39.4 | 61.4 | 108.4 | 184.7 | 0.0 | sim |
| 5 | 78.7 | 57.7 | 97.2 | 151.8 | 247.0 | 0.0 | sim |
| 10 | 85.7 | 105.6 | 194.6 | 287.9 | 457.6 | 0.0 | sim |
| 25 | 88.5 | 258.1 | 492.7 | 604.2 | 827.3 | 0.0 | sim |
| 50 | 77.1 | 583.7 | 1192.6 | 1548.5 | 2214.7 | 0.0 | sim |
| 100 | 81.1 | 1081.6 | 2195.9 | 2875.1 | 4416.9 | 0.0 | não |

**Capacidade sustentada dentro do SLA: 88.5 req/s** (concorrência 25). Pico bruto: 88.5 req/s (concorrência 25).

## Idempotência sob concorrência

- 50 rajadas × 20 requisições idênticas simultâneas = 1000 requisições
- Violações (≠ 1× 201 + resto 200 + uma key): **0**; keys duplicadas: **0**
- Latência na rajada: p50 83.4 ms · p95 207.8 ms · máx 296.3 ms

## Conflito (mesmo id, payload diferente)

- 50 rajadas · violações: **0** · erros 5xx/rede: **0**

## Rajada do mesmo pagador (corrida de histórico)

- 10 pagadores × 10 Pix simultâneos; R2 esperado em 6 por pagador
- R2 acionado, concorrente: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]` · sequencial: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]`
- Contenção total (1 pagador, c=20): 18.4 req/s, p95 1355.1 ms

## Concorrência por conta destino (R9)

- Acionamentos R9: concorrente 1 · sequencial 1 · esperado 1
- Respostas diferentes de 201: {'conc': 0, 'seq': 0}

## Execuções repetidas do mesmo pedido (C1)

- Execuções sem C1: 1 · execuções rejeitadas por C1: 4
- Status HTTP: [201, 201, 201, 201, 201]

## Validação sob carga

| Caso | req | p95 ms | códigos |
|---|---|---|---|
| amount ausente → 422 | 200 | 13.4 | {422: 200} |
| amount negativo → 422 | 200 | 11.3 | {422: 200} |
| amount decimal → 422 | 200 | 19.7 | {422: 200} |
| data sem fuso → 422 | 200 | 12.2 | {422: 200} |
| documento com 10 dígitos → 422 | 200 | 10.3 | {422: 200} |
| context com event inválido → 422 | 200 | 11.6 | {422: 200} |
| vote sem request_id → 422 | 200 | 13.0 | {422: 200} |
| JSON malformado → 400 | 200 | 53.7 | {400: 200} |

## Leitura (GET)

- c=50: **797.3 req/s**, p50 54.9 ms, p95 115.3 ms, p99 184.9 ms, erros 0

## Mistura realista

- c=25: **99.1 req/s**, p95 623.3 ms, erros 0

| Operação | req | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| GET | 135 | 20.9 | 61.5 | 94.8 |
| POST epp execution | 138 | 112.9 | 256.8 | 310.1 |
| POST epp request | 138 | 623.3 | 1028.5 | 1124.6 |
| POST inválido | 138 | 13.4 | 68.5 | 129.4 |
| POST reenvio | 135 | 27.8 | 81.3 | 103.1 |
| POST retail | 832 | 295.8 | 514.6 | 597.4 |

## Estabilidade (soak)

- 60.27 s a c=25: **77.3 req/s**, p95 573.3 ms, erros 0, deriva do p95 (última/primeira janela) 1.06×
