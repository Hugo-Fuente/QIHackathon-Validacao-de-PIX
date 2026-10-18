# Teste de carga — Motor antifraude Pix (rodada parcial)

- Rodada: `1eaacbd0`
- Alvo: `http://127.0.0.1:3002/pix/transaction`
- Resultado: ramp concluído; execução interrompida na primeira rajada de idempotência depois de uma espera prolongada por lock advisory no PostgreSQL.
- O gerador ficou aguardando. O PostgreSQL mostrou uma transação `idle in transaction` por mais de 438 s e requisições aguardando o mesmo lock. Encerrei o gerador e o container temporário; depois disso não restaram locks ativos da rodada.
- Como o script só grava os artefatos ao terminar todas as fases, esta rodada parcial não tem CSV nem relatório JSON original.

## Configuração

- CPU disponível: 8 CPUs lógicas visíveis ao host e ao Docker.
- API: container Docker temporário, Uvicorn com 2 workers, sem `--reload`, na porta 3002.
- Gerador: processo Python no host; API e gerador ficaram na mesma máquina e compartilham as 8 CPUs.
- Pool SQLAlchemy por worker: `pool_size=10`, `max_overflow=30` (até 40 conexões por worker; 80 para os 2 workers), `pool_recycle=600`, `pool_pre_ping=True`.
- PostgreSQL: `max_connections=100`.
- SLA: p95 ≤ 2000 ms; erro máximo configurado em 1%.
- O runner anexado não envia `INTERNAL-TOKEN`; usei uma cópia temporária com esse cabeçalho para autenticar na API. O arquivo original não foi alterado.

## Ramp de concorrência

| Concorrência | req/s | p50 (ms) | p95 (ms) | p99 (ms) | Erros | SLA |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 14.3 | 70.3 | 94.2 | 150.2 | 0% | dentro |
| 5 | 21.4 | 243.3 | 317.0 | 354.3 | 0% | dentro |
| 10 | 18.7 | 400.8 | 938.3 | 987.3 | 0% | dentro |
| 25 | 16.7 | 1534.2 | 1846.0 | 1875.0 | 0% | dentro |
| 50 | 15.4 | 3240.8 | 3577.3 | 3781.1 | 0% | fora |
| 100 | 13.2 | 7498.7 | 11025.1 | 12036.7 | 0% | fora |

Maior vazão observada dentro do SLA: **21.4 req/s em concorrência 5**. O degrau 25 também ficou dentro do limite de p95, com vazão menor.

## Fases não concluídas

A rodada parou no primeiro storm de idempotência, antes das fases conflict, hot, validation, get, mixed e soak. A fase hot foi executada separadamente e está no [relatório R2](../load_test_20261018_hot_01/report.md).
