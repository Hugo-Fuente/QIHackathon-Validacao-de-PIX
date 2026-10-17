from fastapi import status
from schemas.pix_schema import PixTransactionInput, PixTransactionOutput

class PixResource:
    
    async def on_post_pix(self, payload: PixTransactionInput) -> PixTransactionOutput:
        """
        Recebe a transação Pix, aciona o motor antifraude e devolve a decisão.
        """
        # Futuramente: Aqui vamos chamar o Controller para aplicar as regras e salvar no banco!
        
        return PixTransactionOutput(
            key="b3f1c2e0-7d4a-4c1e-9a52-1f0e6c9d2a77",
            status="approved",
            metadata={"mensagem": "A rota está viva! Motor antifraude em construção."}
        )

    async def on_get_pix(self, id: str) -> PixTransactionOutput:
        """
        Consulta o resultado de uma análise antifraude anterior através do ID do Pix.
        """
        # Futuramente: Buscar no banco de dados usando o Repositório
        
        return PixTransactionOutput(
            key="dummy-key-1234-5678",
            status="approved",
            metadata={"pix_id_buscado": id, "aviso": "Dados de teste"}
        )