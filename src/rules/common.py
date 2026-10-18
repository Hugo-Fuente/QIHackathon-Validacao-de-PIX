"""Pure helpers shared by the rule modules."""

from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

from rules import params
from utils.pix_data import (
    destination_document,
    destination_key,
    parse_datetime,
    source_document,
)


def event_datetime(event: dict) -> datetime:
    return parse_datetime(event["transaction_date"])


def event_context(event: dict) -> dict:
    value = event.get("context")
    return value if isinstance(value, dict) else {}


def payload(transaction: dict) -> dict:
    value = transaction.get("payload")
    return value if isinstance(value, dict) else transaction


def context_of(transaction: dict) -> dict:
    value = payload(transaction).get("context")
    return value if isinstance(value, dict) else {}


def transaction_datetime(transaction: dict) -> datetime:
    return parse_datetime(transaction["transaction_date"])


def event_type(transaction: dict) -> str | None:
    return context_of(transaction).get("event")


def is_outflow(transaction: dict) -> bool:
    return event_type(transaction) in (None, "request")


def is_scheduled_execution(context: dict) -> bool:
    return context.get("event") == "execution" and context.get("origin") == "scheduled"


def within(transaction: dict, event_date: datetime, window: timedelta) -> bool:
    difference = event_date - transaction_datetime(transaction)
    return timedelta(0) <= difference <= window


def window(transactions: tuple[dict, ...] | list[dict], event_date: datetime, duration: timedelta) -> list[dict]:
    return [transaction for transaction in transactions if within(transaction, event_date, duration)]


def destination_account(value: dict) -> dict:
    account = value.get("destination_account")
    return account if isinstance(account, dict) else {}


def destination_owner(value: dict) -> dict:
    owner = destination_account(value).get("owner")
    return owner if isinstance(owner, dict) else {}


def source_data(value: dict) -> dict:
    source = value.get("source")
    return source if isinstance(source, dict) else {}


def recurrent(
    history: tuple[dict, ...] | list[dict], destination_doc: str, event_date: datetime
) -> tuple[list[dict], bool]:
    shared = params.shared()
    related = [
        transaction for transaction in history
        if destination_document(payload(transaction)) == destination_doc
        and within(transaction, event_date, timedelta(days=180))
    ]
    dates = {transaction_datetime(transaction).date() for transaction in related}
    mature = (
        len(dates) >= shared["RECURRENT_DISTINCT_DAYS"]
        and bool(related)
        and event_date - min(transaction_datetime(transaction) for transaction in related)
        >= timedelta(days=shared["RECURRENT_AGE_DAYS"])
    )
    return related, mature


def habitual_value(amount: int, related: list[dict], mature: bool) -> bool:
    shared = params.shared()
    maximum = max((int(tx["amount"]) for tx in related), default=0)
    return mature and maximum > 0 and amount <= maximum * shared["HABITUAL_AMOUNT_FACTOR"]


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    latitude_delta = radians(lat2 - lat1)
    longitude_delta = radians(lon2 - lon1)
    value = (
        sin(latitude_delta / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(longitude_delta / 2) ** 2
    )
    return 6371.0 * 2 * asin(sqrt(max(0.0, min(1.0, value))))


def ip_country(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    first = value.split(".", 1)[0]
    return "BR" if first in {"10", "100", "127", "172", "192", "177", "200", "201"} else None

