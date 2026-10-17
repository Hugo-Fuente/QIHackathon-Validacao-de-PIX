from sqlalchemy import BigInteger, CHAR, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base, now_default, uuid_fk, uuid_pk


class Transacao(Base):
    """O fato financeiro, imutável. Entrada, saída e transferência interna
    são a mesma tabela: natureza é o sentido, meio é o canal."""

    __tablename__ = "transacao"

    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"
    INTERNA = "INTERNA"

    PIX = "PIX"
    TED = "TED"
    BOLETO = "BOLETO"
    INTERNO = "INTERNO"
    MEIOS_EXTERNOS = (PIX, TED, BOLETO)

    transacao_id = uuid_pk()
    natureza = Column(String(10), nullable=False)
    meio = Column(String(20), nullable=False)
    conta_origem_id = uuid_fk("conta.conta_id", nullable=True)
    conta_destino_id = uuid_fk("conta.conta_id", nullable=True)
    contraparte = Column(JSONB(none_as_null=True), nullable=True)
    referencia_externa = Column(String(80), nullable=True)
    autor_empresa_socio_id = uuid_fk("empresa_socio.empresa_socio_id", nullable=True)
    responsabilidade_id = uuid_fk("responsabilidade.responsabilidade_id", nullable=True)
    pagamento_programado_id = uuid_fk("pagamento_programado.pagamento_programado_id", nullable=True)
    chave_idempotencia = Column(String(80), nullable=True)
    hash_requisicao = Column(CHAR(64), nullable=True)
    valor_centavos = Column(BigInteger, nullable=False)
    tarifa_id = Column(Integer, nullable=True)
    categoria = Column(String(40), nullable=True)
    descricao = Column(String(140), nullable=True)
    saldo_origem_apos_centavos = Column(BigInteger, nullable=True)
    saldo_destino_apos_centavos = Column(BigInteger, nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=now_default())
