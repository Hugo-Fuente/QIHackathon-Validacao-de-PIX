from errors import OrcamentoExcedido, ReservaInsuficiente, SaldoLivreInsuficiente
from models import Conta, Orcamento


class Ledger:
    """Como o dinheiro se move entre os três baldes da conta.

        total = reservado + comprometido + livre        (livre é derivado)

    As funções só mexem nos objetos que o controller já TRAVOU (SELECT ...
    FOR UPDATE) e releu — nenhuma lê o banco por conta própria. Por isso é
    seguro escrever o valor calculado em vez de um UPDATE relativo: ninguém
    mais mexe nessa conta até o commit. E, se alguma conta der errado, o
    CHECK `total >= reservado + comprometido` do banco é a última barreira.
    """

    @staticmethod
    def require_funds(conta: Conta, responsabilidade, total_centavos: int) -> None:
        """Há dinheiro para gastar/comprometer? Com responsabilidade, o que
        vale é o RESERVADO dela; sem, é o saldo LIVRE da conta."""
        if responsabilidade is not None:
            if responsabilidade.saldo_reservado_centavos < total_centavos:
                raise ReservaInsuficiente(
                    f"reservado {responsabilidade.saldo_reservado_centavos} < necessário {total_centavos}"
                )
            return

        if conta.saldo_livre_centavos < total_centavos:
            raise SaldoLivreInsuficiente(f"livre {conta.saldo_livre_centavos} < necessário {total_centavos}")

    @staticmethod
    def commit_funds(conta: Conta, responsabilidade, total_centavos: int) -> None:
        """Reserva/livre -> COMPROMETIDO (pagamento programado criado). O saldo
        total não muda: o dinheiro continua na conta, só não está disponível."""
        if responsabilidade is not None:
            responsabilidade.saldo_reservado_centavos -= total_centavos
            responsabilidade.saldo_comprometido_centavos += total_centavos
            conta.saldo_reservado_centavos -= total_centavos

        conta.saldo_comprometido_centavos += total_centavos

    @staticmethod
    def release_commitment(conta: Conta, responsabilidade, total_centavos: int) -> None:
        """COMPROMETIDO -> reserva (ou livre, sem responsabilidade): recusa,
        cancelamento ou falha de um pagamento programado."""
        if responsabilidade is not None:
            responsabilidade.saldo_comprometido_centavos -= total_centavos
            responsabilidade.saldo_reservado_centavos += total_centavos
            conta.saldo_reservado_centavos += total_centavos

        conta.saldo_comprometido_centavos -= total_centavos

    @staticmethod
    def settle_commitment(conta: Conta, responsabilidade, total_centavos: int) -> None:
        """COMPROMETIDO -> saiu da conta (execução do pagamento programado)."""
        if responsabilidade is not None:
            responsabilidade.saldo_comprometido_centavos -= total_centavos

        conta.saldo_comprometido_centavos -= total_centavos
        conta.saldo_total_centavos -= total_centavos

    @staticmethod
    def spend_now(conta: Conta, responsabilidade, total_centavos: int) -> None:
        """Gasto imediato (transação de saída): sai do total e, com
        responsabilidade, também do reservado dela e da conta."""
        conta.saldo_total_centavos -= total_centavos

        if responsabilidade is not None:
            responsabilidade.saldo_reservado_centavos -= total_centavos
            conta.saldo_reservado_centavos -= total_centavos

    # ── orçamento ───────────────────────────────────────────────────

    @staticmethod
    def check_budget(orcamento, total_centavos: int) -> None:
        """Sem orçamento cadastrado para o mês, não há teto."""
        if orcamento is not None and orcamento.utilizado_centavos + total_centavos > orcamento.valor_centavos:
            raise OrcamentoExcedido(
                f"utilizado {orcamento.utilizado_centavos} + {total_centavos} passa de {orcamento.valor_centavos}"
            )

    @staticmethod
    def use_budget(orcamento: Orcamento, total_centavos: int) -> None:
        if orcamento is not None:
            orcamento.utilizado_centavos += total_centavos

    @staticmethod
    def return_budget(orcamento: Orcamento, total_centavos: int) -> None:
        """Devolve o valor ao orçamento (pedido cancelado, recusado ou que
        falhou). Nunca fica abaixo de zero."""
        if orcamento is not None:
            orcamento.utilizado_centavos = max(0, orcamento.utilizado_centavos - total_centavos)

    @staticmethod
    def move_reserve(conta: Conta, origem, destino, valor_centavos: int) -> None:
        """Movimento de reserva: RESERVA (livre -> destino), LIBERACAO (origem
        -> livre) ou TRANSFERENCIA (origem -> destino, a conta não muda)."""
        if origem is not None:
            origem.saldo_reservado_centavos -= valor_centavos
            if destino is None:
                conta.saldo_reservado_centavos -= valor_centavos

        if destino is not None:
            destino.saldo_reservado_centavos += valor_centavos
            if origem is None:
                conta.saldo_reservado_centavos += valor_centavos
