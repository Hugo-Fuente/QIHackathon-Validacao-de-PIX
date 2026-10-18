"""Engine, sessão e contexto de requisição.

O middleware `session_manager` abre o contexto de cada requisição e fecha a
sessão no fim. A sessão é criada sob demanda, quando um controller a pede, e
o repositório confirma a transação completa de gravação da análise.
"""

from contextvars import ContextVar
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from constants import DATABASE_URL


# Bound lock waits and abandoned open transactions so a stuck request cannot hold
# an advisory lock indefinitely. Values are PostgreSQL milliseconds.
POSTGRES_LOCK_TIMEOUT_MS = 5_000
POSTGRES_IDLE_TRANSACTION_TIMEOUT_MS = 15_000
POSTGRES_OPTIONS = (
    f"-c lock_timeout={POSTGRES_LOCK_TIMEOUT_MS} "
    f"-c idle_in_transaction_session_timeout={POSTGRES_IDLE_TRANSACTION_TIMEOUT_MS}"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=10,
    pool_recycle=600,
    pool_pre_ping=True,
    connect_args={"options": POSTGRES_OPTIONS},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Context:
    """Contexto da requisição em andamento; hoje guarda a sessão de banco.

    É um objeto mutável de propósito: o middleware cria o contexto e a rota
    roda com uma cópia do ContextVar, então um `.set()` feito na rota não
    chegaria ao middleware. Como ambos compartilham o mesmo objeto, a sessão
    criada sob demanda pelo controller pode ser fechada pelo middleware.
    """

    def __init__(self) -> None:
        self.db_session: Optional[Session] = None

    def get_or_create_session(self) -> Session:
        if self.db_session is None:
            self.db_session = SessionLocal()

        return self.db_session

    def commit(self) -> None:
        if self.db_session is not None:
            self.db_session.commit()

    def rollback(self) -> None:
        if self.db_session is not None:
            self.db_session.rollback()

    def finalize(self, response_status: int) -> None:
        """Roll back error responses; successful writes are committed by the repository."""
        if response_status >= 400:
            self.rollback()


_context: ContextVar[Optional[Context]] = ContextVar("context", default=None)


def open_context() -> Context:
    """Cria o contexto da requisição (chamado apenas pelo middleware de sessão).

    Quem abre o contexto é responsável por fechar a sessão ao final.
    """
    context = Context()
    _context.set(context)

    return context


def clear_context() -> None:
    """Remove o contexto atual.

    Evita que um uso posterior fora de uma requisição receba o contexto
    anterior, com a sessão já fechada (o SQLAlchemy a reabriria sozinho).
    """
    _context.set(None)


def get_context() -> Context:
    """Devolve o contexto atual; somente os controllers devem chamá-lo.

    Retorna o contexto, e não a sessão, para que os repositories não
    dependam do detalhe de como o banco é acessado. A sessão é criada sob
    demanda, então rotas sem controller (`/`, `/health_check`) não usam banco.
    """
    context = _context.get()

    if context is None:
        raise Exception(
            "Nao existe contexto neste trabalho. "
            + "Quem prepara o contexto de cada requisicao e o middleware "
            + "src/middlewares/session_manager.py. Se voce chegou aqui, ele nao rodou."
        )

    return context
