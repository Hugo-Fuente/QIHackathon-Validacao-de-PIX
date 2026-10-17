from datetime import datetime

from sqlalchemy import and_, or_

from models import EmpresaSocio, Pessoa, Responsabilidade, Tarifa, Transacao
from repositories.base_repository import BaseRepository


class TransacaoRepository(BaseRepository):
    """Transações (imutáveis) e a leitura paginada do extrato."""

    def get_transacao(self, transacao_id: str):
        return self.get_by_id(Transacao, Transacao.transacao_id, transacao_id)

    def find_by_autor_chave(self, autor_empresa_socio_id: str, chave: str):
        return (
            self.session.query(Transacao)
            .filter(
                Transacao.autor_empresa_socio_id == autor_empresa_socio_id,
                Transacao.chave_idempotencia == chave,
            )
            .one_or_none()
        )

    def find_by_meio_referencia(self, meio: str, referencia_externa: str):
        return (
            self.session.query(Transacao)
            .filter(Transacao.meio == meio, Transacao.referencia_externa == referencia_externa)
            .first()
        )

    def find_by_pagamento_programado(self, pagamento_programado_id: str):
        return (
            self.session.query(Transacao)
            .filter(Transacao.pagamento_programado_id == pagamento_programado_id)
            .one_or_none()
        )

    def map_by_pagamentos(self, pagamento_ids: list) -> dict:
        """pagamento_programado_id -> transacao_id, das execuções já feitas."""
        if not pagamento_ids:
            return {}

        rows = (
            self.session.query(Transacao.pagamento_programado_id, Transacao.transacao_id)
            .filter(Transacao.pagamento_programado_id.in_(pagamento_ids))
            .all()
        )

        return {pagamento_id: transacao_id for pagamento_id, transacao_id in rows}

    def add_transacao(self, **fields) -> Transacao:
        return self.add(Transacao(**fields))

    # ── extrato ─────────────────────────────────────────────────────

    def _extrato_query(self):
        """A transação com o que o extrato precisa mostrar além dela: o valor
        da tarifa, o nome do sócio autor e o nome da responsabilidade."""
        return (
            self.session.query(
                Transacao,
                Tarifa.valor_centavos.label("tarifa_centavos"),
                Pessoa.nome.label("autor_nome"),
                Responsabilidade.nome.label("responsabilidade_nome"),
            )
            .outerjoin(Tarifa, Tarifa.tarifa_id == Transacao.tarifa_id)
            .outerjoin(EmpresaSocio, EmpresaSocio.empresa_socio_id == Transacao.autor_empresa_socio_id)
            .outerjoin(Pessoa, Pessoa.pessoa_id == EmpresaSocio.pessoa_id)
            .outerjoin(Responsabilidade, Responsabilidade.responsabilidade_id == Transacao.responsabilidade_id)
        )

    def get_with_details(self, transacao_id: str):
        if self.get_transacao(transacao_id) is None:
            return None

        return self._extrato_query().filter(Transacao.transacao_id == transacao_id).one()

    def list_extrato(self, conta_id: str, filters: dict, cursor, limit: int) -> list:
        """As transações em que a conta é origem OU destino, da mais recente à
        mais antiga, paginadas por cursor (criado_em, transacao_id).

        Cursor, e não OFFSET: uma inserção durante a leitura faria o OFFSET
        repetir ou perder linhas; com o cursor a próxima página continua
        exatamente do último item entregue.

        São duas consultas (origem e destino), cada uma lendo o seu índice
        (conta_origem_id|conta_destino_id, criado_em desc, transacao_id desc)
        já na ordem pedida, e um merge das duas listas — em vez de um OR, que
        obrigaria o banco a ordenar tudo.
        """
        merged = []

        for column in (Transacao.conta_origem_id, Transacao.conta_destino_id):
            query = self._extrato_query().filter(column == conta_id)
            query = self._apply_filters(query, filters)

            if cursor is not None:
                cursor_time, cursor_id = cursor
                query = query.filter(
                    or_(
                        Transacao.criado_em < cursor_time,
                        and_(Transacao.criado_em == cursor_time, Transacao.transacao_id < cursor_id),
                    )
                )

            query = query.order_by(Transacao.criado_em.desc(), Transacao.transacao_id.desc()).limit(limit)
            merged.extend(query.all())

        merged.sort(key=lambda row: (row.Transacao.criado_em, row.Transacao.transacao_id), reverse=True)

        return merged[:limit]

    @staticmethod
    def _apply_filters(query, filters: dict):
        if filters.get("categoria") is not None:
            query = query.filter(Transacao.categoria == filters["categoria"])

        if filters.get("natureza") is not None:
            query = query.filter(Transacao.natureza == filters["natureza"])

        if filters.get("meio") is not None:
            query = query.filter(Transacao.meio == filters["meio"])

        if filters.get("responsabilidade_id") is not None:
            query = query.filter(Transacao.responsabilidade_id == filters["responsabilidade_id"])

        if filters.get("autor_empresa_socio_id") is not None:
            query = query.filter(Transacao.autor_empresa_socio_id == filters["autor_empresa_socio_id"])

        start: datetime = filters.get("de")
        if start is not None:
            query = query.filter(Transacao.criado_em >= start)

        end: datetime = filters.get("ate")
        if end is not None:
            query = query.filter(Transacao.criado_em < end)

        return query
