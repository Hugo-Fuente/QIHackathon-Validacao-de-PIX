# Teste de histórico e log — execução histbd895cfd

Pagador de teste: documento 80060527688, conta 68044840. 11 Pix, 4 com rejeição forçada (C1).

## 1. Cada Pix recebido fica gravado e consultável?

  #  | quando  | valor | forçado C1 | POST | status   | GET | status no GET
  ---+---------+-------+------------+------+----------+-----+--------------
  0  | -55 min | 15000 | não        | 201  | approved | 200 | approved     
  1  | -52 min | 20000 | sim        | 201  | rejected | 200 | rejected     
  2  | -50 min | 18000 | não        | 201  | approved | 200 | approved     
  3  | -45 min | 22000 | não        | 201  | approved | 200 | approved     
  4  | -40 min | 17000 | não        | 201  | approved | 200 | approved     
  5  | -35 min | 25000 | não        | 201  | approved | 200 | approved     
  6  | -30 min | 21000 | sim        | 201  | rejected | 200 | rejected     
  7  | -20 min | 19000 | sim        | 201  | rejected | 200 | rejected     
  8  | -10 min | 23000 | sim        | 201  | rejected | 200 | rejected     
  9  | -8 min  | 16000 | não        | 201  | approved | 200 | approved     
  10 | -2 min  | 24000 | não        | 201  | approved | 200 | approved     

  [OK] todos os POSTs devolveram 201 — códigos=[201]
  [OK] todos os Pix (inclusive rejeitados) respondem GET 200 com a mesma key — 11/11 com GET 200
  [OK] o status do GET é igual ao do POST (a decisão fica gravada, não é recalculada)
  [OK] C1 rejeitou todos os Pix forçados (execução sem pedido) — status=['rejected', 'rejected', 'rejected', 'rejected']

## 2. A API expõe histórico por usuário?

  não     GET /pix/transaction?source_document=80060527688  -> 405
  não     GET /pix/transaction?document=80060527688  -> 405
  não     GET /pix/transaction?payer_document=80060527688  -> 405
  não     GET /pix/transaction?status=rejected&document=80060527688  -> 405
  não     GET /pix/history/80060527688  -> 404
  não     GET /pix/history?document=80060527688  -> 404
  não     GET /pix/users/80060527688/history  -> 404
  não     GET /pix/users/80060527688/transactions  -> 404
  não     GET /pix/accounts/68044840/transactions  -> 404
  não     GET /pix/transactions?document=80060527688  -> 404
  não     GET /pix/transaction/history?document=80060527688  -> 404
  [N/A] existe endpoint que devolve o histórico de um usuário — nenhum dos caminhos comuns devolveu os Pix do pagador

## 3. Histórico no banco (rejeições por janela e movimentação de dinheiro)

  [OK] tabelas pix_transaction, fraud_analysis e rule_hit existem — achadas=['fraud_analysis', 'pix_transaction', 'rule_hit']
  pix_transactions: id, amount, transaction_date, source_document, destination_document, payload, created_at
  fraud_analysis: key, transaction_id, status, risk_score, metadata, created_at
  rule_hits: id, analysis_key, rule_code, points, detail
  [OK] colunas necessárias identificadas (id, data, valor, pagador, status, ligação) — ok

### Extrato do pagador (movimentação de dinheiro, ordem cronológica)

  id                | quando                 | valor | destino     | status   | pontos
  ------------------+------------------------+-------+-------------+----------+-------
  histbd895cfd-u-0  | 2026-10-18 11:22:06+00 | 15000 | 79094160797 | approved | 0     
  histbd895cfd-u-1  | 2026-10-18 11:25:08+00 | 20000 | 61210636994 | rejected | 0     
  histbd895cfd-u-2  | 2026-10-18 11:27:08+00 | 18000 | 71738950385 | approved | 0     
  histbd895cfd-u-3  | 2026-10-18 11:32:08+00 | 22000 | 27274392046 | approved | 0     
  histbd895cfd-u-4  | 2026-10-18 11:37:08+00 | 17000 | 79835447382 | approved | 0     
  histbd895cfd-u-5  | 2026-10-18 11:42:08+00 | 25000 | 46929507246 | approved | 0     
  histbd895cfd-u-6  | 2026-10-18 11:47:09+00 | 21000 | 31452481902 | rejected | 0     
  histbd895cfd-u-7  | 2026-10-18 11:57:09+00 | 19000 | 83998237246 | rejected | 0     
  histbd895cfd-u-8  | 2026-10-18 12:07:09+00 | 23000 | 41934669920 | rejected | 0     
  histbd895cfd-u-9  | 2026-10-18 12:09:09+00 | 16000 | 94973509611 | approved | 0     
  histbd895cfd-u-10 | 2026-10-18 12:15:09+00 | 24000 | 22728294323 | approved | 0     
  [OK] todo Pix enviado está no banco com decisão (status) associada — 11 linhas no banco para 11 enviados
  [OK] o status gravado no banco é o mesmo devolvido pela API
  [OK] o pagador de teste não vê Pix de outro usuário (isolamento) — 11 linhas, todas do pagador de teste

### Rejeitado X vezes em Y minutos (janela contada a partir do último Pix do pagador)

  [OK] rejeições nos últimos 15 min batem com o que a API respondeu — API=1, banco=1
  [OK] rejeições nos últimos 30 min batem com o que a API respondeu — API=3, banco=3
  [OK] rejeições nos últimos 60 min batem com o que a API respondeu — API=4, banco=4
  janela | esperado (API) | banco | resultado
  -------+----------------+-------+----------
  15 min | 1              | 1     | OK       
  30 min | 3              | 3     | OK       
  60 min | 4              | 4     | OK       

Consulta para usar no dia a dia (troque o documento e a janela):

```sql
SELECT count(*) FROM pix_transactions t LEFT JOIN fraud_analysis a ON a.transaction_id = t.id
WHERE t.source_document = '<documento>' AND a.status = 'rejected'
  AND t.transaction_date > now() - interval '60 minutes';
```

### Totais por decisão

  status   | qtde | soma dos valores
  ---------+------+-----------------
  approved | 7    | 137000          
  rejected | 4    | 83000           
  [OK] soma dos valores no banco = soma enviada — enviado=220000, banco=220000.0
  [OK] rejeitados têm pelo menos 1 rule_hit gravado (explica o porquê da decisão) — rule_hits dos rejeitados=[1, 1, 1, 1]

## Resumo

14 OK, 0 falha(s), 1 não verificado(s).

Não verificados:
- existe endpoint que devolve o histórico de um usuário: nenhum dos caminhos comuns devolveu os Pix do pagador → não é exigido pelo contrato (POST + GET por id). Só crie se o enunciado pedir; o histórico já pode ser consultado no banco (seção 3)
