# Ambiente da rodada complete_04

## API, carga e conexões

- API executada em Docker Compose com `/private/tmp/compose.prod.override.yml`; Uvicorn com 2 workers, sem `--reload`.
- Host: 8 CPUs lógicas. O container não tem cota nem afinidade de CPU configurada (`NanoCpus=0`, `CpusetCpus` vazio). O gerador rodou no host, na mesma máquina; portanto, esta rodada usa a API em Docker, mas não tem isolamento físico de CPU.
- SQLAlchemy por worker: `pool_size=10`, `max_overflow=10`, até 20 conexões por worker e 40 no total. PostgreSQL: `max_connections=100`.
- Nas conexões da aplicação: `lock_timeout=5000 ms` e `idle_in_transaction_session_timeout=15000 ms`, enviados pelo `connect_args` do SQLAlchemy.
- SLA da carga: p95 ≤ 2.000 ms; fase soak: 60 s, concorrência 25.

## Banco e volume

- Banco não foi limpo. Antes da rodada: 98.540 linhas e 129 MB em `pix_transactions`.
- Após a carga e a auditoria: 111.755 linhas e 147 MB. O volume ficou registrado para contextualizar a comparação.
- Após a carga: executados `ANALYZE pix_transactions` e `ANALYZE fraud_analysis`.
- Plano de produção usado: dois workers; pool máximo teórico de 40 conexões para `max_connections=100`.

## Resultado resumido

- 26.693 requisições em 223,26 s; 119,6 req/s; erros 0%; p95 926,4 ms; p99 1.494,9 ms.
- Ramp dentro do SLA até concorrência 50 (p95 1.192,6 ms); em concorrência 100, p95 2.195,9 ms.
- Capacidade medida dentro do SLA: 88,5 req/s a concorrência 25, p95 492,7 ms.
- Hot payer: 10/10 grupos tiveram os mesmos 6 acionamentos de R2 no paralelo e no sequencial; p95 da contenção de um pagador 1.355,1 ms.
- R9 paralelo e sequencial tiveram um acionamento cada; para o mesmo `request_id`, uma execução passou e quatro acionaram C1.
- Mixed: p95 623,3 ms, sem erros. Soak: p95 573,3 ms, sem erros; as janelas inicial/final foram 633,3/669,1 ms (drift 1,06×).

Relatórios: [carga](report.md), [resumo JSON](summary.json), [auditoria completa](../audit_report_complete_04.md).
