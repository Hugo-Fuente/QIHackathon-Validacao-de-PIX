# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `598501d6` em 2026-10-18 08:36:38 · alvo `http://localhost:8000/pix/transaction` · duração total 214 s
- Total: **39571** requisições, **184.9 req/s** médios, p95 547.8 ms, p99 721.8 ms, erros inesperados 0 (0.0%)
- SLA usado: p95 ≤ 2000 ms e erros ≤ 1.0%


## Proximidade do critério SOLUÇÃO FUNCIONAL (visão do teste de carga)

| Dimensão | Nota | Situação | Itens |
|---|---|---|---|
| Corretude (idempotência, 409, lock, validação, GET, fluxo EPP) | 83.3% | perto | 20/24 |
| Desempenho (SLA p95 ≤ 2000 ms, sem degradação) | 75.0% | perto | 3/4 |

Este teste não valida se a decisão bate com as regras (isso é o `run_api_tests.py` / `audit_projeto.py --scenarios`) nem o padrão de código (`audit_projeto.py`). Passe o `summary.json` ao auditor com `--load-summary` para somar tudo em uma nota.

## O que falta ajustar

1. **hot** — todas as requisições da rajada retornam 201 (1 diferentes de 201)
   - Como resolver: Rajada do mesmo pagador: o lock do pagador precisa ser obtido na mesma transação que lê o histórico e grava; senão o R2 não dispara.
2. **hot** — concorrente == sequencial em todos os pagadores (lock evita ler histórico incompleto) (concorrente=[6] sequencial=[5, 6])
   - Como resolver: Rajada do mesmo pagador: o lock do pagador precisa ser obtido na mesma transação que lê o histórico e grava; senão o R2 não dispara.
3. **destination** — conta destino serializa o perfil: R9 dispara no quinto pagador (concorrente=1, sequencial=0)
   - Como resolver: Rajada por conta destino: a chave de lock da conta deve serializar a consulta agregada do R9 entre pagadores.
4. **destination** — todos os Pix da rajada são gravados ({'conc': 0, 'seq': 1})
   - Como resolver: Rajada por conta destino: a chave de lock da conta deve serializar a consulta agregada do R9 entre pagadores.
5. **soak** — sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação) (erros=0, p95 369.1→1063.2 ms)
   - Como resolver: Criar índices compostos (coluna, transaction_date) em source_document, destination_account_key, destination_document, device_id, company_id e author_id; trocar as consultas que trazem milhares de linhas para o Python por agregações em SQL (COUNT/SUM/MAX/percentile_cont com filtro de janela e LIMIT 20 para a mediana); conferir com EXPLAIN ANALYZE que não há Seq Scan; subir mais workers só depois disso.

## Verificações de corretude: 23/28 passaram

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
| hot | todas as requisições da rajada retornam 201 | ❌ | 1 diferentes de 201 |
| hot | concorrente == sequencial em todos os pagadores (lock evita ler histórico incompleto) | ❌ | concorrente=[6] sequencial=[5, 6] |
| hot | R2 acionado em 6 dos 10 Pix (do 5º em diante) | ✅ | observado=[6] |
| hot | contenção de um só pagador dentro do SLA (p95 ≤ 2000 ms) | ✅ | p95=823.5ms, 31.7 req/s |
| destination | conta destino serializa o perfil: R9 dispara no quinto pagador | ❌ | concorrente=1, sequencial=0 |
| destination | todos os Pix da rajada são gravados | ❌ | {'conc': 0, 'seq': 1} |
| execution | uma execução passa e as outras quatro acionam C1 | ✅ | sem C1=1, com C1=4, HTTP=[201, 201, 201, 201, 201] |
| execution | todas as execuções duplicadas recebem resposta normal | ✅ | HTTP=[201, 201, 201, 201, 201] |
| validation | amount ausente → 422 | ✅ | 200 req, p95=14.5ms, códigos={422: 200} |
| validation | amount negativo → 422 | ✅ | 200 req, p95=16.9ms, códigos={422: 200} |
| validation | amount decimal → 422 | ✅ | 200 req, p95=14.2ms, códigos={422: 200} |
| validation | data sem fuso → 422 | ✅ | 200 req, p95=14.6ms, códigos={422: 200} |
| validation | documento com 10 dígitos → 422 | ✅ | 200 req, p95=10.9ms, códigos={422: 200} |
| validation | context com event inválido → 422 | ✅ | 200 req, p95=14.7ms, códigos={422: 200} |
| validation | vote sem request_id → 422 | ✅ | 200 req, p95=14.1ms, códigos={422: 200} |
| validation | JSON malformado → 400 | ✅ | 200 req, p95=15.1ms, códigos={400: 200} |
| get | todo GET devolve a mesma key do POST (200) ou 404 se inexistente | ✅ | 11911 req, erros=0, p95=117.8ms |
| mixed | mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo) | ✅ | 2129 req, erros=0, 139.9 req/s, p95=398.1ms |
| mixed | mistura dentro do SLA (p95 ≤ 2000 ms) | ✅ | p95=398.1ms, 139.9 req/s |
| soak | sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação) | ❌ | erros=0, p95 369.1→1063.2 ms |

