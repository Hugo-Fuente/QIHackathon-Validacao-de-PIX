from sqlalchemy.exc import IntegrityError

from controllers.access_control import AccessControl
from controllers.approval_rules import ApprovalRules
from controllers.base_controller import BaseController
from controllers.reserve_ops import ReserveOps
from dtos import MovimentoReservaDTO
from errors import (
    ChaveIdempotenciaAusente,
    ChaveIdempotenciaReutilizada,
    ResponsabilidadeNaoEncontrada,
    TipoIncoerente,
)
from models import MovimentoReserva, PermissaoSocio, RegraAprovacao
from repositories import ContaRepository, EmpresaRepository, GovernancaRepository, ResponsabilidadeRepository
from utils.db_errors import violated_constraint
from utils.idempotency import is_valid_key, request_hash


class MovimentoReservaController(BaseController, AccessControl, ApprovalRules, ReserveOps):
    """Reservar (livre -> responsabilidade), liberar (responsabilidade -> livre)
    e transferir (entre responsabilidades). O saldo TOTAL da conta nunca muda:
    é só o dinheiro mudando de balde."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.empresa_repository = EmpresaRepository(self.context)
        self.conta_repository = ContaRepository(self.context)
        self.responsabilidade_repository = ResponsabilidadeRepository(self.context)
        self.governanca_repository = GovernancaRepository(self.context)

    def create(self, payload: dict, pessoa_id, idempotency_key):
        """Devolve (movimento, criado). Retentativa idêntica: (movimento, False)."""
        if not is_valid_key(idempotency_key):
            raise ChaveIdempotenciaAusente()

        pessoa = self.identify(pessoa_id)

        tipo = payload["tipo"]
        origem_id = payload.get("responsabilidade_origem_id")
        destino_id = payload.get("responsabilidade_destino_id")

        if not self._coherent(tipo, origem_id, destino_id):
            raise TipoIncoerente(f"{tipo} with origem={origem_id} and destino={destino_id}")

        origem = self._load(origem_id)
        destino = self._load(destino_id)
        base = origem or destino

        if origem is not None and destino is not None and origem.conta_id != destino.conta_id:
            raise TipoIncoerente("both responsibilities must belong to the same account")

        conta = self.conta_repository.get_conta(base.conta_id)
        socio = self.require_socio(pessoa, conta.empresa_id)
        acao = PermissaoSocio.LIBERAR_RESERVA if tipo == MovimentoReserva.LIBERACAO else PermissaoSocio.GERIR_RESPONSABILIDADE
        permissao = self.require_permission(socio, acao, [origem, destino])

        # ── a trava ──
        conta = self.conta_repository.lock_contas([conta.conta_id])[conta.conta_id]
        origem = self._load(origem_id, fresh=True)
        destino = self._load(destino_id, fresh=True)

        body_hash = request_hash(payload)
        existing = self.responsabilidade_repository.find_movimento_by_autor_chave(socio.empresa_socio_id, idempotency_key)

        if existing is not None:
            if existing.hash_requisicao == body_hash:
                return MovimentoReservaDTO.obj_to_dict(existing), False

            raise ChaveIdempotenciaReutilizada()

        self.require_active_account(conta)
        self.check_limit(permissao, payload["valor_centavos"])

        acao_regra = RegraAprovacao.LIBERACAO_RESERVA if tipo == MovimentoReserva.LIBERACAO else RegraAprovacao.RESERVA
        regra = self.resolve_rule(conta.empresa_id, acao_regra, None, payload["valor_centavos"])

        movimento = MovimentoReserva(
            conta_id=conta.conta_id,
            tipo=tipo,
            responsabilidade_origem_id=origem.responsabilidade_id if origem else None,
            responsabilidade_destino_id=destino.responsabilidade_id if destino else None,
            valor_centavos=payload["valor_centavos"],
            autor_empresa_socio_id=socio.empresa_socio_id,
            aprovacoes_exigidas=0,
            chave_idempotencia=idempotency_key,
            hash_requisicao=body_hash,
            motivo=payload.get("motivo"),
        )

        if regra is not None:
            # Com regra: nasce aguardando e NÃO mexe em saldo. O efeito só
            # acontece na última aprovação, que repete a conferência sob a trava.
            movimento.aprovacoes_exigidas = self.approvals_for(regra, conta.empresa_id, socio.empresa_socio_id, [origem, destino])
            movimento.status = MovimentoReserva.AGUARDANDO_APROVACAO
        else:
            self.apply_movement(movimento, conta, origem, destino)

        try:
            self.responsabilidade_repository.add(movimento)
        except IntegrityError as error:
            self.session.rollback()

            if violated_constraint(error) == "uq_movimento_autor_chave":
                raise ChaveIdempotenciaReutilizada()

            raise

        movimento_dto = MovimentoReservaDTO.obj_to_dict(movimento)
        self.session.commit()

        return movimento_dto, True

    # ── apoio ───────────────────────────────────────────────────────

    @staticmethod
    def _coherent(tipo: str, origem_id, destino_id) -> bool:
        if tipo == MovimentoReserva.RESERVA:
            return origem_id is None and destino_id is not None

        if tipo == MovimentoReserva.LIBERACAO:
            return origem_id is not None and destino_id is None

        return origem_id is not None and destino_id is not None and origem_id != destino_id

    def _load(self, responsabilidade_id, fresh: bool = False):
        if responsabilidade_id is None:
            return None

        responsabilidade = self.responsabilidade_repository.get_responsabilidade(responsabilidade_id, lock=fresh)

        if responsabilidade is None:
            raise ResponsabilidadeNaoEncontrada()

        return responsabilidade
