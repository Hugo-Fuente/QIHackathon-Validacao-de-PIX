# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)

- Rodada `d04333c6` em 2026-10-18 06:45:41 · alvo `http://127.0.0.1:3002/pix/transaction` · duração total 48 s
- Total: **132** requisições, **2.7 req/s** médios, p95 5137.5 ms, p99 5166.0 ms, erros inesperados 0 (0.0%)
- SLA usado: p95 ≤ 2000.0 ms e erros ≤ 1.0%

## Verificações de corretude: 7/7 passaram

| Fase | Verificação | Resultado | Detalhe |
|---|---|---|---|
| smoke | POST válido devolve 201 com key e status | ✅ | http 201 |
| smoke | reenvio idêntico devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET devolve 200 com a mesma key | ✅ | http 200 |
| smoke | GET de id inexistente devolve 404 | ✅ | http 404 |
| hot | todas as requisições da rajada retornam 201 | ✅ | 0 diferentes de 201 |
| hot | concorrente == sequencial em todos os pagadores (lock evita ler histórico incompleto) | ✅ | concorrente=[6] sequencial=[6] |
| hot | R2 acionado em 6 dos 10 Pix (do 5º em diante) | ✅ | observado=[6] |

## Rajada do mesmo pagador (corrida de histórico)

- 10 pagadores × 10 Pix simultâneos; R2 esperado em 6 por pagador
- R2 acionado, concorrente: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]` · sequencial: `[6, 6, 6, 6, 6, 6, 6, 6, 6, 6]`
- Contenção total (1 pagador, c=20): 7.6 req/s, p95 5137.5 ms

## Configuração de execução

- CPU disponível: 8 CPUs lógicas visíveis ao host e ao Docker.
- API: container Docker temporário, Uvicorn com 2 workers, sem `--reload`, na porta 3002.
- Gerador: processo Python no host; API e gerador ficaram na mesma máquina e compartilham as 8 CPUs.
- Pool SQLAlchemy por worker: `pool_size=10`, `max_overflow=30` (até 40 conexões por worker; 80 para os 2 workers), `pool_recycle=600`, `pool_pre_ping=True`.
- PostgreSQL: `max_connections=100`.
- SLA: p95 ≤ 2000 ms; erro máximo configurado em 1%.
- O runner anexado não envia `INTERNAL-TOKEN`; usei uma cópia temporária com esse cabeçalho para autenticar na API. O arquivo original não foi alterado.
