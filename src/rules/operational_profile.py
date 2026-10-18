"""Pure checks for trusted, pre-approved EPP operating profiles."""

from datetime import timedelta

from rules.common import (
    context_of,
    destination_document,
    destination_key,
    event_context,
    event_datetime,
    payload,
    source_document,
)
from utils.pix_data import parse_datetime


def authorized_payroll_profile(event: dict, context: dict, settings: dict) -> dict | None:
    """Return audit metadata when this scheduled payroll payment fits its approved profile.

    The EPP is the authority for profile enrollment, approval quorum and beneficiary-roster
    membership. Its authenticated context is persisted with the request for later replay.
    """
    epp = event_context(event)
    event_type = epp.get("event")
    if epp.get("origin") != "scheduled":
        return None

    if event_type == "request":
        profile = epp.get("operational_profile")
        if not _profile_is_valid(event, epp, profile, settings, event_datetime(event)):
            return None
        return _audit_profile(profile, epp)

    if event_type != "execution":
        return None

    request = context.get("request_event")
    request_status = context.get("request_status")
    if request is None or request_status in (None, "rejected") or context.get("has_prior_execution"):
        return None

    original = payload(request)
    original_context = context_of(request)
    profile = original_context.get("operational_profile")
    reference = epp.get("operational_profile_ref")
    if (
        original_context.get("event") != "request"
        or original_context.get("origin") != "scheduled"
        or not isinstance(reference, dict)
        or reference.get("status") != "active"
    ):
        return None
    if not same_payment(event, original):
        return None
    if epp.get("request_id") != request.get("id"):
        return None
    if epp.get("request_hash") != original_context.get("request_hash"):
        return None
    if epp.get("company_id") != original_context.get("company_id"):
        return None
    if epp.get("responsibility_id") != original_context.get("responsibility_id"):
        return None
    if not _profile_reference_matches(reference, profile):
        return None
    if epp.get("batch_id") != original_context.get("batch_id"):
        return None
    if epp.get("batch_total_cents") != original_context.get("batch_total_cents"):
        return None
    if not _profile_is_valid(event, original_context, profile, settings, event_datetime(event)):
        return None
    return _audit_profile(profile, original_context)


def _profile_is_valid(event: dict, epp: dict, profile: object, settings: dict, at) -> bool:
    if not isinstance(profile, dict):
        return False
    profile_id = profile.get("profile_id")
    version = profile.get("version")
    if (
        not isinstance(profile_id, str) or not profile_id.strip()
        or type(version) is not int or version < 1
        or profile.get("operation_type") != "payroll"
        or profile.get("status") != "active"
        or profile.get("company_id") != epp.get("company_id")
        or not epp.get("company_id")
        or profile.get("responsibility_id") != epp.get("responsibility_id")
        or not epp.get("responsibility_id")
        or epp.get("beneficiary_authorized") is not True
    ):
        return False

    max_payment = profile.get("max_payment_cents")
    max_batch = profile.get("max_batch_cents")
    batch_total = epp.get("batch_total_cents")
    amount = event.get("amount")
    if any(type(value) is not int or value <= 0 for value in (max_payment, max_batch, batch_total, amount)):
        return False
    if amount > max_payment or not amount <= batch_total <= max_batch:
        return False
    if not isinstance(epp.get("batch_id"), str) or not epp["batch_id"].strip():
        return False

    approver_ids: set[str] = set()
    approved_at = []
    approvals = profile.get("approvals")
    if not isinstance(approvals, list):
        return False
    try:
        for approval in approvals:
            if not isinstance(approval, dict):
                return False
            partner_id = approval.get("partner_id")
            if not isinstance(partner_id, str) or not partner_id.strip() or partner_id in approver_ids:
                return False
            timestamp = parse_datetime(approval["approved_at"])
            if timestamp > at or at - timestamp > timedelta(days=settings["R24_OPERATIONAL_PROFILE_MAX_AGE_DAYS"]):
                return False
            approver_ids.add(partner_id)
            approved_at.append(timestamp)
        expires_at = parse_datetime(profile["expires_at"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False

    author_id = epp.get("author_id")
    if (
        len(approver_ids) < settings["R24_OPERATIONAL_PROFILE_MIN_APPROVERS"]
        or not author_id or author_id in approver_ids
        or not approved_at or expires_at <= at
        or expires_at > min(approved_at) + timedelta(days=settings["R24_OPERATIONAL_PROFILE_MAX_AGE_DAYS"])
    ):
        return False
    return True


def _profile_reference_matches(reference: dict, profile: object) -> bool:
    return (
        isinstance(profile, dict)
        and reference.get("profile_id") == profile.get("profile_id")
        and type(reference.get("version")) is int
        and reference.get("version") == profile.get("version")
    )


def same_payment(current: dict, original: dict) -> bool:
    try:
        current_source = current.get("source_account") or {}
        original_source = original.get("source_account") or {}
        return (
            int(current["amount"]) == int(original["amount"])
            and source_document(current) == source_document(original)
            and tuple(str(current_source.get(key, "")) for key in ("branch", "account_number"))
            == tuple(str(original_source.get(key, "")) for key in ("branch", "account_number"))
            and destination_document(current) == destination_document(original)
            and destination_key(current) == destination_key(original)
        )
    except (KeyError, TypeError, ValueError):
        return False


def _audit_profile(profile: dict, epp: dict) -> dict:
    return {
        "profile_id": profile["profile_id"],
        "version": profile["version"],
        "operation_type": profile["operation_type"],
        "responsibility_id": profile["responsibility_id"],
        "batch_id": epp["batch_id"],
        "batch_total_cents": epp["batch_total_cents"],
        "r24_exempt": True,
    }
