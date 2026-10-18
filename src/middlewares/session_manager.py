from fastapi import FastAPI, Request

from database import clear_context, open_context


def register_session_manager_middleware(application: FastAPI) -> None:
    """Gerencia o ciclo de vida da sessão de banco de cada requisição.

    - rollback se a requisição terminar em exceção;
    - close sempre, no `finally`, devolvendo a conexão ao pool;
    - commit nunca: o repositório confirma a gravação completa da análise.

    A sessão é criada sob demanda pelo contexto, na primeira vez que um
    controller a pede. Rotas que não usam banco (`/`, `/health_check`) não
    dependem dele; por isso `db_session` pode ser None e toda operação
    abaixo precisa checá-lo.

    É o middleware mais interno: roda depois da checagem do token e, por
    isso, é o primeiro registrado em app.py.
    """

    @application.middleware("http")
    async def manage_session(request: Request, call_next):
        context = open_context()

        try:
            response = await call_next(request)
            context.finalize(response.status_code)
            return response
        except Exception:
            # Evita devolver ao pool uma conexão com transação abortada.
            context.finalize(500)
            raise
        finally:
            if context.db_session is not None:
                context.db_session.close()

            # Fora de uma requisição, pedir o contexto deve falhar.
            clear_context()
