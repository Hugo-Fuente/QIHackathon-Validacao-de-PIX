import logging
import sys

from constants import APP_ENV, SERVICE_NAME
from utils.request_context import get_request_id


# O campo request_id é preenchido por RequestIdFilter.
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s] - %(message)s"


class RequestIdFilter(logging.Filter):
    """Acrescenta o request_id da requisição atual a cada registro de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def setup_logging() -> None:
    """Configura o log da aplicação (chamada uma vez, na inicialização)."""
    level = logging.INFO
    if APP_ENV.upper() in ("LOCAL", "TEST"):
        level = logging.DEBUG

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    # No handler (e não em um logger) para cobrir também logs de bibliotecas.
    handler.addFilter(RequestIdFilter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = [handler]

    # O urllib3 é muito verboso em DEBUG.
    for biblioteca_falante in ["urllib3"]:
        logging.getLogger(biblioteca_falante).setLevel(logging.CRITICAL)


def get_logger(class_name: str) -> logging.Logger:
    """Logger nomeado com o serviço e o módulo de origem."""
    return logging.getLogger(f"{SERVICE_NAME}.{class_name}")
