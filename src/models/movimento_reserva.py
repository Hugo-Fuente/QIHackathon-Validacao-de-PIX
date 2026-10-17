from sqlalchemy import BigInteger, CHAR, Column, DateTime, Integer, String

from models.base import Base, now_default, uuid_fk, uuid_pk


class MovimentoReserva(Base):
    """Histórico de cada mexida na reserva: reservar (livre -> responsabilidade),
    liberar (responsabilidade -> livre) e transferir (entre responsabilidades)."""

    __tablename__ = "movimento_reserva"

    RESERVA = "RESERVA"
    LIBERACAO = "LIBERACAO"
    TRANSFERENCIA = "TRANSFERENCIA"
    TIPOS = (RESERVA, LIBERACAO, TRANSFERENCIA)

    AGUARDANDO_APROVACAO = "AGUARDANDO_APROVACAO"
    APLICADO = "APLICADO"
    RECUSADO = "RECUSADO"

    movimento_id = uuid_pk()
    conta_id = uuid_fk("conta.conta_id", nullable=False)
    tipo = Column(String(15), nullable=False)
    responsabilidade_origem_id = uuid_fk("responsabilidade.responsabilidade_id", nullable=True)
    responsabilidade_destino_id = uuid_fk("responsabilidade.responsabilidade_id", nullable=True)
    valor_centavos = Column(BigInteger, nullable=False)
    autor_empresa_socio_id = uuid_fk("empresa_socio.empresa_socio_id", nullable=False)
    status = Column(String(25), nullable=False)
    aprovacoes_exigidas = Column(Integer, nullable=False, default=0)
    chave_idempotencia = Column(String(80), nullable=False)
    hash_requisicao = Column(CHAR(64), nullable=False)
    motivo = Column(String(140), nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=now_default())
    decidido_em = Column(DateTime(timezone=True), nullable=True)
