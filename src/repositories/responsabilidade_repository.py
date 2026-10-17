from models import MovimentoReserva, Orcamento, Responsabilidade
from repositories.base_repository import BaseRepository


class ResponsabilidadeRepository(BaseRepository):
    """Responsabilidade, orçamento e movimentos de reserva."""

    # ── responsabilidade ────────────────────────────────────────────

    def get_responsabilidade(self, responsabilidade_id: str, lock: bool = False):
        return self.get_by_id(
            Responsabilidade, Responsabilidade.responsabilidade_id, responsabilidade_id, lock=lock
        )

    def get_da_conta(self, conta_id: str, responsabilidade_id: str, fresh: bool = False):
        """A responsabilidade, só se ela for DESTA conta (senão None → 404).
        `fresh=True` relê o saldo do banco — use depois de travar a conta."""
        responsabilidade = self.get_responsabilidade(responsabilidade_id, lock=fresh)

        if responsabilidade is None or responsabilidade.conta_id != str(conta_id):
            return None

        return responsabilidade

    def find_by_nome(self, conta_id: str, nome: str):
        return (
            self.session.query(Responsabilidade)
            .filter(Responsabilidade.conta_id == conta_id, Responsabilidade.nome == nome)
            .one_or_none()
        )

    def add_responsabilidade(self, **fields) -> Responsabilidade:
        return self.add(Responsabilidade(saldo_reservado_centavos=0, saldo_comprometido_centavos=0, **fields))

    def list_by_conta(self, conta_id: str) -> list:
        return self.session.query(Responsabilidade).filter(Responsabilidade.conta_id == conta_id).all()

    # ── orçamento ───────────────────────────────────────────────────

    def get_orcamento(self, responsabilidade_id: str, competencia: str):
        return (
            self.session.query(Orcamento)
            .filter(Orcamento.responsabilidade_id == responsabilidade_id, Orcamento.competencia == competencia)
            .populate_existing()
            .one_or_none()
        )

    def add_orcamento(self, responsabilidade_id: str, competencia: str, valor_centavos: int) -> Orcamento:
        orcamento = Orcamento(
            responsabilidade_id=responsabilidade_id,
            competencia=competencia,
            valor_centavos=valor_centavos,
            utilizado_centavos=0,
        )

        return self.add(orcamento)

    # ── movimento de reserva ────────────────────────────────────────

    def get_movimento(self, movimento_id: str, lock: bool = False):
        return self.get_by_id(MovimentoReserva, MovimentoReserva.movimento_id, movimento_id, lock=lock)

    def find_movimento_by_autor_chave(self, autor_empresa_socio_id: str, chave: str):
        return (
            self.session.query(MovimentoReserva)
            .filter(
                MovimentoReserva.autor_empresa_socio_id == autor_empresa_socio_id,
                MovimentoReserva.chave_idempotencia == chave,
            )
            .one_or_none()
        )

    def add_movimento(self, **fields) -> MovimentoReserva:
        return self.add(MovimentoReserva(**fields))
