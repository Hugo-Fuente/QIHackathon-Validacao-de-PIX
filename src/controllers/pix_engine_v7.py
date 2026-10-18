"""Pure orchestration of RFC v7 Pix rules.

Persistence, locks and SQL stay in PixController/PixRepository. The engine
accepts the event and the plain-data history snapshot prepared by the repo.
"""

from rules.combine import combine_hits, status_for_score
from rules.common import distance_km, event_context
from rules.epp import EPP_RULES
from history_snapshot import PixHistory
from rules.integrity import c1
from rules.pix_core import CORE_RULES, not_evaluated

RULES_VERSION = "v7"
NOTIFY_RULES = {"R15", "R16", "R20", "R21", "R22", "R30", "R31", "R32", "C1"}


def process_transaction_v7(input_data: dict, history: PixHistory) -> dict:
    """Evaluate the event using only the repository's immutable history snapshot."""
    profile = _build_profile(input_data, history)
    evaluation_context = {
        "destination_account_activity": history.destination_account_activity,
        "device_payer_count": history.device_payer_count,
        "device_author_companies": set(history.device_author_companies),
        "recent_payer_count": history.recent_payer_count,
        "destination_document_activity": history.destination_document_activity,
        "partner_company_counts": history.partner_company_counts,
        "request_event": history.request_event,
        "request_status": history.request_status,
        "has_prior_execution": history.has_prior_execution,
        "source_metrics": history.source_metrics,
        "seen_destination_account": history.seen_destination_account,
    }

    results = []
    epp = event_context(input_data)
    rule_functions = ([c1] if epp else []) + list(CORE_RULES)
    if epp:
        rule_functions.extend(EPP_RULES)
    for rule in rule_functions:
        outcome = rule(input_data, profile, evaluation_context)
        if outcome is None:
            continue
        points, detail = outcome
        code = "C1" if rule is c1 else rule.__name__.upper()
        if not any(hit["code"] == code for hit in results):
            results.append({"code": code, "points": points, "detail": detail})

    if any(hit["code"] == "R23" for hit in results):
        results = [hit for hit in results if hit["code"] != "R5"]

    risk_score = combine_hits(results)
    status = status_for_score(risk_score, results)
    actions = (
        ["notify_all_partners_mobile"]
        if epp and status != "approved" and ({hit["code"] for hit in results} & NOTIFY_RULES)
        else []
    )
    reasons = [
        {"code": hit["code"], "rule": hit["code"], "points": hit["points"], "detail": hit["detail"]}
        for hit in results
    ]
    metadata = {
        "risk_score": risk_score,
        "reasons": reasons,
        "rules_version": RULES_VERSION,
        "recommended_actions": actions,
        "not_evaluated": not_evaluated(input_data, profile, evaluation_context),
    }
    return {"status": status, "risk_score": risk_score, "metadata": metadata, "rule_hits": results}


def _build_profile(event: dict, history: PixHistory) -> dict:
    import statistics
    from datetime import timedelta

    from rules import params
    from rules.common import (
        destination_document,
        event_datetime,
        recurrent,
        transaction_datetime,
    )

    source_document = str(((event.get("source_account") or {}).get("owner") or {}).get("document_number", ""))
    source_history = list(history.source_events)
    trusted_history = list(history.trusted_events)
    successful_profile = [
        tx for tx in trusted_history if tx.get("destination_document") != source_document
    ][-params.PROFILE_SAMPLE_SIZE:]
    values = [int(tx["amount"]) for tx in successful_profile]
    median_amount = (
        history.profile_median
        if history.profile_median is not None
        else statistics.median(values) if values else 0
    )
    successful_profile_count = int(history.successful_profile_count or len(successful_profile))
    mature = (
        successful_profile_count >= params.PROFILE_MATURE_COUNT
        and len({transaction_datetime(tx).date() for tx in successful_profile}) >= params.PROFILE_MATURE_DAYS
        and event_datetime(event) - transaction_datetime(successful_profile[0]) >= timedelta(days=params.PROFILE_MATURE_AGE_DAYS)
    )
    limit = params.PROFILE_LIMIT_CENTS
    if mature:
        from math import ceil

        limit = max(limit, ceil(params.PROFILE_LIMIT_MULTIPLIER * median_amount))
    related_history, recurrent_counterparty = recurrent(
        trusted_history, destination_document(event), event_datetime(event)
    )
    max_related_amount = max((int(tx["amount"]) for tx in related_history), default=0)
    habitual = (
        recurrent_counterparty and max_related_amount > 0
        and int(event["amount"]) <= max_related_amount * params.HABITUAL_AMOUNT_FACTOR
    )
    return {
        "source_history": source_history,
        "trusted_history": trusted_history,
        "successful_profile": successful_profile,
        "median_amount": median_amount,
        "mature": mature,
        "limit": limit,
        "related_history": related_history,
        "recurrent": recurrent_counterparty,
        "max_related_amount": max_related_amount,
        "habitual": habitual,
        "outgoing_count": history.source_event_count or len(source_history),
        "trusted_event_count": history.trusted_event_count or len(trusted_history),
        "successful_profile_count": successful_profile_count,
    }


# Kept as a public helper for callers that used the former engine utility.
_distance_km = distance_km
