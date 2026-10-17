"""Os erros do domínio da conta compartilhada.

Cada código da RFC (SALDO_LIVRE_INSUFICIENTE, LIMITE_SOCIO_EXCEDIDO...) é
uma classe, e o `code` dela é o próprio nome do código — é ele que o cliente
lê no corpo da resposta. O status HTTP vem da família da classe-base:

    400 formato · 401 sem identidade · 403 sem permissão · 404 não existe
    409 conflito de unicidade/idempotência
    422 regra de negócio sobre um pedido bem formado

Quem levanta é o controller (regra de negócio); quem traduz em HTTP é o
exception handler (src/errors/handlers.py).
"""

from errors.base_error import QIException


class ErroDeDominio(QIException):
    """Base abstrata (sem `code`): as subclasses declaram code/title/translation."""

    http_status_code = 500

    def __init__(self, description: str = None) -> None:
        super().__init__(
            self.title,
            self.code,
            self.http_status_code,
            description or self.title,
            self.translation,
        )


class RequisicaoInvalida(ErroDeDominio):
    http_status_code = 400


class NaoIdentificado(ErroDeDominio):
    http_status_code = 401


class Proibido(ErroDeDominio):
    http_status_code = 403


class NaoEncontrado(ErroDeDominio):
    http_status_code = 404


class Conflito(ErroDeDominio):
    http_status_code = 409


class RegraDeNegocio(ErroDeDominio):
    http_status_code = 422


# ───────────────────────────── 400 ─────────────────────────────


class ChaveIdempotenciaAusente(RequisicaoInvalida):
    code = "CHAVE_IDEMPOTENCIA_AUSENTE"
    title = "Idempotency-Key header is required"
    translation = "O header Idempotency-Key é obrigatório (de 1 a 80 caracteres)."


# ───────────────────────────── 401 / 403 ─────────────────────────────


class PessoaNaoIdentificada(NaoIdentificado):
    code = "PESSOA_NAO_IDENTIFICADA"
    title = "Person not identified"
    translation = "O header X-Pessoa-Id é obrigatório e precisa ser de uma pessoa cadastrada."


class PermissaoNegada(Proibido):
    code = "PERMISSAO_NEGADA"
    title = "Permission denied"
    translation = "Você não tem permissão para fazer isto nesta empresa, conta ou responsabilidade."


# ───────────────────────────── 404 ─────────────────────────────


class EmpresaNaoEncontrada(NaoEncontrado):
    code = "EMPRESA_NAO_ENCONTRADA"
    title = "Company not found"
    translation = "A empresa não foi encontrada."


class ContaNaoEncontrada(NaoEncontrado):
    code = "CONTA_NAO_ENCONTRADA"
    title = "Account not found"
    translation = "A conta não foi encontrada."


class SocioNaoEncontrado(NaoEncontrado):
    code = "SOCIO_NAO_ENCONTRADO"
    title = "Partner not found"
    translation = "O sócio não foi encontrado nesta empresa."


class TransacaoNaoEncontrada(NaoEncontrado):
    code = "TRANSACAO_NAO_ENCONTRADA"
    title = "Transaction not found"
    translation = "A transação não foi encontrada."


class ResponsabilidadeNaoEncontrada(NaoEncontrado):
    code = "RESPONSABILIDADE_NAO_ENCONTRADA"
    title = "Responsibility not found"
    translation = "A responsabilidade não foi encontrada nesta conta."


class PagamentoProgramadoNaoEncontrado(NaoEncontrado):
    code = "PAGAMENTO_PROGRAMADO_NAO_ENCONTRADO"
    title = "Scheduled payment not found"
    translation = "O pagamento programado não foi encontrado."


class MovimentoReservaNaoEncontrado(NaoEncontrado):
    code = "MOVIMENTO_RESERVA_NAO_ENCONTRADO"
    title = "Reserve movement not found"
    translation = "O movimento de reserva não foi encontrado."


# ───────────────────────────── 409 ─────────────────────────────


class EmpresaJaCadastrada(Conflito):
    code = "EMPRESA_JA_CADASTRADA"
    title = "Company already registered"
    translation = "Já existe uma empresa com este CNPJ ou esta razão social."


class EmailJaCadastrado(Conflito):
    code = "EMAIL_JA_CADASTRADO"
    title = "E-mail already registered"
    translation = "Já existe uma pessoa cadastrada com este e-mail (e CPF diferente)."


