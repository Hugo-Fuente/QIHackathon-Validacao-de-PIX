from datetime import date

from sqlalchemy.exc import IntegrityError

from controllers.access_control import AccessControl
from controllers.approval_rules import ApprovalRules
from controllers.base_controller import BaseController
from controllers.ledger import Ledger
from dtos import TransacaoDTO
from errors import (
    AprovacaoNecessaria,
    BoletoJaPago,
    BoletoVencido,
    ChaveIdempotenciaAusente,
    ChaveIdempotenciaReutilizada,
    ContaNaoEncontrada,
    InvalidParameter,
    MeioIncoerente,
    PermissaoNegada,
    ResponsabilidadeNaoEncontrada,
    TransacaoNaoEncontrada,
    TransacaoSemContaNossa,
)
from models import PermissaoSocio, RegraAprovacao, Transacao
from repositories import (
    ContaRepository,
    EmpresaRepository,
    GovernancaRepository,
    ResponsabilidadeRepository,
    TransacaoRepository,
)
from utils import clock
from utils.db_errors import violated_constraint
from utils.idempotency import is_valid_key, request_hash


class TransacaoController(BaseController, AccessControl, ApprovalRules):
    """Movimenta dinheiro na hora: entrada de fora, saída para outro banco e
    transferência interna. É aqui que mora a regra da RFC:

        toda operação que muda saldo começa travando a CONTA (FOR UPDATE, em
        ordem de conta_id), e só então lê, confere e grava — num único commit.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.empresa_repository = EmpresaRepository(self.context)
        self.conta_repository = ContaRepository(self.context)
        self.transacao_repository = TransacaoRepository(self.context)
        self.responsabilidade_repository = ResponsabilidadeRepository(self.context)
        self.governanca_repository = GovernancaRepository(self.context)

    def create(self, payload: dict, pessoa_id, idempotency_key):
        """Devolve (resposta, criada): criada=False é uma retentativa idêntica
        (200), criada=True é uma transação nova (201).

        A natureza não vem no corpo — sai da presença de origem e destino:
        só destino é ENTRADA (o parceiro de pagamentos, sem X-Pessoa-Id); só
        origem é SAIDA; os dois, INTERNA.
        """
        if payload.get("conta_origem_id") is None:
            return self._create_entrada(payload)

        return self._create_saida_ou_interna(payload, pessoa_id, idempotency_key)

    def get(self, transacao_id: str, pessoa_id) -> dict:
        pessoa = self.identify(pessoa_id)
        row = self.transacao_repository.get_with_details(transacao_id)

        if row is None:
            raise TransacaoNaoEncontrada()

        transacao = row.Transacao
        tem_vinculo = False

        for conta_id in (transacao.conta_origem_id, transacao.conta_destino_id):
            if conta_id is None:
                continue

            conta = self.conta_repository.get_conta(conta_id)
            socio = self.empresa_repository.get_socio_by_pessoa(conta.empresa_id, pessoa.pessoa_id)

            if socio is not None and self.empresa_repository.get_permissao(socio.empresa_socio_id, PermissaoSocio.CONSULTAR):
                tem_vinculo = True

        if not tem_vinculo:
            raise PermissaoNegada()

        return TransacaoDTO.obj_to_dict(
            transacao, row.tarifa_centavos, autor_nome=row.autor_nome, responsabilidade_nome=row.responsabilidade_nome
        )

    # ── entrada de fora do banco ────────────────────────────────────

    def _create_entrada(self, payload: dict):
        """O parceiro avisa que entrou dinheiro. Só INTERNAL-TOKEN: sem sócio,
        sem tarifa. O identificador do parceiro (referencia_externa) é a chave
        de idempotência: a mesma notificação duas vezes credita uma só vez."""
        if payload.get("responsabilidade_id") is not None:
            raise InvalidParameter("responsabilidade_id is not allowed in an incoming transaction")

        meio = payload["meio"]

        if meio == Transacao.INTERNO:
            raise MeioIncoerente()

        destino = self.conta_repository.get_conta(payload["conta_destino_id"])

        if destino is None:
            raise ContaNaoEncontrada()

        body_hash = request_hash(payload)
        conta = self.conta_repository.lock_contas([destino.conta_id])[destino.conta_id]

        existing = self.transacao_repository.find_by_meio_referencia(meio, payload["referencia_externa"])
        if existing is not None:
            if existing.hash_requisicao == body_hash and existing.conta_destino_id == conta.conta_id:
                return self._to_dto(existing), False

            raise ChaveIdempotenciaReutilizada()

        self.require_active_account(conta)

        valor = payload["valor_centavos"]
        conta.saldo_total_centavos += valor

        try:
            transacao = self.transacao_repository.add_transacao(
                natureza=Transacao.ENTRADA,
                meio=meio,
                conta_destino_id=conta.conta_id,
                contraparte=payload.get("contraparte"),
                referencia_externa=payload["referencia_externa"],
                hash_requisicao=body_hash,
                valor_centavos=valor,
                categoria=payload.get("categoria"),
                descricao=payload.get("descricao"),
                saldo_destino_apos_centavos=conta.saldo_total_centavos,
            )
        except IntegrityError as error:
            self._raise_conflict(error)

        transacao_dto = self._to_dto(transacao)
        self.session.commit()

        return transacao_dto, True

    # ── saída e transferência interna ───────────────────────────────

    def _create_saida_ou_interna(self, payload: dict, pessoa_id, idempotency_key):
        if not is_valid_key(idempotency_key):
            raise ChaveIdempotenciaAusente()

        pessoa = self.identify(pessoa_id)

        origem = self.conta_repository.get_conta(payload["conta_origem_id"])
        if origem is None:
            raise ContaNaoEncontrada()

        socio = self.require_socio(pessoa, origem.empresa_id)

        responsabilidade = None
        if payload.get("responsabilidade_id") is not None:
            responsabilidade = self.responsabilidade_repository.get_da_conta(origem.conta_id, payload["responsabilidade_id"])
            if responsabilidade is None:
                raise ResponsabilidadeNaoEncontrada()

        permissao = self.require_permission(socio, PermissaoSocio.EXECUTAR_PAGAMENTO, [responsabilidade])

        meio = payload["meio"]
        destino_id = payload.get("conta_destino_id")
        is_interna = destino_id is not None

        if is_interna:
            if str(destino_id) == origem.conta_id:
                raise TransacaoSemContaNossa("origin and destination are the same account")

            if self.conta_repository.get_conta(destino_id) is None:
                raise ContaNaoEncontrada()

            if meio != Transacao.INTERNO:
                raise MeioIncoerente()
        elif meio == Transacao.INTERNO:
            raise MeioIncoerente()

        # ── a trava: contas em ordem crescente de id, e só então ler ──
        locked = self.conta_repository.lock_contas([origem.conta_id, destino_id])
        origem = locked[origem.conta_id]
        destino = locked[str(destino_id)] if is_interna else None

        if responsabilidade is not None:
            responsabilidade = self.responsabilidade_repository.get_da_conta(origem.conta_id, responsabilidade.responsabilidade_id, fresh=True)

        body_hash = request_hash(payload)

        existing = self.transacao_repository.find_by_autor_chave(socio.empresa_socio_id, idempotency_key)
        if existing is not None:
            if existing.hash_requisicao == body_hash:
                return self._to_dto(existing), False

            raise ChaveIdempotenciaReutilizada()

        referencia = payload.get("referencia_externa")
        if referencia is not None and self.transacao_repository.find_by_meio_referencia(meio, referencia) is not None:
            if meio == Transacao.BOLETO:
                raise BoletoJaPago()

            raise ChaveIdempotenciaReutilizada("external reference already used")

        valor = payload["valor_centavos"]
        tarifa = None
        tarifa_valor = 0

        if not is_interna:
            tarifa = self.conta_repository.get_tarifa_vigente(meio, clock.now())
            tarifa_valor = tarifa.valor_centavos

        total = valor + tarifa_valor

        # ── as conferências 422, na ordem da RFC ──
        self.require_active_account(origem)
        if is_interna:
            self.require_active_account(destino)

        if meio == Transacao.BOLETO and self._due_date(payload["contraparte"]) < clock.today():
            raise BoletoVencido()

        self.check_limit(permissao, valor)

        if self.resolve_rule(origem.empresa_id, RegraAprovacao.PAGAMENTO, meio, valor) is not None:
            raise AprovacaoNecessaria()

        orcamento = None
        if responsabilidade is not None:
            orcamento = self.responsabilidade_repository.get_orcamento(responsabilidade.responsabilidade_id, clock.competence())
            Ledger.check_budget(orcamento, total)

        Ledger.require_funds(origem, responsabilidade, total)

        # ── tudo certo: grava (baixa, orçamento, crédito, transação) ──
        Ledger.spend_now(origem, responsabilidade, total)
        Ledger.use_budget(orcamento, total)

        if is_interna:
            destino.saldo_total_centavos += valor

        try:
            transacao = self.transacao_repository.add_transacao(
                natureza=Transacao.INTERNA if is_interna else Transacao.SAIDA,
                meio=meio,
                conta_origem_id=origem.conta_id,
                conta_destino_id=destino.conta_id if is_interna else None,
                contraparte=payload.get("contraparte"),
                referencia_externa=referencia,
                autor_empresa_socio_id=socio.empresa_socio_id,
                responsabilidade_id=responsabilidade.responsabilidade_id if responsabilidade else None,
                chave_idempotencia=idempotency_key,
                hash_requisicao=body_hash,
                valor_centavos=valor,
                tarifa_id=tarifa.tarifa_id if tarifa else None,
                categoria=payload.get("categoria"),
                descricao=payload.get("descricao"),
                saldo_origem_apos_centavos=origem.saldo_total_centavos,
                saldo_destino_apos_centavos=destino.saldo_total_centavos if is_interna else None,
            )
        except IntegrityError as error:
            self._raise_conflict(error)

        transacao_dto = self._to_dto(transacao, autor_nome=pessoa.nome)
        transacao_dto["responsabilidade_nome"] = responsabilidade.nome if responsabilidade else None
        self.session.commit()

        return transacao_dto, True

    # ── apoio ───────────────────────────────────────────────────────

    def _to_dto(self, transacao: Transacao, autor_nome=None) -> dict:
        tarifa = self.conta_repository.get_tarifa(transacao.tarifa_id)

        return TransacaoDTO.obj_to_dict(transacao, tarifa.valor_centavos if tarifa else 0, autor_nome=autor_nome)

    def _raise_conflict(self, error: IntegrityError) -> None:
        """A última defesa: duas requisições que a trava não serializou (contas
        diferentes) esbarraram numa UNIQUE. Desfaz tudo e responde 409."""
        self.session.rollback()
        constraint = violated_constraint(error)

        if constraint == "uq_transacao_meio_referencia":
            raise BoletoJaPago()

        if constraint in ("uq_transacao_autor_chave", "uq_transacao_pagamento_programado"):
            raise ChaveIdempotenciaReutilizada()

        raise error

    @staticmethod
    def _due_date(contraparte: dict) -> date:
        try:
            return date.fromisoformat(contraparte["vencimento"])
        except (KeyError, ValueError, TypeError):
            raise InvalidParameter("contraparte.vencimento is not a valid date")
