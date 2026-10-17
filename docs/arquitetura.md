# Arquitetura

Camadas: `resource` (HTTP) → `controller` (regra de negócio; **único** que faz
`commit`, um por requisição) → `repository` (só SQL). O contexto fica em um
`ContextVar`, a sessão é aberta pelo middleware.

## Dinheiro

Inteiros em centavos. Três saldos na conta: `total`, `reservado`, `comprometido`.
`livre = total − reservado − comprometido`. O banco garante
`CHECK (total >= reservado + comprometido)`.

## Concorrência

- `lock_contas`: `SELECT ... FOR UPDATE` das contas envolvidas **ordenadas por
  `conta_id`** (sem deadlock em transferências cruzadas).
- Pedidos (pagamento programado, movimento de reserva) são travados e o status é
  relido após o lock.
- Endpoints síncronos rodam em threadpool; pool do engine: 10 + 30.

## Idempotência

`Idempotency-Key` + hash sha256 do corpo canônico. Mesmo hash → replay (200);
hash diferente → 409. Garantias no banco: `UNIQUE(autor, chave)`,
`UNIQUE(meio, referencia_externa)`, `UNIQUE(pagamento_programado_id)`,
`UNIQUE(empresa_socio_id, alvo)` nos votos, índice parcial para boleto ativo.

## Governança

Permissão por ação (`CONSULTAR`, `EXECUTAR_PAGAMENTO`, `APROVAR`,
`GERIR_RESPONSABILIDADE`, `LIBERAR_RESERVA`, `GERIR_GOVERNANCA`) com escopo
`PROPRIAS`/`TODAS` e limite. Regra de aprovação: a que tem `meio` vence a sem
`meio`; depois a de maior `acima_de`. O autor não vota no próprio pedido; regra
inatingível é recusada (`REGRA_INATINGIVEL`).

## Auditoria

`transacao`, `tarifa` (versionada), `conta_status_evento` e `evento_auditoria`
são imutáveis (trigger `proibir_alteracao`).
