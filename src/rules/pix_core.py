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
    settings = context.get("rule_parameters") or params.for_rule("R1")
    epp = event_context(event)
    amount = int(event["amount"])
    if epp or amount < settings['R1_MIN_AMOUNT_CENTS']:
        return None
    limit = int(profile.get("limit", settings['PROFILE_LIMIT_CENTS']))
    if amount < limit:
        return None
    if profile["habitual"]:
        return 1, f"Amount {amount} cents is habitual for this recurring counterparty (limit {limit})."
    return 2, f"Amount {amount} cents reaches payer limit {limit}."


def r2(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R2")
    epp = event_context(event)
    if is_scheduled_execution(epp):
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        count = int(metrics.get("r2_count", 0)) + 1
    else:
        recent = window(profile["source_history"], event_datetime(event), timedelta(seconds=settings['R2_WINDOW_SECONDS']))
        count = len(recent) + 1
    if count >= settings['R2_MIN_EVENTS']:
        return 2, f"At least five payer events in 60 seconds ({count})."
    return None


def r3(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R3")
    if is_scheduled_execution(event_context(event)):
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        count = int(metrics.get("r3_count", 0)) + 1
        total = int(metrics.get("r3_sum", 0)) + int(event["amount"])
    else:
        recent = window(profile["source_history"], event_datetime(event), timedelta(minutes=settings['R3_WINDOW_MINUTES']))
        count = len(recent) + 1
        total = sum(int(tx["amount"]) for tx in recent) + int(event["amount"])
    limit = int(profile.get("limit", settings['PROFILE_LIMIT_CENTS']))
    threshold = max(settings['R3_MIN_TOTAL_CENTS'], settings['R3_LIMIT_FACTOR'] * limit)
    if count >= settings['R3_MIN_EVENTS'] and total >= threshold:
        return 2, f"Ten-minute total reaches twice the payer limit ({threshold} cents)."
    return None


def r4(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R4")
    epp = event_context(event)
    history = profile["trusted_history"]
    responsibility_id = epp.get("responsibility_id")
    if epp and responsibility_id:
        history = [tx for tx in history if context_of(tx).get("responsibility_id") == responsibility_id]
    elif not epp:
        history = profile["successful_profile"]
    history = history[-settings['PROFILE_SAMPLE_SIZE']:]
    if not epp:
        median = profile["median_amount"]
    else:
        values = [int(tx["amount"]) for tx in history]
        median = sorted(values)[len(values) // 2] if values else 0
        if values and len(values) % 2 == 0:
            median = (sorted(values)[len(values) // 2 - 1] + sorted(values)[len(values) // 2]) / 2
    amount = int(event["amount"])
    if len(history) < settings['R4_MIN_HISTORY'] or amount < settings['R4_MIN_AMOUNT_CENTS'] or median <= 0:
        return None
    related, mature = recurrent(profile["trusted_history"], destination_document(event), event_datetime(event))
    maximum = max((int(tx["amount"]) for tx in related), default=0)
    habitual = mature and maximum > 0 and amount <= maximum * settings['HABITUAL_AMOUNT_FACTOR']
    if not habitual and amount >= settings['R4_MEDIAN_FACTOR'] * median:
        return 2, f"Amount is at least five times the {median:g}-cent median."
    return None


def r5(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R5")
    history = profile["trusted_history"]
    amount = int(event["amount"])
    if (
        destination_document(event) == source_document(event)
        or len(history) < settings['R5_MIN_HISTORY']
        or amount < settings['R5_MIN_AMOUNT_CENTS']
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
    if len(history) < settings['R5_PROFILE_MEDIAN_COUNT'] or amount >= profile["median_amount"]:
        return 1, "First payment to this destination account from a payer with history."
    return None


def r6(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R6")
    if destination_document(event) == source_document(event):
        return None
    account = event.get("destination_account") or {}
    opening = account.get("opening_date")
    amount = int(event["amount"])
    if opening is None:
        return None
    age = event_datetime(event) - _date(opening)
    if timedelta(0) <= age <= timedelta(days=settings['R6_MAX_ACCOUNT_AGE_DAYS']):
        recent_small = [
            tx for tx in window(profile["source_history"], event_datetime(event), timedelta(minutes=settings['R6_SMALL_PAYMENT_WINDOW_MINUTES']))
            if int(tx["amount"]) < settings['R6_SMALL_PAYMENT_MAX_EVENT_CENTS'] and destination_key(payload(tx)) == destination_key(event)
        ]
        effective_amount = amount
        small_total = amount + sum(int(tx["amount"]) for tx in recent_small)
        if amount < settings['R6_MIN_AMOUNT_CENTS'] and len(recent_small) + 1 >= settings['R6_SMALL_PAYMENT_MIN_EVENTS'] and small_total >= settings['R6_SMALL_PAYMENT_MIN_TOTAL_CENTS']:
            effective_amount = small_total
        if effective_amount >= settings['R6_MIN_AMOUNT_CENTS']:
            return 2, f"Destination account is {age.days} days old."
    return None


def r7(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R7")
    if event_context(event) or len(profile["trusted_history"]) < settings['R7_MIN_HISTORY'] or int(event["amount"]) < settings['R7_MIN_AMOUNT_CENTS']:
        return None
    recent_devices = {
        (payload(tx).get("source") or {}).get("device_id")
        for tx in profile["trusted_history"][-settings['PROFILE_SAMPLE_SIZE']:]
    }
    device_id = source_data(event).get("device_id")
    if device_id and device_id not in recent_devices:
        return 2, "Payer used a device absent from the last 20 trusted events."
    return None


def r8(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R8")
    amount = int(event["amount"])
    if amount >= settings['R8_MAX_EVENT_CENTS']:
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        count = int(metrics.get("r8_count", 0)) + 1
        total = amount + int(metrics.get("r8_sum", 0))
    else:
        recent = [
            tx for tx in window(profile["source_history"], event_datetime(event), timedelta(minutes=settings['R8_WINDOW_MINUTES']))
            if int(tx["amount"]) < settings['R8_MAX_EVENT_CENTS'] and destination_key(payload(tx)) == destination_key(event)
        ]
        count = len(recent) + 1
        total = amount + sum(int(tx["amount"]) for tx in recent)
    if count >= settings['R8_MIN_EVENTS'] and total >= settings['R8_MIN_TOTAL_CENTS']:
        return 2, f"At least three sub-R$1,000 transfers total {total} cents in five minutes."
    return None


def r9(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R9")
    if event_context(event) or destination_document(event) == source_document(event):
        return None
    activity = context.get("destination_account_activity", {})
    senders = int(activity.get("sender_count", 0)) + (0 if activity.get("current_sender_present") else 1)
    total = int(event["amount"]) + int(activity.get("amount_total", 0))
    opening = (event.get("destination_account") or {}).get("opening_date")
    destination_doc = destination_document(event)
    old_cnpj = (
        len(destination_doc) == 14 and opening is not None
        and event_datetime(event) - _date(opening) > timedelta(days=settings['R9_CNPJ_ACCOUNT_AGE_DAYS'])
    )
    if senders >= settings['R9_MIN_SENDERS'] and total >= settings['R9_MIN_TOTAL_CENTS'] and not old_cnpj:
        return 3, f"Destination received from {senders} payers, totaling {total} cents in 60 minutes."
    return None


def r10(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R10")
    if event_context(event):
        return None
    opening = (event.get("source_account") or {}).get("opening_date")
    amount = int(event["amount"])
    if opening is None or amount < settings['R10_MIN_AMOUNT_CENTS']:
        return None
    age = event_datetime(event) - _date(opening)
    if timedelta(0) <= age <= timedelta(days=settings['R10_MAX_ACCOUNT_AGE_DAYS']):
        history_count = int(profile.get("trusted_event_count", len(profile["trusted_history"])))
        points = 2 if history_count < settings['R10_PROFILE_EVENTS'] else 1
        return points, f"Payer account is {age.days} days old with {history_count} prior events."
    return None


def r11(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R11")
    if event_context(event):
        return None
    current_geo = source_data(event).get("geolocation")
    recent = window(profile["source_history"], event_datetime(event), timedelta(minutes=settings['R11_WINDOW_MINUTES']))
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
        if distance >= settings['R11_MIN_DISTANCE_KM'] and distance / hours > settings['R11_MIN_SPEED_KMH']:
            return 3, f"Impossible travel: {distance:.1f} km in {hours:.2f} hours."
    return None


def r12(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R12")
    if event_context(event):
        pairs = set(context.get("device_author_companies", ()))
        author_id = event_context(event).get("author_id")
        company_id = event_context(event).get("company_id")
        if author_id and company_id:
            pairs.add((author_id, company_id))
        authors = {author for author, _ in pairs}
        companies = {company for _, company in pairs}
        if len(authors) >= settings['R12_MIN_PAYER_DOCUMENTS'] and len(companies) >= settings['R12_MIN_COMPANIES']:
            return 2, "Device was used by at least three authors across different companies in 24 hours."
        return None
    owner_count = int(context.get("device_payer_count", 1))
    if owner_count >= settings['R12_MIN_PAYER_DOCUMENTS']:
        return 2, f"Device was used by {owner_count} payer documents in 24 hours."
    return None


def r28(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R28")
    amount = int(event["amount"])
    limit = int(profile.get("limit", settings['PROFILE_LIMIT_CENTS']))
    from math import ceil

    lower = ceil(limit * settings['R28_LOWER_LIMIT_RATIO'])
    if event_context(event) or not lower <= amount < limit:
        return None
    recent = [
        tx for tx in window(profile["source_history"], event_datetime(event), timedelta(hours=settings['R28_WINDOW_HOURS']))
        if lower <= int(tx["amount"]) < limit
    ]
    if len(recent) + 1 >= settings['R28_MIN_EVENTS']:
        return 2, f"At least three events fall in the 90%-to-100% band below limit {limit}."
    return None


def r29(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R29")
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
            tx for tx in window(profile["source_history"], event_datetime(event), timedelta(minutes=settings['R29_WINDOW_MINUTES']))
            if destination_document(payload(tx)) == destination_document(event)
        ]
        recent_count = len(recent)
        recent_total = sum(int(tx["amount"]) for tx in recent)
        prior = [
            tx for tx in profile["related_history"]
            if event_datetime(event) - transaction_datetime(tx) > timedelta(minutes=settings['R29_WINDOW_MINUTES'])
        ]
        prior_max = max((int(tx["amount"]) for tx in prior), default=0)
        prior_days = {transaction_datetime(tx).date() for tx in prior}
        mature_prior = (
            len(prior_days) >= settings['RECURRENT_DISTINCT_DAYS'] and bool(prior)
            and event_datetime(event) - min(transaction_datetime(tx) for tx in prior) >= timedelta(days=settings['RECURRENT_AGE_DAYS'])
        )
    total = int(event["amount"]) + recent_total
    exempt = mature_prior and prior_max > 0 and total <= prior_max * settings['R29_RECURRENT_EXEMPTION_FACTOR']
    if recent_count + 1 >= settings['R29_MIN_EVENTS'] and total >= profile["limit"] and not exempt:
        return 2, f"At least four transfers to one document total {total} cents in 60 minutes."
    return None


def r33(event: dict, profile: dict, context: dict) -> RuleResult:
    settings = context.get("rule_parameters") or params.for_rule("R33")
    if event_context(event) or profile["mature"] or profile["habitual"]:
        return None
    opening = (event.get("source_account") or {}).get("opening_date")
    if opening is None:
        return None
    age = event_datetime(event) - _date(opening)
    amount = int(event["amount"])
    if timedelta(days=settings['R33_MIN_ACCOUNT_AGE_DAYS']) < age and settings['R33_MIN_AMOUNT_CENTS'] <= amount < settings['PROFILE_LIMIT_CENTS']:
        return 1, "Cold-start value step for an established account without a mature profile."
    return None


def not_evaluated(event: dict, profile: dict, context: dict) -> list[dict]:
    """Missing-input diagnostics retained in response metadata."""
    missing = []
    opening = (event.get("destination_account") or {}).get("opening_date")
    if destination_document(event) != source_document(event) and opening is None:
        missing.append({"rule": "R6", "reason": "Destination opening date was not supplied."})
    if not event_context(event):
        r11_settings = params.for_rule("R11")
        recent = window(profile["source_history"], event_datetime(event), timedelta(minutes=r11_settings["R11_WINDOW_MINUTES"]))
        current_geo = source_data(event).get("geolocation")
        previous_geo = (payload(recent[-1]).get("source") or {}).get("geolocation") if recent else None
        if recent and (not isinstance(current_geo, dict) or not isinstance(previous_geo, dict)):
            missing.append({"rule": "R11", "reason": "A recent event exists, but one event has no geolocation."})
    epp = event_context(event)
    if epp and epp.get("event") == "request":
        r25_settings = params.for_rule("R25")
        r26_settings = params.for_rule("R26")
        inflows = epp.get("inflows_24h")
        inflow_median = epp.get("inflows_24h_median")
        if (
            not isinstance(inflows, (int, float)) or isinstance(inflows, bool)
            or not isinstance(inflow_median, (int, float)) or isinstance(inflow_median, bool)
            or inflow_median <= 0 or epp.get("last_inflow_at") is None
        ):
            missing.append({
                "rule": "R25",
                "reason": f"R25 needs inflows_24h, a positive {r25_settings['R25_BASELINE_DAYS']}-day inflows_24h_median and last_inflow_at.",
            })
        if (context.get("destination_document_activity") or {}).get("median_amount_total") is None:
            missing.append({
                "rule": "R26",
                "reason": f"The destination has fewer than {r26_settings['R26_MIN_BASELINE_DAYS']} active baseline windows for its 24-hour median.",
            })
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

