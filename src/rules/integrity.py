"""Pure integrity check C1 for EPP votes and executions."""

from rules.common import event_context, payload
from rules.operational_profile import same_payment


def c1(event: dict, profile: dict, context: dict) -> tuple[int, str] | None:
    event_context = event.get("context") or {}
    if event_context.get("event") not in ("vote", "execution"):
        return None

    request = context.get("request_event")
    request_status = context.get("request_status")
    if request is None:
        return 0, "Referenced request does not exist."

    request_payload = request.get("payload") or request
    original_context = request_payload.get("context") or {}
    if original_context.get("event") != "request" or request_status in (None, "rejected"):
        return 0, "Referenced request is missing, invalid, or rejected."
    if original_context.get("request_hash") != event_context.get("request_hash"):
        return 0, "Request hash differs from the stored request."
    if event_context.get("event") == "execution" and context.get("has_prior_execution"):
        return 0, "This request already has a non-rejected execution."
    return None


def c1_v2(event: dict, profile: dict, context: dict) -> tuple[int, str] | None:
    """C1 also confirms the execution repeats the stored payment exactly."""
    result = c1(event, profile, context)
    if result is not None:
        return result
    if event_context(event).get("event") != "execution":
        return None
    request = context.get("request_event")
    if request is None or not same_payment(event, payload(request)):
        return 0, "Execution amount, payer account, destination document, or destination account differs from the stored request."
    return None

