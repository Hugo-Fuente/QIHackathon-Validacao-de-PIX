# Teste de histórico e log — execução histcfd343e3

Pagador de teste: documento 70047319982, conta 82763405. 11 Pix, 4 com rejeição forçada (C1).

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

  não     GET /pix/transaction?source_document=70047319982  -> 405
  não     GET /pix/transaction?document=70047319982  -> 405
  não     GET /pix/transaction?payer_document=70047319982  -> 405
  não     GET /pix/transaction?status=rejected&document=70047319982  -> 405
  não     GET /pix/history/70047319982  -> 404
  não     GET /pix/history?document=70047319982  -> 404
  não     GET /pix/users/70047319982/history  -> 404
  não     GET /pix/users/70047319982/transactions  -> 404
  não     GET /pix/accounts/82763405/transactions  -> 404
  não     GET /pix/transactions?document=70047319982  -> 404
  não     GET /pix/transaction/history?document=70047319982  -> 404
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
  histcfd343e3-u-0  | 2026-10-18 11:17:45+00 | 15000 | 46123997882 | approved | 0     
  histcfd343e3-u-1  | 2026-10-18 11:20:47+00 | 20000 | 12376171670 | rejected | 0     
  histcfd343e3-u-2  | 2026-10-18 11:22:48+00 | 18000 | 60053063463 | approved | 0     
  histcfd343e3-u-3  | 2026-10-18 11:27:48+00 | 22000 | 10451352403 | approved | 0     
  histcfd343e3-u-4  | 2026-10-18 11:32:48+00 | 17000 | 51286002311 | approved | 0     
  histcfd343e3-u-5  | 2026-10-18 11:37:48+00 | 25000 | 71029375129 | approved | 0     
  histcfd343e3-u-6  | 2026-10-18 11:42:48+00 | 21000 | 13695718843 | rejected | 0     
  histcfd343e3-u-7  | 2026-10-18 11:52:48+00 | 19000 | 23913653430 | rejected | 0     
  histcfd343e3-u-8  | 2026-10-18 12:02:48+00 | 23000 | 17674563182 | rejected | 0     
  histcfd343e3-u-9  | 2026-10-18 12:04:48+00 | 16000 | 90611960391 | approved | 0     
  histcfd343e3-u-10 | 2026-10-18 12:10:49+00 | 24000 | 73188231078 | approved | 0     
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
