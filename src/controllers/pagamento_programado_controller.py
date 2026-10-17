from datetime import date

from sqlalchemy.exc import IntegrityError

from controllers.access_control import AccessControl
from controllers.approval_rules import ApprovalRules
from controllers.base_controller import BaseController
from controllers.ledger import Ledger
from controllers.pedido_ops import PedidoOps
from dtos import PagamentoProgramadoDTO
from errors import (
    BoletoEmPedidoAtivo,
    BoletoJaPago,
    BoletoVencido,
    ChaveIdempotenciaAusente,
    ChaveIdempotenciaReutilizada,
    ContaNaoEncontrada,
    DataNaoChegou,
    DataNoPassado,
    EstadoFinal,
    InvalidParameter,
    JaExecutado,
    NaoAgendado,
    PagamentoProgramadoNaoEncontrado,
    ResponsabilidadeNaoEncontrada,
)
from models import PagamentoProgramado, PermissaoSocio, RegraAprovacao, Transacao
from repositories import (
    ContaRepository,
    EmpresaRepository,
    GovernancaRepository,
    PagamentoProgramadoRepository,
    ResponsabilidadeRepository,
    TransacaoRepository,
)
from utils import clock
from utils.cursor import decode_cursor, encode_cursor, parse_limit
from utils.db_errors import violated_constraint
from utils.idempotency import is_valid_key, request_hash


