from controllers.access_control import AccessControl
from controllers.base_controller import BaseController
from dtos import ContaDTO, TransacaoDTO
from errors import ContaNaoEncontrada, InvalidParameter, SaldoNaoZerado, TransicaoInvalida
from models import PermissaoSocio, Status
from repositories import ContaRepository, EmpresaRepository, TransacaoRepository
from utils import clock
from utils.cursor import decode_cursor, encode_cursor, parse_bound, parse_limit

# De onde cada status pode ir. ENCERRADA é final.
ALLOWED_TRANSITIONS = {
    Status.EM_APROVACAO: {Status.ATIVA},
    Status.ATIVA: {Status.BLOQUEADA, Status.ENCERRADA},
    Status.BLOQUEADA: {Status.ATIVA, Status.ENCERRADA},
    Status.ENCERRADA: set(),
}


class ContaController(BaseController, AccessControl):
    """Consulta da conta, mudança de status (back-office) e extrato."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.empresa_repository = EmpresaRepository(self.context)
        self.conta_repository = ContaRepository(self.context)
        self.transacao_repository = TransacaoRepository(self.context)

    def get(self, conta_id: str, pessoa_id) -> dict:
        conta = self._authorized_conta(conta_id, pessoa_id)

        return self._conta_to_dto(conta)

    def update_status(self, conta_id: str, new_status: str, motivo) -> dict:
        """O back-office aprova, bloqueia, desbloqueia ou encerra a conta.

        Trava a conta com a MESMA trava dos pagamentos: se um pagamento já
        tinha a trava, o bloqueio espera (aquele pagamento é válido e os
        seguintes serão recusados com CONTA_NAO_ATIVA); se o bloqueio veio
        primeiro, o pagamento lê BLOQUEADA e é recusado.

        Idempotente: pedir o status que a conta já tem devolve 200 sem criar
        evento novo, então o histórico não acumula duplicatas.
        """
        if self.conta_repository.get_conta(conta_id) is None:
            raise ContaNaoEncontrada()

        conta = self.conta_repository.get_conta(conta_id, lock=True)
        current = self.conta_repository.get_status_by_id(conta.status_id)

        if current.codigo == new_status:
            return self._conta_to_dto(conta)

        if new_status not in ALLOWED_TRANSITIONS[current.codigo]:
            raise TransicaoInvalida(f"cannot go from {current.codigo} to {new_status}")

        if new_status == Status.ENCERRADA and conta.saldo_total_centavos != 0:
            raise SaldoNaoZerado(f"balance is {conta.saldo_total_centavos}")

        status = self.conta_repository.get_status_by_codigo(new_status)
        conta.status_id = status.status_id
        self.conta_repository.add_status_event(conta.conta_id, status.status_id, motivo)

        self.session.flush()
        conta_dto = self._conta_to_dto(conta)
        self.session.commit()

        return conta_dto

    def get_extrato(self, conta_id: str, pessoa_id, params: dict) -> dict:
        """As transações da conta, da mais recente à mais antiga, por cursor."""
        conta = self._authorized_conta(conta_id, pessoa_id)

        limit = parse_limit(params.get("limite"))
        cursor = decode_cursor(params["cursor"]) if params.get("cursor") else None

        filters = {
            "categoria": params.get("categoria"),
            "natureza": params.get("natureza"),
            "meio": params.get("meio"),
            "responsabilidade_id": params.get("responsabilidade_id"),
            "autor_empresa_socio_id": params.get("autor_empresa_socio_id"),
            "de": parse_bound(params["de"], "de", is_end=False) if params.get("de") else None,
            "ate": parse_bound(params["ate"], "ate", is_end=True) if params.get("ate") else None,
        }

        if filters["de"] and filters["ate"] and filters["de"] >= filters["ate"]:
            raise InvalidParameter("de is after ate")

        # Pede um a mais que o limite só para saber se existe próxima página.
        rows = self.transacao_repository.list_extrato(conta.conta_id, filters, cursor, limit + 1)
        has_more = len(rows) > limit
        page = rows[:limit]

        next_cursor = None
        if has_more:
            last = page[-1].Transacao
            next_cursor = encode_cursor(last.criado_em, last.transacao_id)

        return {
            "itens": [TransacaoDTO.row_to_extrato_item(row, conta.conta_id) for row in page],
            "proximo_cursor": next_cursor,
        }

    # ── apoio ───────────────────────────────────────────────────────

    def _authorized_conta(self, conta_id: str, pessoa_id):
        """401 -> 404 -> 403 -> 403: quem é, a conta existe, é sócia da
        empresa dona dela, e pode consultar."""
        pessoa = self.identify(pessoa_id)
        conta = self.conta_repository.get_conta(conta_id)

        if conta is None:
            raise ContaNaoEncontrada()

        socio = self.require_socio(pessoa, conta.empresa_id)
        self.require_permission(socio, PermissaoSocio.CONSULTAR)

        return conta

    def _conta_to_dto(self, conta) -> dict:
        status = self.conta_repository.get_status_by_id(conta.status_id)
        events = self.conta_repository.list_status_events(conta.conta_id)

        return ContaDTO.obj_to_dict(conta, status.codigo, events, clock.now())
