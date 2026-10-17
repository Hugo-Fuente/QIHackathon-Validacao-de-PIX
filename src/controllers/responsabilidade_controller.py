import re
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from controllers.access_control import AccessControl
from controllers.base_controller import BaseController
from controllers.ledger import Ledger  # noqa: F401  (documenta de onde vêm os saldos)
from dtos import ResponsabilidadeDTO
from errors import (
    ContaNaoEncontrada,
    InvalidParameter,
    OrcamentoAbaixoDoUtilizado,
    PeriodoInvalido,
    PermissaoNegada,
    ResponsabilidadeJaExiste,
    ResponsabilidadeNaoEncontrada,
    ResponsabilidadeNaoESocio,
    SubstitutoInvalido,
)
from models import PermissaoSocio
from repositories import ContaRepository, EmpresaRepository, GovernancaRepository, ResponsabilidadeRepository
from utils import clock
from utils.cursor import parse_moment
from utils.db_errors import violated_constraint

COMPETENCE_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ResponsabilidadeController(BaseController, AccessControl):
    """Responsabilidade (organização lógica do dinheiro), substituição do
    responsável e orçamento mensal."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.empresa_repository = EmpresaRepository(self.context)
        self.conta_repository = ContaRepository(self.context)
        self.responsabilidade_repository = ResponsabilidadeRepository(self.context)
        self.governanca_repository = GovernancaRepository(self.context)

    def create(self, payload: dict, pessoa_id) -> dict:
        pessoa = self.identify(pessoa_id)
        conta = self.conta_repository.get_conta(payload["conta_id"])

        if conta is None:
            raise ContaNaoEncontrada()

        socio = self.require_socio(pessoa, conta.empresa_id)
        permissao = self.empresa_repository.get_permissao(socio.empresa_socio_id, PermissaoSocio.GERIR_RESPONSABILIDADE)

        if permissao is None:
            raise PermissaoNegada()

        # Escopo PROPRIAS: só pode criar uma responsabilidade da qual ele mesmo
        # é o responsável (ainda não existe responsabilidade para conferir).
        if permissao.escopo == PermissaoSocio.PROPRIAS and payload["responsavel_empresa_socio_id"] != socio.empresa_socio_id:
            raise PermissaoNegada()

        responsavel = self.empresa_repository.get_socio_da_empresa(conta.empresa_id, payload["responsavel_empresa_socio_id"])

        if responsavel is None:
            raise ResponsabilidadeNaoESocio()

        nome = payload["nome"].strip()

        if self.responsabilidade_repository.find_by_nome(conta.conta_id, nome) is not None:
            raise ResponsabilidadeJaExiste()

        try:
            responsabilidade = self.responsabilidade_repository.add_responsabilidade(
                conta_id=conta.conta_id, nome=nome, responsavel_empresa_socio_id=responsavel.empresa_socio_id
            )
        except IntegrityError as error:
            self.session.rollback()

            if violated_constraint(error) == "uq_responsabilidade_conta_nome":
                raise ResponsabilidadeJaExiste()

            raise

        self.governanca_repository.add_evento(
            conta.empresa_id,
            socio.empresa_socio_id,
            "RESPONSABILIDADE_CRIADA",
            "RESPONSABILIDADE",
            responsabilidade.responsabilidade_id,
            {"nome": nome, "responsavel_empresa_socio_id": responsavel.empresa_socio_id},
        )

        responsabilidade_dto = ResponsabilidadeDTO.only_id(responsabilidade)
        self.session.commit()

        return responsabilidade_dto

    def get(self, responsabilidade_id: str, pessoa_id) -> dict:
        pessoa = self.identify(pessoa_id)
        responsabilidade, conta = self._load(responsabilidade_id)
        socio = self.require_socio(pessoa, conta.empresa_id)
        self.require_permission(socio, PermissaoSocio.CONSULTAR)

        return self._to_dto(responsabilidade)

    def set_substituicao(self, responsabilidade_id: str, payload: dict, pessoa_id) -> dict:
        """Define o substituto e a janela em que ele age pelo responsável.
        Idempotente: o PUT repetido deixa o mesmo estado (e não duplica a
        auditoria)."""
        pessoa = self.identify(pessoa_id)
        responsabilidade, conta = self._load(responsabilidade_id)
        socio = self.require_socio(pessoa, conta.empresa_id)
        self.require_permission(socio, PermissaoSocio.GERIR_RESPONSABILIDADE, [responsabilidade])

        inicio = parse_moment(payload["inicio"], "inicio")
        fim = parse_moment(payload["fim"], "fim")

        if fim <= inicio:
            raise PeriodoInvalido("fim must be after inicio")

        substituto = self.empresa_repository.get_socio_da_empresa(conta.empresa_id, payload["substituto_empresa_socio_id"])

        if substituto is None or substituto.empresa_socio_id == responsabilidade.responsavel_empresa_socio_id:
            raise SubstitutoInvalido()

        unchanged = (
            responsabilidade.substituto_empresa_socio_id == substituto.empresa_socio_id
            and responsabilidade.substituicao_inicio == inicio
            and responsabilidade.substituicao_fim == fim
        )

        if not unchanged:
            responsabilidade.substituto_empresa_socio_id = substituto.empresa_socio_id
            responsabilidade.substituicao_inicio = inicio
            responsabilidade.substituicao_fim = fim
            self.session.flush()

            self.governanca_repository.add_evento(
                conta.empresa_id,
                socio.empresa_socio_id,
                "SUBSTITUICAO_DEFINIDA",
                "RESPONSABILIDADE",
                responsabilidade.responsabilidade_id,
                {
                    "substituto_empresa_socio_id": substituto.empresa_socio_id,
                    "inicio": inicio.isoformat(),
                    "fim": fim.isoformat(),
                },
            )

        responsabilidade_dto = self._to_dto(responsabilidade)
        self.session.commit()

        return responsabilidade_dto

    def set_orcamento(self, responsabilidade_id: str, competencia: str, payload: dict, pessoa_id) -> dict:
        """Cria ou atualiza o teto do mês. Trava a CONTA antes de ler o
        `utilizado`: um pagamento em andamento também mexe nele, e sem a
        trava o teto poderia ficar abaixo do que acabou de ser usado."""
        pessoa = self.identify(pessoa_id)

        if not COMPETENCE_PATTERN.match(competencia):
            raise InvalidParameter("competencia must be AAAA-MM")

        responsabilidade, conta = self._load(responsabilidade_id)
        socio = self.require_socio(pessoa, conta.empresa_id)
        self.require_permission(socio, PermissaoSocio.GERIR_RESPONSABILIDADE, [responsabilidade])

        self.conta_repository.lock_contas([conta.conta_id])

        valor = payload["valor_centavos"]
        orcamento = self.responsabilidade_repository.get_orcamento(responsabilidade.responsabilidade_id, competencia)

        if orcamento is None:
            orcamento = self.responsabilidade_repository.add_orcamento(responsabilidade.responsabilidade_id, competencia, valor)
            anterior = None
        else:
            if valor < orcamento.utilizado_centavos:
                raise OrcamentoAbaixoDoUtilizado(f"utilizado {orcamento.utilizado_centavos} > {valor}")

            anterior = orcamento.valor_centavos
            orcamento.valor_centavos = valor
            self.session.flush()

        if anterior != valor:
            self.governanca_repository.add_evento(
                conta.empresa_id,
                socio.empresa_socio_id,
                "ORCAMENTO_DEFINIDO",
                "ORCAMENTO",
                orcamento.orcamento_id,
                {"competencia": competencia, "valor_centavos": valor, "anterior_centavos": anterior},
            )

        orcamento_dto = ResponsabilidadeDTO.orcamento_to_dict(orcamento)
        self.session.commit()

        return orcamento_dto

    # ── apoio ───────────────────────────────────────────────────────

    def _load(self, responsabilidade_id: str):
        responsabilidade = self.responsabilidade_repository.get_responsabilidade(responsabilidade_id)

        if responsabilidade is None:
            raise ResponsabilidadeNaoEncontrada()

        conta = self.conta_repository.get_conta(responsabilidade.conta_id)

        return responsabilidade, conta

    def _socio_resumo(self, empresa_socio_id):
        if empresa_socio_id is None:
            return None

        return {"empresa_socio_id": empresa_socio_id, "nome": self.empresa_repository.get_nome_do_socio(empresa_socio_id)}

    def _to_dto(self, responsabilidade) -> dict:
        now = clock.now()
        substituto_vigente = None
        substituicao = None

        if responsabilidade.substituto_empresa_socio_id is not None:
            inicio: datetime = responsabilidade.substituicao_inicio
            fim: datetime = responsabilidade.substituicao_fim
            substituto = self._socio_resumo(responsabilidade.substituto_empresa_socio_id)
            substituicao = {**substituto, "inicio": inicio.isoformat(), "fim": fim.isoformat()}

            if inicio <= now < fim:
                substituto_vigente = substituto

        orcamento = self.responsabilidade_repository.get_orcamento(responsabilidade.responsabilidade_id, clock.competence())

        return ResponsabilidadeDTO.obj_to_dict(
            responsabilidade,
            self._socio_resumo(responsabilidade.responsavel_empresa_socio_id),
            substituto_vigente,
            substituicao,
            ResponsabilidadeDTO.orcamento_to_dict(orcamento) if orcamento else None,
        )
