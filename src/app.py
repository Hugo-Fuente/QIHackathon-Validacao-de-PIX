from fastapi import FastAPI, Depends
from fastapi.security import APIKeyHeader

# Isto avisa o Swagger que existe um cabeçalho global
token_auth = APIKeyHeader(name="INTERNAL-TOKEN", auto_error=False)

from constants import check_variables
from errors import register_error_handlers
from errors.base_error import error_verification
from middlewares import (
    register_internal_token_middleware,
    register_request_context_middleware,
    register_request_logger_middleware,
    register_session_manager_middleware,
)
from resources import (
    ContaResource,
    EmpresaResource,
    HealthCheckResource,
    PagamentoProgramadoResource,
    ResponsabilidadeResource,
    TransacaoResource,
)
from utils.logger import setup_logging


def create_app() -> FastAPI:
    """Monta a aplicação: middlewares, rotas e tratadores de erro."""
    application = FastAPI(
        title="Sistema Bancário API",
        description="API do Bootcamp QiTech",
        dependencies=[Depends(token_auth)]
    )

    # O FastAPI executa os middlewares do último registrado para o primeiro.
    # Ordem de execução de uma requisição:
    #   request_context -> request_logger -> internal_token -> session_manager -> rota
    # - o identificador precisa existir antes do log;
    # - o log vem antes do token para registrar também os acessos recusados;
    # - a sessão de banco é a mais interna: requisições barradas não a abrem.
    register_session_manager_middleware(application)
    register_internal_token_middleware(application)
    register_request_logger_middleware(application)
    register_request_context_middleware(application)

    health_check_resource = HealthCheckResource()
    empresa_resource = EmpresaResource()
    conta_resource = ContaResource()
    transacao_resource = TransacaoResource()
    responsabilidade_resource = ResponsabilidadeResource()
    pagamento_resource = PagamentoProgramadoResource()

    # Tabela de rotas. Caminhos no singular; ações sobre um recurso são
    # sub-recursos (/aprovacao, /cancelamento, /execucao). Status HTTP e regras
    # de negócio ficam nos resources e controllers.
    routes = [
        ("/", health_check_resource.on_get_home, ["GET"]),
        ("/health_check", health_check_resource.on_get_health_check, ["GET"]),
        # empresa, sócios, governança
        ("/empresa", empresa_resource.on_post, ["POST"]),
        ("/empresa/{empresa_id}", empresa_resource.on_get, ["GET"]),
        ("/empresa/{empresa_id}/socio/{empresa_socio_id}/permissao/{acao}", empresa_resource.on_put_permissao, ["PUT"]),
        ("/empresa/{empresa_id}/socio/{empresa_socio_id}/permissao/{acao}", empresa_resource.on_delete_permissao, ["DELETE"]),
        ("/empresa/{empresa_id}/regra_aprovacao", empresa_resource.on_put_regra, ["PUT"]),
        ("/empresa/{empresa_id}/regra_aprovacao/{regra_id}", empresa_resource.on_delete_regra, ["DELETE"]),
        # conta
        ("/conta/{conta_id}", conta_resource.on_get, ["GET"]),
        ("/conta/{conta_id}/status", conta_resource.on_patch_status, ["PATCH"]),
        ("/conta/{conta_id}/extrato", conta_resource.on_get_extrato, ["GET"]),
        ("/conta/{conta_id}/pagamento_programado", conta_resource.on_get_pagamentos, ["GET"]),
        # responsabilidade, substituição, orçamento, reserva
        ("/responsabilidade", responsabilidade_resource.on_post, ["POST"]),
        ("/responsabilidade/{responsabilidade_id}", responsabilidade_resource.on_get, ["GET"]),
        ("/responsabilidade/{responsabilidade_id}/substituicao", responsabilidade_resource.on_put_substituicao, ["PUT"]),
        ("/responsabilidade/{responsabilidade_id}/orcamento/{competencia}", responsabilidade_resource.on_put_orcamento, ["PUT"]),
        ("/movimento_reserva", responsabilidade_resource.on_post_movimento, ["POST"]),
        ("/movimento_reserva/{movimento_id}/aprovacao", pagamento_resource.on_post_aprovacao_movimento, ["POST"]),
        # transação
        ("/transacao", transacao_resource.on_post, ["POST"]),
        ("/transacao/{transacao_id}", transacao_resource.on_get, ["GET"]),
        # pagamento programado
        ("/pagamento_programado", pagamento_resource.on_post, ["POST"]),
        ("/pagamento_programado/{pagamento_id}/aprovacao", pagamento_resource.on_post_aprovacao, ["POST"]),
        ("/pagamento_programado/{pagamento_id}/cancelamento", pagamento_resource.on_post_cancelamento, ["POST"]),
        ("/pagamento_programado/{pagamento_id}/execucao", pagamento_resource.on_post_execucao, ["POST"]),
    ]

    for path, endpoint, methods in routes:
        application.add_api_route(path, endpoint, methods=methods)

    register_error_handlers(application)

    return application


def main() -> FastAPI:
    # Falha na inicialização se a configuração estiver incompleta.
    check_variables()
    error_verification()
    setup_logging()

    return create_app()


app = main()
