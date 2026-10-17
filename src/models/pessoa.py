from sqlalchemy import Column, Date, String

from models.base import Base, uuid_pk


class Pessoa(Base):
    """Pessoa física. Os dados moram aqui uma vez só (CPF único); a mesma
    pessoa pode ser sócia de várias empresas, com papéis e permissões
    diferentes em cada uma (EMPRESA_SOCIO)."""

    __tablename__ = "pessoa"

    pessoa_id = uuid_pk()
    cpf = Column(String(11), nullable=False)
    nome = Column(String(120), nullable=False)
    email = Column(String(120), nullable=False)
    data_nascimento = Column(Date, nullable=False)
