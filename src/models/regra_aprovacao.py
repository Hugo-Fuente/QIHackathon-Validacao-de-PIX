from sqlalchemy import BigInteger, Boolean, Column, Integer, String

from models.base import Base, uuid_fk, uuid_pk


class RegraAprovacao(Base):
    """Acima de X, N aprovações de outros sócios (ou de todos)."""

    __tablename__ = "regra_aprovacao"

    PAGAMENTO = "PAGAMENTO"
    RESERVA = "RESERVA"
    LIBERACAO_RESERVA = "LIBERACAO_RESERVA"
    ACOES = (PAGAMENTO, RESERVA, LIBERACAO_RESERVA)

    regra_id = uuid_pk()
    empresa_id = uuid_fk("empresa.empresa_id", nullable=False)
    acao = Column(String(30), nullable=False)
    meio = Column(String(20), nullable=True)
    acima_de_centavos = Column(BigInteger, nullable=False)
    exige_todos = Column(Boolean, nullable=False, default=False)
    aprovacoes_necessarias = Column(Integer, nullable=True)
