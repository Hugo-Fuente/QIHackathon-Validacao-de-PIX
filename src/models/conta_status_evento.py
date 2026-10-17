from sqlalchemy import Column, DateTime, Integer, String

from models.base import Base, now_default, uuid_fk, uuid_pk


class ContaStatusEvento(Base):
    """Cada mudança de status da conta. CONTA.status_id é só a leitura
    rápida do estado atual; o histórico (e o tempo em cada status) está aqui."""

    __tablename__ = "conta_status_evento"

    evento_id = uuid_pk()
    conta_id = uuid_fk("conta.conta_id", nullable=False)
    status_id = Column(Integer, nullable=False)
    motivo = Column(String(140), nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=now_default())
