from sqlalchemy import BigInteger, Column, Integer, String

from models.base import Base, uuid_fk, uuid_pk


class Conta(Base):
    """A conta da empresa. O dinheiro vive em três baldes que nunca se
    sobrepõem: total = reservado + comprometido + livre (livre é derivado)."""

    __tablename__ = "conta"

    conta_id = uuid_pk()
    empresa_id = uuid_fk("empresa.empresa_id", nullable=False)
    status_id = Column(Integer, nullable=False)
    agencia = Column(String(4), nullable=False)
    numero = Column(String(10), nullable=False)
    saldo_total_centavos = Column(BigInteger, nullable=False, default=0)
    saldo_reservado_centavos = Column(BigInteger, nullable=False, default=0)
    saldo_comprometido_centavos = Column(BigInteger, nullable=False, default=0)

    @property
    def saldo_livre_centavos(self) -> int:
        return self.saldo_total_centavos - self.saldo_reservado_centavos - self.saldo_comprometido_centavos
