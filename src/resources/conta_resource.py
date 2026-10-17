from typing import Optional

from fastapi import Request

from controllers import ContaController, PagamentoProgramadoController
from resources._http import PESSOA_HEADER, respond
from utils.schema_handler import SchemaHandler


class ContaResource:
    """Consulta da conta, status (back-office), extrato e lista de pagamentos."""

    def on_get(self, conta_id: str, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(ContaController().get(conta_id, x_pessoa_id))

    @SchemaHandler.validate("patch_conta_status.json")
    def on_patch_status(self, conta_id: str, payload: dict):
        # Back-office: só INTERNAL-TOKEN, sem X-Pessoa-Id.
        return respond(ContaController().update_status(conta_id, payload["status"], payload.get("motivo")))

    @SchemaHandler.validate_query_params("get_extrato.json")
    def on_get_extrato(self, conta_id: str, request: Request, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(ContaController().get_extrato(conta_id, x_pessoa_id, dict(request.query_params)))

    @SchemaHandler.validate_query_params("get_pagamentos_programados.json")
    def on_get_pagamentos(self, conta_id: str, request: Request, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(PagamentoProgramadoController().list_by_conta(conta_id, x_pessoa_id, dict(request.query_params)))
