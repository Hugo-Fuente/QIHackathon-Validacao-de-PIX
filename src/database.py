"""Engine, sessão e contexto de requisição.

O middleware `session_manager` abre o contexto de cada requisição e fecha a
sessão no fim. A sessão é criada sob demanda, quando um controller a pede, e
o commit é sempre decidido pelo controller.
"""

from contextvars import ContextVar
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from constants import DATABASE_URL


engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=30, pool_recycle=600, pool_pre_ping=True)

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
