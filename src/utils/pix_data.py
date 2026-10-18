"""Small pure helpers for values shared by API, persistence and rule code."""

from datetime import datetime, timezone
from typing import Any


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Expected a datetime value")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def destination_key(value: dict) -> tuple[str, str, str]:
    account = value.get("destination_account")
    account = account if isinstance(account, dict) else {}
    return tuple(str(account.get(key, "")) for key in ("participant", "branch", "account_number"))


def destination_document(value: dict) -> str:
    account = value.get("destination_account")
    account = account if isinstance(account, dict) else {}
    owner = account.get("owner")
    owner = owner if isinstance(owner, dict) else {}
    return str(owner.get("document_number", ""))


def source_document(value: dict) -> str:
    account = value.get("source_account")
    account = account if isinstance(account, dict) else {}
    owner = account.get("owner")
    owner = owner if isinstance(owner, dict) else {}
    return str(owner.get("document_number", ""))
