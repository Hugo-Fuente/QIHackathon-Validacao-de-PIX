# Auditoria do projeto — Grupo 27

Gerado em 2026-10-18 06:52. Análise estática é heurística: aponta onde olhar.

| Critério | FAIL | WARN | OK |
|---|---|---|---|
| PADRÃO DE CÓDIGO | 3 | 4 | 21 |
| SOLUÇÃO FUNCIONAL | 1 | 0 | 5 |

## PADRÃO DE CÓDIGO

- **INFO** arquivos .py por camada: route=3, service=0, repo=3, rule=0, test=30, other=30
- **FAIL** camada 'service' não encontrada (pastas/arquivos esperados: ['service', 'services'])
- **FAIL** camada 'rule' não encontrada (pastas/arquivos esperados: ['regras', 'rules'])
- **FAIL** rota não acessa banco nem tem SQL
  - `src/controllers/pix_engine_v7.py:8 import sqlalchemy.orm`
- **OK** rota não chama regras direto (deve passar pelo serviço)
- **WARN** rota não importa repositório direto
  - `src/controllers/pix_controller.py:5 import repositories.pix_repository`
  - `src/controllers/pix_engine_v7.py:11 import repositories.pix_repository`
- **OK** serviço não tem SQL nem conexão direta ao banco
- **OK** serviço não levanta HTTPException (confirmar o padrão do Base Service)
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
