# Auditoria do projeto — Grupo 27

Gerado em 2026-10-18 07:57. Análise estática é heurística: aponta onde olhar.

| Critério | FAIL | WARN | OK |
|---|---|---|---|
| PADRÃO DE CÓDIGO | 2 | 4 | 21 |
| SOLUÇÃO FUNCIONAL | 1 | 0 | 20 |

## Proximidade dos critérios

| Critério | Nota | Situação | FAIL | WARN |
|---|---|---|---|---|
| PADRÃO DE CÓDIGO | 85.2% | perto | 2 | 4 |
| SOLUÇÃO FUNCIONAL | 95.2% | pronto para entregar | 1 | 0 |

Nota = (itens OK + 0,5 × itens WARN) ÷ itens avaliados. INFO não conta. É heurística: ordena o trabalho, não substitui a revisão do time.

## Nota única combinada

**8,96/10 (89,6%)** — cálculo sobre os 48 itens pontuados dos dois critérios, com o mesmo peso por item; corresponde a 43 pontos de 48 possíveis.

## O que falta ajustar (FAIL primeiro, depois WARN)

1. **[FAIL] PADRÃO DE CÓDIGO** — camada 'rule' não encontrada (pastas/arquivos esperados: ['regras', 'rules'])
   - Como resolver: Criar a pasta/arquivo da camada ou ajustar --layers para os nomes reais (resources/controllers/repositories/rules).
2. **[FAIL] PADRÃO DE CÓDIGO** — serviço não tem SQL nem conexão direta ao banco
   - Como resolver: Mover Session/query/SQL do controller para um repositório; o controller recebe o repositório por injeção.
   - Evidência: `src/controllers/pix_engine_v7.py:8 import sqlalchemy.orm`
3. **[FAIL] SOLUÇÃO FUNCIONAL** — as 3 tabelas do diagrama existem no código/migrations
   - Como resolver: Criar as tabelas pix_transaction, fraud_analysis e rule_hit conforme o diagrama da RFC v7.
   - Evidência: `fraud_analysis`
4. **[WARN] PADRÃO DE CÓDIGO** — serviço não levanta HTTPException (confirmar o padrão do Base Service)
   - Como resolver: Revisar o item e os locais listados no detalhe.
   - Evidência: `src/controllers/pix_controller.py:23`
   - Evidência: `src/controllers/pix_engine_v7.py:134`
5. **[WARN] PADRÃO DE CÓDIGO** — pg_advisory_xact_lock só no repositório/camada de dados
   - Como resolver: Revisar o item e os locais listados no detalhe.
   - Evidência: `src/controllers/pix_engine_v7.py:1`
6. **[WARN] PADRÃO DE CÓDIGO** — cada regra (R1–R33, C1) é citada em algum teste
   - Como resolver: Escrever um teste unitário por regra, com borda abaixo/acima do limite (ver README, 'casos de borda').
   - Evidência: `R1`
   - Evidência: `R2`
   - Evidência: `R3`
7. **[WARN] PADRÃO DE CÓDIGO** — há testes unitários das regras, sem banco (arquivos *rule*/*regra* em tests)
   - Como resolver: Criar tests/test_rules_*.py chamando as funções puras sem banco.

## PADRÃO DE CÓDIGO

- **INFO** arquivos .py por camada: route=2, service=3, repo=3, rule=0, test=30, other=28
- **FAIL** camada 'rule' não encontrada (pastas/arquivos esperados: ['regras', 'rules'])
- **OK** rota não acessa banco nem tem SQL
- **OK** rota não chama regras direto (deve passar pelo serviço)
- **OK** rota não importa repositório direto
- **FAIL** serviço não tem SQL nem conexão direta ao banco
  - `src/controllers/pix_engine_v7.py:8 import sqlalchemy.orm`
- **WARN** serviço não levanta HTTPException (confirmar o padrão do Base Service)
  - `src/controllers/pix_controller.py:23`
  - `src/controllers/pix_engine_v7.py:134`
- **OK** repositório não conhece HTTP/FastAPI
- **OK** repositório não importa regras (só persiste e consulta)
- **OK** regras puras: sem framework, banco ou SQL
- **OK** regras puras: sem relógio do sistema (usar transaction_date do evento)
- **OK** regras sem números mágicos (limites/janelas vêm de rule_parameter ou constantes nomeadas)
- **OK** commit/rollback concentrados em um ponto (uma transação por requisição)
- **WARN** pg_advisory_xact_lock só no repositório/camada de dados
  - `src/controllers/pix_engine_v7.py:1`
- **OK** existem testes (30 arquivos)
- **INFO** 78 funções de teste
- **OK** todo teste tem asserção
- **WARN** cada regra (R1–R33, C1) é citada em algum teste
  - `R1`
  - `R2`
  - `R3`
  - `R4`
  - `R5`
  - `R6`
  - `R7`
  - `R8`
  - `R9`
  - `R10`
  - `R11`
  - `R12`
  - `R13`
  - `R14`
  - `R15`
  - … e mais 19
- **OK** há teste de idempotência (reenvio 200 / conflito 409)
- **OK** há teste de validação 422/400
- **OK** há teste de concorrência (threads/asyncio.gather/ThreadPool)
- **OK** há teste de GET 404
- **WARN** há testes unitários das regras, sem banco (arquivos *rule*/*regra* em tests)
- **OK** existe README.md
- **OK** existe Dockerfile
- **OK** existe docker-compose
- **OK** existe dependências
- **OK** existe .env.example
- **OK** esquema do banco versionado (migrations/SQL)
- **INFO** COMPARE MANUALMENTE com o Base Service: estrutura de pastas, nomes, injeção de dependência, tratamento de erro e config. O script não tem acesso a ele.

## SOLUÇÃO FUNCIONAL

- **OK** README traz comandos para subir o projeto
  - `# sobe a API e o PostgreSQL`
  - `curl -X POST http://localhost:8000/pix/transaction \`
  - `curl http://localhost:8000/pix/transaction/pix-000123`
  - `docker compose run --rm api pytest`
- **OK** README explica Docker/Compose
- **FAIL** as 3 tabelas do diagrama existem no código/migrations
  - `fraud_analysis`
- **OK** todas as regras (R1–R33, C1) aparecem no código
- **OK** há UNIQUE no banco (barreira de idempotência)
- **OK** payload_hash é calculado/gravado (distingue reenvio de reuso do id)
- **OK** índices secundários para o histórico (RFC: coluna + transaction_date)
- **OK** API responde em http://localhost:8000/pix/transaction
- **OK** POST devolve 201 com key e status (http 201)
- **OK** Pix gravado e consultável: GET devolve a mesma key (http 200)
- **OK** GET de id inexistente devolve 404 (http 404)
- **OK** dado sobrevive ao restart (http 200)
- **OK** decisões batem com as regras: 49/49 cenários do pix_api_tests.json
- **OK** todas as regras têm cenário no JSON
- **OK** carga: POST válido devolve 201 com key e status
- **OK** carga: reenvio idêntico devolve 200 com a mesma key
- **OK** carga: GET devolve 200 com a mesma key
- **OK** carga: GET de id inexistente devolve 404
- **OK** carga: mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo)
- **OK** carga: mistura dentro do SLA (p95 ≤ 2000 ms)
- **OK** carga: sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação)
