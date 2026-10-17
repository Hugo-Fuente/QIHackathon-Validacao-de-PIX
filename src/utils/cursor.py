import base64
import json
from datetime import date, datetime, timedelta, timezone

from errors import InvalidParameter
from utils.clock import BUSINESS_TZ

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def encode_cursor(created_at: datetime, row_id: str) -> str:
    """O cursor é a posição do último item da página: (criado_em, id).

    Paginar por OFFSET quebra quando entram linhas durante a leitura (linhas
    repetem ou somem); por posição, cada página continua exatamente de onde
    a anterior parou. O cursor é opaco para o cliente: ele só devolve.
    """
    raw = json.dumps({"t": created_at.isoformat(), "id": str(row_id)})

    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str):
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        created_at = datetime.fromisoformat(data["t"])
        row_id = str(data["id"])

        if created_at.tzinfo is None or len(row_id) != 36:
            raise ValueError("cursor sem fuso ou com id malformado")

        return created_at, row_id
    except Exception:
        raise InvalidParameter("cursor is malformed")


def parse_limit(raw_limit) -> int:
    """O tamanho da página: 1 a 100 (o schema já barrou o que não é número)."""
    if raw_limit is None:
        return DEFAULT_LIMIT

    limit = int(raw_limit)

    if limit < 1 or limit > MAX_LIMIT:
        raise InvalidParameter(f"limite must be between 1 and {MAX_LIMIT}")

    return limit


def parse_moment(raw_value: str, name: str) -> datetime:
    """Um instante ISO-8601 com fuso. Sem fuso, vale o horário de Brasília."""
    try:
        moment = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidParameter(f"{name} is not a valid date-time")

    return moment if moment.tzinfo else moment.replace(tzinfo=BUSINESS_TZ)


def parse_bound(raw_value: str, name: str, is_end: bool) -> datetime:
    """Aceita uma data (AAAA-MM-DD) ou um instante ISO-8601.

    Data pura vale o DIA INTEIRO (fuso de Brasília): `de=2026-10-01` começa à
    meia-noite do dia 1, e `ate=2026-10-31` inclui o dia 31 até 23:59:59.
    O limite superior é sempre exclusivo (`criado_em < ate`).
    """
    if len(raw_value) == 10:
        try:
            day = date.fromisoformat(raw_value)
        except ValueError:
            raise InvalidParameter(f"{name} is not a valid date")

        start = datetime(day.year, day.month, day.day, tzinfo=BUSINESS_TZ)

        return start + timedelta(days=1) if is_end else start

    return parse_moment(raw_value, name).astimezone(timezone.utc)
