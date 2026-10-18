# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `777bd4fd` em 2026-10-18 07:21:20 · alvo `http://localhost:8000/pix/transaction` · duração total 143 s
- Total: **15123** requisições, **105.8 req/s** médios, p95 130.8 ms, p99 5023.3 ms, erros inesperados 0 (0.0%)
- SLA usado: p95 ≤ 2000 ms e erros ≤ 1.0%

## Verificações de corretude: 17/18 passaram

| Fase | Verificação | Resultado | Detalhe |
|---|---|---|---|
| smoke | POST válido devolve 201 com key e status | ✅ | http 201 |
| smoke | reenvio idêntico devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET de id inexistente devolve 404 | ✅ | http 404 |
| idempotency | 50 rajadas: exatamente 1x 201, o resto 200, uma única key | ✅ | 0 violações; timeouts=0 |
| conflict | 1 vencedor; mesmo payload = 200; payload diferente = 409; uma key | ✅ | 0 violações |
| conflict | nenhum 5xx nem erro de rede (violação de UNIQUE não pode vazar) | ✅ | 0 erros |
| validation | amount ausente → 422 | ✅ | 200 req, p95=15.3ms, códigos={422: 200} |
| validation | amount negativo → 422 | ✅ | 200 req, p95=8.6ms, códigos={422: 200} |
| validation | amount decimal → 422 | ✅ | 200 req, p95=9.3ms, códigos={422: 200} |
| validation | data sem fuso → 422 | ✅ | 200 req, p95=21.5ms, códigos={422: 200} |
| validation | documento com 10 dígitos → 422 | ✅ | 200 req, p95=8.0ms, códigos={422: 200} |
| validation | context com event inválido → 422 | ✅ | 200 req, p95=9.7ms, códigos={422: 200} |
| validation | vote sem request_id → 422 | ✅ | 200 req, p95=11.5ms, códigos={422: 200} |
| validation | JSON malformado → 400 | ✅ | 200 req, p95=12.1ms, códigos={400: 200} |
| get | todo GET devolve a mesma key do POST (200) ou 404 se inexistente | ✅ | 13143 req, erros=0, p95=108.0ms |
| mixed | mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo) | ✅ | 101 req, erros=0, 6.0 req/s, p95=7693.5ms |
| soak | sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação) | ❌ | erros=0, p95 5050.2→10678.0 ms |

## Idempotência sob concorrência

- 50/50 rajadas concluídas × 20 requisições idênticas = 1000 chamadas registradas
- Rajadas com timeout: 0 · interrompido: não
- Violações (≠ 1× 201 + resto 200 + uma key): **0**; keys duplicadas: **0**
- Latência na rajada: p50 176.0 ms · p95 307.1 ms · máx 387.2 ms

## Conflito (mesmo id, payload diferente)

- 50/50 rajadas concluídas · violações: **0** · erros 5xx/rede: **0**
- Rajadas com timeout: 0 · interrompido: não

## Validação sob carga

| Caso | req | p95 ms | códigos |
|---|---|---|---|
| amount ausente → 422 | 200 | 15.3 | {422: 200} |
| amount negativo → 422 | 200 | 8.6 | {422: 200} |
| amount decimal → 422 | 200 | 9.3 | {422: 200} |
| data sem fuso → 422 | 200 | 21.5 | {422: 200} |
| documento com 10 dígitos → 422 | 200 | 8.0 | {422: 200} |
| context com event inválido → 422 | 200 | 9.7 | {422: 200} |
| vote sem request_id → 422 | 200 | 11.5 | {422: 200} |
| JSON malformado → 400 | 200 | 12.1 | {400: 200} |

## Leitura (GET)

- c=50: **873.9 req/s**, p50 52.9 ms, p95 108.0 ms, p99 182.5 ms, erros 0

## Mistura realista

- c=25: **6.0 req/s**, p95 7693.5 ms, erros 0

| Operação | req | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| GET | 6 | 609.0 | 983.1 | 983.1 |
| POST epp execution | 10 | 3896.5 | 4756.0 | 4756.0 |
| POST epp request | 10 | 4625.8 | 7697.9 | 7697.9 |
| POST inválido | 9 | 21.8 | 818.1 | 818.1 |
| POST reenvio | 6 | 1276.0 | 2272.3 | 2272.3 |
| POST retail | 60 | 4355.7 | 7698.9 | 7773.9 |

## Estabilidade (soak)

- 61.14 s a c=25: **4.6 req/s**, p95 9536.7 ms, erros 0, deriva do p95 (última/primeira janela) 2.11×
