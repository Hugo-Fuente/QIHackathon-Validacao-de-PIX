# Auditoria do projeto — Grupo 27

Gerado em 2026-10-18 08:33. Análise estática é heurística: aponta onde olhar.

| Critério | FAIL | WARN | OK |
|---|---|---|---|
| PADRÃO DE CÓDIGO | 0 | 1 | 25 |
| SOLUÇÃO FUNCIONAL | 0 | 0 | 7 |

## Proximidade dos critérios

| Critério | Nota | Situação | FAIL | WARN |
|---|---|---|---|---|
| PADRÃO DE CÓDIGO | 98.1% | pronto para entregar | 0 | 1 |
| SOLUÇÃO FUNCIONAL | 100.0% | pronto para entregar | 0 | 0 |

Nota = (itens OK + 0,5 × itens WARN) ÷ itens avaliados. INFO não conta. É heurística: ordena o trabalho, não substitui a revisão do time.

## O que falta ajustar (FAIL primeiro, depois WARN)

1. **[WARN] PADRÃO DE CÓDIGO** — regras sem números mágicos (limites/janelas vêm de rule_parameter ou constantes nomeadas)
   - Como resolver: Nomear os parâmetros (constantes ou rule_parameter) com o mesmo valor da RFC.
   - Evidência: `src/rules/params.py:3 literal 100`
   - Evidência: `src/rules/params.py:7 literal 20`
   - Evidência: `src/rules/params.py:8 literal 10`

## PADRÃO DE CÓDIGO

- **INFO** arquivos .py por camada: route=2, service=3, repo=3, rule=7, test=34, other=31
- **OK** rota não acessa banco nem tem SQL
- **OK** rota não chama regras direto (deve passar pelo serviço)
- **OK** rota não importa repositório direto
- **OK** serviço não tem SQL nem conexão direta ao banco
- **OK** serviço não levanta HTTPException (confirmar o padrão do Base Service)
- **OK** repositório não conhece HTTP/FastAPI
- **OK** repositório não importa regras (só persiste e consulta)
- **OK** regras puras: sem framework, banco ou SQL
- **OK** regras puras: sem relógio do sistema (usar transaction_date do evento)
- **WARN** regras sem números mágicos (limites/janelas vêm de rule_parameter ou constantes nomeadas)
  - `src/rules/params.py:3 literal 100`
  - `src/rules/params.py:7 literal 20`
  - `src/rules/params.py:8 literal 10`
  - `src/rules/params.py:10 literal 14`
  - `src/rules/params.py:12 literal 14`
  - `src/rules/params.py:21 literal 60`
  - `src/rules/params.py:22 literal 10`
  - `src/rules/params.py:32 literal 30`
  - `src/rules/params.py:41 literal 60`
  - `src/rules/params.py:43 literal 30`
  - `src/rules/params.py:44 literal 30`
  - `src/rules/params.py:47 literal 60`
  - `src/rules/params.py:48 literal 50`
  - `src/rules/params.py:49 literal 900`
  - `src/rules/params.py:52 literal 24`
  - … e mais 54
- **OK** commit/rollback concentrados em um ponto (uma transação por requisição)
- **OK** pg_advisory_xact_lock só no repositório/camada de dados
- **OK** existem testes (34 arquivos)
- **INFO** 117 funções de teste
- **OK** todo teste tem asserção
- **OK** cada regra (R1–R33, C1) é citada em algum teste
- **OK** há teste de idempotência (reenvio 200 / conflito 409)
- **OK** há teste de validação 422/400
- **OK** há teste de concorrência (threads/asyncio.gather/ThreadPool)
- **OK** há teste de GET 404
- **OK** há testes unitários das regras, sem banco (arquivos *rule*/*regra* em tests)
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
- **OK** as 3 tabelas do diagrama existem no código/migrations
- **OK** todas as regras (R1–R33, C1) aparecem no código
- **OK** há UNIQUE no banco (barreira de idempotência)
- **OK** payload_hash é calculado/gravado (distingue reenvio de reuso do id)
- **OK** índices secundários para o histórico (RFC: coluna + transaction_date)
