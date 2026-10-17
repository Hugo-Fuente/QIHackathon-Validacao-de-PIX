from sqlalchemy import Column, String

from models.base import Base, uuid_pk


class Empresa(Base):
    """A cliente, dona da conta e de todo o dinheiro."""

    __tablename__ = "empresa"

    empresa_id = uuid_pk()
    cnpj = Column(String(14), nullable=False)
    razao_social = Column(String(150), nullable=False)
