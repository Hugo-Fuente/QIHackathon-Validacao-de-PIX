# Auditoria do projeto — Grupo 27

Gerado em 2026-10-18 07:50. Análise estática é heurística: aponta onde olhar.

| Critério | FAIL | WARN | OK |
|---|---|---|---|
| PADRÃO DE CÓDIGO | 2 | 4 | 21 |
| SOLUÇÃO FUNCIONAL | 1 | 0 | 12 |
| TESTES DE CARGA | 1 | 0 | 5 |

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
- **FAIL** as 17 tabelas do diagrama existem no código/migrations
  - `fraud_analysis`
  - `analysis_recommended_action`
  - `analysis_family_total`
  - `rule_parameter`
  - `rule_catalog`
  - `risk_family`
  - `decision_band`
  - `ip_geo_range`
  - `pix_epp_context`
  - `pix_epp_partner_document`
  - `pix_epp_control_change`
  - `pix_epp_reserve_movement`
  - `pix_epp_inflow`
  - `pix_epp_refused_request`
- **OK** todas as regras (R1–R33, C1) aparecem no código
- **OK** há UNIQUE no banco (barreira de idempotência)
- **OK** payload_hash é calculado/gravado (distingue reenvio de reuso do id)
- **OK** API responde em http://localhost:8000/pix/transaction
- **OK** POST devolve 201 com key e status (http 201)
- **OK** Pix gravado e consultável: GET devolve a mesma key (http 200)
- **OK** GET de id inexistente devolve 404 (http 404)
- **OK** dado sobrevive ao restart (http 200)
- **OK** decisões batem com as regras: 49/49 cenários do pix_api_tests.json
- **OK** todas as regras têm cenário no JSON

## TESTES DE CARGA

- **INFO** resumo de carga: results/load_test_20261018_sql_01/summary.json
  - `rodada=1257649e`
  - `requisições=22308`
  - `p95=179.2 ms`
  - `erros=0`
- **INFO** métricas mixed: p95=128.7 ms, erros=0
- **INFO** métricas soak: p95=196.8 ms, erros=0
- **OK** smoke: POST válido devolve 201 com key e status
  - `http 201`
- **OK** smoke: reenvio idêntico devolve 200 com a mesma key
  - `http 200`
- **OK** smoke: GET devolve 200 com a mesma key
  - `http 200`
- **OK** smoke: GET de id inexistente devolve 404
  - `http 404`
- **OK** mixed: mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo)
  - `6328 req, erros=0, 420.5 req/s, p95=128.7ms`
- **FAIL** soak: sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação)
  - `erros=0, p95 119.2→319.6 ms`

## Nota única

**8.70/10** — 46 verificações pontuadas; OK=1, WARN=0,5, FAIL=0; INFO não entra no cálculo.
