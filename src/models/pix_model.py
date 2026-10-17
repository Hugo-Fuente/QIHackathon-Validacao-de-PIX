from datetime import datetime
from sqlalchemy import Column, String, BigInteger, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

# Se você já tiver um Base no seu projeto antigo (ex: em src/models/base.py), 
# pode importar de lá. Caso contrário, usamos este aqui:
Base = declarative_base()

class PixTransactionModel(Base):
    __tablename__ = "pix_transactions"

    id = Column(String(50), primary_key=True)
    amount = Column(BigInteger, nullable=False)
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    source_document = Column(String(20), nullable=False)
    destination_document = Column(String(20), nullable=False)
    payload = Column(JSONB, nullable=False) # Guarda o JSON inteiro para consultas futuras
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))

class PixDecisionModel(Base):
    __tablename__ = "pix_decisions"

    key = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    transaction_id = Column(String(50), ForeignKey("pix_transactions.id"), unique=True, nullable=False)
    status = Column(String(30), nullable=False) # 'approved', 'rejected', 'two_factor_required'
    metadata_ = Column("metadata", JSONB) # Usamos metadata_ no Python pois metadata é palavra reservada do SQLAlchemy
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP"))