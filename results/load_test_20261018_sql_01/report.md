# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `1257649e` em 2026-10-18 07:47:51 · alvo `http://localhost:8000/pix/transaction` · duração total 75 s
- Total: **22308** requisições, **295.9 req/s** médios, p95 179.2 ms, p99 288.0 ms, erros inesperados 0 (0.0%)
- SLA usado: p95 ≤ 2000 ms e erros ≤ 1.0%

## Verificações de corretude: 5/6 passaram

| Fase | Verificação | Resultado | Detalhe |
|---|---|---|---|
| smoke | POST válido devolve 201 com key e status | ✅ | http 201 |
| smoke | reenvio idêntico devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET de id inexistente devolve 404 | ✅ | http 404 |
| mixed | mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo) | ✅ | 6328 req, erros=0, 420.5 req/s, p95=128.7ms |
| soak | sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação) | ❌ | erros=0, p95 119.2→319.6 ms |

## Mistura realista

- c=25: **420.5 req/s**, p95 128.7 ms, erros 0

| Operação | req | p50 ms | p95 ms | p99 ms |
|---|---|---|---|---|
| GET | 572 | 26.9 | 66.6 | 100.5 |
| POST epp execution | 576 | 71.2 | 139.0 | 173.9 |
| POST epp request | 576 | 61.8 | 136.4 | 179.3 |
| POST inválido | 575 | 18.7 | 54.7 | 97.7 |
| POST reenvio | 573 | 46.9 | 98.1 | 139.0 |
| POST retail | 3456 | 60.6 | 137.4 | 185.6 |

## Estabilidade (soak)

- 60.04 s a c=25: **266.1 req/s**, p95 196.8 ms, erros 0, deriva do p95 (última/primeira janela) 2.68×
