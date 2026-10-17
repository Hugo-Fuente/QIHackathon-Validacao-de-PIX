from abc import ABCMeta

from database import get_context
from utils.logger import get_logger


class BaseController(metaclass=ABCMeta):
    """Base dos controllers: obtém o contexto da requisição, a sessão e o logger.

    Construir um controller abre (sob demanda) a sessão de banco da requisição.
    """

    def __init__(self, class_name: str) -> None:
        self.context = get_context()
        self.session = self.context.get_or_create_session()
        self.logger = get_logger(class_name)
