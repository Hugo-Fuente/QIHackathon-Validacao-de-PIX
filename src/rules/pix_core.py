"""Pure retail Pix rules: R1–R12, R28, R29 and R33."""

from datetime import timedelta
from typing import Callable

from rules import params
from rules.common import (
    context_of, destination_document, destination_key, event_context,
    event_datetime, is_scheduled_execution, payload, recurrent, source_data,
    source_document, transaction_datetime, window,
)

RuleResult = tuple[int, str] | None


def r1(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    amount = int(event["amount"])
    if epp or amount < params.R1_MIN_AMOUNT_CENTS:
        return None
    limit = int(profile.get("limit", params.PROFILE_LIMIT_CENTS))
    if amount < limit:
        return None
    if profile["habitual"]:
        return 1, f"Amount {amount} cents is habitual for this recurring counterparty (limit {limit})."
    return 2, f"Amount {amount} cents reaches payer limit {limit}."


def r2(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    if is_scheduled_execution(epp):
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        count = int(metrics.get("r2_count", 0)) + 1
    else:
        recent = window(profile["source_history"], event_datetime(event), timedelta(seconds=params.R2_WINDOW_SECONDS))
        count = len(recent) + 1
    if count >= params.R2_MIN_EVENTS:
        return 2, f"At least five payer events in 60 seconds ({count})."
    return None


def r3(event: dict, profile: dict, context: dict) -> RuleResult:
    if is_scheduled_execution(event_context(event)):
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        count = int(metrics.get("r3_count", 0)) + 1
        total = int(metrics.get("r3_sum", 0)) + int(event["amount"])
    else:
        recent = window(profile["source_history"], event_datetime(event), timedelta(minutes=params.R3_WINDOW_MINUTES))
        count = len(recent) + 1
        total = sum(int(tx["amount"]) for tx in recent) + int(event["amount"])
    limit = int(profile.get("limit", params.PROFILE_LIMIT_CENTS))
    threshold = max(params.R3_MIN_TOTAL_CENTS, params.R3_LIMIT_FACTOR * limit)
    if count >= params.R3_MIN_EVENTS and total >= threshold:
        return 2, f"Ten-minute total reaches twice the payer limit ({threshold} cents)."
    return None


def r4(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    history = profile["trusted_history"]
    responsibility_id = epp.get("responsibility_id")
    if epp and responsibility_id:
        history = [tx for tx in history if context_of(tx).get("responsibility_id") == responsibility_id]
    elif not epp:
        history = profile["successful_profile"]
    history = history[-params.PROFILE_SAMPLE_SIZE:]
    if not epp:
        median = profile["median_amount"]
    else:
        values = [int(tx["amount"]) for tx in history]
        median = sorted(values)[len(values) // 2] if values else 0
        if values and len(values) % 2 == 0:
            median = (sorted(values)[len(values) // 2 - 1] + sorted(values)[len(values) // 2]) / 2
    amount = int(event["amount"])
    if len(history) < params.R4_MIN_HISTORY or amount < params.R4_MIN_AMOUNT_CENTS or median <= 0:
        return None
    related, mature = recurrent(profile["trusted_history"], destination_document(event), event_datetime(event))
    maximum = max((int(tx["amount"]) for tx in related), default=0)
    habitual = mature and maximum > 0 and amount <= maximum * params.HABITUAL_AMOUNT_FACTOR
    if not habitual and amount >= params.R4_MEDIAN_FACTOR * median:
        return 2, f"Amount is at least five times the {median:g}-cent median."
    return None


def r5(event: dict, profile: dict, context: dict) -> RuleResult:
    history = profile["trusted_history"]
    amount = int(event["amount"])
    if (
        destination_document(event) == source_document(event)
        or len(history) < params.R5_MIN_HISTORY
        or amount < params.R5_MIN_AMOUNT_CENTS
        or is_scheduled_execution(event_context(event))
    ):
        return None
    key = destination_key(event)
    seen_destination = context.get("seen_destination_account")
    has_seen_destination = (
        seen_destination
        if seen_destination is not None
        else any(destination_key(payload(tx)) == key for tx in history)
    )
    if has_seen_destination:
        return None
    if len(history) < params.R5_PROFILE_MEDIAN_COUNT or amount >= profile["median_amount"]:
        return 1, "First payment to this destination account from a payer with history."
    return None


def r6(event: dict, profile: dict, context: dict) -> RuleResult:
    if destination_document(event) == source_document(event):
        return None
    account = event.get("destination_account") or {}
    opening = account.get("opening_date")
    amount = int(event["amount"])
    if opening is None:
        return None
    age = event_datetime(event) - _date(opening)
    if timedelta(0) <= age <= timedelta(days=params.R6_MAX_ACCOUNT_AGE_DAYS):
        recent_small = [
            tx for tx in window(profile["source_history"], event_datetime(event), timedelta(minutes=params.R8_WINDOW_MINUTES))
            if int(tx["amount"]) < params.R8_MAX_EVENT_CENTS and destination_key(payload(tx)) == destination_key(event)
        ]
        effective_amount = amount
        small_total = amount + sum(int(tx["amount"]) for tx in recent_small)
        if amount < params.R6_MIN_AMOUNT_CENTS and len(recent_small) + 1 >= params.R8_MIN_EVENTS and small_total >= params.R8_MIN_TOTAL_CENTS:
            effective_amount = small_total
        if effective_amount >= params.R6_MIN_AMOUNT_CENTS:
            return 2, f"Destination account is {age.days} days old."
    return None


def r7(event: dict, profile: dict, context: dict) -> RuleResult:
    if event_context(event) or len(profile["trusted_history"]) < params.R7_MIN_HISTORY or int(event["amount"]) < params.R7_MIN_AMOUNT_CENTS:
        return None
    recent_devices = {
        (payload(tx).get("source") or {}).get("device_id")
        for tx in profile["trusted_history"][-params.PROFILE_SAMPLE_SIZE:]
    }
    device_id = source_data(event).get("device_id")
    if device_id and device_id not in recent_devices:
        return 2, "Payer used a device absent from the last 20 trusted events."
    return None


def r8(event: dict, profile: dict, context: dict) -> RuleResult:
    amount = int(event["amount"])
    if amount >= params.R8_MAX_EVENT_CENTS:
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        count = int(metrics.get("r8_count", 0)) + 1
        total = amount + int(metrics.get("r8_sum", 0))
    else:
        recent = [
            tx for tx in window(profile["source_history"], event_datetime(event), timedelta(minutes=params.R8_WINDOW_MINUTES))
            if int(tx["amount"]) < params.R8_MAX_EVENT_CENTS and destination_key(payload(tx)) == destination_key(event)
        ]
        count = len(recent) + 1
        total = amount + sum(int(tx["amount"]) for tx in recent)
    if count >= params.R8_MIN_EVENTS and total >= params.R8_MIN_TOTAL_CENTS:
        return 2, f"At least three sub-R$1,000 transfers total {total} cents in five minutes."
    return None


def r9(event: dict, profile: dict, context: dict) -> RuleResult:
    if event_context(event) or destination_document(event) == source_document(event):
        return None
    activity = context.get("destination_account_activity", {})
    senders = int(activity.get("sender_count", 0)) + (0 if activity.get("current_sender_present") else 1)
    total = int(event["amount"]) + int(activity.get("amount_total", 0))
    opening = (event.get("destination_account") or {}).get("opening_date")
    destination_doc = destination_document(event)
    old_cnpj = (
        len(destination_doc) == 14 and opening is not None
        and event_datetime(event) - _date(opening) > timedelta(days=params.R9_CNPJ_ACCOUNT_AGE_DAYS)
    )
    if senders >= params.R9_MIN_SENDERS and total >= params.R9_MIN_TOTAL_CENTS and not old_cnpj:
        return 3, f"Destination received from {senders} payers, totaling {total} cents in 60 minutes."
    return None


def r10(event: dict, profile: dict, context: dict) -> RuleResult:
    if event_context(event):
        return None
    opening = (event.get("source_account") or {}).get("opening_date")
    amount = int(event["amount"])
    if opening is None or amount < params.R10_MIN_AMOUNT_CENTS:
        return None
    age = event_datetime(event) - _date(opening)
    if timedelta(0) <= age <= timedelta(days=params.R10_MAX_ACCOUNT_AGE_DAYS):
        history_count = int(profile.get("trusted_event_count", len(profile["trusted_history"])))
        points = 2 if history_count < params.R10_PROFILE_EVENTS else 1
        return points, f"Payer account is {age.days} days old with {history_count} prior events."
    return None


def r11(event: dict, profile: dict, context: dict) -> RuleResult:
    if event_context(event):
        return None
    current_geo = source_data(event).get("geolocation")
    recent = window(profile["source_history"], event_datetime(event), timedelta(minutes=params.R11_WINDOW_MINUTES))
    if not recent or not isinstance(current_geo, dict):
        return None
    previous = recent[-1]
    previous_geo = (payload(previous).get("source") or {}).get("geolocation")
    if not isinstance(previous_geo, dict):
        return None
    hours = (event_datetime(event) - transaction_datetime(previous)).total_seconds() / 3600
    if hours > 0:
        distance = _distance_km(
            float(previous_geo["latitude"]), float(previous_geo["longitude"]),
            float(current_geo["latitude"]), float(current_geo["longitude"]),
        )
        if distance >= params.R11_MIN_DISTANCE_KM and distance / hours > params.R11_MIN_SPEED_KMH:
            return 3, f"Impossible travel: {distance:.1f} km in {hours:.2f} hours."
    return None


def r12(event: dict, profile: dict, context: dict) -> RuleResult:
    if event_context(event):
        pairs = set(context.get("device_author_companies", ()))
        author_id = event_context(event).get("author_id")
        company_id = event_context(event).get("company_id")
        if author_id and company_id:
            pairs.add((author_id, company_id))
        authors = {author for author, _ in pairs}
        companies = {company for _, company in pairs}
        if len(authors) >= params.R12_MIN_PAYER_DOCUMENTS and len(companies) >= params.R12_MIN_COMPANIES:
            return 2, "Device was used by at least three authors across different companies in 24 hours."
        return None
    owner_count = int(context.get("device_payer_count", 1))
    if owner_count >= params.R12_MIN_PAYER_DOCUMENTS:
        return 2, f"Device was used by {owner_count} payer documents in 24 hours."
    return None


def r28(event: dict, profile: dict, context: dict) -> RuleResult:
    amount = int(event["amount"])
    limit = int(profile.get("limit", params.PROFILE_LIMIT_CENTS))
    from math import ceil

    lower = ceil(limit * params.R28_LOWER_LIMIT_RATIO)
    if event_context(event) or not lower <= amount < limit:
        return None
    recent = [
        tx for tx in window(profile["source_history"], event_datetime(event), timedelta(hours=params.R28_WINDOW_HOURS))
        if lower <= int(tx["amount"]) < limit
    ]
    if len(recent) + 1 >= params.R28_MIN_EVENTS:
        return 2, f"At least three events fall in the 90%-to-100% band below limit {limit}."
    return None


def r29(event: dict, profile: dict, context: dict) -> RuleResult:
    if destination_document(event) == source_document(event):
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        recent_count = int(metrics.get("r29_count", 0))
        recent_total = int(metrics.get("r29_sum", 0))
        prior_max = int(metrics.get("r29_prior_max", 0))
        mature_prior = bool(metrics.get("r29_prior_mature", 0))
    else:
        recent = [
            tx for tx in window(profile["source_history"], event_datetime(event), timedelta(minutes=params.R29_WINDOW_MINUTES))
            if destination_document(payload(tx)) == destination_document(event)
        ]
        recent_count = len(recent)
        recent_total = sum(int(tx["amount"]) for tx in recent)
        prior = [
            tx for tx in profile["related_history"]
            if event_datetime(event) - transaction_datetime(tx) > timedelta(minutes=params.R29_WINDOW_MINUTES)
        ]
        prior_max = max((int(tx["amount"]) for tx in prior), default=0)
        prior_days = {transaction_datetime(tx).date() for tx in prior}
        mature_prior = (
            len(prior_days) >= params.RECURRENT_DISTINCT_DAYS and bool(prior)
            and event_datetime(event) - min(transaction_datetime(tx) for tx in prior) >= timedelta(days=params.RECURRENT_AGE_DAYS)
        )
    total = int(event["amount"]) + recent_total
    exempt = mature_prior and prior_max > 0 and total <= prior_max * params.R29_RECURRENT_EXEMPTION_FACTOR
    if recent_count + 1 >= params.R29_MIN_EVENTS and total >= profile["limit"] and not exempt:
        return 2, f"At least four transfers to one document total {total} cents in 60 minutes."
    return None


def r33(event: dict, profile: dict, context: dict) -> RuleResult:
    if event_context(event) or profile["mature"] or profile["habitual"]:
        return None
    opening = (event.get("source_account") or {}).get("opening_date")
    if opening is None:
        return None
    age = event_datetime(event) - _date(opening)
    amount = int(event["amount"])
    if timedelta(days=params.R10_MAX_ACCOUNT_AGE_DAYS) < age and params.R10_MIN_AMOUNT_CENTS <= amount < params.PROFILE_LIMIT_CENTS:
        return 1, "Cold-start value step for an established account without a mature profile."
    return None


def not_evaluated(event: dict, profile: dict, context: dict) -> list[dict]:
    """Missing-input diagnostics retained in response metadata."""
    missing = []
    opening = (event.get("destination_account") or {}).get("opening_date")
    if destination_document(event) != source_document(event) and opening is None:
        missing.append({"rule": "R6", "reason": "Destination opening date was not supplied."})
    if not event_context(event):
        recent = window(profile["source_history"], event_datetime(event), timedelta(minutes=params.R11_WINDOW_MINUTES))
        current_geo = source_data(event).get("geolocation")
        previous_geo = (payload(recent[-1]).get("source") or {}).get("geolocation") if recent else None
        if recent and (not isinstance(current_geo, dict) or not isinstance(previous_geo, dict)):
            missing.append({"rule": "R11", "reason": "A recent event exists, but one event has no geolocation."})
    epp = event_context(event)
    if epp and epp.get("event") == "request":
        if epp.get("free_balance") is None:
            missing.append({"rule": "R20", "reason": "Free balance was not supplied."})
        if epp.get("account_activated_at") is None:
            missing.append({"rule": "R24", "reason": "Company activation date was not supplied."})
            missing.append({"rule": "R30", "reason": "Company activation date was not supplied."})
    return missing


def _date(value):
    from rules.common import parse_datetime
    return parse_datetime(value)


def _distance_km(lat1, lon1, lat2, lon2):
    from rules.common import distance_km
    return distance_km(lat1, lon1, lat2, lon2)


CORE_RULES: tuple[Callable[[dict, dict, dict], RuleResult], ...] = (
    r1, r2, r3, r4, r5, r6, r7, r8, r9, r10, r11, r12, r28, r29, r33,
)

