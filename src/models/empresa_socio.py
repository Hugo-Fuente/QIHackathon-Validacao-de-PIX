from sqlalchemy import Column, Integer, String

from models.base import Base, uuid_fk, uuid_pk


class EmpresaSocio(Base):
    """O vínculo pessoa <-> empresa. É o alvo de toda autoria: quem fez o
    quê, em nome de qual empresa."""

    __tablename__ = "empresa_socio"

    SOCIO = "SOCIO"
    SOCIO_ADMINISTRADOR = "SOCIO_ADMINISTRADOR"

    empresa_socio_id = uuid_pk()
    empresa_id = uuid_fk("empresa.empresa_id", nullable=False)
    pessoa_id = uuid_fk("pessoa.pessoa_id", nullable=False)
    papel = Column(String(20), nullable=False)
    participacao_bp = Column(Integer, nullable=False)
