"""Application orchestration for Pix transactions."""

from controllers.pix_engine_v7 import process_transaction_v7
from database import get_context
from errors.custom_errors import ConflictError, NotFoundError
from repositories.pix_repository import PixRepository
from rules.common import destination_key, distance_km, parse_datetime


def calculate_distance_km(lat1, lon1, lat2, lon2):
    return distance_km(lat1, lon1, lat2, lon2)


class PixController:
    def __init__(self):
        self.repository = PixRepository()

    def process_transaction(self, input_data: dict) -> dict:
        input_data = self._normalize_transaction(input_data)
        session = get_context().get_or_create_session()
        pix_id = str(input_data["id"])
        payer = str(input_data["source_account"]["owner"]["document_number"])
        destination = "|".join(destination_key(input_data))
        payload_hash = self.repository.compute_payload_hash(input_data)

        self.repository.lock_keys(session, pix_id, payer, destination)
        existing = self.repository.get_transaction_by_id(session, pix_id)
        if existing:
            stored_hash = self.repository.compute_payload_hash(dict(existing.payload or {}))
            if stored_hash != payload_hash:
                raise ConflictError("Event id was already used with a different payload")
            decision = self.repository.get_decision_by_transaction_id(session, pix_id)
            if decision is None:
                raise NotFoundError("A decisão deste evento ainda não está disponível.")
            return {
                "key": str(decision.key),
                "status": decision.status,
                "metadata": decision.metadata_ or {},
                "_http_status": 200,
            }

        history = self.repository.build_history(session, input_data)
        analysis = process_transaction_v7(input_data, history)
        decision, created = self.repository.save_analysis(
            session=session,
            unit_of_work=get_context(),
            transaction_data=input_data,
            status=analysis["status"],
            risk_score=analysis["risk_score"],
            metadata=analysis["metadata"],
            rule_hits=analysis["rule_hits"],
            payload_hash=payload_hash,
        )
        return {
            "key": str(decision.key),
            "status": decision.status,
            "metadata": decision.metadata_,
            "_http_status": 201 if created else 200,
        }

    @staticmethod
    def _normalize_transaction(input_data: dict) -> dict:
        normalized = dict(input_data)
        normalized["transaction_date"] = parse_datetime(input_data["transaction_date"]).isoformat()
        return normalized

    def get_transaction_analysis(self, transaction_id: str) -> dict:
        session = get_context().get_or_create_session()
        decision = self.repository.get_decision_by_transaction_id(session, transaction_id)
        if not decision:
            raise NotFoundError("Análise não encontrada para este ID de Pix.")
        return {
            "key": str(decision.key),
            "status": decision.status,
            "metadata": decision.metadata_ or {},
        }
