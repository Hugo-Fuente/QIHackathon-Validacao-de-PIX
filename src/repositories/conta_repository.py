from datetime import datetime

from sqlalchemy import func

from models import Conta, ContaStatusEvento, Status, Tarifa
from repositories.base_repository import BaseRepository, is_uuid


class ContaRepository(BaseRepository):
    """Conta, status (atual e histórico) e tarifa."""

    def get_conta(self, conta_id: str, lock: bool = False):
        return self.get_by_id(Conta, Conta.conta_id, conta_id, lock=lock)

    def get_conta_da_empresa(self, empresa_id: str):
        return self.session.query(Conta).filter(Conta.empresa_id == empresa_id).one_or_none()

    def lock_contas(self, conta_ids: list) -> dict:
        """A regra única da RFC: toda operação que muda saldo ou pedido começa
        travando a(s) CONTA(s) com SELECT ... FOR UPDATE, SEMPRE em ordem
        crescente de conta_id.

        A ordem fixa é o que elimina o deadlock: se A->B e B->A chegam ao
        mesmo tempo, as duas disputam primeiro a MESMA conta (a de menor id),
        e uma espera a outra, em vez de cada uma segurar uma e pedir a outra.

        O `populate_existing` relê o saldo do banco depois de conseguir a
        trava — é a releitura que impede dois débitos de R$ 80 sobre R$ 100.
        """
        ids = sorted({str(conta_id) for conta_id in conta_ids if conta_id and is_uuid(conta_id)})

        if not ids:
            return {}

        rows = (
            self.session.query(Conta)
            .filter(Conta.conta_id.in_(ids))
            .order_by(Conta.conta_id)
            .with_for_update()
            .populate_existing()
            .all()
        )

        return {conta.conta_id: conta for conta in rows}

    def next_account_number(self) -> str:
        """Número da conta: 8 dígitos da sequência + dígito verificador (cabe
        nos 10 caracteres da coluna). A sequência nunca repete, nem sob
        concorrência."""
        sequence = self.session.execute(func.nextval("conta_numero_seq")).scalar()
        digits = f"{sequence:08d}"
        verifier = sum(int(digit) for digit in digits) % 10

        return f"{digits}-{verifier}"

    def add_conta(self, empresa_id: str, status_id: int, agencia: str, numero: str) -> Conta:
        conta = Conta(
            empresa_id=empresa_id,
            status_id=status_id,
            agencia=agencia,
            numero=numero,
            saldo_total_centavos=0,
            saldo_reservado_centavos=0,
            saldo_comprometido_centavos=0,
        )

        return self.add(conta)

    # ── status ──────────────────────────────────────────────────────

    def get_status_by_codigo(self, codigo: str) -> Status:
        return self.session.query(Status).filter(Status.codigo == codigo).one()

    def get_status_by_id(self, status_id: int) -> Status:
        return self.session.query(Status).filter(Status.status_id == status_id).one()

    def add_status_event(self, conta_id: str, status_id: int, motivo=None) -> ContaStatusEvento:
        return self.add(ContaStatusEvento(conta_id=conta_id, status_id=status_id, motivo=motivo))

    def list_status_events(self, conta_id: str) -> list:
        """O histórico da conta com o código de cada status: [(evento, codigo)]."""
        return (
            self.session.query(ContaStatusEvento, Status.codigo)
            .join(Status, Status.status_id == ContaStatusEvento.status_id)
            .filter(ContaStatusEvento.conta_id == conta_id)
            .order_by(ContaStatusEvento.criado_em, ContaStatusEvento.evento_id)
            .all()
        )

    # ── tarifa ──────────────────────────────────────────────────────

    def get_tarifa_vigente(self, meio: str, at: datetime):
        """A tarifa em vigor de um meio: a de maior `vigente_desde` que já
        começou. Quem paga fica com o tarifa_id gravado no pedido/transação,
        então o preço combinado nunca muda depois."""
        return (
            self.session.query(Tarifa)
            .filter(Tarifa.meio == meio, Tarifa.vigente_desde <= at)
            .order_by(Tarifa.vigente_desde.desc(), Tarifa.tarifa_id.desc())
            .first()
        )

    def get_tarifa(self, tarifa_id):
        if tarifa_id is None:
            return None

        return self.session.query(Tarifa).filter(Tarifa.tarifa_id == tarifa_id).one_or_none()
