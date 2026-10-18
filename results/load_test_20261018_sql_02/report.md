# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `e74e29a6` em 2026-10-18 07:52:47 · alvo `http://localhost:8000/pix/transaction` · duração total 75 s
- Total: **18325** requisições, **242.7 req/s** médios, p95 172.1 ms, p99 242.3 ms, erros inesperados 0 (0.0%)
- SLA usado: p95 ≤ 2000 ms e erros ≤ 1.0%


## Proximidade do critério SOLUÇÃO FUNCIONAL (visão do teste de carga)

| Dimensão | Nota | Situação | Itens |
|---|---|---|---|
| Corretude (idempotência, 409, lock, validação, GET, fluxo EPP) | 100.0% | pronto | 5/5 |
| Desempenho (SLA p95 ≤ 2000 ms, sem degradação) | 100.0% | pronto | 2/2 |

Este teste não valida se a decisão bate com as regras (isso é o `run_api_tests.py` / `audit_projeto.py --scenarios`) nem o padrão de código (`audit_projeto.py`). Passe o `summary.json` ao auditor com `--load-summary` para somar tudo em uma nota.

## O que falta ajustar

- Nada pendente nas fases executadas.

Fases não executadas nesta rodada (a nota não as cobre): ramp, idempotency, conflict, hot, validation, get.

## Verificações de corretude: 7/7 passaram

| Fase | Verificação | Resultado | Detalhe |
|---|---|---|---|
| smoke | POST válido devolve 201 com key e status | ✅ | http 201 |
| smoke | reenvio idêntico devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET de id inexistente devolve 404 | ✅ | http 404 |
| mixed | mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo) | ✅ | 4558 req, erros=0, 302.4 req/s, p95=174.8ms |
| mixed | mistura dentro do SLA (p95 ≤ 2000 ms) | ✅ | p95=174.8ms, 302.4 req/s |
| soak | sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação) | ✅ | erros=0, p95 176.0→97.4 ms |

## Mistura realista

- c=25: **302.4 req/s**, p95 174.8 ms, erros 0

| Operação | req | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| GET | 411 | 34.2 | 85.5 | 122.9 |
| POST epp execution | 415 | 96.2 | 176.8 | 253.6 |
| POST epp request | 415 | 89.3 | 182.4 | 245.4 |
| POST inválido | 415 | 23.9 | 68.8 | 131.0 |
| POST reenvio | 412 | 56.4 | 114.8 | 149.5 |
| POST retail | 2490 | 87.2 | 190.8 | 254.2 |

## Estabilidade (soak)

- 60.07 s a c=25: **229.2 req/s**, p95 170.8 ms, erros 0, deriva do p95 (última/primeira janela) 0.55×
