from connectors.rest_connector import BaseConnectorResponse, RestConnector
from constants import BANKSLIP_API_INTERNAL_TOKEN, BANKSLIP_API_TIMEOUT, BANKSLIP_API_URL


class BankSlipConnector(RestConnector):
    """Cliente da API de boletos.

    Define apenas os endpoints e payloads deste serviço; o transporte HTTP
    fica no RestConnector. Devolve a resposta sem interpretá-la.
    """

    def __init__(self) -> None:
        super().__init__(
            class_name=__name__,
            base_url=BANKSLIP_API_URL,
            timeout=BANKSLIP_API_TIMEOUT,
            internal_token=BANKSLIP_API_INTERNAL_TOKEN,
        )

    def create_bank_slip(
        self, amount: int, expiration_date: str, payer_name: str, payer_document_number: str
    ) -> BaseConnectorResponse:
        """Solicita a emissão de um boleto. `amount` em centavos (inteiro)."""
        payload = {
            "amount": amount,
            "expiration_date": expiration_date,
            "payer_data": {
                "name": payer_name,
                "document_number": payer_document_number,
            },
        }

        return self.send(endpoint="/bank_slip", method="POST", payload=payload)

    def get_bank_slip_by_key(self, bank_slip_key: str) -> BaseConnectorResponse:
        """Consulta um boleto pela chave (404 indica que não existe)."""
        return self.send(endpoint=f"/bank_slip/{bank_slip_key}", method="GET")
