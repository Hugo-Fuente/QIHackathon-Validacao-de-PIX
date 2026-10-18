from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 1, 31, 12, 0, tzinfo=timezone.utc)


def event(amount=100_000, *, offset_minutes=0, context=None, source_doc="11111111111", dest_doc="22222222222", dest_acct="d-1"):
    result = {
        "id": "event-current",
        "amount": amount,
        "transaction_date": NOW + timedelta(minutes=offset_minutes),
        "source_account": {"owner": {"document_number": source_doc}, "opening_date": NOW - timedelta(days=365)},
        "destination_account": {
            "participant": "00000002", "branch": "0001", "account_number": dest_acct,
            "owner": {"document_number": dest_doc}, "opening_date": NOW - timedelta(days=365),
        },
        "source": {"device_id": "device-current", "ip": "177.10.0.1"},
    }
    if context is not None:
        result["context"] = context
    return result


def transaction(amount=100_000, *, minutes_ago=10, days_ago=None, source_doc="11111111111", dest_doc="33333333333",
                dest_acct="prior-account", event_type=None, context=None, device="device-old", geolocation=None, ip="177.10.0.1"):
    when = NOW - (timedelta(days=days_ago) if days_ago is not None else timedelta(minutes=minutes_ago))
    epp = dict(context or {})
    if event_type is not None:
        epp["event"] = event_type
    payload = {
        "source": {"device_id": device, "ip": ip},
        "destination_account": {
            "participant": "00000002", "branch": "0001", "account_number": dest_acct,
            "owner": {"document_number": dest_doc},
        },
    }
    if geolocation is not None:
        payload["source"]["geolocation"] = geolocation
    if epp:
        payload["context"] = epp
    return {
        "id": f"prior-{when.isoformat()}-{amount}-{dest_acct}",
        "amount": amount,
        "transaction_date": when,
        "source_document": source_doc,
        "destination_document": dest_doc,
        "payload": payload,
    }


def profile(**overrides):
    value = {
        "source_history": [],
        "trusted_history": [],
        "successful_profile": [],
        "median_amount": 100_000,
        "mature": True,
        "limit": 500_000,
        "related_history": [],
        "recurrent": False,
        "max_related_amount": 0,
        "habitual": False,
        "outgoing_count": 0,
    }
    value.update(overrides)
    return value


def epp_event(event_name="request", amount=100_000, **context_fields):
    context = {"event": event_name, "author_id": "author-a", "company_id": "company-a", **context_fields}
    return event(amount, context=context)
