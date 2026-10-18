"""Pure EPP-specific rules: R13–R27 and R30–R32."""

from collections import defaultdict
from datetime import timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from rules import params
from rules.common import (
    context_of, destination_document, destination_key, event_context,
    distance_km, event_datetime, event_type, ip_country, is_outflow,
    is_scheduled_execution, payload, recurrent, source_data, source_document, transaction_datetime,
    window,
)

RuleResult = tuple[int, str] | None
BRAZIL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def r13(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    if epp.get("event") != "request":
        return None
    limits = [
        value for value in (epp.get("author_limit"), epp.get("approval_trigger"))
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    if not limits:
        return None
    ceiling = min(limits)
    lower = ceiling * params.R13_LOWER_LIMIT_RATIO
    upper = ceiling * params.R13_UPPER_LIMIT_RATIO
    author_id = epp.get("author_id")
    requests = [
        tx for tx in window(profile["source_history"], event_datetime(event), timedelta(hours=params.R13_WINDOW_HOURS))
        if event_type(tx) == "request" and context_of(tx).get("author_id") == author_id
        and lower <= int(tx["amount"]) <= upper
    ]
    if lower <= int(event["amount"]) <= upper and len(requests) + 1 >= params.R13_MIN_EVENTS and not profile["habitual"]:
        return 2, f"Author repeated values immediately below the {ceiling}-cent control limit."
    return None


def r14(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    if epp.get("event") != "request":
        return None
    current_date = event_datetime(event)
    amount = int(event["amount"])
    for refusal in epp.get("refused_requests_24h") or []:
        if not isinstance(refusal, dict):
            continue
        try:
            age = current_date - _date(refusal["refused_at"])
            refused_amount = int(refusal["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        same_destination = refusal.get("destination_document") == destination_document(event)
        refused_by_other = refusal.get("refused_by") != epp.get("author_id")
        if (
            same_destination and refused_by_other
            and timedelta(0) <= age <= timedelta(hours=params.R14_WINDOW_HOURS)
            and refused_amount * params.R14_MIN_AMOUNT_RATIO <= amount <= refused_amount * params.R14_MAX_AMOUNT_RATIO
        ):
            return 2, "Request recreates a similar payment refused by another partner in the last 24 hours."
    return None


def r15(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    if epp.get("event") != "vote":
        return None
    request = context.get("request_event")
    if not request:
        return None
    original = payload(request)
    original_source = original.get("source") or {}
    current_source = source_data(event)
    same_device = bool(current_source.get("device_id")) and current_source.get("device_id") == original_source.get("device_id")
    same_ip_fast = False
    if current_source.get("ip") and current_source.get("ip") == original_source.get("ip"):
        elapsed = event_datetime(event) - transaction_datetime(request)
        same_ip_fast = timedelta(0) <= elapsed < timedelta(seconds=params.R15_MAX_VOTE_SECONDS)
    if same_device or same_ip_fast:
        return 3, "Vote used the request author's device or same IP within ten seconds."
    return None


def r16(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    loosened = epp.get("control_loosened_at")
    activated = epp.get("account_activated_at")
    if epp.get("event") != "request" or not loosened or not activated:
        return None
    current_date = event_datetime(event)
    company_age = current_date - _date(activated)
    elapsed = current_date - _date(loosened)
    if company_age >= timedelta(days=params.R16_MIN_COMPANY_AGE_DAYS) and timedelta(0) <= elapsed <= timedelta(hours=params.R16_WINDOW_HOURS):
        return 3, "Company controls were loosened within 24 hours before this request."
    return None


def _author_requests(event: dict, profile: dict) -> list[dict]:
    author = event_context(event).get("author_id")
    requests = [
        tx for tx in profile["trusted_history"]
        if event_type(tx) == "request" and context_of(tx).get("author_id") == author
    ]
    return sorted(requests, key=transaction_datetime)


def r17(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    author_requests = _author_requests(event, profile)
    if epp.get("event") != "request" or len(author_requests) < params.R17_MIN_HISTORY or int(event["amount"]) < params.R17_MIN_AMOUNT_CENTS:
        return None
    known_devices = {
        (payload(tx).get("source") or {}).get("device_id")
        for tx in author_requests[-params.PROFILE_SAMPLE_SIZE:]
    }
    device_id = source_data(event).get("device_id")
    if device_id and device_id not in known_devices:
        return 2, "Partner used a device absent from their last 20 requests."
    return None


def r18(event: dict, profile: dict, context: dict) -> RuleResult:
    if event_context(event).get("event") != "request":
        return None
    requests = _author_requests(event, profile)
    if not requests:
        return None
    previous = requests[-1]
    old_source = (payload(previous).get("source") or {})
    current_source = source_data(event)
    elapsed_hours = (event_datetime(event) - transaction_datetime(previous)).total_seconds() / 3600
    if not 0 < elapsed_hours <= params.R18_WINDOW_HOURS:
        return None
    old_geo, current_geo = old_source.get("geolocation"), current_source.get("geolocation")
    if isinstance(old_geo, dict) and isinstance(current_geo, dict):
        distance = distance_km(
            float(old_geo["latitude"]), float(old_geo["longitude"]),
            float(current_geo["latitude"]), float(current_geo["longitude"]),
        )
        if distance >= params.R18_MIN_DISTANCE_KM and distance / elapsed_hours > params.R18_MIN_SPEED_KMH:
            return 3, f"Partner travelled {distance:.1f} km in {elapsed_hours:.2f} hours."
    elif ip_country(old_source.get("ip")) and ip_country(current_source.get("ip")) and ip_country(old_source.get("ip")) != ip_country(current_source.get("ip")):
        return 3, "Partner IP changed to a different country within 12 hours."
    return None


def r19(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    amount = int(event["amount"])
    if epp.get("event") != "request" or epp.get("origin") != "immediate" or amount < params.R19_MIN_AMOUNT_CENTS:
        return None
    author_requests = _author_requests(event, profile)
    local_date = event_datetime(event).astimezone(BRAZIL_TIMEZONE)
    if not params.R19_START_HOUR <= local_date.hour < params.R19_END_HOUR or len(author_requests) < params.R19_MIN_HISTORY:
        return None
    had_night_activity = any(
        params.R19_START_HOUR <= transaction_datetime(tx).astimezone(BRAZIL_TIMEZONE).hour < params.R19_END_HOUR
        for tx in author_requests
    )
    if not had_night_activity:
        return 1, "Partner requested an immediate payment between midnight and 05:00 BRT despite no prior overnight activity."
    return None


def r20(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    free_balance = epp.get("free_balance")
    if (
        epp.get("event") != "request" or epp.get("responsibility_id")
        or not isinstance(free_balance, (int, float)) or isinstance(free_balance, bool) or free_balance <= 0
    ):
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        previous_total = int(metrics.get("r20_sum", 0))
    else:
        previous = [
            tx for tx in window(profile["source_history"], event_datetime(event), timedelta(hours=params.R20_WINDOW_HOURS))
            if not context_of(tx).get("responsibility_id") and not is_scheduled_execution(context_of(tx))
        ]
        previous_total = sum(int(tx["amount"]) for tx in previous)
    total = int(event["amount"]) + previous_total
    initial_balance = int(free_balance) + previous_total
    if total >= params.R20_MIN_TOTAL_CENTS and total >= initial_balance * params.R20_MIN_BALANCE_RATIO:
        return 2, f"Free-balance outflow is {total} cents, at least 70% of {initial_balance} cents."
    return None


def r21(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    released = epp.get("reserved_amount_released")
    released_at = epp.get("reserved_released_at")
    if epp.get("event") != "request" or not released or not released_at:
        return None
    elapsed = event_datetime(event) - _date(released_at)
    known_destination = any(
        destination_document(payload(tx)) == destination_document(event)
        for tx in profile["trusted_history"]
    )
    if (
        int(event["amount"]) >= int(released * params.R21_MIN_RELEASED_RATIO)
        and timedelta(0) <= elapsed <= timedelta(minutes=params.R21_WINDOW_MINUTES)
        and not known_destination
    ):
        return 3, "At least 80% of a recently released reserve is being sent to a new counterparty."
    return None


def r22(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    amount = int(event["amount"])
    if epp.get("event") != "request" or amount < params.R22_MIN_AMOUNT_CENTS:
        return None
    partners = {str(value) for value in epp.get("partner_documents", [])}
    if destination_document(event) not in partners:
        return None
    maximum = profile["max_related_amount"]
    habitual = profile["recurrent"] and maximum > 0 and maximum * params.HABITUAL_MIN_FACTOR <= amount <= maximum * params.HABITUAL_AMOUNT_FACTOR
    if not habitual:
        return 1, "Payment destination is a partner's document."
    return None


def r23(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    responsibility = epp.get("responsibility_id")
    if epp.get("event") != "request" or not responsibility or int(event["amount"]) < params.R23_MIN_AMOUNT_CENTS:
        return None
    current_destination = destination_key(event)
    metrics = context.get("source_metrics")
    if metrics is not None and "r23_event_count" in metrics:
        history_count = int(metrics.get("r23_event_count", 0))
        destination_count = int(metrics.get("r23_destination_count", 0))
        destination_seen = bool(metrics.get("r23_current_destination_present"))
    else:
        history = [
            tx for tx in profile["trusted_history"]
            if context_of(tx).get("responsibility_id") == responsibility
            and event_type(tx) == "request"
            and event_datetime(event) - transaction_datetime(tx) <= timedelta(days=params.R23_WINDOW_DAYS)
        ]
        destinations = {destination_key(payload(tx)) for tx in history}
        history_count = len(history)
        destination_count = len(destinations)
        destination_seen = current_destination in destinations
    if (
        history_count >= params.R23_MIN_RESPONSIBILITY_EVENTS
        and destination_count <= params.R23_MAX_DESTINATIONS
        and not destination_seen
    ):
        return 1, "Established payment responsibility is sending to a new destination."
    return None


def r24(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    amount = int(event["amount"])
    if (
        epp.get("event") == "vote"
        or destination_document(event) == source_document(event)
        or amount < params.R24_SMALL_CENTS
    ):
        return None
    activated = epp.get("account_activated_at")
    if activated:
        company_age = event_datetime(event) - _date(activated)
        immature = company_age <= timedelta(days=params.R24_MATURE_AGE_DAYS) or profile["outgoing_count"] < params.R24_MATURE_OUTFLOWS
    else:
        immature = True
    if immature:
        points = 2 if amount >= params.R24_LARGE_CENTS else 1
        return points, f"Company is immature with {profile['outgoing_count']} prior outflows; amount is {amount} cents."
    return None


def r25(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    inflows = epp.get("inflows_24h")
    last_inflow = epp.get("last_inflow_at")
    amount = int(event["amount"])
    if epp.get("event") != "request" or not isinstance(inflows, (int, float)) or not last_inflow or amount < params.R25_MIN_OUTFLOW_CENTS:
        return None
    elapsed = event_datetime(event) - _date(last_inflow)
    known_destination = any(
        destination_document(payload(tx)) == destination_document(event)
        for tx in profile["trusted_history"]
    )
    activated = epp.get("account_activated_at")
    young = activated is not None and event_datetime(event) - _date(activated) <= timedelta(days=params.R25_MAX_COMPANY_AGE_DAYS)
    only_new_payers = int(context.get("recent_payer_count", 0)) <= 1
    if (
        inflows >= params.R25_MIN_INFLOW_CENTS
        and amount >= inflows * params.R25_MIN_OUTFLOW_RATIO
        and timedelta(0) <= elapsed <= timedelta(hours=params.R25_MAX_INFLOW_AGE_HOURS)
        and not known_destination and (young or only_new_payers)
    ):
        return 3, "At least 80% of recent external inflows are leaving for a new destination within two hours."
    return None


def r26(event: dict, profile: dict, context: dict) -> RuleResult:
    if event_context(event).get("event") != "request":
        return None
    activity = context.get("destination_document_activity", {})
    company_count = int(activity.get("company_count", 0)) + (
        1 if event_context(event).get("company_id") and not activity.get("current_company_present") else 0
    )
    total = int(event["amount"]) + int(activity.get("amount_total", 0))
    if company_count >= params.R26_MIN_COMPANIES and total >= params.R26_MIN_TOTAL_CENTS and not profile["recurrent"]:
        return 3, f"Destination received from {company_count} companies, totaling {total} cents in 24 hours."
    return None


def r27(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    if epp.get("event") != "request":
        return None
    companies = context.get("partner_company_counts", {})
    for partner in {str(value) for value in epp.get("partner_documents", [])}:
        if int(companies.get(partner, 0)) >= params.R27_MIN_COMPANIES:
            return 0, f"Partner document {partner} is associated with at least three active companies."
    return None


def r30(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    if (
        epp.get("event") != "request"
        or epp.get("responsibility_id")
        or not epp.get("account_activated_at")
    ):
        return None
    event_date = event_datetime(event)
    company_age = event_date - _date(epp["account_activated_at"])
    if company_age < timedelta(days=params.R30_MIN_COMPANY_AGE_DAYS) or profile["outgoing_count"] < params.R30_MIN_HISTORY_OUTFLOWS:
        return None
    metrics = context.get("source_metrics")
    if metrics is not None:
        if int(metrics.get("r30_baseline_count", 0)) < params.R30_MIN_HISTORY_OUTFLOWS:
            return None
        trimmed_average = (
            int(metrics.get("r30_daily_sum", 0)) - int(metrics.get("r30_daily_max", 0))
        ) / params.R30_BASELINE_DIVISOR
        total = int(event["amount"]) + int(metrics.get("r30_recent_sum", 0))
    else:
        baseline_events = [
            tx for tx in profile["source_history"]
            if timedelta(hours=params.R30_RECENT_WINDOW_HOURS) < event_date - transaction_datetime(tx) <= timedelta(days=params.R30_BASELINE_DAYS + 1)
            and is_outflow(tx) and not context_of(tx).get("responsibility_id")
            and not is_scheduled_execution(context_of(tx))
        ]
        if len(baseline_events) < params.R30_MIN_HISTORY_OUTFLOWS:
            return None
        daily_totals: dict[object, int] = defaultdict(int)
        for transaction in baseline_events:
            daily_totals[transaction_datetime(transaction).date()] += int(transaction["amount"])
        trimmed_average = (sum(daily_totals.values()) - max(daily_totals.values())) / params.R30_BASELINE_DIVISOR
        recent = [
            tx for tx in window(profile["source_history"], event_date, timedelta(hours=params.R30_RECENT_WINDOW_HOURS))
            if is_outflow(tx) and not context_of(tx).get("responsibility_id")
            and not is_scheduled_execution(context_of(tx))
        ]
        total = int(event["amount"]) + sum(int(tx["amount"]) for tx in recent)
    if total >= params.R30_MIN_TOTAL_CENTS and total >= params.R30_BASELINE_MULTIPLIER * trimmed_average and not profile["habitual"]:
        return 2, f"Company outflow {total} cents exceeds three times its trimmed daily average."
    return None


def r31(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    amount = int(event["amount"])
    if epp.get("event") != "request" or amount < params.R31_MIN_AMOUNT_CENTS:
        return None
    company_partners = {str(value) for value in epp.get("partner_documents", [])}
    destination_partners = {str(value) for value in epp.get("destination_partner_documents", [])}
    if not company_partners.intersection(destination_partners):
        return None
    maximum = profile["max_related_amount"]
    recurring = profile["recurrent"] and maximum > 0 and maximum * params.HABITUAL_MIN_FACTOR <= amount <= maximum * params.HABITUAL_AMOUNT_FACTOR
    if not recurring:
        return 2, "Destination is linked to a partner of the paying company."
    return None


def r32(event: dict, profile: dict, context: dict) -> RuleResult:
    epp = event_context(event)
    changed = epp.get("credential_changed_at")
    if epp.get("event") != "request" or epp.get("origin") != "immediate" or int(event["amount"]) < params.R32_MIN_AMOUNT_CENTS or not changed:
        return None
    elapsed = event_datetime(event) - _date(changed)
    created = epp.get("credential_created_at")
    recent_credential = created and event_datetime(event) - _date(created) < timedelta(days=params.R32_NEW_CREDENTIAL_DAYS)
    if timedelta(0) <= elapsed <= timedelta(hours=params.R32_WINDOW_HOURS) and not recent_credential:
        return 2, "An immediate payment of at least R$2,000 followed a credential change within 24 hours."
    return None


def _date(value):
    from rules.common import parse_datetime
    return parse_datetime(value)


EPP_RULES: tuple[Callable[[dict, dict, dict], RuleResult], ...] = (
    r13, r14, r15, r16, r17, r18, r19, r20, r21, r22, r23, r24, r25, r26, r27, r30, r31, r32,
)

