from fastapi import FastAPI, Depends, Response
from fastapi.security import APIKeyHeader
from resources.pix_resource import PixResource

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

    @application.get("/", include_in_schema=False)
    async def home():
        return {"status": "ok"}

    @application.get("/health_check", status_code=204, include_in_schema=False)
    async def health_check():
        return Response(status_code=204)

    # O FastAPI executa os middlewares do último registrado para o primeiro.
    register_session_manager_middleware(application)
    register_internal_token_middleware(application)
    register_request_logger_middleware(application)
    register_request_context_middleware(application)

    # Instanciamos o nosso novo resource
    pix_resource = PixResource()

 # Tabela de rotas do Antifraude Pix
    routes = [
        ("/pix/transaction", pix_resource.on_post_pix, ["POST"]),
        ("/pix/transaction/{id}", pix_resource.on_get_pix, ["GET"]),
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