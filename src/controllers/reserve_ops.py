from controllers.ledger import Ledger
from models import MovimentoReserva
from utils import clock


class ReserveOps:
    """Aplicar um movimento de reserva. Usado na criação (sem regra de
    aprovação) e na última aprovação (com regra) — as duas vezes sob a trava
    da conta e repetindo a conferência de saldo.

    Mixin: exige `self.conta_repository` e o AccessControl.
    """

    def apply_movement(self, movimento: MovimentoReserva, conta, origem, destino) -> None:
        self.require_active_account(conta)

        if movimento.tipo == MovimentoReserva.RESERVA:
            # reservar tira do LIVRE da conta
            Ledger.require_funds(conta, None, movimento.valor_centavos)
        else:
            # liberar e transferir tiram do RESERVADO da responsabilidade de origem
            Ledger.require_funds(conta, origem, movimento.valor_centavos)

        Ledger.move_reserve(conta, origem, destino, movimento.valor_centavos)

        movimento.status = MovimentoReserva.APLICADO
        movimento.decidido_em = clock.now()
