from typing import Optional

from controllers import TransacaoController
from resources._http import IDEMPOTENCY_HEADER, PESSOA_HEADER, created_or_replayed, respond
from utils.schema_handler import SchemaHandler


class TransacaoResource:
    """Movimentação imediata de dinheiro: entrada, saída e transferência interna."""

    @SchemaHandler.validate("post_transacao.json")
    def on_post(
        self,
        payload: dict,
        x_pessoa_id: Optional[str] = PESSOA_HEADER,
        idempotency_key: Optional[str] = IDEMPOTENCY_HEADER,
    ):
        transacao, created = TransacaoController().create(payload, x_pessoa_id, idempotency_key)

        return created_or_replayed(transacao, created)

    def on_get(self, transacao_id: str, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(TransacaoController().get(transacao_id, x_pessoa_id))
