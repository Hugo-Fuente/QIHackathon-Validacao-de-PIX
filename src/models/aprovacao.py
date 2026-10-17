from sqlalchemy import Column, DateTime, String

from models.base import Base, now_default, uuid_fk, uuid_pk


class Aprovacao(Base):
    """Um voto de um sócio sobre um pedido (pagamento programado OU movimento
    de reserva — exatamente um dos dois ids é preenchido)."""

    __tablename__ = "aprovacao"

    APROVADA = "APROVADA"
    RECUSADA = "RECUSADA"

    aprovacao_id = uuid_pk()
    empresa_socio_id = uuid_fk("empresa_socio.empresa_socio_id", nullable=False)
    pagamento_programado_id = uuid_fk("pagamento_programado.pagamento_programado_id", nullable=True)
    movimento_reserva_id = uuid_fk("movimento_reserva.movimento_id", nullable=True)
    decisao = Column(String(10), nullable=False)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=now_default())
