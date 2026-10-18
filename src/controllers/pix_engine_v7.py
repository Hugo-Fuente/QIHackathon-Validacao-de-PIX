import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models.pix_model import PixTransactionModel
from repositories.pix_repository import PixRepository


RULES_VERSION = "v7"
NOTIFY_RULES = {"R15", "R16", "R20", "R21", "R22", "R30", "R31", "R32", "C1"}


def _date(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Expected a datetime value")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _payload(transaction: PixTransactionModel) -> dict:
    value = transaction.payload or {}
    return value if isinstance(value, dict) else {}


def _context(transaction: PixTransactionModel) -> dict:
    value = _payload(transaction).get("context")
    return value if isinstance(value, dict) else {}


def _event(transaction: PixTransactionModel) -> str | None:
    return _context(transaction).get("event")


def _is_outflow(transaction: PixTransactionModel) -> bool:
    return _event(transaction) in (None, "request")


def _transaction_date(transaction: PixTransactionModel) -> datetime:
    return _date(transaction.transaction_date)


def _within(transaction: PixTransactionModel, event_date: datetime, window: timedelta) -> bool:
    difference = event_date - _transaction_date(transaction)
    return timedelta(0) <= difference <= window


def _window(
    transactions: list[PixTransactionModel], event_date: datetime, minutes: int
) -> list[PixTransactionModel]:
    duration = timedelta(minutes=minutes)
    return [tx for tx in transactions if _within(tx, event_date, duration)]


def _destination_account(payload: dict) -> dict:
    value = payload.get("destination_account")
    return value if isinstance(value, dict) else {}


def _destination_owner(payload: dict) -> dict:
    value = _destination_account(payload).get("owner")
    return value if isinstance(value, dict) else {}


def _destination_key(payload: dict) -> tuple[str, str, str]:
    account = _destination_account(payload)
    return (
        str(account.get("participant", "")),
        str(account.get("branch", "")),
        str(account.get("account_number", "")),
    )


def _destination_document(payload: dict) -> str:
    return str(_destination_owner(payload).get("document_number", ""))


def _is_scheduled_execution(context: dict) -> bool:
    return context.get("event") == "execution" and context.get("origin") == "scheduled"


def _recurrent(
    history: list[PixTransactionModel],
    destination_document: str,
    event_date: datetime,
) -> tuple[list[PixTransactionModel], bool]:
    related = [
        tx
        for tx in history
        if _destination_document(_payload(tx)) == destination_document
        and _within(tx, event_date, timedelta(days=180))
    ]
    distinct_days = {_transaction_date(tx).date() for tx in related}
    mature_relation = (
        len(distinct_days) >= 3
        and bool(related)
        and event_date - min(_transaction_date(tx) for tx in related) >= timedelta(days=14)
    )
    return related, mature_relation


def _make_hit(code: str, points: int, detail: str) -> dict:
    return {"code": code, "points": points, "detail": detail}


def process_transaction_v7(repository: PixRepository, input_data: dict) -> dict:
    from database import get_context

    context_manager = get_context()
    session = context_manager.get_or_create_session()
    pix_id = input_data["id"]
    source_document = input_data["source_account"]["owner"]["document_number"]
    destination_document = input_data["destination_account"]["owner"]["document_number"]
    amount = int(input_data["amount"])
    event_date = _date(input_data["transaction_date"])
    context = input_data.get("context") or {}
    event_type = context.get("event")

    repository.acquire_advisory_locks(session, pix_id, source_document, destination_document)
    existing = repository.get_transaction_by_id(session, pix_id)
    payload_hash = repository.compute_payload_hash(input_data)
    if existing:
        stored_hash = repository.compute_payload_hash(dict(existing.payload or {}))
        if stored_hash != payload_hash:
            raise HTTPException(status_code=409, detail="Event id was already used with a different payload")
        decision = repository.get_decision_by_transaction_id(session, pix_id)
        return {
            "key": str(decision.key),
            "status": decision.status,
            "metadata": decision.metadata_ or {},
            "_http_status": 200,
        }

    all_history = repository.get_transactions_before(session, event_date)
    trusted_history = repository.get_non_rejected_transactions_before(session, event_date)
    source_history = [tx for tx in all_history if tx.source_document == source_document and _is_outflow(tx)]
    trusted_source = [
        tx for tx in trusted_history
        if tx.source_document == source_document and _is_outflow(tx)
    ]
    source_history.sort(key=_transaction_date)
    trusted_source.sort(key=_transaction_date)
    current_payload = input_data
    current_destination_key = _destination_key(current_payload)
    current_dest_doc = destination_document
    current_geo = (input_data.get("source") or {}).get("geolocation")
    hits: list[dict] = []
    not_evaluated: list[dict] = []

    def add(code: str, points: int, detail: str) -> None:
        if not any(hit["code"] == code for hit in hits):
            hits.append(_make_hit(code, points, detail))

    def not_evaluated_rule(code: str, detail: str) -> None:
        not_evaluated.append({"rule": code, "reason": detail})

    successful_profile = [
        tx for tx in trusted_source
        if tx.destination_document != source_document
    ][-20:]
    profile_values = [int(tx.amount) for tx in successful_profile]
    median_amount = statistics.median(profile_values) if profile_values else 0
    profile_mature = (
        len(successful_profile) >= 10
        and len({_transaction_date(tx).date() for tx in successful_profile}) >= 5
        and event_date - _transaction_date(successful_profile[0]) >= timedelta(days=14)
    )
    limit = max(500_000, int(3 * median_amount)) if profile_mature else 500_000
    related_history, recurrent = _recurrent(trusted_source, current_dest_doc, event_date)
    max_related_amount = max((int(tx.amount) for tx in related_history), default=0)
    habitual = recurrent and max_related_amount > 0 and amount <= max_related_amount * 1.2
    current_source = input_data.get("source") or {}
    scheduled_execution = _is_scheduled_execution(context)

    if context is None or not context:
        if amount >= limit:
            points = 1 if habitual else 2
            add("R1", points, f"Amount {amount} cents; limit {limit} cents; habitual={habitual}.")
    if not context and current_dest_doc == source_document:
        pass

    # R2 counts event time, not request arrival time, and includes this request.
    if not scheduled_execution:
        recent_60s = _window(source_history, event_date, 1)
        if len(recent_60s) + 1 >= 5:
            add("R2", 2, f"At least five payer events in 60 seconds ({len(recent_60s) + 1}).")

    # R3 uses the same customer-relative limit as R1.
    if not scheduled_execution:
        recent_10m = _window(source_history, event_date, 10)
        if len(recent_10m) + 1 >= 2 and sum(int(tx.amount) for tx in recent_10m) + amount >= 2 * limit:
            add("R3", 2, f"Ten-minute total reaches twice the payer limit ({2 * limit} cents).")

    if context:
        responsibility_id = context.get("responsibility_id")
        profile_for_r4 = [
            tx for tx in trusted_source
            if not responsibility_id or _context(tx).get("responsibility_id") == responsibility_id
        ][-20:]
    else:
        profile_for_r4 = successful_profile
    r4_values = [int(tx.amount) for tx in profile_for_r4]
    r4_median = statistics.median(r4_values) if r4_values else 0
    if len(profile_for_r4) >= 5 and amount >= 50_000 and r4_median > 0:
        r4_related, r4_recurrent = _recurrent(trusted_source, current_dest_doc, event_date)
        r4_max = max((int(tx.amount) for tx in r4_related), default=0)
        if not (r4_recurrent and r4_max > 0 and amount <= r4_max * 1.2) and amount >= 5 * r4_median:
            add("R4", 2, f"Amount is at least five times the {r4_median:g}-cent median.")

    if len(trusted_source) >= 3 and amount >= 100_000 and not scheduled_execution:
        prior_to_account = any(_destination_key(_payload(tx)) == current_destination_key for tx in trusted_source)
        if not prior_to_account and (len(trusted_source) < 5 or amount >= median_amount):
            add("R5", 1, "First payment to this destination account from a payer with history.")

    if current_dest_doc != source_document:
        destination_opening = input_data["destination_account"].get("opening_date")
        if destination_opening is None:
            not_evaluated_rule("R6", "Destination opening date was not supplied.")
        elif amount >= 100_000:
            elapsed = event_date - _date(destination_opening)
            r6_amount = amount
            recent_small = [
                tx for tx in _window(source_history, event_date, 5)
                if int(tx.amount) < 100_000
                and _destination_key(_payload(tx)) == current_destination_key
            ]
            if amount < 100_000 and len(recent_small) + 1 >= 3:
                r6_amount = amount + sum(int(tx.amount) for tx in recent_small)
            if timedelta(0) <= elapsed <= timedelta(days=30) and r6_amount >= 100_000:
                add("R6", 2, f"Destination account is {elapsed.days} days old.")

    if not context and len(trusted_source) >= 3 and amount >= 50_000:
        recent_devices = {
            (_payload(tx).get("source") or {}).get("device_id")
            for tx in trusted_source[-20:]
        }
        device_id = current_source.get("device_id")
        if device_id and device_id not in recent_devices:
            add("R7", 2, "Payer used a device absent from the last 20 trusted events.")

    recent_5m_same_account = [
        tx for tx in _window(source_history, event_date, 5)
        if _destination_key(_payload(tx)) == current_destination_key
        and int(tx.amount) < 100_000
    ]
    if amount < 100_000 and len(recent_5m_same_account) + 1 >= 3:
        small_total = amount + sum(int(tx.amount) for tx in recent_5m_same_account)
        if small_total >= 200_000:
            add("R8", 2, f"At least three sub-R$1,000 transfers total {small_total} cents in five minutes.")

    if not context and current_dest_doc != source_document:
        destination_history = [
            tx for tx in _window(all_history, event_date, 60)
            if _destination_key(_payload(tx)) == current_destination_key
        ]
        senders = {tx.source_document for tx in destination_history}
        senders.add(source_document)
        total_received = amount + sum(int(tx.amount) for tx in destination_history)
        destination_opening = input_data["destination_account"].get("opening_date")
        is_old_cnpj = (
            len(current_dest_doc) == 14
            and destination_opening is not None
            and event_date - _date(destination_opening) > timedelta(days=30)
        )
        if len(senders) >= 5 and total_received >= 1_000_000 and not is_old_cnpj:
            add("R9", 3, f"Destination received from {len(senders)} payers, totaling {total_received} cents in 60 minutes.")

    source_opening = input_data["source_account"].get("opening_date")
    if not context and source_opening is not None and amount >= 200_000:
        account_age = event_date - _date(source_opening)
        if timedelta(0) <= account_age <= timedelta(days=30):
            points = 2 if len(trusted_source) < 3 else 1
            add("R10", points, f"Payer account is {account_age.days} days old with {len(trusted_source)} prior events.")

    if not context and isinstance(current_geo, dict):
        previous_geo_event = None
        for tx in reversed(_window(source_history, event_date, 60)):
            previous_source = _payload(tx).get("source") or {}
            geo = previous_source.get("geolocation")
            if isinstance(geo, dict):
                previous_geo_event = (tx, geo)
                break
        if previous_geo_event:
            previous_tx, previous_geo = previous_geo_event
            difference_hours = (event_date - _transaction_date(previous_tx)).total_seconds() / 3600
            if difference_hours > 0:
                distance = _distance_km(
                    float(previous_geo["latitude"]), float(previous_geo["longitude"]),
                    float(current_geo["latitude"]), float(current_geo["longitude"]),
                )
                if distance >= 50 and distance / difference_hours > 900:
                    add("R11", 3, f"Impossible travel: {distance:.1f} km in {difference_hours:.2f} hours.")
        elif _window(source_history, event_date, 60):
            not_evaluated_rule("R11", "A recent event exists, but one event has no geolocation.")

    if not context:
        recent_device_events = _window(all_history, event_date, 24 * 60)
        shared_owners = {
            tx.source_document for tx in recent_device_events
            if (_payload(tx).get("source") or {}).get("device_id") == current_source.get("device_id")
        }
        shared_owners.add(source_document)
        if len(shared_owners) >= 3:
            add("R12", 2, f"Device was used by {len(shared_owners)} payer documents in 24 hours.")
    else:
        recent_device_events = _window(all_history, event_date, 24 * 60)
        shared_author_companies = {
            (_context(tx).get("author_id"), _context(tx).get("company_id"))
            for tx in recent_device_events
            if (_payload(tx).get("source") or {}).get("device_id") == current_source.get("device_id")
            and _context(tx).get("author_id")
            and _context(tx).get("company_id")
        }
        if context.get("author_id") and context.get("company_id"):
            shared_author_companies.add((context["author_id"], context["company_id"]))
        distinct_authors = {author for author, _ in shared_author_companies}
        distinct_companies = {company for _, company in shared_author_companies}
        if len(distinct_authors) >= 3 and len(distinct_companies) >= 2:
            add("R12", 2, "Device was used by at least three authors across different companies in 24 hours.")

    if not context and amount >= int(limit * 0.9) and amount < limit:
        near_floor = [
            tx for tx in _window(source_history, event_date, 24 * 60)
            if int(limit * 0.9) <= int(tx.amount) < limit
        ]
        if len(near_floor) + 1 >= 3:
            add("R28", 2, f"At least three events fall in the 90%-to-100% band below limit {limit}.")

    if current_dest_doc != source_document:
        recent_60m_same_document = [
            tx for tx in _window(source_history, event_date, 60)
            if _destination_document(_payload(tx)) == current_dest_doc
        ]
        r29_total = amount + sum(int(tx.amount) for tx in recent_60m_same_document)
        prior_to_window = [
            tx for tx in related_history
            if event_date - _transaction_date(tx) > timedelta(minutes=60)
        ]
        prior_max = max((int(tx.amount) for tx in prior_to_window), default=0)
        recurrent_r29 = (
            len({_transaction_date(tx).date() for tx in prior_to_window}) >= 3
            and bool(prior_to_window)
            and event_date - min(_transaction_date(tx) for tx in prior_to_window) >= timedelta(days=14)
        )
        if (
            len(recent_60m_same_document) + 1 >= 4
            and r29_total >= limit
            and not (recurrent_r29 and prior_max > 0 and r29_total <= prior_max * 1.5)
        ):
            add("R29", 2, f"At least four transfers to one document total {r29_total} cents in 60 minutes.")

    if not context and not profile_mature and source_opening is not None:
        account_age = event_date - _date(source_opening)
        if timedelta(days=30) < account_age and 200_000 <= amount < 500_000 and not habitual:
            add("R33", 1, "Cold-start value step for an established account without a mature profile.")

    if context:
        _evaluate_epp_rules(
            repository=repository,
            session=session,
            input_data=input_data,
            event_date=event_date,
            context=context,
            all_history=all_history,
            source_history=source_history,
            trusted_source=trusted_source,
            amount=amount,
            source_document=source_document,
            destination_document=current_dest_doc,
            destination_key=current_destination_key,
            median_amount=median_amount,
            add=add,
            not_evaluated_rule=not_evaluated_rule,
        )

    if any(hit["code"] == "R23" for hit in hits):
        hits = [hit for hit in hits if hit["code"] != "R5"]

    score = _score(hits)
    status = "rejected" if score >= 5 else "two_factor_required" if score >= 2 else "approved"
    if any(hit["code"] == "C1" for hit in hits):
        status = "rejected"
    reasons = [
        {
            "code": hit["code"],
            "rule": hit["code"],
            "points": hit["points"],
            "detail": hit["detail"],
        }
        for hit in hits
    ]
    action_rules = {hit["code"] for hit in hits} & NOTIFY_RULES
    recommended_actions = (
        ["notify_all_partners_mobile"]
        if context and status != "approved" and action_rules
        else []
    )
    metadata = {
        "risk_score": score,
        "reasons": reasons,
        "rules_version": RULES_VERSION,
        "recommended_actions": recommended_actions,
        "not_evaluated": not_evaluated,
    }
    decision = repository.save_analysis(
        session=session,
        transaction_data=input_data,
        payload_hash=payload_hash,
        status=status,
        risk_score=score,
        metadata=metadata,
        rule_hits=hits,
    )
    return {
        "key": str(decision.key),
        "status": decision.status,
        "metadata": decision.metadata_,
        "_http_status": 201,
    }


def _evaluate_epp_rules(
    repository: PixRepository,
    session: Session,
    input_data: dict,
    event_date: datetime,
    context: dict,
    all_history: list[PixTransactionModel],
    source_history: list[PixTransactionModel],
    trusted_source: list[PixTransactionModel],
    amount: int,
    source_document: str,
    destination_document: str,
    destination_key: tuple[str, str, str],
    median_amount: float,
    add,
    not_evaluated_rule,
) -> None:
    event_type = context.get("event")
    author_id = context.get("author_id")
    company_id = context.get("company_id")
    source = input_data.get("source") or {}
    is_request = event_type == "request"
    recent_24h = _window(source_history, event_date, 24 * 60)
    recent_requests = [tx for tx in recent_24h if _event(tx) == "request"]
    destination_opening = input_data["destination_account"].get("opening_date")
    source_opening = input_data["source_account"].get("opening_date")
    activation_value = context.get("account_activated_at")
    activated_at = _date(activation_value) if activation_value else None
    account_age = event_date - activated_at if activated_at else None
    related, recurrent = _recurrent(trusted_source, destination_document, event_date)
    max_related = max((int(tx.amount) for tx in related), default=0)
    habitual = recurrent and max_related > 0 and amount <= max_related * 1.2
    scheduled_execution = _is_scheduled_execution(context)

    # R13: repeated requests just below the lower configured limit.
    limits = [
        value for value in (context.get("author_limit"), context.get("approval_trigger"))
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if is_request and limits:
        ceiling = min(limits)
        lower, upper = ceiling * 0.9, ceiling * 0.999
        prior_hugging = [
            tx for tx in recent_requests
            if _context(tx).get("author_id") == author_id and lower <= int(tx.amount) <= upper
        ]
        if lower <= amount <= upper and len(prior_hugging) + 1 >= 3 and not habitual:
            add("R13", 2, f"Author repeated values immediately below the {ceiling}-cent control limit.")

    # R14 is based on explicit refusals supplied by the EPP, not similar prior requests.
    if is_request:
        refused_requests = context.get("refused_requests_24h") or []
        for refusal in refused_requests:
            if not isinstance(refusal, dict):
                continue
            try:
                refusal_age = event_date - _date(refusal["refused_at"])
                refusal_amount = int(refusal["amount"])
            except (KeyError, TypeError, ValueError):
                continue
            same_destination = refusal.get("destination_document") == destination_document
            refused_by_other = refusal.get("refused_by") != author_id
            if (
                same_destination and refused_by_other and timedelta(0) <= refusal_age <= timedelta(hours=24)
                and refusal_amount * 0.8 <= amount <= refusal_amount * 1.2
            ):
                add("R14", 2, "Request recreates a similar payment refused by another partner in the last 24 hours.")
                break

    # C1 validates votes and executions against the immutable request.
    c1_failed = False
    if event_type in ("vote", "execution"):
        request_id = context.get("request_id")
        request_hash = context.get("request_hash")
        original = repository.get_transaction_by_id(session, str(request_id)) if request_id else None
        if original is None:
            c1_failed = True
            c1_detail = "Referenced request does not exist."
        else:
            original_context = _context(original)
            original_decision = repository.get_decision_by_transaction_id(session, original.id)
            if original_context.get("event") != "request" or original_decision is None or original_decision.status == "rejected":
                c1_failed = True
                c1_detail = "Referenced request is missing, invalid, or rejected."
            elif original_context.get("request_hash") != request_hash:
                c1_failed = True
                c1_detail = "Request hash differs from the stored request."
            else:
                c1_detail = ""
        if event_type == "execution" and not c1_failed:
            for tx in all_history:
                prior_context = _context(tx)
                if prior_context.get("event") == "execution" and prior_context.get("request_id") == request_id:
                    prior_decision = repository.get_decision_by_transaction_id(session, tx.id)
                    if prior_decision and prior_decision.status != "rejected":
                        c1_failed = True
                        c1_detail = "This request already has a non-rejected execution."
                        break
        if c1_failed:
            add("C1", 0, c1_detail)

    # R15: the vote uses the author's device or same IP within ten seconds.
    if event_type == "vote" and context.get("request_id"):
        original = repository.get_transaction_by_id(session, str(context["request_id"]))
        if original:
            original_payload = _payload(original)
            original_source = original_payload.get("source") or {}
            same_device = bool(source.get("device_id")) and source.get("device_id") == original_source.get("device_id")
            same_ip_fast = False
            if source.get("ip") and source.get("ip") == original_source.get("ip"):
                elapsed = event_date - _transaction_date(original)
                same_ip_fast = timedelta(0) <= elapsed < timedelta(seconds=10)
            if same_device or same_ip_fast:
                add("R15", 3, "Vote used the request author's device or same IP within ten seconds.")

    # R16: recent weakening of company controls followed by a request.
    loosened_value = context.get("control_loosened_at")
    if is_request and loosened_value and activated_at:
        elapsed = event_date - _date(loosened_value)
        if account_age is not None and account_age >= timedelta(days=7) and timedelta(0) <= elapsed <= timedelta(hours=24):
            add("R16", 3, "Company controls were loosened within 24 hours before this request.")

    author_requests = [
        tx for tx in trusted_source
        if _event(tx) == "request" and _context(tx).get("author_id") == author_id
    ]
    author_requests.sort(key=_transaction_date)

    # R17: new device for a partner with an established request history.
    if is_request and len(author_requests) >= 3 and amount >= 50_000:
        prior_devices = {
            (_payload(tx).get("source") or {}).get("device_id") for tx in author_requests[-20:]
        }
        if source.get("device_id") and source.get("device_id") not in prior_devices:
            add("R17", 2, "Partner used a device absent from their last 20 requests.")

    # R18: impossible travel for this author; fallback checks a country change in IP.
    if is_request and author_requests:
        previous = author_requests[-1]
        previous_payload = _payload(previous)
        previous_source = previous_payload.get("source") or {}
        elapsed_hours = (event_date - _transaction_date(previous)).total_seconds() / 3600
        if 0 < elapsed_hours <= 12:
            previous_geo = previous_source.get("geolocation")
            current_geo = source.get("geolocation")
            if isinstance(previous_geo, dict) and isinstance(current_geo, dict):
                distance = _distance_km(
                    float(previous_geo["latitude"]), float(previous_geo["longitude"]),
                    float(current_geo["latitude"]), float(current_geo["longitude"]),
                )
                if distance >= 50 and distance / elapsed_hours > 900:
                    add("R18", 3, f"Partner travelled {distance:.1f} km in {elapsed_hours:.2f} hours.")
            elif _ip_country(previous_source.get("ip")) and _ip_country(source.get("ip")) and _ip_country(previous_source.get("ip")) != _ip_country(source.get("ip")):
                add("R18", 3, "Partner IP changed to a different country within 12 hours.")

    # R19: unusual overnight activity, after enough operations to establish a baseline.
    if is_request and context.get("origin") == "immediate" and amount >= 100_000:
        local_time = event_date.astimezone(ZoneInfo("America/Sao_Paulo"))
        if 0 <= local_time.hour < 5 and len(author_requests) >= 10:
            night_operations = sum(
                1 for tx in author_requests
                if 0 <= _transaction_date(tx).astimezone(ZoneInfo("America/Sao_Paulo")).hour < 5
            )
            if night_operations == 0:
                add("R19", 1, "Partner requested an immediate payment between midnight and 05:00 BRT despite no prior overnight activity.")

    # R20: free-balance depletion, excluding reserved and scheduled outflows.
    free_balance = context.get("free_balance")
    if is_request and isinstance(free_balance, (int, float)) and not isinstance(free_balance, bool) and free_balance > 0:
        previous_free = [
            tx for tx in _window(source_history, event_date, 24 * 60)
            if not _context(tx).get("responsibility_id") and not _is_scheduled_execution(_context(tx))
        ]
        previous_total = sum(int(tx.amount) for tx in previous_free)
        total_outflow = amount + previous_total
        initial_balance = int(free_balance) + previous_total
        if total_outflow >= 500_000 and total_outflow >= initial_balance * 0.7:
            add("R20", 2, f"Free-balance outflow is {total_outflow} cents, at least 70% of {initial_balance} cents.")

    # R21: released reserve followed by a large payment to a new counterparty.
    if is_request and context.get("reserved_amount_released") and context.get("reserved_released_at"):
        released_amount = int(context["reserved_amount_released"])
        elapsed = event_date - _date(context["reserved_released_at"])
        known_destination = any(
            _destination_document(_payload(tx)) == destination_document for tx in trusted_source
        )
        if amount >= released_amount * 0.8 and timedelta(0) <= elapsed <= timedelta(minutes=30) and not known_destination:
            add("R21", 3, "At least 80% of a recently released reserve is being sent to a new counterparty.")

    # R22: payment to a company partner, excluding an ordinary recurring amount.
    partner_documents = {str(value) for value in context.get("partner_documents", [])}
    if is_request and amount >= 200_000 and destination_document in partner_documents:
        if not (recurrent and max_related > 0 and max_related * 0.8 <= amount <= max_related * 1.2):
            add("R22", 1, "Payment destination is a partner's document.")

    # R23: a mature responsibility paying a new destination.
    responsibility_id = context.get("responsibility_id")
    if is_request and responsibility_id and amount >= 100_000:
        responsibility_history = [
            tx for tx in trusted_source
            if _context(tx).get("responsibility_id") == responsibility_id
            and _event(tx) == "request"
            and event_date - _transaction_date(tx) <= timedelta(days=90)
        ]
        destinations = {_destination_key(_payload(tx)) for tx in responsibility_history}
        already_paid = destination_key in destinations
        if len(responsibility_history) >= 5 and len(destinations) <= 3 and not already_paid:
            add("R23", 1, "Established payment responsibility is sending to a new destination.")

    # R24: cold or immature company outflow thresholds.
    if event_type != "vote" and amount >= 500_000:
        if activated_at is None:
            not_evaluated_rule("R24", "Company activation date was not supplied.")
        else:
            outgoing_count = len([tx for tx in source_history if _is_outflow(tx)])
            if (account_age is not None and account_age <= timedelta(days=30)) or outgoing_count < 10:
                points = 2 if amount >= 2_000_000 else 1
                add("R24", points, f"Company is immature with {outgoing_count} prior outflows; amount is {amount} cents.")

    # R25: quick conversion of recent inflows into a new external destination.
    inflows = context.get("inflows_24h")
    last_inflow = context.get("last_inflow_at")
    if is_request and isinstance(inflows, (int, float)) and last_inflow and amount >= 100_000:
        elapsed = event_date - _date(last_inflow)
        known_destination = any(
            _destination_document(_payload(tx)) == destination_document for tx in trusted_source
        )
        company_young = account_age is not None and account_age <= timedelta(days=90)
        payers = {tx.source_document for tx in _window(all_history, event_date, 24 * 60)}
        only_new_payers = len(payers) <= 1
        if (
            inflows >= 1_000_000 and amount >= inflows * 0.8
            and timedelta(0) <= elapsed <= timedelta(hours=2)
            and not known_destination and (company_young or only_new_payers)
        ):
            add("R25", 3, "At least 80% of recent external inflows are leaving for a new destination within two hours.")

    # R26: network destination concentration across companies.
    if is_request:
        network_events = [
            tx for tx in _window(all_history, event_date, 24 * 60)
            if _destination_document(_payload(tx)) == destination_document
        ]
        companies = {
            _context(tx).get("company_id") for tx in network_events if _context(tx).get("company_id")
        }
        if company_id:
            companies.add(company_id)
        total_network_amount = amount + sum(int(tx.amount) for tx in network_events)
        if len(companies) >= 4 and total_network_amount >= 1_000_000 and not recurrent:
            add("R26", 3, f"Destination received from {len(companies)} companies, totaling {total_network_amount} cents in 24 hours.")

    # R27 is an informational zero-point alert for partners active across companies.
    if is_request:
        recent_events = _window(all_history, event_date, 30 * 24 * 60)
        current_partners = {str(value) for value in context.get("partner_documents", [])}
        for partner in current_partners:
            active_companies = {
                _context(tx).get("company_id") for tx in recent_events
                if partner in {str(value) for value in _context(tx).get("partner_documents", [])}
                and _context(tx).get("company_id")
            }
            if company_id:
                active_companies.add(company_id)
            if len(active_companies) >= 3:
                add("R27", 0, f"Partner document {partner} is associated with at least three active companies.")
                break

    # R30: outflow above a trimmed daily average for an established company.
    if (
        is_request
        and not context.get("responsibility_id")
        and activated_at
        and account_age is not None
        and account_age >= timedelta(days=30)
    ):
        base_events = [
            tx for tx in source_history
            if timedelta(hours=24) < event_date - _transaction_date(tx) <= timedelta(days=31)
            and _is_outflow(tx)
            and not _context(tx).get("responsibility_id")
            and not _is_scheduled_execution(_context(tx))
        ]
        if len(base_events) >= 10:
            daily_totals: dict[date, int] = defaultdict(int)
            for tx in base_events:
                daily_totals[_transaction_date(tx).date()] += int(tx.amount)
            trimmed_average = (sum(daily_totals.values()) - max(daily_totals.values())) / 29
            recent_company_outflows = [
                tx for tx in _window(source_history, event_date, 24 * 60)
                if _is_outflow(tx)
                and not _context(tx).get("responsibility_id")
                and not _is_scheduled_execution(_context(tx))
            ]
            total_24h = amount + sum(int(tx.amount) for tx in recent_company_outflows)
            if total_24h >= 1_000_000 and total_24h >= 3 * trimmed_average and not habitual:
                add("R30", 2, f"Company outflow {total_24h} cents exceeds three times its trimmed daily average.")

    # R31: destination company or person is linked to a company partner.
    destination_partners = {str(value) for value in context.get("destination_partner_documents", [])}
    if is_request and amount >= 200_000 and partner_documents.intersection(destination_partners):
        ordinary_recurring = recurrent and max_related > 0 and max_related * 0.8 <= amount <= max_related * 1.2
        if not ordinary_recurring:
            add("R31", 2, "Destination is linked to a partner of the paying company.")

    # R32: immediate payment after the author's credentials changed.
    changed_at = context.get("credential_changed_at")
    if is_request and context.get("origin") == "immediate" and amount >= 200_000 and changed_at:
        elapsed = event_date - _date(changed_at)
        credential_created = context.get("credential_created_at")
        recent_credential = credential_created and event_date - _date(credential_created) < timedelta(days=7)
        if timedelta(0) <= elapsed <= timedelta(hours=24) and not recent_credential:
            add("R32", 2, "An immediate payment of at least R$2,000 followed a credential change within 24 hours.")


def _score(hits: list[dict]) -> int:
    grouped = {
        "value": ({"R1", "R3", "R4", "R28"}, 3),
        "fractioning": ({"R8", "R29"}, 2),
        "controls": ({"R13", "R14", "R16"}, 3),
        "session": ({"R17", "R18", "R19", "R32"}, 4),
        "account_behavior": ({"R20", "R21"}, 3),
        "linked_destination": ({"R22", "R31"}, 2),
    }
    grouped_codes = set()
    total = 0
    for codes, cap in grouped.values():
        grouped_codes.update(codes)
        total += min(cap, sum(hit["points"] for hit in hits if hit["code"] in codes))
    total += sum(hit["points"] for hit in hits if hit["code"] not in grouped_codes)
    return total


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    latitude_delta = radians(lat2 - lat1)
    longitude_delta = radians(lon2 - lon1)
    value = (
        sin(latitude_delta / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(longitude_delta / 2) ** 2
    )
    return 6371.0 * 2 * asin(sqrt(max(0.0, min(1.0, value))))


def _ip_country(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    first = value.split(".", 1)[0]
    return "BR" if first in {"10", "100", "127", "172", "192", "177", "200", "201"} else None
