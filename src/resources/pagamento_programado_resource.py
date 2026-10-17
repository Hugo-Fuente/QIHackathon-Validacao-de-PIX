from typing import Optional

from fastapi import Body

from controllers import AprovacaoController, PagamentoProgramadoController
from resources._http import IDEMPOTENCY_HEADER, PESSOA_HEADER, created_or_replayed, respond
from utils.schema_handler import SchemaHandler


class PagamentoProgramadoResource:
    """Programar, aprovar, cancelar e executar pagamentos."""

    @SchemaHandler.validate("post_pagamento_programado.json")
    def on_post(
        self,
        payload: dict,
        x_pessoa_id: Optional[str] = PESSOA_HEADER,
        idempotency_key: Optional[str] = IDEMPOTENCY_HEADER,
    ):
        pedido, created = PagamentoProgramadoController().create(payload, x_pessoa_id, idempotency_key)

        return created_or_replayed(pedido, created)

    @SchemaHandler.validate("post_aprovacao.json")
    def on_post_aprovacao(self, pagamento_id: str, payload: dict, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        voto, created = AprovacaoController().vote_pagamento(pagamento_id, payload, x_pessoa_id)

        return created_or_replayed(voto, created)

    @SchemaHandler.validate("post_aprovacao.json")
    def on_post_aprovacao_movimento(self, movimento_id: str, payload: dict, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        voto, created = AprovacaoController().vote_movimento(movimento_id, payload, x_pessoa_id)

        return created_or_replayed(voto, created)

    @SchemaHandler.validate("post_cancelamento.json")
    def on_post_cancelamento(self, pagamento_id: str, payload: dict = Body(default_factory=dict), x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(PagamentoProgramadoController().cancel(pagamento_id, payload.get("motivo"), x_pessoa_id))

    def on_post_execucao(self, pagamento_id: str):
        # O parceiro / agendador: só INTERNAL-TOKEN.
        transacao, created = PagamentoProgramadoController().execute(pagamento_id)

        return created_or_replayed(transacao, created)