class PagamentoProgramadoController(BaseController, AccessControl, ApprovalRules, PedidoOps):
    """Programar, listar, cancelar e executar pagamentos.

    Intenção não é fato: programar COMPROMETE o dinheiro (valor + tarifa saem
    do livre/reservado e vão para o comprometido) mas nenhuma transação nasce.
    Só a execução, na data prevista, cria a TRANSACAO e baixa o saldo.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.empresa_repository = EmpresaRepository(self.context)
        self.conta_repository = ContaRepository(self.context)
        self.transacao_repository = TransacaoRepository(self.context)
        self.responsabilidade_repository = ResponsabilidadeRepository(self.context)
        self.pagamento_repository = PagamentoProgramadoRepository(self.context)
        self.governanca_repository = GovernancaRepository(self.context)

    # ── programar ───────────────────────────────────────────────────

    def create(self, payload: dict, pessoa_id, idempotency_key):
        """Devolve (pedido, criado). Retentativa idêntica: (pedido, False)."""
        if not is_valid_key(idempotency_key):
            raise ChaveIdempotenciaAusente()

        pessoa = self.identify(pessoa_id)
        conta = self.conta_repository.get_conta(payload["conta_id"])

        if conta is None:
            raise ContaNaoEncontrada()

        socio = self.require_socio(pessoa, conta.empresa_id)

        responsabilidade = None
        if payload.get("responsabilidade_id") is not None:
            responsabilidade = self.responsabilidade_repository.get_da_conta(conta.conta_id, payload["responsabilidade_id"])
            if responsabilidade is None:
                raise ResponsabilidadeNaoEncontrada()

        permissao = self.require_permission(socio, PermissaoSocio.EXECUTAR_PAGAMENTO, [responsabilidade])

        data_prevista = self._parse_date(payload["data_prevista"])
        if data_prevista < clock.today():
            raise DataNoPassado()

        meio = payload["meio"]
        valor = payload["valor_centavos"]

        if meio == Transacao.BOLETO:
            self.check_boleto_due(payload["contraparte"])

        self.check_limit(permissao, valor)

        # ── a trava ──
        conta = self.conta_repository.lock_contas([conta.conta_id])[conta.conta_id]
        if responsabilidade is not None:
            responsabilidade = self.responsabilidade_repository.get_da_conta(conta.conta_id, responsabilidade.responsabilidade_id, fresh=True)

        body_hash = request_hash(payload)
        existing = self.pagamento_repository.find_by_autor_chave(socio.empresa_socio_id, idempotency_key)

        if existing is not None:
            if existing.hash_requisicao == body_hash:
                return self._to_dto(existing), False

            raise ChaveIdempotenciaReutilizada()

        referencia = payload.get("referencia_externa")
        if meio == Transacao.BOLETO:
            if self.pagamento_repository.find_ativo_by_boleto(meio, referencia) is not None:
                raise BoletoEmPedidoAtivo()

            if self.transacao_repository.find_by_meio_referencia(meio, referencia) is not None:
                raise BoletoJaPago()

        self.require_active_account(conta)

        tarifa = self.conta_repository.get_tarifa_vigente(meio, clock.now())
        total = valor + tarifa.valor_centavos

        orcamento = None
        if responsabilidade is not None:
            orcamento = self.responsabilidade_repository.get_orcamento(responsabilidade.responsabilidade_id, clock.competence(data_prevista))
            Ledger.check_budget(orcamento, total)

        Ledger.require_funds(conta, responsabilidade, total)

        regra = self.resolve_rule(conta.empresa_id, RegraAprovacao.PAGAMENTO, meio, valor)
        exigidas = 0
        if regra is not None:
            exigidas = self.approvals_for(regra, conta.empresa_id, socio.empresa_socio_id, [responsabilidade])

        # Compromete o dinheiro JÁ, na mesma transação: a execução futura não
        # pode falhar por saldo, e o mesmo dinheiro não é prometido duas vezes.
        Ledger.commit_funds(conta, responsabilidade, total)
        Ledger.use_budget(orcamento, total)

        try:
            pedido = self.pagamento_repository.add_pagamento(
                conta_id=conta.conta_id,
                responsabilidade_id=responsabilidade.responsabilidade_id if responsabilidade else None,
                autor_empresa_socio_id=socio.empresa_socio_id,
                meio=meio,
                contraparte=payload["contraparte"],
                referencia_externa=referencia,
                valor_centavos=valor,
                tarifa_id=tarifa.tarifa_id,
                data_prevista=data_prevista,
                status=PagamentoProgramado.AGUARDANDO_APROVACAO if exigidas > 0 else PagamentoProgramado.AGENDADO,
                aprovacoes_exigidas=exigidas,
                chave_idempotencia=idempotency_key,
                hash_requisicao=body_hash,
                categoria=payload.get("categoria"),
                descricao=payload.get("descricao"),
            )
        except IntegrityError as error:
            self.session.rollback()
            constraint = violated_constraint(error)

            if constraint == "uq_pp_boleto_ativo":
                raise BoletoEmPedidoAtivo()

            if constraint == "uq_pp_autor_chave":
                raise ChaveIdempotenciaReutilizada()

            raise

        pedido_dto = PagamentoProgramadoDTO.obj_to_dict(pedido, tarifa.valor_centavos)
        self.session.commit()

        return pedido_dto, True

    # ── listar ──────────────────────────────────────────────────────

    def list_by_conta(self, conta_id: str, pessoa_id, params: dict) -> dict:
        pessoa = self.identify(pessoa_id)
        conta = self.conta_repository.get_conta(conta_id)

        if conta is None:
            raise ContaNaoEncontrada()

        socio = self.require_socio(pessoa, conta.empresa_id)
        self.require_permission(socio, PermissaoSocio.CONSULTAR)

        limit = parse_limit(params.get("limite"))
        cursor = decode_cursor(params["cursor"]) if params.get("cursor") else None

        rows = self.pagamento_repository.list_by_conta(conta.conta_id, params.get("status"), cursor, limit + 1)
        has_more = len(rows) > limit
        page = rows[:limit]

        ids = [pedido.pagamento_programado_id for pedido in page]
        votos = self.governanca_repository.list_votos_dos_pagamentos(ids)
        transacoes = self.transacao_repository.map_by_pagamentos(ids)

        itens = []
        for pedido in page:
            votos_do_pedido = [(voto, nome) for voto, nome in votos if voto.pagamento_programado_id == pedido.pagamento_programado_id]
            tarifa = self.conta_repository.get_tarifa(pedido.tarifa_id)
            itens.append(
                PagamentoProgramadoDTO.obj_to_dict(
                    pedido, tarifa.valor_centavos, votos_do_pedido, transacoes.get(pedido.pagamento_programado_id)
                )
            )

        next_cursor = None
        if has_more:
            next_cursor = encode_cursor(page[-1].criado_em, page[-1].pagamento_programado_id)

        return {"itens": itens, "proximo_cursor": next_cursor}

    # ── cancelar ────────────────────────────────────────────────────

    def cancel(self, pagamento_id: str, motivo, pessoa_id) -> dict:
        """O autor, ou quem tem GERIR_RESPONSABILIDADE, cancela um pedido
        pendente ou agendado e o dinheiro comprometido volta. Idempotente:
        cancelar o que já está CANCELADO devolve 200."""
        pessoa = self.identify(pessoa_id)
        pedido = self.pagamento_repository.get_pagamento(pagamento_id)

        if pedido is None:
            raise PagamentoProgramadoNaoEncontrado()

        conta = self.conta_repository.get_conta(pedido.conta_id)
        socio = self.require_socio(pessoa, conta.empresa_id)
        responsabilidade = self._responsabilidade(pedido)

        if pedido.autor_empresa_socio_id != socio.empresa_socio_id:
            self.require_permission(socio, PermissaoSocio.GERIR_RESPONSABILIDADE, [responsabilidade])

        # conta primeiro, depois o pedido — e relê o status (outro pode ter vencido a corrida)
        conta = self.conta_repository.lock_contas([conta.conta_id])[conta.conta_id]
        pedido = self.pagamento_repository.get_pagamento(pagamento_id, lock=True)
        responsabilidade = self._responsabilidade(pedido, fresh=True)

        if pedido.status == PagamentoProgramado.CANCELADO:
            return self._to_dto(pedido)

        if pedido.status == PagamentoProgramado.EXECUTADO:
            raise JaExecutado()

        if pedido.status in (PagamentoProgramado.RECUSADO, PagamentoProgramado.FALHOU):
            raise EstadoFinal()

        self.release_payment(pedido, conta, responsabilidade)
        pedido.status = PagamentoProgramado.CANCELADO
        pedido.motivo = motivo
        self.session.flush()

        pedido_dto = self._to_dto(pedido)
        self.session.commit()

        return pedido_dto

    # ── executar ────────────────────────────────────────────────────

    def execute(self, pagamento_id: str):
        """O parceiro (ou o agendador) executa o pedido AGENDADO na data
        prevista: cria a TRANSACAO e baixa o comprometido. Só INTERNAL-TOKEN.

        Devolve (transacao, criada). Repetir devolve a MESMA transação (200):
        a UNIQUE(pagamento_programado_id) da transação é a última defesa.
        """
        pedido = self.pagamento_repository.get_pagamento(pagamento_id)

        if pedido is None:
            raise PagamentoProgramadoNaoEncontrado()

        conta = self.conta_repository.lock_contas([pedido.conta_id])[pedido.conta_id]
        pedido = self.pagamento_repository.get_pagamento(pagamento_id, lock=True)

        if pedido.status == PagamentoProgramado.EXECUTADO:
            existing = self.transacao_repository.find_by_pagamento_programado(pedido.pagamento_programado_id)
            return self._transacao_dto(existing), False

        if pedido.status != PagamentoProgramado.AGENDADO:
            raise NaoAgendado(f"payment is {pedido.status}")

        if pedido.data_prevista > clock.today():
            raise DataNaoChegou()

        # conta bloqueada: o pedido continua AGENDADO e o dinheiro, comprometido
        self.require_active_account(conta)

        responsabilidade = self._responsabilidade(pedido, fresh=True)

        if pedido.meio == Transacao.BOLETO:
            falha = self._boleto_failure(pedido)

            if falha is not None:
                # O pedido FALHA definitivamente e o dinheiro volta — e isso
                # precisa ficar gravado MESMO com a resposta sendo um erro:
                # commit primeiro, erro depois.
                self.release_payment(pedido, conta, responsabilidade)
                pedido.status = PagamentoProgramado.FALHOU
                pedido.motivo = falha.title
                self.session.commit()
                raise falha

        tarifa = self.conta_repository.get_tarifa(pedido.tarifa_id)
        total = pedido.valor_centavos + tarifa.valor_centavos

        Ledger.settle_commitment(conta, responsabilidade, total)
        pedido.status = PagamentoProgramado.EXECUTADO

        try:
            transacao = self.transacao_repository.add_transacao(
                natureza=Transacao.SAIDA,
                meio=pedido.meio,
                conta_origem_id=conta.conta_id,
                contraparte=pedido.contraparte,
                referencia_externa=pedido.referencia_externa,
                autor_empresa_socio_id=pedido.autor_empresa_socio_id,
                responsabilidade_id=pedido.responsabilidade_id,
                pagamento_programado_id=pedido.pagamento_programado_id,
                valor_centavos=pedido.valor_centavos,
                tarifa_id=pedido.tarifa_id,
                categoria=pedido.categoria,
                descricao=pedido.descricao,
                saldo_origem_apos_centavos=conta.saldo_total_centavos,
            )
        except IntegrityError as error:
            self.session.rollback()
            constraint = violated_constraint(error)

            if constraint == "uq_transacao_meio_referencia":
                raise BoletoJaPago()

            if constraint == "uq_transacao_pagamento_programado":
                raise JaExecutado()

            raise

        transacao_dto = self._transacao_dto(transacao)
        self.session.commit()

        return transacao_dto, True

    # ── apoio ───────────────────────────────────────────────────────

    def _boleto_failure(self, pedido):
        """O boleto não pode mais ser pago? (vencido, ou já pago por outro caminho)."""
        try:
            self.check_boleto_due(pedido.contraparte)
        except BoletoVencido as error:
            return error

        if self.transacao_repository.find_by_meio_referencia(pedido.meio, pedido.referencia_externa) is not None:
            return BoletoJaPago()

        return None

    def _responsabilidade(self, pedido, fresh: bool = False):
        if pedido.responsabilidade_id is None:
            return None

        return self.responsabilidade_repository.get_da_conta(pedido.conta_id, pedido.responsabilidade_id, fresh=fresh)

    def _to_dto(self, pedido) -> dict:
        tarifa = self.conta_repository.get_tarifa(pedido.tarifa_id)
        votos = self.governanca_repository.list_votos_dos_pagamentos([pedido.pagamento_programado_id])
        transacao = self.transacao_repository.find_by_pagamento_programado(pedido.pagamento_programado_id)

        return PagamentoProgramadoDTO.obj_to_dict(
            pedido, tarifa.valor_centavos, votos, transacao.transacao_id if transacao else None
        )

    def _transacao_dto(self, transacao) -> dict:
        from dtos import TransacaoDTO

        tarifa = self.conta_repository.get_tarifa(transacao.tarifa_id)
        autor_nome = self.empresa_repository.get_nome_do_socio(transacao.autor_empresa_socio_id)

        return TransacaoDTO.obj_to_dict(transacao, tarifa.valor_centavos if tarifa else 0, autor_nome=autor_nome)

    @staticmethod
    def _parse_date(raw: str) -> date:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            raise InvalidParameter(f"{raw} is not a real date")
