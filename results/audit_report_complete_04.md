# Auditoria do projeto — Grupo 27

Gerado em 2026-10-18 09:01. Análise estática é heurística: aponta onde olhar.

| Critério | FAIL | WARN | OK |
|---|---|---|---|
| PADRÃO DE CÓDIGO | 0 | 1 | 25 |
| SOLUÇÃO FUNCIONAL | 0 | 0 | 42 |

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
  - `src/rules/params.py:13 literal 14`
  - `src/rules/params.py:20 literal 60`
  - `src/rules/params.py:21 literal 10`
  - `src/rules/params.py:31 literal 30`
  - `src/rules/params.py:40 literal 60`
  - `src/rules/params.py:42 literal 30`
  - `src/rules/params.py:43 literal 30`
  - `src/rules/params.py:46 literal 60`
  - `src/rules/params.py:47 literal 50`
  - `src/rules/params.py:48 literal 900`
  - `src/rules/params.py:51 literal 24`
  - … e mais 54
- **OK** commit/rollback concentrados em um ponto (uma transação por requisição)
- **OK** pg_advisory_xact_lock só no repositório/camada de dados
- **OK** existem testes (34 arquivos)
- **INFO** 119 funções de teste
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
- **OK** carga: existe ao menos um degrau dentro do SLA (p95 ≤ 2000.0 ms, erros ≤ 1.0%)
- **OK** carga: 50 rajadas: exatamente 1x 201, o resto 200, uma única key
- **OK** carga: 1 vencedor; mesmo payload = 200; payload diferente = 409; uma key
- **OK** carga: nenhum 5xx nem erro de rede (violação de UNIQUE não pode vazar)
- **OK** carga: todas as requisições da rajada retornam 201
- **OK** carga: concorrente == sequencial em todos os pagadores (lock evita ler histórico incompleto)
- **OK** carga: R2 acionado em 6 dos 10 Pix (do 5º em diante)
- **OK** carga: contenção de um só pagador dentro do SLA (p95 ≤ 2000.0 ms)
- **OK** carga: conta destino serializa o perfil: R9 dispara no quinto pagador
- **OK** carga: todos os Pix da rajada são gravados
- **OK** carga: uma execução passa e as outras quatro acionam C1
- **OK** carga: todas as execuções duplicadas recebem resposta normal
- **OK** carga: amount ausente → 422
- **OK** carga: amount negativo → 422
- **OK** carga: amount decimal → 422
- **OK** carga: data sem fuso → 422
- **OK** carga: documento com 10 dígitos → 422
- **OK** carga: context com event inválido → 422
- **OK** carga: vote sem request_id → 422
- **OK** carga: JSON malformado → 400
- **OK** carga: todo GET devolve a mesma key do POST (200) ou 404 se inexistente
- **OK** carga: mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo)
- **OK** carga: mistura dentro do SLA (p95 ≤ 2000.0 ms)
- **OK** carga: sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação)
