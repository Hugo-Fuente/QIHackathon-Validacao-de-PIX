from sqlalchemy import BigInteger, Column, DateTime, Integer, String

from models.base import Base


class Tarifa(Base):
    """Preço por meio, versionado e imutável: mudar o preço cria linha nova."""

    __tablename__ = "tarifa"

    tarifa_id = Column(Integer, primary_key=True)
    meio = Column(String(20), nullable=False)
    valor_centavos = Column(BigInteger, nullable=False)
    vigente_desde = Column(DateTime(timezone=True), nullable=False)
