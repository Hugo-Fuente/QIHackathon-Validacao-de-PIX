from controllers.pix_controller import PixController
from schemas.pix_schema import PixTransactionInput, PixTransactionOutput

class PixResource:
    def __init__(self):
        self.controller = PixController()

    async def on_post_pix(self, payload: PixTransactionInput) -> PixTransactionOutput:
        """Recebe a transação Pix, processa o motor antifraude e grava no banco."""
        # Transforma o payload do Pydantic em dicionário para o controller processar
        data_dict = payload.model_dump(mode="json")
        result = self.controller.process_transaction(data_dict)
        return PixTransactionOutput(**result)

    async def on_get_pix(self, id: str) -> PixTransactionOutput:
        """Consulta a análise antifraude gravada através do ID do Pix."""
        result = self.controller.get_transaction_analysis(id)
        return PixTransactionOutput(**result)