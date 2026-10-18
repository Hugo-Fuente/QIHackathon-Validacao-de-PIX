# Planos de histórico após a carga

Tabela após `ANALYZE`: 111.755 linhas, 147 MB. Foram usados `EXPLAIN (ANALYZE, BUFFERS)`; nenhum plano abaixo contém `Seq Scan` em `pix_transactions`.

| Consulta representativa | Plano escolhido | Tempo observado |
|---|---|---:|
| Pagador + intervalo de 180 dias | `Index Only Scan` — `ix_pix_transactions_source_destination_account_date` | 0,145 ms |
| Conta destino + 60 min | `Index Scan` — `ix_pix_transactions_destination_account_date` | 0,435 ms |
| Documento destino + 60 min | `Index Only Scan` — `ix_pix_transactions_destination_date` | 0,460 ms |
| Dispositivo + 24 h | `Index Scan` — `ix_pix_transactions_device_date` | 0,266 ms |
| Empresa + 90 dias | `Index Scan` — `ix_pix_transactions_company_date` | 0,223 ms |
| Autor + 24 h | `Index Scan` — `ix_pix_transactions_author_date` | 0,143 ms |
| Pagador + documento destino + 180 dias | `Index Scan` — `ix_pix_transactions_source_destination_account_date`; documento destino aplicado como filtro | 0,245 ms |
| `request_id` de execução + intervalo | `Index Scan` — `ix_pix_transactions_request_date` | 0,106 ms |
| Contagem de pagadores recentes, 24 h | `Index Only Scan` — `ix_pix_transactions_outflow_date_source` | 173,157 ms |
| Documento de parceiro em JSONB + pedido + 30 dias | `Bitmap Index Scan` — `ix_pix_transactions_partner_documents_gin` | 0,682 ms |

O índice dedicado `ix_pix_transactions_source_destination_date` existe e foi aplicado pela migration 002. Para o par observado, o planner escolheu o índice por conta destino e filtrou `destination_document`; essa busca retornou 14 linhas em 0,245 ms. A consulta ampla de pagadores recentes também ficou indexada, mas a agregação sobre 108.319 eventos usou mais buffers e demorou 173 ms.
