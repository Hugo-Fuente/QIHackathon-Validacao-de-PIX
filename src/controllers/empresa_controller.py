from datetime import date

from sqlalchemy.exc import IntegrityError

from controllers.access_control import AccessControl
from controllers.base_controller import BaseController
from dtos import EmpresaDTO
from errors import (
    DataNascimentoInvalida,
    DocumentoInvalido,
    EmailJaCadastrado,
    EmpresaJaCadastrada,
    EmpresaNaoEncontrada,
    EstruturaSocietariaInvalida,
    SocioMenorDeIdade,
    SomaParticipacaoInvalida,
)
from models import EmpresaSocio, PermissaoSocio, Status
from repositories import ContaRepository, EmpresaRepository
from utils import clock
from utils.db_errors import violated_constraint
from utils.document_number import is_valid_cnpj, is_valid_cpf, only_digits

MINIMUM_AGE = 18
TOTAL_BASIS_POINTS = 10000
DEFAULT_AGENCY = "0001"


class EmpresaController(BaseController, AccessControl):
    """Cadastro e consulta da empresa (a conta compartilhada nasce junto)."""

    def __init__(self) -> None:
        super().__init__(__name__)
        self.empresa_repository = EmpresaRepository(self.context)
        self.conta_repository = ContaRepository(self.context)

    def create(self, payload: dict) -> dict:
        """Cadastra a empresa, os sócios, a conta e as permissões padrão —
        TUDO ou NADA, num único commit.

        Primeiro as regras que só olham o corpo (nenhuma escrita acontece se
        alguma falhar). Depois uma transação: se duas requisições com o mesmo
        CNPJ (ou razão social) chegam juntas, as duas passam pela checagem
        prévia — porque nenhuma gravou ainda — e a segunda esbarra na
        UNIQUE do banco, que desfaz o cadastro inteiro (nem pessoas novas
        nem conta ficam gravadas) e vira 409. A checagem prévia só poupa
        trabalho no caso comum; quem garante é a restrição.
        """
        cnpj = only_digits(payload["cnpj"])
        razao_social = " ".join(payload["razao_social"].split())

        if not is_valid_cnpj(cnpj):
            raise DocumentoInvalido(f"CNPJ {payload['cnpj']} is not valid")

        socios = self._validate_socios(payload["socios"])
        self._validate_structure(socios)

        if self.empresa_repository.exists_cnpj_or_razao_social(cnpj, razao_social.lower()):
            raise EmpresaJaCadastrada()

        try:
            empresa = self.empresa_repository.add_empresa(cnpj, razao_social)

            # As pessoas entram em ordem de CPF: dois cadastros que dividem
            # sócios novos pegam as mesmas linhas na mesma ordem e não se
            # travam um ao outro (mesma ideia da ordem por conta_id).
            pessoas = {}
            for socio in sorted(socios, key=lambda item: item["cpf"]):
                pessoas[socio["cpf"]] = self.empresa_repository.upsert_pessoa(
                    socio["cpf"], socio["nome"], socio["email"], socio["data_nascimento"]
                )

            vinculos = []
            for socio in socios:
                vinculo = self.empresa_repository.add_socio(
                    empresa.empresa_id, pessoas[socio["cpf"]].pessoa_id, socio["papel"], socio["participacao_bp"]
                )
                self._grant_default_permissions(vinculo)
                vinculos.append((vinculo, socio["cpf"]))

            em_aprovacao = self.conta_repository.get_status_by_codigo(Status.EM_APROVACAO)
            conta = self.conta_repository.add_conta(
                empresa.empresa_id,
                em_aprovacao.status_id,
                DEFAULT_AGENCY,
                self.conta_repository.next_account_number(),
            )
            self.conta_repository.add_status_event(conta.conta_id, em_aprovacao.status_id, "Conta cadastrada")
        except IntegrityError as error:
            self.session.rollback()
            constraint = violated_constraint(error)

            if constraint in ("uq_empresa_cnpj", "uq_empresa_razao_social"):
                raise EmpresaJaCadastrada()

            if constraint == "uq_pessoa_email":
                raise EmailJaCadastrado()

            raise

        empresa_dto = EmpresaDTO.only_ids(empresa.empresa_id, conta.conta_id, vinculos)
        self.session.commit()

        return empresa_dto

    def get(self, empresa_id: str, pessoa_id) -> dict:
        pessoa = self.identify(pessoa_id)
        empresa = self.empresa_repository.get_empresa(empresa_id)

        if empresa is None:
            raise EmpresaNaoEncontrada()

        socio = self.require_socio(pessoa, empresa.empresa_id)
        self.require_permission(socio, PermissaoSocio.CONSULTAR)

        socios = []
        for vinculo, pessoa_do_socio in self.empresa_repository.list_socios(empresa.empresa_id):
            permissoes = self.empresa_repository.list_permissoes(vinculo.empresa_socio_id)
            socios.append((vinculo, pessoa_do_socio, permissoes))

        conta = self.conta_repository.get_conta_da_empresa(empresa.empresa_id)

        return EmpresaDTO.obj_to_dict(empresa, conta, socios)

    # ── regras do cadastro ──────────────────────────────────────────

    def _validate_socios(self, raw_socios: list) -> list:
        """Documentos válidos e idade mínima. Devolve os sócios já normalizados
        (CPF só com dígitos, data como `date`)."""
        socios = []

        for raw in raw_socios:
            cpf = only_digits(raw["cpf"])

            if not is_valid_cpf(cpf):
                raise DocumentoInvalido(f"CPF {raw['cpf']} is not valid")

            birthdate = self._parse_date(raw["data_nascimento"])

            if self._age_in_years(birthdate) < MINIMUM_AGE:
                raise SocioMenorDeIdade(f"partner {raw['nome']} is under {MINIMUM_AGE}")

            socios.append(
                {
                    "cpf": cpf,
                    "nome": raw["nome"].strip(),
                    "email": raw["email"].strip().lower(),
                    "data_nascimento": birthdate,
                    "papel": raw["papel"],
                    "participacao_bp": raw["participacao_bp"],
                }
            )

        return socios

    @staticmethod
    def _validate_structure(socios: list) -> None:
        if not socios:
            raise EstruturaSocietariaInvalida("the company needs at least one partner")

        if len({socio["cpf"] for socio in socios}) != len(socios):
            raise EstruturaSocietariaInvalida("partners must have distinct CPFs")

        if not any(socio["papel"] == EmpresaSocio.SOCIO_ADMINISTRADOR for socio in socios):
            raise EstruturaSocietariaInvalida("the company needs at least one SOCIO_ADMINISTRADOR")

        total = sum(socio["participacao_bp"] for socio in socios)

        if total != TOTAL_BASIS_POINTS:
            raise SomaParticipacaoInvalida(f"shares sum {total}, expected {TOTAL_BASIS_POINTS}")

    def _grant_default_permissions(self, vinculo: EmpresaSocio) -> None:
        """O administrador faz tudo (todas as ações, escopo TODAS, sem limite);
        o sócio comum só consulta. Depois a empresa ajusta, caso a caso."""
        if vinculo.papel == EmpresaSocio.SOCIO_ADMINISTRADOR:
            actions = PermissaoSocio.ACOES
        else:
            actions = (PermissaoSocio.CONSULTAR,)

        for action in actions:
            self.empresa_repository.add_permissao(vinculo.empresa_socio_id, action, PermissaoSocio.TODAS, None)

    @staticmethod
    def _parse_date(raw_date: str) -> date:
        try:
            return date.fromisoformat(raw_date)
        except ValueError:
            raise DataNascimentoInvalida(f"{raw_date} is not a real date")

    @staticmethod
    def _age_in_years(birthdate: date) -> int:
        today = clock.today()
        age = today.year - birthdate.year

        if (today.month, today.day) < (birthdate.month, birthdate.day):
            age -= 1

        return age
