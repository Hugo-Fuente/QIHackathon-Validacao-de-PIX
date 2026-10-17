from datetime import date, datetime, timedelta, timezone

BRASILIA = timezone(timedelta(hours=-3))


def today() -> date:
    return datetime.now(BRASILIA).date()
