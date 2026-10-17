from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID

from models.base import Base, now_default, uuid_fk, uuid_pk


class EventoAuditoria(Base):
    """Rastro das mudanças de governança: quem mudou permissão, regra,
    substituição, orçamento ou responsabilidade, e o que mudou."""

    __tablename__ = "evento_auditoria"

    evento_id = uuid_pk()
    empresa_id = uuid_fk("empresa.empresa_id", nullable=False)
    autor_empresa_socio_id = uuid_fk("empresa_socio.empresa_socio_id", nullable=False)
    acao = Column(String(40), nullable=False)
    alvo_tipo = Column(String(30), nullable=False)
    alvo_id = Column(UUID(as_uuid=False), nullable=False)
    dados = Column(JSONB, nullable=False, default=dict)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=now_default())
