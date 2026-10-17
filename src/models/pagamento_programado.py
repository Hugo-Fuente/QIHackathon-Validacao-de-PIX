from sqlalchemy import BigInteger, CHAR, Column, Date, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base, now_default, uuid_fk, uuid_pk


class PagamentoProgramado(Base):
    """Intenção futura de pagar. Compromete o dinheiro, mas nada saiu: só a
    execução cria a TRANSACAO."""

    __tablename__ = "pagamento_programado"

    AGUARDANDO_APROVACAO = "AGUARDANDO_APROVACAO"
    AGENDADO = "AGENDADO"
    EXECUTADO = "EXECUTADO"
    RECUSADO = "RECUSADO"
    CANCELADO = "CANCELADO"
    FALHOU = "FALHOU"
    STATUS = (AGUARDANDO_APROVACAO, AGENDADO, EXECUTADO, RECUSADO, CANCELADO, FALHOU)

    pagamento_programado_id = uuid_pk()
    conta_id = uuid_fk("conta.conta_id", nullable=False)
    responsabilidade_id = uuid_fk("responsabilidade.responsabilidade_id", nullable=True)
    autor_empresa_socio_id = uuid_fk("empresa_socio.empresa_socio_id", nullable=False)
    meio = Column(String(20), nullable=False)
    contraparte = Column(JSONB, nullable=False)
    referencia_externa = Column(String(80), nullable=True)
    valor_centavos = Column(BigInteger, nullable=False)
    tarifa_id = Column(Integer, nullable=False)
    data_prevista = Column(Date, nullable=False)
    status = Column(String(25), nullable=False)
    aprovacoes_exigidas = Column(Integer, nullable=False, default=0)
    chave_idempotencia = Column(String(80), nullable=False)
    hash_requisicao = Column(CHAR(64), nullable=False)
    categoria = Column(String(40), nullable=True)
    descricao = Column(String(140), nullable=True)
    motivo = Column(String(140), nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=now_default())
