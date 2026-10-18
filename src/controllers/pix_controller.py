from fastapi import HTTPException

from controllers.pix_engine_v7 import _distance_km, process_transaction_v7
from database import get_context
from repositories.pix_repository import PixRepository


def calculate_distance_km(lat1, lon1, lat2, lon2):
    return _distance_km(lat1, lon1, lat2, lon2)


class PixController:
    def __init__(self):
        self.repository = PixRepository()

    def process_transaction(self, input_data: dict) -> dict:
        return process_transaction_v7(self.repository, input_data)

    def get_transaction_analysis(self, transaction_id: str) -> dict:
        session = get_context().get_or_create_session()
        decision = self.repository.get_decision_by_transaction_id(session, transaction_id)
        if not decision:
            raise HTTPException(status_code=404, detail="Análise não encontrada para este ID de Pix.")
        return {
            "key": str(decision.key),
            "status": decision.status,
            "metadata": decision.metadata_ or {},
        }