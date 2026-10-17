from sqlalchemy import func

from models import Aprovacao, EmpresaSocio, EventoAuditoria, Pessoa, RegraAprovacao
from repositories.base_repository import BaseRepository


class GovernancaRepository(BaseRepository):
    """Regras de aprovação, votos e auditoria."""

    # ── regras ──────────────────────────────────────────────────────

    def get_regra(self, regra_id: str):
        return self.get_by_id(RegraAprovacao, RegraAprovacao.regra_id, regra_id)

    def find_regra(self, empresa_id: str, acao: str, meio, acima_de_centavos: int):
        """A regra pela chave natural (empresa, ação, meio, acima_de). `meio`
        None casa com meio NULL — é o NULLS NOT DISTINCT da UNIQUE."""
        query = self.session.query(RegraAprovacao).filter(
            RegraAprovacao.empresa_id == empresa_id,
            RegraAprovacao.acao == acao,
            RegraAprovacao.acima_de_centavos == acima_de_centavos,
        )

        if meio is None:
            query = query.filter(RegraAprovacao.meio.is_(None))
        else:
            query = query.filter(RegraAprovacao.meio == meio)

        return query.populate_existing().one_or_none()

    def list_regras(self, empresa_id: str, acao: str) -> list:
        return (
            self.session.query(RegraAprovacao)
            .filter(RegraAprovacao.empresa_id == empresa_id, RegraAprovacao.acao == acao)
            .all()
        )

    def add_regra(self, **fields) -> RegraAprovacao:
        return self.add(RegraAprovacao(**fields))

    def delete_regra(self, regra: RegraAprovacao) -> None:
        self.session.delete(regra)
        self.session.flush()

    # ── votos ───────────────────────────────────────────────────────

    def find_voto(self, empresa_socio_id: str, pagamento_programado_id=None, movimento_reserva_id=None):
        query = self.session.query(Aprovacao).filter(Aprovacao.empresa_socio_id == empresa_socio_id)

        if pagamento_programado_id is not None:
            query = query.filter(Aprovacao.pagamento_programado_id == pagamento_programado_id)
        else:
            query = query.filter(Aprovacao.movimento_reserva_id == movimento_reserva_id)

        return query.one_or_none()

    def add_voto(self, empresa_socio_id: str, decisao: str, pagamento_programado_id=None, movimento_reserva_id=None):
        voto = Aprovacao(
            empresa_socio_id=empresa_socio_id,
            decisao=decisao,
            pagamento_programado_id=pagamento_programado_id,
            movimento_reserva_id=movimento_reserva_id,
        )

        return self.add(voto)

    def count_aprovadas(self, pagamento_programado_id=None, movimento_reserva_id=None) -> int:
        query = self.session.query(func.count(Aprovacao.aprovacao_id)).filter(Aprovacao.decisao == Aprovacao.APROVADA)

        if pagamento_programado_id is not None:
            query = query.filter(Aprovacao.pagamento_programado_id == pagamento_programado_id)
        else:
            query = query.filter(Aprovacao.movimento_reserva_id == movimento_reserva_id)

        return query.scalar()

    def list_votos_dos_pagamentos(self, pagamento_ids: list) -> list:
        """Os votos recebidos pelos pagamentos, com o nome de quem votou:
        [(Aprovacao, nome)] em ordem cronológica."""
        if not pagamento_ids:
            return []

        return (
            self.session.query(Aprovacao, Pessoa.nome)
            .join(EmpresaSocio, EmpresaSocio.empresa_socio_id == Aprovacao.empresa_socio_id)
            .join(Pessoa, Pessoa.pessoa_id == EmpresaSocio.pessoa_id)
            .filter(Aprovacao.pagamento_programado_id.in_(pagamento_ids))
            .order_by(Aprovacao.criado_em, Aprovacao.aprovacao_id)
            .all()
        )

    # ── auditoria ───────────────────────────────────────────────────

    def add_evento(self, empresa_id: str, autor_empresa_socio_id: str, acao: str, alvo_tipo: str, alvo_id: str, dados: dict):
        evento = EventoAuditoria(
            empresa_id=empresa_id,
            autor_empresa_socio_id=autor_empresa_socio_id,
            acao=acao,
            alvo_tipo=alvo_tipo,
            alvo_id=alvo_id,
            dados=dados,
        )

        return self.add(evento)
