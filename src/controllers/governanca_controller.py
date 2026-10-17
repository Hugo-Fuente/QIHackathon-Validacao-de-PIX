from sqlalchemy.exc import IntegrityError

from controllers.access_control import AccessControl
from controllers.base_controller import BaseController
from dtos import PermissaoDTO
from errors import (
    EmpresaNaoEncontrada,
    InvalidParameter,
    LimiteInvalido,
    ParametrosInconsistentes,
    RegraInatingivel,
    SocioNaoEncontrado,
    UltimoGestor,
)
from models import PermissaoSocio
from repositories import EmpresaRepository, GovernancaRepository
from utils.db_errors import violated_constraint


class GovernancaController(BaseController, AccessControl):
    """Quem pode o quê (permissões por sócio) e a partir de quanto é preciso
    a aprovação de outros sócios (regras). Toda mudança grava um
    EVENTO_AUDITORIA na mesma transação.

    Todas as mudanças travam a linha da EMPRESA: duas alterações simultâneas
    de governança (dois sócios tirando a permissão um do outro, por exemplo)
    se enfileiram em vez de cada uma ler um estado que a outra já mudou.
    """

    def __init__(self) -> None:
        super().__init__(__name__)
        self.empresa_repository = EmpresaRepository(self.context)
        self.governanca_repository = GovernancaRepository(self.context)

    # ── permissões ──────────────────────────────────────────────────

    def put_permissao(self, empresa_id: str, empresa_socio_id: str, acao: str, payload: dict, pessoa_id) -> dict:
        """Define ou atualiza a permissão. Idempotente: UNIQUE(empresa_socio_id,
        acao) — o PUT repetido deixa o mesmo estado e não duplica a auditoria."""
        caller, empresa = self._authorize(empresa_id, pessoa_id)
        alvo = self._socio(empresa, empresa_socio_id)
        self._check_action(acao)

        escopo = payload["escopo"]
        limite = payload.get("limite_transacao_centavos")

        if limite is not None and limite < 1:
            raise LimiteInvalido()

        permissao = self.empresa_repository.get_permissao(alvo.empresa_socio_id, acao)
        anterior = None

        if permissao is None:
            permissao = self._create_permissao(alvo.empresa_socio_id, acao, escopo, limite)
            changed = True
        else:
            anterior = {"escopo": permissao.escopo, "limite_transacao_centavos": permissao.limite_transacao_centavos}
            changed = anterior != {"escopo": escopo, "limite_transacao_centavos": limite}

            if changed:
                permissao.escopo = escopo
                permissao.limite_transacao_centavos = limite
                self.session.flush()

        if changed:
            self.governanca_repository.add_evento(
                empresa.empresa_id,
                caller.empresa_socio_id,
                "PERMISSAO_DEFINIDA",
                "PERMISSAO",
                permissao.permissao_id,
                {
                    "empresa_socio_id": alvo.empresa_socio_id,
                    "acao": acao,
                    "escopo": escopo,
                    "limite_transacao_centavos": limite,
                    "anterior": anterior,
                },
            )

        permissao_dto = PermissaoDTO.obj_to_dict(permissao)
        self.session.commit()

        return permissao_dto

    def delete_permissao(self, empresa_id: str, empresa_socio_id: str, acao: str, pessoa_id) -> None:
        """Revoga a permissão. Idempotente: revogar o que não existe é 204.
        Não deixa a empresa sem nenhum GERIR_GOVERNANCA (ULTIMO_GESTOR)."""
        caller, empresa = self._authorize(empresa_id, pessoa_id)
        alvo = self._socio(empresa, empresa_socio_id)
        self._check_action(acao)

        permissao = self.empresa_repository.get_permissao(alvo.empresa_socio_id, acao)

        if permissao is None:
            self.session.commit()
            return

        if acao == PermissaoSocio.GERIR_GOVERNANCA and self.empresa_repository.count_com_permissao(empresa.empresa_id, acao) <= 1:
            raise UltimoGestor()

        dados = {
            "empresa_socio_id": alvo.empresa_socio_id,
            "acao": acao,
            "escopo": permissao.escopo,
            "limite_transacao_centavos": permissao.limite_transacao_centavos,
        }
        permissao_id = permissao.permissao_id
        self.empresa_repository.delete_permissao(permissao)

        self.governanca_repository.add_evento(
            empresa.empresa_id, caller.empresa_socio_id, "PERMISSAO_REVOGADA", "PERMISSAO", permissao_id, dados
        )
        self.session.commit()

    # ── regras de aprovação ─────────────────────────────────────────

    def put_regra(self, empresa_id: str, payload: dict, pessoa_id) -> dict:
        """Cria ou atualiza a regra pela chave natural (acao, meio, acima_de).
        Só vale para pedidos NOVOS: os em andamento guardam o número de
        aprovações exigidas que valia quando nasceram."""
        caller, empresa = self._authorize(empresa_id, pessoa_id)

        acao = payload["acao"]
        meio = payload.get("meio")
        acima_de = payload["acima_de_centavos"]
        exige_todos = payload.get("exige_todos", False)
        necessarias = payload.get("aprovacoes_necessarias")

        if exige_todos == (necessarias is not None):
            raise ParametrosInconsistentes()

        aprovadores = len(self.empresa_repository.list_aprovadores(empresa.empresa_id))

        if aprovadores < 1 or (necessarias is not None and necessarias > aprovadores):
            raise RegraInatingivel(f"the rule needs {necessarias or 'all'} approvers and the company has {aprovadores}")

        regra = self.governanca_repository.find_regra(empresa.empresa_id, acao, meio, acima_de)
        anterior = None

        if regra is None:
            try:
                regra = self.governanca_repository.add_regra(
                    empresa_id=empresa.empresa_id,
                    acao=acao,
                    meio=meio,
                    acima_de_centavos=acima_de,
                    exige_todos=exige_todos,
                    aprovacoes_necessarias=necessarias,
                )
            except IntegrityError as error:
                self.session.rollback()

                if violated_constraint(error) == "uq_regra_aprovacao":
                    raise InvalidParameter("concurrent update of the same rule, try again")

                raise
        else:
            anterior = {"exige_todos": regra.exige_todos, "aprovacoes_necessarias": regra.aprovacoes_necessarias}

            if anterior != {"exige_todos": exige_todos, "aprovacoes_necessarias": necessarias}:
                regra.exige_todos = exige_todos
                regra.aprovacoes_necessarias = necessarias
                self.session.flush()
            else:
                anterior = "igual"

        if anterior != "igual":
            self.governanca_repository.add_evento(
                empresa.empresa_id,
                caller.empresa_socio_id,
                "REGRA_DEFINIDA",
                "REGRA_APROVACAO",
                regra.regra_id,
                {
                    "acao": acao,
                    "meio": meio,
                    "acima_de_centavos": acima_de,
                    "exige_todos": exige_todos,
                    "aprovacoes_necessarias": necessarias,
                    "anterior": anterior,
                },
            )

        regra_dto = {"regra_id": regra.regra_id}
        self.session.commit()

        return regra_dto

    def delete_regra(self, empresa_id: str, regra_id: str, pessoa_id) -> None:
        """Idempotente: remover uma regra que não existe é 204."""
        caller, empresa = self._authorize(empresa_id, pessoa_id)
        regra = self.governanca_repository.get_regra(regra_id)

        if regra is None or regra.empresa_id != empresa.empresa_id:
            self.session.commit()
            return

        dados = {
            "acao": regra.acao,
            "meio": regra.meio,
            "acima_de_centavos": regra.acima_de_centavos,
            "exige_todos": regra.exige_todos,
            "aprovacoes_necessarias": regra.aprovacoes_necessarias,
        }
        regra_id = regra.regra_id
        self.governanca_repository.delete_regra(regra)

        self.governanca_repository.add_evento(
            empresa.empresa_id, caller.empresa_socio_id, "REGRA_REMOVIDA", "REGRA_APROVACAO", regra_id, dados
        )
        self.session.commit()

    # ── apoio ───────────────────────────────────────────────────────

    def _authorize(self, empresa_id: str, pessoa_id):
        """401 -> 404 -> 403 e a trava da empresa. Devolve (sócio, empresa)."""
        pessoa = self.identify(pessoa_id)

        if self.empresa_repository.get_empresa(empresa_id) is None:
            raise EmpresaNaoEncontrada()

        caller = self.require_socio(pessoa, empresa_id)
        self.require_permission(caller, PermissaoSocio.GERIR_GOVERNANCA)

        empresa = self.empresa_repository.get_empresa(empresa_id, lock=True)

        # A permissão pode ter sido tirada enquanto esperávamos a trava.
        self.require_permission(caller, PermissaoSocio.GERIR_GOVERNANCA)

        return caller, empresa

    def _socio(self, empresa, empresa_socio_id: str):
        socio = self.empresa_repository.get_socio_da_empresa(empresa.empresa_id, empresa_socio_id)

        if socio is None:
            raise SocioNaoEncontrado()

        return socio

    @staticmethod
    def _check_action(acao: str) -> None:
        if acao not in PermissaoSocio.ACOES:
            raise InvalidParameter(f"acao must be one of {', '.join(PermissaoSocio.ACOES)}")

    def _create_permissao(self, empresa_socio_id: str, acao: str, escopo: str, limite):
        try:
            return self.empresa_repository.add_permissao(empresa_socio_id, acao, escopo, limite)
        except IntegrityError as error:
            self.session.rollback()

            if violated_constraint(error) == "uq_permissao_socio_acao":
                raise InvalidParameter("concurrent update of the same permission, try again")

            raise
