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
from utils.logger import setup_logging


def create_app() -> FastAPI:
    """Monta a aplicação: middlewares, rotas e tratadores de erro."""
    application = FastAPI(
        title="Antifraude Pix API",
        description="Hackathon Risk Solutions QI Tech 2026",
        dependencies=[Depends(token_auth)]
    )

    # O FastAPI executa os middlewares do último registrado para o primeiro.
    register_session_manager_middleware(application)
    register_internal_token_middleware(application)
    register_request_logger_middleware(application)
    register_request_context_middleware(application)

    # Aqui vamos instanciar os nossos novos resources do Pix (em breve)
    # pix_resource = PixResource()

    # Tabela de rotas do Antifraude Pix
    routes = [
        # As nossas novas rotas entrarão aqui:
        # ("/pix/transaction", pix_resource.on_post_pix, ["POST"]),
        # ("/pix/transaction/{id}", pix_resource.on_get_pix, ["GET"]),
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