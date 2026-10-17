from sqlalchemy import BigInteger, Column, String

from models.base import Base, uuid_fk, uuid_pk


class PermissaoSocio(Base):
    """O que um sócio pode fazer (ação), em que escopo e até que valor."""

    __tablename__ = "permissao_socio"

    CONSULTAR = "CONSULTAR"
    EXECUTAR_PAGAMENTO = "EXECUTAR_PAGAMENTO"
    APROVAR = "APROVAR"
    GERIR_RESPONSABILIDADE = "GERIR_RESPONSABILIDADE"
    LIBERAR_RESERVA = "LIBERAR_RESERVA"
    GERIR_GOVERNANCA = "GERIR_GOVERNANCA"
    ACOES = (CONSULTAR, EXECUTAR_PAGAMENTO, APROVAR, GERIR_RESPONSABILIDADE, LIBERAR_RESERVA, GERIR_GOVERNANCA)

    PROPRIAS = "PROPRIAS"
    TODAS = "TODAS"

    permissao_id = uuid_pk()
    empresa_socio_id = uuid_fk("empresa_socio.empresa_socio_id", nullable=False)
    acao = Column(String(30), nullable=False)
    escopo = Column(String(10), nullable=False)
    limite_transacao_centavos = Column(BigInteger, nullable=True)
