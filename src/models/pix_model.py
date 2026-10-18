import uuid
from datetime import datetime
from sqlalchemy import Column, String, BigInteger, SmallInteger, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class PixTransactionModel(Base):
    __tablename__ = "pix_transactions"

    id = Column(String(50), primary_key=True)
    amount = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    source_document = Column(String(20), nullable=False)
    destination_document = Column(String(20), nullable=False)
    payload = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))

class PixDecisionModel(Base):
    __tablename__ = "fraud_analysis"

    key = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transaction_id = Column(String(50), ForeignKey("pix_transactions.id"), unique=True, nullable=False)
    status = Column(String(30), nullable=False)
    risk_score = Column(SmallInteger, nullable=False)  # <-- Adicionada a coluna que faltava!
    metadata_ = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))
