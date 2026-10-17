from typing import Optional

from controllers import MovimentoReservaController, ResponsabilidadeController
from resources._http import IDEMPOTENCY_HEADER, PESSOA_HEADER, created_or_replayed, http_status, respond
from utils.schema_handler import SchemaHandler


class ResponsabilidadeResource:
    """Responsabilidades, substituição, orçamento e movimentos de reserva."""

    @SchemaHandler.validate("post_responsabilidade.json")
    def on_post(self, payload: dict, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(ResponsabilidadeController().create(payload, x_pessoa_id), http_status.HTTP_201_CREATED)

    def on_get(self, responsabilidade_id: str, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(ResponsabilidadeController().get(responsabilidade_id, x_pessoa_id))

    @SchemaHandler.validate("put_substituicao.json")
    def on_put_substituicao(self, responsabilidade_id: str, payload: dict, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(ResponsabilidadeController().set_substituicao(responsabilidade_id, payload, x_pessoa_id))

    @SchemaHandler.validate("put_orcamento.json")
    def on_put_orcamento(self, responsabilidade_id: str, competencia: str, payload: dict, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(ResponsabilidadeController().set_orcamento(responsabilidade_id, competencia, payload, x_pessoa_id))

    @SchemaHandler.validate("post_movimento_reserva.json")
    def on_post_movimento(
        self,
        payload: dict,
        x_pessoa_id: Optional[str] = PESSOA_HEADER,
        idempotency_key: Optional[str] = IDEMPOTENCY_HEADER,
    ):
        movimento, created = MovimentoReservaController().create(payload, x_pessoa_id, idempotency_key)

        return created_or_replayed(movimento, created)
