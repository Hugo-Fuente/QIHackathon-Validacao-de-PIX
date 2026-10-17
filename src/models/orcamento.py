from sqlalchemy import BigInteger, CHAR, Column

from models.base import Base, uuid_fk, uuid_pk


class Orcamento(Base):
    """Teto de uso da responsabilidade por mês (competência AAAA-MM)."""

    __tablename__ = "orcamento"

    orcamento_id = uuid_pk()
    responsabilidade_id = uuid_fk("responsabilidade.responsabilidade_id", nullable=False)
    competencia = Column(CHAR(7), nullable=False)
    valor_centavos = Column(BigInteger, nullable=False)
    utilizado_centavos = Column(BigInteger, nullable=False, default=0)
