from datetime import datetime

from errors import ContaNaoAtiva, LimiteSocioExcedido, PermissaoNegada, PessoaNaoIdentificada
from models import Conta, EmpresaSocio, PermissaoSocio, Pessoa, Responsabilidade, Status
from utils import clock


class AccessControl:
    """Quem é a pessoa, de que empresa ela é sócia e o que pode fazer.

    É um mixin dos controllers: exige que a classe tenha `self.empresa_repository`.

    A identidade vem do header X-Pessoa-Id (login está fora do escopo desta
    entrega). Daí a cadeia de perguntas, sempre nesta ordem:

        401  quem é você?                 (identify)
        403  você é sócio desta empresa?  (require_socio)
        403  sua permissão cobre esta ação, neste escopo? (require_permission)
        422  o valor cabe no seu limite?  (check_limit)
    """

    def identify(self, pessoa_id) -> Pessoa:
        if not pessoa_id:
            raise PessoaNaoIdentificada()

        pessoa = self.empresa_repository.get_pessoa(pessoa_id)

        if pessoa is None:
            raise PessoaNaoIdentificada()

        return pessoa

    def require_socio(self, pessoa: Pessoa, empresa_id: str) -> EmpresaSocio:
        socio = self.empresa_repository.get_socio_by_pessoa(empresa_id, pessoa.pessoa_id)

        if socio is None:
            raise PermissaoNegada()

        return socio

    def require_permission(self, socio: EmpresaSocio, acao: str, responsabilidades=()) -> PermissaoSocio:
        """A permissão do sócio para a ação, conferindo o ESCOPO.

        TODAS: vale em qualquer responsabilidade e também no saldo livre.
        PROPRIAS: só vale se TODAS as responsabilidades envolvidas forem dele
        (ou ele for o substituto, dentro da janela). Sem responsabilidade
        nenhuma (saldo livre da empresa), PROPRIAS não alcança.
        """
        permissao = self.empresa_repository.get_permissao(socio.empresa_socio_id, acao)

        if permissao is None or not self.scope_covers(permissao, socio, responsabilidades):
            raise PermissaoNegada()

        return permissao

    def scope_covers(self, permissao: PermissaoSocio, socio: EmpresaSocio, responsabilidades=(), at: datetime = None) -> bool:
        if permissao.escopo == PermissaoSocio.TODAS:
            return True

        responsabilidades = [item for item in responsabilidades if item is not None]

        if not responsabilidades:
            return False

        return all(self.acts_for(socio, item, at) for item in responsabilidades)

    @staticmethod
    def acts_for(socio: EmpresaSocio, responsabilidade: Responsabilidade, at: datetime = None) -> bool:
        """O sócio age por esta responsabilidade? Sim se é o responsável, ou se
        é o substituto e agora está dentro da janela da substituição."""
        at = at or clock.now()

        if responsabilidade.responsavel_empresa_socio_id == socio.empresa_socio_id:
            return True

        return (
            responsabilidade.substituto_empresa_socio_id == socio.empresa_socio_id
            and responsabilidade.substituicao_inicio is not None
            and responsabilidade.substituicao_inicio <= at < responsabilidade.substituicao_fim
        )

    @staticmethod
    def check_limit(permissao: PermissaoSocio, valor_centavos: int) -> None:
        """O teto por operação do sócio nesta ação (nulo = sem teto). Vale antes
        de qualquer regra de aprovação: aprovação de outros sócios não libera
        um sócio acima do próprio limite."""
        limite = permissao.limite_transacao_centavos

        if limite is not None and valor_centavos > limite:
            raise LimiteSocioExcedido(f"valor {valor_centavos} passa do limite de {limite} deste sócio")

    def require_active_account(self, conta: Conta) -> None:
        """Só conta ATIVA movimenta dinheiro (exige `self.conta_repository`)."""
        status = self.conta_repository.get_status_by_id(conta.status_id)

        if status.codigo != Status.ATIVA:
            raise ContaNaoAtiva(f"account status is {status.codigo}")