## Capacidade (degraus de concorrência)

| Concorrência | req/s | p50 ms | p95 ms | p99 ms | máx ms | erros % | no SLA |
|---|---|---|---|---|---|---|---|
| 1 | 53.3 | 16.9 | 24.8 | 38.2 | 155.1 | 0.0 | sim |
| 5 | 200.8 | 23.0 | 34.2 | 52.3 | 89.4 | 0.0 | sim |
| 10 | 205.7 | 43.9 | 79.8 | 125.7 | 387.8 | 0.0 | sim |
| 25 | 201.4 | 117.0 | 196.9 | 258.6 | 459.2 | 0.0 | sim |
| 50 | 171.1 | 274.3 | 491.9 | 593.7 | 789.8 | 0.0 | sim |
| 100 | 169.4 | 570.8 | 750.4 | 800.9 | 973.0 | 0.0 | sim |

**Capacidade sustentada dentro do SLA: 205.7 req/s** (concorrência 10). Pico bruto: 205.7 req/s (concorrência 10).

## Idempotência sob concorrência

- 50 rajadas × 20 requisições idênticas simultâneas = 1000 requisições
- Violações (≠ 1× 201 + resto 200 + uma key): **0**; keys duplicadas: **0**
- Latência na rajada: p50 57.3 ms · p95 111.5 ms · máx 328.2 ms

## Conflito (mesmo id, payload diferente)

- 50 rajadas · violações: **0** · erros 5xx/rede: **0**

## Rajada do mesmo pagador (corrida de histórico)

- 10 pagadores × 10 Pix simultâneos; R2 esperado em 6 por pagador
- R2 acionado, concorrente: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]` · sequencial: `[5, 6, 6, 6, 6, 6, 6, 6, 6, 6]`
- Contenção total (1 pagador, c=20): 31.7 req/s, p95 823.5 ms

## Concorrência por conta destino (R9)

- Acionamentos R9: concorrente 1 · sequencial 0 · esperado 1
- Respostas diferentes de 201: {'conc': 0, 'seq': 1}

## Execuções repetidas do mesmo pedido (C1)

- Execuções sem C1: 1 · execuções rejeitadas por C1: 4
- Status HTTP: [201, 201, 201, 201, 201]

## Validação sob carga

| Caso | req | p95 ms | códigos |
|---|---|---|---|
| amount ausente → 422 | 200 | 14.5 | {422: 200} |
| amount negativo → 422 | 200 | 16.9 | {422: 200} |
| amount decimal → 422 | 200 | 14.2 | {422: 200} |
| data sem fuso → 422 | 200 | 14.6 | {422: 200} |
| documento com 10 dígitos → 422 | 200 | 10.9 | {422: 200} |
| context com event inválido → 422 | 200 | 14.7 | {422: 200} |
| vote sem request_id → 422 | 200 | 14.1 | {422: 200} |
| JSON malformado → 400 | 200 | 15.1 | {400: 200} |

## Leitura (GET)

- c=50: **792.3 req/s**, p50 58.0 ms, p95 117.8 ms, p99 175.0 ms, erros 0

## Mistura realista

- c=25: **139.9 req/s**, p95 398.1 ms, erros 0

| Operação | req | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| GET | 191 | 60.7 | 132.7 | 409.5 |
| POST epp execution | 194 | 165.9 | 304.9 | 673.6 |
| POST epp request | 194 | 306.5 | 652.5 | 865.3 |
| POST inválido | 194 | 50.7 | 127.9 | 417.3 |
| POST reenvio | 191 | 83.2 | 204.0 | 427.2 |
| POST retail | 1165 | 172.5 | 406.1 | 610.1 |

## Estabilidade (soak)

- 60.92 s a c=25: **136.3 req/s**, p95 300.5 ms, erros 0, deriva do p95 (última/primeira janela) 2.88×
