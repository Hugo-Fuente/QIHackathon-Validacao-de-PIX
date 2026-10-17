# Conta compartilhada para EPP

API REST (Python 3.11 + FastAPI + PostgreSQL 16) que implementa a RFC
**"Conta compartilhada para EPP: o dinheiro é da sociedade, e cada sócio opera
com poder, limite e autoria"**.

A conta pertence à empresa. Cada sócio opera com *permissão por ação e escopo*,
*limite por transação*, *orçamento mensal por responsabilidade* e *regras de
aprovação*. Toda movimentação carrega a autoria do sócio e fica no extrato.

## Subir

```bash
docker compose up        # API em http://localhost:3000, banco PostgreSQL
```

## Testar

Com a API de pé, pode executar os testes automatizados localmente. É recomendado o uso do Python 3.11.

**Opção A: Localmente (Linux / Mac)**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

**Opção B: Localmente (Windows PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -q
```

**Opção C: Via Docker (À prova de falhas)**
Caso enfrente erros de compilação de dependências locais (como falhas ao instalar o `psycopg2` no Windows), pode injetar e correr os testes diretamente no ambiente isolado do contentor:

```bash
# 1. Copie os ficheiros de dependências e a pasta de testes para o contentor
docker cp requirements.txt sistema-bancario-qitech-bootcamp-api-1:/tmp/
docker cp requirements-dev.txt sistema-bancario-qitech-bootcamp-api-1:/tmp/
docker cp tests sistema-bancario-qitech-bootcamp-api-1:/tmp/

# 2. Execute a instalação e os testes como root
docker exec -u root -it sistema-bancario-qitech-bootcamp-api-1 sh -c "cp /tmp/requirements* . && cp -r /tmp/tests . && pip install -r requirements-dev.txt && export PYTHONPATH=/app:/app/src && pytest -q"
```

Os testes falam com a API por HTTP e cobrem: cadastro, idempotência, saldo (total / reservado / comprometido), reservas, pagamento programado, aprovações e **concorrência** (dois Pix de R$ 80 com R$ 100 de saldo, transferências cruzadas sem deadlock, execução e cancelamento simultâneos, voto duplicado). `DbUtils.rollback()` recria o banco a partir de `database/database.sql`.

## Autenticação

- `INTERNAL-TOKEN: <token>` em toda rota (padrão `default_token`).
- `X-Pessoa-Id: <uuid>` identifica o sócio que age. Entradas (crédito vindo de
  fora) e a execução de pagamento programado usam apenas o token.
- `Idempotency-Key` é obrigatório em operações que movem dinheiro de um sócio.

## Rotas

| Rota | O que faz |
|---|---|
| `POST /empresa`, `GET /empresa/{id}` | cadastra empresa + sócios + conta (`EM_APROVACAO`) |
| `PUT/DELETE /empresa/{id}/socio/{sid}/permissao/{acao}` | permissão por ação/escopo/limite |
| `PUT /empresa/{id}/regra_aprovacao`, `DELETE .../{rid}` | regras de aprovação por valor/meio |
| `GET /conta/{id}`, `PATCH /conta/{id}/status` | saldos e ciclo de vida da conta |
| `GET /conta/{id}/extrato` | extrato com paginação por cursor e filtros |
| `GET /conta/{id}/pagamento_programado` | lista pagamentos programados |
| `POST /responsabilidade`, `GET /responsabilidade/{id}` | carteira com responsável |
| `PUT /responsabilidade/{id}/substituicao` | substituto por janela de tempo |
| `PUT /responsabilidade/{id}/orcamento/{competencia}` | orçamento mensal |
| `POST /movimento_reserva`, `POST /movimento_reserva/{id}/aprovacao` | reservar, liberar, transferir |
| `POST /transacao`, `GET /transacao/{id}` | Pix, TED, boleto, interna e entrada |
| `POST /pagamento_programado` (+ `/aprovacao`, `/cancelamento`, `/execucao`) | agendamento e ciclo |

Valores em **centavos** (inteiros). Erros: `{title, description, translation, code}`
com o `code` igual ao nome do código da RFC (ex.: `SALDO_LIVRE_INSUFICIENTE`).

## Decisões

Veja `docs/arquitetura.md`. Desvios em relação à RFC:

- `POST /pagamento_programado` recebe `conta_id` (a conta não é derivável sem responsabilidade).
- `POST /empresa` devolve também `socios` com os ids criados.
- Boleto exige `referencia_externa` e `contraparte.vencimento` (AAAA-MM-DD).
- Código adicional `MEIO_INCOERENTE` (422).
- Relógio de negócio: Brasília (UTC-3).
