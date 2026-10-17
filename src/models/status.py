from sqlalchemy import Column, Integer, String

from models.base import Base


class Status(Base):
    """Estados da conta. Tabela de referência, populada pelo database.sql."""

    __tablename__ = "status"

    EM_APROVACAO = "EM_APROVACAO"
    ATIVA = "ATIVA"
    BLOQUEADA = "BLOQUEADA"
    ENCERRADA = "ENCERRADA"

    status_id = Column(Integer, primary_key=True)
    codigo = Column(String(20), nullable=False)
    descricao = Column(String(60), nullable=False)
