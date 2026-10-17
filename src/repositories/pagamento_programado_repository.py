from sqlalchemy import and_, or_

from models import PagamentoProgramado
from repositories.base_repository import BaseRepository


class PagamentoProgramadoRepository(BaseRepository):
    """Pagamentos programados (a intenção futura de pagar)."""

    def get_pagamento(self, pagamento_programado_id: str, lock: bool = False):
        return self.get_by_id(
            PagamentoProgramado, PagamentoProgramado.pagamento_programado_id, pagamento_programado_id, lock=lock
        )

    def find_by_autor_chave(self, autor_empresa_socio_id: str, chave: str):
        return (
            self.session.query(PagamentoProgramado)
            .filter(
                PagamentoProgramado.autor_empresa_socio_id == autor_empresa_socio_id,
                PagamentoProgramado.chave_idempotencia == chave,
            )
            .one_or_none()
        )

    def find_ativo_by_boleto(self, meio: str, referencia_externa: str):
        """O boleto já está num pedido ativo (aguardando aprovação ou agendado)?"""
        return (
            self.session.query(PagamentoProgramado)
            .filter(
                PagamentoProgramado.meio == meio,
                PagamentoProgramado.referencia_externa == referencia_externa,
                PagamentoProgramado.status.in_([PagamentoProgramado.AGUARDANDO_APROVACAO, PagamentoProgramado.AGENDADO]),
            )
            .first()
        )

    def add_pagamento(self, **fields) -> PagamentoProgramado:
        return self.add(PagamentoProgramado(**fields))

    def list_by_conta(self, conta_id: str, status, cursor, limit: int) -> list:
        """Os pagamentos da conta, do mais novo ao mais antigo, por cursor."""
        query = self.session.query(PagamentoProgramado).filter(PagamentoProgramado.conta_id == conta_id)

        if status is not None:
            query = query.filter(PagamentoProgramado.status == status)

        if cursor is not None:
            cursor_time, cursor_id = cursor
            query = query.filter(
                or_(
                    PagamentoProgramado.criado_em < cursor_time,
                    and_(
                        PagamentoProgramado.criado_em == cursor_time,
                        PagamentoProgramado.pagamento_programado_id < cursor_id,
                    ),
                )
            )

        query = query.order_by(
            PagamentoProgramado.criado_em.desc(), PagamentoProgramado.pagamento_programado_id.desc()
        )

        return query.limit(limit).all()