class ChaveIdempotenciaReutilizada(Conflito):
    code = "CHAVE_IDEMPOTENCIA_REUTILIZADA"
    title = "Idempotency key or external reference reused with a different body"
    translation = "Esta chave de idempotência (ou referência externa) já foi usada com um corpo diferente."


class BoletoJaPago(Conflito):
    code = "BOLETO_JA_PAGO"
    title = "Bank slip already paid"
    translation = "Este boleto já foi pago."


class BoletoEmPedidoAtivo(Conflito):
    code = "BOLETO_EM_PEDIDO_ATIVO"
    title = "Bank slip already in an active scheduled payment"
    translation = "Este boleto já está em um pagamento programado ativo."


class ResponsabilidadeJaExiste(Conflito):
    code = "RESPONSABILIDADE_JA_EXISTE"
    title = "Responsibility name already used in this account"
    translation = "Já existe uma responsabilidade com este nome nesta conta."


class VotoJaRegistrado(Conflito):
    code = "VOTO_JA_REGISTRADO"
    title = "Vote already registered with a different decision"
    translation = "Você já votou neste pedido com outra decisão."


# ───────────────────────────── 422 ─────────────────────────────
# cadastro da empresa


class DocumentoInvalido(RegraDeNegocio):
    code = "DOCUMENTO_INVALIDO"
    title = "Invalid CNPJ or CPF"
    translation = "O CNPJ ou CPF informado não é válido (dígitos verificadores)."


class DataNascimentoInvalida(RegraDeNegocio):
    code = "DATA_NASCIMENTO_INVALIDA"
    title = "Invalid birth date"
    translation = "A data de nascimento informada não existe."


class SocioMenorDeIdade(RegraDeNegocio):
    code = "SOCIO_MENOR_DE_IDADE"
    title = "Partner under 18"
    translation = "Todo sócio precisa ter pelo menos 18 anos."


class EstruturaSocietariaInvalida(RegraDeNegocio):
    code = "ESTRUTURA_SOCIETARIA_INVALIDA"
    title = "Invalid corporate structure"
    translation = "A empresa precisa de ao menos um sócio, ao menos um SOCIO_ADMINISTRADOR e CPFs distintos."


class SomaParticipacaoInvalida(RegraDeNegocio):
    code = "SOMA_PARTICIPACAO_INVALIDA"
    title = "Invalid sum of shares"
    translation = "A participação dos sócios (participacao_bp) precisa somar exatamente 10000."


# conta


class TransicaoInvalida(RegraDeNegocio):
    code = "TRANSICAO_INVALIDA"
    title = "Invalid account status transition"
    translation = "Esta mudança de status da conta não é permitida."


class SaldoNaoZerado(RegraDeNegocio):
    code = "SALDO_NAO_ZERADO"
    title = "Balance is not zero"
    translation = "Só é possível encerrar uma conta com saldo total zerado."


# permissões, regras, responsabilidades


class UltimoGestor(RegraDeNegocio):
    code = "ULTIMO_GESTOR"
    title = "Last governance manager"
    translation = "Ao menos um sócio precisa manter a permissão GERIR_GOVERNANCA."


class LimiteInvalido(RegraDeNegocio):
    code = "LIMITE_INVALIDO"
    title = "Invalid limit"
    translation = "O limite por transação precisa ser um inteiro maior que zero (ou nulo, sem teto)."


class RegraInatingivel(RegraDeNegocio):
    code = "REGRA_INATINGIVEL"
    title = "Approval rule cannot be reached"
    translation = "Não há sócios aprovadores elegíveis suficientes para cumprir esta regra."


class ParametrosInconsistentes(RegraDeNegocio):
    code = "PARAMETROS_INCONSISTENTES"
    title = "Inconsistent parameters"
    translation = "Informe exige_todos verdadeiro OU aprovacoes_necessarias — nunca os dois, nunca nenhum."


class ResponsabilidadeNaoESocio(RegraDeNegocio):
    code = "RESPONSABILIDADE_NAO_E_SOCIO"
    title = "Responsible is not a partner of the company"
    translation = "O responsável precisa ser sócio da empresa dona da conta."


