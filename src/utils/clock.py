"""O relógio do negócio.

"Hoje" e "este mês" (competência do orçamento, data prevista de um pagamento)
são conceitos de calendário do cliente, e o cliente é brasileiro: o dia vira
à meia-noite de Brasília (UTC-3, sem horário de verão desde 2019). O servidor
roda em UTC, então usar `date.today()` viraria o dia às 21h daqui.

Fica num arquivo só para o dia em que isto mudar (ou para um teste que precise
fixar o tempo) existir um lugar único para trocar.
"""

from datetime import date, datetime, timedelta, timezone

BUSINESS_TZ = timezone(timedelta(hours=-3))


def now() -> datetime:
    """O instante atual, com fuso (timestamptz no banco)."""
    return datetime.now(timezone.utc)


def today() -> date:
    return datetime.now(BUSINESS_TZ).date()


def competence(day: date = None) -> str:
    """O mês de um dia no formato do orçamento: 'AAAA-MM'."""
    day = day or today()
    return f"{day.year:04d}-{day.month:02d}"
