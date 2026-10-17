from sqlalchemy.exc import IntegrityError

from controllers.access_control import AccessControl
from controllers.approval_rules import ApprovalRules
from controllers.base_controller import BaseController
from controllers.pedido_ops import PedidoOps
from controllers.reserve_ops import ReserveOps
from dtos import PagamentoProgramadoDTO
from errors import (
    AutorNaoAprovaOProprio,
    MovimentoReservaNaoEncontrado,
    PagamentoProgramadoNaoEncontrado,
    PedidoNaoPendente,
    VotoJaRegistrado,
)
from models import Aprovacao, MovimentoReserva, PagamentoProgramado, PermissaoSocio
from repositories import (
    ContaRepository,
    EmpresaRepository,
    GovernancaRepository,
    PagamentoProgramadoRepository,
    ResponsabilidadeRepository,
)
from utils import clock
from utils.db_errors import violated_constraint


class AprovacaoController(BaseController, AccessControl, ApprovalRules, PedidoOps, ReserveOps):
    """O voto de um sócio sobre um pedido (pagamento programado ou movimento
    de reserva). Ao atingir `aprovacoes_exigidas` o pedido avança; uma recusa
    o encerra e devolve o dinheiro.

    A ordem é a da RFC: trava a CONTA, depois o pedido, e RELÊ o status —
    quem votou ao mesmo tempo pode ter mudado o pedido enquanto esta
    requisição esperava a trava (e aí é PEDIDO_NAO_PENDENTE).
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.empresa_repository = EmpresaRepository(self.context)
        self.conta_repository = ContaRepository(self.context)
        self.responsabilidade_repository = ResponsabilidadeRepository(self.context)
        self.pagamento_repository = PagamentoProgramadoRepository(self.context)
        self.governanca_repository = GovernancaRepository(self.context)

    # ── pagamento programado ────────────────────────────────────────

    def vote_pagamento(self, pagamento_id: str, payload: dict, pessoa_id):
        """Devolve (voto, criado). Voto repetido idêntico: (voto, False) -> 200."""
        pessoa = self.identify(pessoa_id)
        pedido = self.pagamento_repository.get_pagamento(pagamento_id)

        if pedido is None:
            raise PagamentoProgramadoNaoEncontrado()

        conta = self.conta_repository.get_conta(pedido.conta_id)
        socio = self.require_socio(pessoa, conta.empresa_id)
        responsabilidade = self._responsabilidade(pedido)
        self.require_permission(socio, PermissaoSocio.APROVAR, [responsabilidade])

        # ── a trava: conta, depois pedido, e relê ──
        conta = self.conta_repository.lock_contas([conta.conta_id])[conta.conta_id]
        pedido = self.pagamento_repository.get_pagamento(pagamento_id, lock=True)
        responsabilidade = self._responsabilidade(pedido, fresh=True)

        decisao = payload["decisao"]
        existing = self.governanca_repository.find_voto(socio.empresa_socio_id, pagamento_programado_id=pedido.pagamento_programado_id)

        if existing is not None:
            if existing.decisao == decisao:
                return self._vote_dto(existing, pedido), False

            raise VotoJaRegistrado()

        if pedido.autor_empresa_socio_id == socio.empresa_socio_id:
            raise AutorNaoAprovaOProprio()

        if pedido.status != PagamentoProgramado.AGUARDANDO_APROVACAO:
            raise PedidoNaoPendente(f"payment is {pedido.status}")

        voto = self._add_vote(socio.empresa_socio_id, decisao, pagamento_programado_id=pedido.pagamento_programado_id)

        if decisao == Aprovacao.RECUSADA:
            self.release_payment(pedido, conta, responsabilidade)
            pedido.status = PagamentoProgramado.RECUSADO
        elif self.governanca_repository.count_aprovadas(pagamento_programado_id=pedido.pagamento_programado_id) >= pedido.aprovacoes_exigidas:
            # Nenhum saldo muda: o dinheiro já estava comprometido.
            pedido.status = PagamentoProgramado.AGENDADO

        self.session.flush()
        voto_dto = self._vote_dto(voto, pedido)
        self.session.commit()

        return voto_dto, True

    # ── movimento de reserva ────────────────────────────────────────

    def vote_movimento(self, movimento_id: str, payload: dict, pessoa_id):
        pessoa = self.identify(pessoa_id)
        movimento = self.responsabilidade_repository.get_movimento(movimento_id)

        if movimento is None:
            raise MovimentoReservaNaoEncontrado()

        conta = self.conta_repository.get_conta(movimento.conta_id)
        socio = self.require_socio(pessoa, conta.empresa_id)
        origem = self._load_responsabilidade(movimento.responsabilidade_origem_id)
        destino = self._load_responsabilidade(movimento.responsabilidade_destino_id)
        self.require_permission(socio, PermissaoSocio.APROVAR, [origem, destino])

        conta = self.conta_repository.lock_contas([conta.conta_id])[conta.conta_id]
        movimento = self.responsabilidade_repository.get_movimento(movimento_id, lock=True)
        origem = self._load_responsabilidade(movimento.responsabilidade_origem_id, fresh=True)
        destino = self._load_responsabilidade(movimento.responsabilidade_destino_id, fresh=True)

        decisao = payload["decisao"]
        existing = self.governanca_repository.find_voto(socio.empresa_socio_id, movimento_reserva_id=movimento.movimento_id)

        if existing is not None:
            if existing.decisao == decisao:
                return self._vote_dto(existing, movimento), False

            raise VotoJaRegistrado()

        if movimento.autor_empresa_socio_id == socio.empresa_socio_id:
            raise AutorNaoAprovaOProprio()

        if movimento.status != MovimentoReserva.AGUARDANDO_APROVACAO:
            raise PedidoNaoPendente(f"movement is {movimento.status}")

        voto = self._add_vote(socio.empresa_socio_id, decisao, movimento_reserva_id=movimento.movimento_id)

        if decisao == Aprovacao.RECUSADA:
            movimento.status = MovimentoReserva.RECUSADO
            movimento.decidido_em = clock.now()
        elif self.governanca_repository.count_aprovadas(movimento_reserva_id=movimento.movimento_id) >= movimento.aprovacoes_exigidas:
            # Último voto: o efeito acontece AGORA, repetindo a conferência de
            # saldo sob a trava (o livre/reservado pode ter mudado desde o pedido).
            self.apply_movement(movimento, conta, origem, destino)

        self.session.flush()
        voto_dto = self._vote_dto(voto, movimento)
        self.session.commit()

        return voto_dto, True

    # ── apoio ───────────────────────────────────────────────────────

    def _add_vote(self, empresa_socio_id: str, decisao: str, **target):
        try:
            return self.governanca_repository.add_voto(empresa_socio_id, decisao, **target)
        except IntegrityError as error:
            self.session.rollback()

            if violated_constraint(error) in ("uq_aprovacao_socio_pp", "uq_aprovacao_socio_movimento"):
                raise VotoJaRegistrado()

            raise

    def _vote_dto(self, voto, pedido) -> dict:
        if isinstance(pedido, PagamentoProgramado):
            registradas = self.governanca_repository.count_aprovadas(pagamento_programado_id=pedido.pagamento_programado_id)
        else:
            registradas = self.governanca_repository.count_aprovadas(movimento_reserva_id=pedido.movimento_id)

        return PagamentoProgramadoDTO.vote_to_dict(voto, pedido.status, registradas, pedido.aprovacoes_exigidas)

    def _responsabilidade(self, pedido, fresh: bool = False):
        if pedido.responsabilidade_id is None:
            return None

        return self.responsabilidade_repository.get_da_conta(pedido.conta_id, pedido.responsabilidade_id, fresh=fresh)

    def _load_responsabilidade(self, responsabilidade_id, fresh: bool = False):
        if responsabilidade_id is None:
            return None

        return self.responsabilidade_repository.get_responsabilidade(responsabilidade_id, lock=fresh)
