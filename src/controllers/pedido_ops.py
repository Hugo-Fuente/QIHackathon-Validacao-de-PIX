from controllers.ledger import Ledger
from errors import BoletoVencido, InvalidParameter
from utils import clock


class PedidoOps:
    """Operações sobre pedidos que comprometem dinheiro (pagamento programado)
    e sobre movimentos de reserva, compartilhadas por mais de um controller.

    Mixin: exige `self.conta_repository` e `self.responsabilidade_repository`.
    """

    def payment_total(self, pedido) -> int:
        """valor + tarifa CONGELADA no pedido: exatamente o que será debitado."""
        tarifa = self.conta_repository.get_tarifa(pedido.tarifa_id)

        return pedido.valor_centavos + tarifa.valor_centavos

    def payment_budget(self, pedido):
        """O orçamento que o pedido consumiu: o do mês da data prevista."""
        if pedido.responsabilidade_id is None:
            return None

        competence = clock.competence(pedido.data_prevista)

        return self.responsabilidade_repository.get_orcamento(pedido.responsabilidade_id, competence)

    def release_payment(self, pedido, conta, responsabilidade) -> None:
        """Recusa, cancelamento ou falha: devolve valor + tarifa do comprometido
        para a reserva (ou o livre) e subtrai do orçamento. A conta precisa
        estar travada, e o pedido, relido."""
        total = self.payment_total(pedido)

        Ledger.release_commitment(conta, responsabilidade, total)
        Ledger.return_budget(self.payment_budget(pedido), total)

    @staticmethod
    def check_boleto_due(contraparte: dict) -> None:
        """Boleto com vencimento antes de hoje não se paga."""
        try:
            from datetime import date

            due = date.fromisoformat(contraparte["vencimento"])
        except (KeyError, ValueError, TypeError):
            raise InvalidParameter("contraparte.vencimento is not a valid date")

        if due < clock.today():
            raise BoletoVencido()