class PeriodoInvalido(RegraDeNegocio):
    code = "PERIODO_INVALIDO"
    title = "Invalid period"
    translation = "O fim da substituição precisa ser depois do início."


class SubstitutoInvalido(RegraDeNegocio):
    code = "SUBSTITUTO_INVALIDO"
    title = "Invalid substitute"
    translation = "O substituto precisa ser sócio da empresa e diferente do responsável."


class OrcamentoAbaixoDoUtilizado(RegraDeNegocio):
    code = "ORCAMENTO_ABAIXO_DO_UTILIZADO"
    title = "Budget below the amount already used"
    translation = "O orçamento não pode ficar abaixo do valor já utilizado no mês."


# dinheiro


class TipoIncoerente(RegraDeNegocio):
    code = "TIPO_INCOERENTE"
    title = "Movement type does not match its responsibilities"
    translation = "As responsabilidades informadas não combinam com o tipo do movimento."


class MeioIncoerente(RegraDeNegocio):
    code = "MEIO_INCOERENTE"
    title = "Channel does not match the transaction ends"
    translation = "Transferência entre contas nossas usa o meio INTERNO; para fora do banco, use PIX, TED ou BOLETO."


class SaldoLivreInsuficiente(RegraDeNegocio):
    code = "SALDO_LIVRE_INSUFICIENTE"
    title = "Insufficient free balance"
    translation = "O saldo livre da conta não cobre este valor."


class ReservaInsuficiente(RegraDeNegocio):
    code = "RESERVA_INSUFICIENTE"
    title = "Insufficient reserved balance"
    translation = "O valor reservado da responsabilidade não cobre este valor."


class LimiteSocioExcedido(RegraDeNegocio):
    code = "LIMITE_SOCIO_EXCEDIDO"
    title = "Partner limit exceeded"
    translation = "O valor passa do limite por operação deste sócio."


class ContaNaoAtiva(RegraDeNegocio):
    code = "CONTA_NAO_ATIVA"
    title = "Account is not active"
    translation = "A conta não está ativa."


class AprovacaoNecessaria(RegraDeNegocio):
    code = "APROVACAO_NECESSARIA"
    title = "Approval required"
    translation = "Este valor exige aprovação de outros sócios: use o pagamento programado."


class OrcamentoExcedido(RegraDeNegocio):
    code = "ORCAMENTO_EXCEDIDO"
    title = "Budget exceeded"
    translation = "O orçamento do mês desta responsabilidade não comporta este valor."


class TransacaoSemContaNossa(RegraDeNegocio):
    code = "TRANSACAO_SEM_CONTA_NOSSA"
    title = "Transaction without a distinct account of ours"
    translation = "A transação precisa envolver uma conta nossa, e origem e destino não podem ser a mesma conta."


class BoletoVencido(RegraDeNegocio):
    code = "BOLETO_VENCIDO"
    title = "Bank slip expired"
    translation = "O boleto está vencido."


# pagamento programado e aprovação


class DataNoPassado(RegraDeNegocio):
    code = "DATA_NO_PASSADO"
    title = "Date is in the past"
    translation = "A data prevista não pode estar no passado."


class AutorNaoAprovaOProprio(RegraDeNegocio):
    code = "AUTOR_NAO_APROVA_O_PROPRIO"
    title = "Author cannot approve their own request"
    translation = "O autor do pedido não pode votar nele."


class PedidoNaoPendente(RegraDeNegocio):
    code = "PEDIDO_NAO_PENDENTE"
    title = "Request is not pending"
    translation = "O pedido não está mais aguardando aprovação."


class JaExecutado(RegraDeNegocio):
    code = "JA_EXECUTADO"
    title = "Already executed"
    translation = "O pagamento já foi executado e não pode ser cancelado."


class EstadoFinal(RegraDeNegocio):
    code = "ESTADO_FINAL"
    title = "Request is in a final state"
    translation = "O pedido está em estado final (recusado ou falhou) e não muda mais."


class NaoAgendado(RegraDeNegocio):
    code = "NAO_AGENDADO"
    title = "Payment is not scheduled"
    translation = "Só um pagamento AGENDADO pode ser executado."


class DataNaoChegou(RegraDeNegocio):
    code = "DATA_NAO_CHEGOU"
    title = "Scheduled date has not arrived"
    translation = "A data prevista do pagamento ainda não chegou."
