from typing import Optional

from fastapi import Response

from controllers import EmpresaController, GovernancaController
from resources._http import PESSOA_HEADER, http_status, respond
from utils.schema_handler import SchemaHandler


class EmpresaResource:
    """A porta HTTP da empresa, dos sócios e da governança.

    Um método daqui faz três coisas: confere o corpo (o decorator do schema),
    chama o controller e devolve o status. Regra de negócio mora no controller.
    Não há `__init__`: o resource é compartilhado por todas as requisições.
    """

    @SchemaHandler.validate("post_empresa.json")
    def on_post(self, payload: dict):
        # Só INTERNAL-TOKEN: o cadastro acontece antes de existir sócio.
        return respond(EmpresaController().create(payload), http_status.HTTP_201_CREATED)

    def on_get(self, empresa_id: str, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(EmpresaController().get(empresa_id, x_pessoa_id))

    @SchemaHandler.validate("put_permissao.json")
    def on_put_permissao(
        self, empresa_id: str, empresa_socio_id: str, acao: str, payload: dict, x_pessoa_id: Optional[str] = PESSOA_HEADER
    ):
        return respond(GovernancaController().put_permissao(empresa_id, empresa_socio_id, acao, payload, x_pessoa_id))

    def on_delete_permissao(self, empresa_id: str, empresa_socio_id: str, acao: str, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        GovernancaController().delete_permissao(empresa_id, empresa_socio_id, acao, x_pessoa_id)
        return Response(status_code=http_status.HTTP_204_NO_CONTENT)

    @SchemaHandler.validate("put_regra_aprovacao.json")
    def on_put_regra(self, empresa_id: str, payload: dict, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        return respond(GovernancaController().put_regra(empresa_id, payload, x_pessoa_id))

    def on_delete_regra(self, empresa_id: str, regra_id: str, x_pessoa_id: Optional[str] = PESSOA_HEADER):
        GovernancaController().delete_regra(empresa_id, regra_id, x_pessoa_id)
        return Response(status_code=http_status.HTTP_204_NO_CONTENT)
