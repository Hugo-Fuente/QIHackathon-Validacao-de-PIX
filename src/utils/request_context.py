import re
import uuid
from contextvars import ContextVar

# Cabeçalho padrão de correlação, entendido por proxies e ferramentas de log.
REQUEST_ID_HEADER = "X-Request-ID"

# Formato aceito para identificadores vindos de fora (ver build_request_id).
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Valor usado no log fora de uma requisição (ex.: inicialização).
NO_REQUEST_ID = "-"

# ContextVar isola o valor por requisição em andamento; uma variável global
# seria sobrescrita por requisições concorrentes. Vive em utils/ porque o
# logger depende dele e não pode importar de middlewares/ (ciclo de import).
_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)


def get_request_id() -> str:
    """Identificador da requisição em atendimento."""
    return _request_id.get()


def set_request_id(request_id: str) -> None:
    """Define o identificador da requisição atual (chamado pelo middleware)."""
    _request_id.set(request_id)


def build_request_id(received_request_id: str = None) -> str:
    """Reaproveita o identificador recebido ou gera um novo.

    O valor vem do cliente e termina no log, então só é aceito se casar por
    completo com SAFE_REQUEST_ID; caso contrário, uma quebra de linha
    permitiria forjar entradas de log (log injection).
    """
    if received_request_id is not None and SAFE_REQUEST_ID.fullmatch(received_request_id):
        return received_request_id

    return str(uuid.uuid4())
