# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `1fa16791` em 2026-10-18 08:35:35 · alvo `http://localhost:8000/pix/transaction` · duração total 1 s
- Total: **0** requisições, **0.0 req/s** médios, p95 0.0 ms, p99 0.0 ms, erros inesperados 0 (0%)
- SLA usado: p95 ≤ 2000 ms e erros ≤ 1.0%


## Proximidade do critério SOLUÇÃO FUNCIONAL (visão do teste de carga)

| Dimensão | Nota | Situação | Itens |
|---|---|---|---|
| Corretude (idempotência, 409, lock, validação, GET, fluxo EPP) | 100.0% | pronto | 8/8 |
| Desempenho (SLA p95 ≤ 2000 ms, sem degradação) | - | sem dados | 0/0 |

Este teste não valida se a decisão bate com as regras (isso é o `run_api_tests.py` / `audit_projeto.py --scenarios`) nem o padrão de código (`audit_projeto.py`). Passe o `summary.json` ao auditor com `--load-summary` para somar tudo em uma nota.

## O que falta ajustar

- Nada pendente nas fases executadas.

Fases não executadas nesta rodada (a nota não as cobre): ramp, idempotency, conflict, hot, validation, get, mixed, soak.

## Verificações de corretude: 8/8 passaram

| Fase | Verificação | Resultado | Detalhe |
|---|---|---|---|
| smoke | POST válido devolve 201 com key e status | ✅ | http 201 |
| smoke | reenvio idêntico devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET de id inexistente devolve 404 | ✅ | http 404 |
| destination | conta destino serializa o perfil: R9 dispara no quinto pagador | ✅ | concorrente=1, sequencial=1 |
| destination | todos os Pix da rajada são gravados | ✅ | {'conc': 0, 'seq': 0} |
| execution | uma execução passa e as outras quatro acionam C1 | ✅ | sem C1=1, com C1=4, HTTP=[201, 201, 201, 201, 201] |
| execution | todas as execuções duplicadas recebem resposta normal | ✅ | HTTP=[201, 201, 201, 201, 201] |

## Concorrência por conta destino (R9)

- Acionamentos R9: concorrente 1 · sequencial 1 · esperado 1
- Respostas diferentes de 201: {'conc': 0, 'seq': 0}

## Execuções repetidas do mesmo pedido (C1)

- Execuções sem C1: 1 · execuções rejeitadas por C1: 4
- Status HTTP: [201, 201, 201, 201, 201]
