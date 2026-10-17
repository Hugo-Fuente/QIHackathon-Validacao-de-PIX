from sqlalchemy import BigInteger, Column, DateTime, String

from models.base import Base, uuid_fk, uuid_pk


class Responsabilidade(Base):
    """Organização LÓGICA de parte do dinheiro por finalidade (Freelas,
    Impostos...), normalmente com um sócio responsável. Não é conta bancária."""

    __tablename__ = "responsabilidade"

    responsabilidade_id = uuid_pk()
    conta_id = uuid_fk("conta.conta_id", nullable=False)
    nome = Column(String(80), nullable=False)
    responsavel_empresa_socio_id = uuid_fk("empresa_socio.empresa_socio_id", nullable=False)
    substituto_empresa_socio_id = uuid_fk("empresa_socio.empresa_socio_id", nullable=True)
    substituicao_inicio = Column(DateTime(timezone=True), nullable=True)
    substituicao_fim = Column(DateTime(timezone=True), nullable=True)
    saldo_reservado_centavos = Column(BigInteger, nullable=False, default=0)
    saldo_comprometido_centavos = Column(BigInteger, nullable=False, default=0)
