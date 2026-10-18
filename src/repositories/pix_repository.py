import hashlib
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from models.pix_model import PixTransactionModel, PixDecisionModel
from sqlalchemy import text

class PixRepository:

    def compute_payload_hash(self, payload_dict: dict) -> str:
        """Calcula o SHA-256 do payload normalizado para garantir idempotência."""
        normalized = json.dumps(payload_dict, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_transaction_by_id(self, session: Session, transaction_id: str):
        return session.query(PixTransactionModel).filter(PixTransactionModel.id == transaction_id).first()

    def get_transactions_before(self, session: Session, event_date: datetime):
        return session.query(PixTransactionModel).filter(
            PixTransactionModel.transaction_date <= event_date
        ).order_by(PixTransactionModel.transaction_date.asc()).all()

    def get_non_rejected_transactions_before(self, session: Session, event_date: datetime):
        return session.query(PixTransactionModel).join(
            PixDecisionModel,
            PixTransactionModel.id == PixDecisionModel.transaction_id,
        ).filter(
            PixTransactionModel.transaction_date <= event_date,
            PixDecisionModel.status != "rejected",
        ).order_by(PixTransactionModel.transaction_date.asc()).all()

    def get_decision_by_transaction_id(self, session: Session, transaction_id: str):
        return session.query(PixDecisionModel).filter(PixDecisionModel.transaction_id == transaction_id).first()

    def count_recent_transactions_by_source(self, session: Session, source_document: str, minutes: int = 10) -> int:
        threshold = datetime.utcnow() - timedelta(minutes=minutes)
        return session.query(PixTransactionModel).filter(
            PixTransactionModel.source_document == source_document,
            PixTransactionModel.created_at >= threshold
        ).count()

    def get_recent_transactions_window(self, session: Session, source_document: str, seconds: int):
        threshold = datetime.utcnow() - timedelta(seconds=seconds)
        return session.query(PixTransactionModel).filter(
            PixTransactionModel.source_document == source_document,
            PixTransactionModel.created_at >= threshold
        ).all()

    def get_transactions_in_minutes(self, session: Session, source_document: str, minutes: int):
        threshold = datetime.utcnow() - timedelta(minutes=minutes)
        return session.query(PixTransactionModel).filter(
            PixTransactionModel.source_document == source_document,
            PixTransactionModel.created_at >= threshold
        ).all()

    def get_transactions_by_source_and_destination(
        self,
        session: Session,
        source_document: str,
        destination_account_number: str,
        minutes: int,
    ):
        window_start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return session.query(PixTransactionModel).filter(
            PixTransactionModel.source_document == source_document,
            PixTransactionModel.payload["destination_account"]["account_number"].astext == destination_account_number,
            PixTransactionModel.transaction_date >= window_start
        ).all()

    def get_destination_recent_activity(self, session: Session, destination_account_number: str, minutes: int):
        window_start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return session.query(PixTransactionModel).filter(
            PixTransactionModel.payload["destination_account"]["account_number"].astext == destination_account_number,
            PixTransactionModel.transaction_date >= window_start
        ).all()

    def get_user_successful_history(self, session: Session, source_document: str, limit: int = 20):
        return session.query(PixTransactionModel).join(
            PixDecisionModel,
            PixTransactionModel.id == PixDecisionModel.transaction_id
        ).filter(
            PixTransactionModel.source_document == source_document,
            PixDecisionModel.status != "rejected"
        ).order_by(PixTransactionModel.transaction_date.desc()).limit(limit).all()

    def has_previous_transaction_with_destination(self, session: Session, source_document: str, dest_document: str) -> bool:
        count = session.query(PixTransactionModel).filter(
            PixTransactionModel.source_document == source_document,
            PixTransactionModel.destination_document == dest_document
        ).count()
        return count > 0

    def acquire_advisory_locks(self, session: Session, pix_id: str, source_doc: str, dest_doc: str):
        """
        Adquire locks consultivos no PostgreSQL na mesma ordem para evitar deadlocks,
        conforme exigido pela arquitetura do RFC.
        """
        # Convertemos strings em inteiros para o advisory lock do Postgres usando hash
        lock_id = abs(int(hashlib.md5(pix_id.encode()).hexdigest(), 16)) % (2**31)
        lock_source = abs(int(hashlib.md5(source_doc.encode()).hexdigest(), 16)) % (2**31)
        lock_dest = abs(int(hashlib.md5(dest_doc.encode()).hexdigest(), 16)) % (2**31)

        # Ordena para garantir consistência e evitar deadlocks
        ordered_locks = sorted([lock_id, lock_source, lock_dest])

        for l in ordered_locks:
            session.execute(text(f"SELECT pg_advisory_xact_lock({l})"))

    def save_analysis(self, session: Session, transaction_data: dict, payload_hash: str, status: str, risk_score: int, metadata: dict, rule_hits: list):
        """Salva a transação, a decisão e as regras acionadas numa única transação de banco."""

        session.execute(text("""
            INSERT INTO fraud_rules (code, name, default_points)
            VALUES
                ('R33', 'Degrau de início frio', 1),
                ('C1', 'Integridade do pedido, voto e execução', 0)
            ON CONFLICT (code) DO NOTHING
        """))
        
        # 1. Salva a transação Pix
        tx_model = PixTransactionModel(
            id=transaction_data["id"],
            amount=transaction_data["amount"],
            transaction_date=transaction_data["transaction_date"],
            source_document=transaction_data["source_account"]["owner"]["document_number"],
            destination_document=transaction_data["destination_account"]["owner"]["document_number"],
            payload=transaction_data
        )
        session.add(tx_model)
        session.flush()

        # 2. Salva a decisão antifraude
        decision_model = PixDecisionModel(
            transaction_id=transaction_data["id"],
            status=status,
            risk_score=risk_score,
            metadata_=metadata
        )
        session.add(decision_model)
        session.flush()

        # 3. Salva os hits de regras na tabela rule_hits
        for hit in rule_hits:
            session.execute(
                text("""
                    INSERT INTO rule_hits (analysis_key, rule_code, points, detail)
                    VALUES (:key, :code, :points, :detail)
                """),
                {
                    "key": decision_model.key,
                    "code": hit["code"],
                    "points": hit["points"],
                    "detail": hit["detail"]
                }
            )

        session.commit()
        return decision_model