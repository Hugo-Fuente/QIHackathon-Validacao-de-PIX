from datetime import timedelta

import pytest
from pydantic import ValidationError

from rules.epp import r13, r14, r15, r16, r17, r18, r19, r20, r21, r22, r23, r24, r24_v3, r25, r26, r27, r30, r31, r32
from rules.registry import RULE_IMPLEMENTATION_REGISTRY
from schemas.pix_schema import OperationalProfileSchema
from tests.rule_support import NOW, epp_event, event, profile, transaction


def test_r13_three_requests_near_control_limit():
    history = [transaction(amount=990_000, minutes_ago=i, event_type="request", context={"author_id": "author-a"}) for i in (1, 2)]
    current = epp_event(amount=990_000, author_limit=1_000_000, approval_trigger=1_100_000)
    assert r13(current, profile(source_history=history), {})[0] == 2
    assert r13(epp_event(amount=899_999, author_limit=1_000_000), profile(source_history=history), {}) is None


def test_r14_recreation_of_other_partner_refusal_within_twenty_four_hours():
    current = epp_event(amount=100_000, refused_requests_24h=[{
        "refused_at": NOW - timedelta(hours=24), "amount": 100_000,
        "destination_document": "22222222222", "refused_by": "author-b",
    }])
    assert r14(current, profile(), {})[0] == 2
    current["context"]["refused_requests_24h"][0]["refused_by"] = "author-a"
    assert r14(current, profile(), {}) is None


def test_r15_vote_same_device_or_same_ip_under_ten_seconds():
    request = transaction(minutes_ago=1)
    request["payload"]["source"] = {"device_id": "shared", "ip": "10.1.1.1"}
    current = epp_event("vote")
    current["source"] = {"device_id": "shared", "ip": "192.0.2.2"}
    assert r15(current, profile(), {"request_event": request})[0] == 3
    current["source"] = {"device_id": "different", "ip": "10.1.1.1"}
    request["transaction_date"] = NOW - timedelta(seconds=9)
    assert r15(current, profile(), {"request_event": request})[0] == 3
    request["transaction_date"] = NOW - timedelta(seconds=10)
    assert r15(current, profile(), {"request_event": request}) is None


def test_r16_control_change_within_twenty_four_hours_on_mature_company():
    current = epp_event(control_loosened_at=NOW - timedelta(hours=24), account_activated_at=NOW - timedelta(days=7))
    assert r16(current, profile(), {})[0] == 3
    current["context"]["control_loosened_at"] = NOW - timedelta(hours=24, seconds=1)
    assert r16(current, profile(), {}) is None
    current["context"]["control_loosened_at"] = NOW - timedelta(hours=1)
    current["context"]["account_activated_at"] = NOW - timedelta(days=6)
    assert r16(current, profile(), {}) is None


def test_r17_new_author_device_requires_history_and_value_floor():
    history = [transaction(event_type="request", context={"author_id": "author-a"}, device=f"known-{i}") for i in range(3)]
    current = epp_event(amount=50_000)
    current["source"]["device_id"] = "new-device"
    assert r17(current, profile(trusted_history=history), {})[0] == 2
    assert r17(epp_event(amount=49_999), profile(trusted_history=history), {}) is None


def test_r18_author_impossible_travel():
    previous = transaction(minutes_ago=60, event_type="request", context={"author_id": "author-a"},
                           geolocation={"latitude": 0.0, "longitude": 0.0}, ip="10.1.1.1")
    current = epp_event()
    current["source"]["geolocation"] = {"latitude": 0.0, "longitude": 10.0}
    assert r18(current, profile(trusted_history=[previous]), {})[0] == 3
    previous["payload"]["source"].pop("geolocation")
    current["source"].pop("geolocation")
    assert r18(current, profile(trusted_history=[previous]), {}) is None


def test_r19_unusual_night_hour_after_ten_author_operations():
    night = NOW.replace(hour=5)  # 02:00 BRT
    current = epp_event(amount=100_000, origin="immediate")
    current["transaction_date"] = night
    history = [transaction(days_ago=i, event_type="request", context={"author_id": "author-a"}) for i in range(1, 11)]
    assert r19(current, profile(trusted_history=history), {})[0] == 1
    history[0]["transaction_date"] = night - timedelta(days=1)
    assert r19(current, profile(trusted_history=history), {}) is None


def test_r20_accumulated_free_balance_at_seventy_percent_and_reserved_exclusion():
    current = epp_event(amount=700_000, free_balance=1_000_000)
    assert r20(current, profile(), {})[0] == 2
    assert r20(epp_event(amount=699_999, free_balance=1_000_000), profile(), {}) is None
    assert r20(epp_event(amount=700_000, free_balance=1_000_000, responsibility_id="payroll"), profile(), {}) is None


def test_r21_recent_reserve_release_to_new_destination():
    current = epp_event(amount=80_000, reserved_amount_released=100_000,
                        reserved_released_at=NOW - timedelta(minutes=30))
    assert r21(current, profile(), {})[0] == 3
    current["context"]["reserved_released_at"] = NOW - timedelta(minutes=30, seconds=1)
    assert r21(current, profile(), {}) is None


def test_r22_partner_destination_needs_amount_floor_and_not_habitual():
    current = epp_event(amount=200_000, partner_documents=["22222222222"])
    assert r22(current, profile(), {})[0] == 1
    assert r22(epp_event(amount=199_999, partner_documents=["22222222222"]), profile(), {}) is None
    assert r22(current, profile(recurrent=True, max_related_amount=200_000), {}) is None


def test_r23_new_counterparty_for_established_responsibility():
    history = [transaction(days_ago=i, event_type="request", context={"responsibility_id": "tax"},
                           dest_doc=f"old-{i % 2}") for i in range(1, 6)]
    current = epp_event(amount=100_000, responsibility_id="tax")
    assert r23(current, profile(trusted_history=history), {})[0] == 1
    assert r23(epp_event(amount=99_999, responsibility_id="tax"), profile(trusted_history=history), {}) is None


def test_r24_new_company_outflow_has_one_or_two_points_by_amount():
    current = epp_event(amount=500_000, account_activated_at=NOW - timedelta(days=30))
    assert r24(current, profile(outgoing_count=10), {})[0] == 1
    assert r24(epp_event(amount=2_000_000, account_activated_at=NOW - timedelta(days=30)), profile(), {})[0] == 2
    self_payment = epp_event(amount=500_000, account_activated_at=NOW - timedelta(days=30))
    self_payment["destination_account"]["owner"]["document_number"] = "11111111111"
    assert r24(self_payment, profile(), {}) is None


def _operational_profile(*, evidence_age_days=30, operation_type="operating_expenses"):
    evidence = [
        {
            "kind": kind,
            "reference_id": f"verification-{kind}",
            "source": f"registry-{kind}",
            "observed_value": {
                "company_size": "small",
                "monthly_revenue": 5_000_000,
                "employee_count": 18,
            }[kind],
            "verified_at": (NOW - timedelta(days=evidence_age_days)).isoformat(),
        }
        for kind in ("company_size", "monthly_revenue", "employee_count")
    ]
    return {
        "profile_id": "profile-a",
        "version": 1,
        "operation_type": operation_type,
        "status": "active",
        "company_id": "company-a",
        "responsibility_id": "operating-expenses",
        "company_size": "small",
        "monthly_revenue_cents": 5_000_000,
        "employee_count": 18,
        "evidence": evidence,
        "max_payment_cents": 600_000,
        "max_batch_cents": 1_000_000,
        "approvals": [
            {"partner_id": "partner-a", "approved_at": (NOW - timedelta(days=1)).isoformat()},
            {"partner_id": "partner-b", "approved_at": (NOW - timedelta(days=1)).isoformat()},
        ],
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
    }


def test_r24_v3_accepts_verified_profile_for_scheduled_operating_expense():
    operation = _operational_profile()
    OperationalProfileSchema.model_validate(operation)
    current = epp_event(
        amount=500_000,
        origin="scheduled",
        account_activated_at=NOW - timedelta(days=10),
        responsibility_id="operating-expenses",
        operational_profile=operation,
        beneficiary_authorized=True,
        batch_id="batch-a",
        batch_total_cents=500_000,
    )
    assert r24_v3(current, profile(), {}) is None


def test_active_ruleset_registers_r24_v3():
    assert RULE_IMPLEMENTATION_REGISTRY["R24"]["v3"] is r24_v3


def test_r24_v3_fails_closed_when_operational_evidence_is_missing_or_stale():
    missing = _operational_profile()
    missing.pop("evidence")
    with pytest.raises(ValidationError):
        OperationalProfileSchema.model_validate(missing)

    stale = _operational_profile(evidence_age_days=91)
    current = epp_event(
        amount=500_000,
        origin="scheduled",
        account_activated_at=NOW - timedelta(days=10),
        responsibility_id="operating-expenses",
        operational_profile=stale,
        beneficiary_authorized=True,
        batch_id="batch-a",
        batch_total_cents=500_000,
    )
    assert r24_v3(current, profile(), {})[0] == 1


def test_r24_v3_revalidates_profile_and_exact_payment_on_execution():
    operation = _operational_profile()
    request = epp_event(
        amount=500_000,
        origin="scheduled",
        account_activated_at=NOW - timedelta(days=10),
        responsibility_id="operating-expenses",
        operational_profile=operation,
        beneficiary_authorized=True,
        batch_id="batch-a",
        batch_total_cents=500_000,
        request_hash="request-hash",
    )
    current = epp_event(
        "execution",
        amount=500_000,
        origin="scheduled",
        account_activated_at=NOW - timedelta(days=10),
        responsibility_id="operating-expenses",
        request_id="request-a",
        request_hash="request-hash",
        operational_profile_ref={"profile_id": "profile-a", "version": 1, "status": "active"},
        batch_id="batch-a",
        batch_total_cents=500_000,
    )
    request["id"] = "request-a"
    wrapper = {"id": "request-a", "payload": request}
    context = {"request_event": wrapper, "request_status": "approved", "has_prior_execution": False}
    assert r24_v3(current, profile(), context) is None

    current["amount"] = 500_001
    assert r24_v3(current, profile(), context)[0] == 1


def test_r24_v3_rejects_evidence_that_does_not_match_claimed_values():
    operation = _operational_profile()
    operation["evidence"][1]["observed_value"] = 50_000_000
    current = epp_event(
        amount=500_000,
        origin="scheduled",
        account_activated_at=NOW - timedelta(days=10),
        responsibility_id="operating-expenses",
        operational_profile=operation,
        beneficiary_authorized=True,
        batch_id="batch-a",
        batch_total_cents=500_000,
    )
    assert r24_v3(current, profile(), {})[0] == 1


def test_r25_external_inflow_to_new_destination_within_two_hours():
    current = epp_event(amount=800_000, inflows_24h=1_000_000, inflows_24h_median=300_000,
                        last_inflow_at=NOW - timedelta(hours=2),
                        account_activated_at=NOW - timedelta(days=90))
    assert r25(current, profile(), {"recent_payer_count": 1})[0] == 3
    current["context"]["last_inflow_at"] = NOW - timedelta(hours=2, seconds=1)
    assert r25(current, profile(), {"recent_payer_count": 1}) is None


def test_r26_four_companies_and_three_times_destination_median():
    current = epp_event(amount=500_000)
    stats = {
        "company_count": 3,
        "amount_total": 500_000,
        "current_company_present": False,
        "median_amount_total": 300_000,
    }
    assert r26(current, profile(), {"destination_document_activity": stats})[0] == 3
    stats["median_amount_total"] = 400_000
    assert r26(current, profile(), {"destination_document_activity": stats}) is None


def test_r27_zero_point_linked_partner_alert():
    current = epp_event(partner_documents=["33333333333"])
    assert r27(current, profile(), {"partner_company_counts": {"33333333333": 3}}) == (0, "Partner document 33333333333 is associated with at least three active companies.")


def test_r30_thirty_day_company_age_and_three_times_daily_average():
    baseline = [transaction(amount=10_000_000, days_ago=day) for day in range(2, 12)]
    p = profile(source_history=baseline, outgoing_count=10)
    current = epp_event(amount=9_310_344, account_activated_at=NOW - timedelta(days=30))
    assert r30(current, p, {}) is None
    current["amount"] = 9_310_345
    assert r30(current, p, {})[0] == 2
    current["context"]["account_activated_at"] = NOW - timedelta(days=29)
    assert r30(current, p, {}) is None


def test_r31_linked_destination_exempts_recurring_value_within_twenty_percent():
    current = epp_event(amount=240_000, partner_documents=["22222222222"],
                        destination_partner_documents=["22222222222"])
    p = profile(recurrent=True, max_related_amount=200_000)
    assert r31(current, p, {}) is None
    current["amount"] = 240_001
    assert r31(current, p, {})[0] == 2


def test_r32_credential_change_window_is_twenty_four_hours():
    current = epp_event(amount=200_000, origin="immediate", credential_changed_at=NOW - timedelta(hours=23))
    assert r32(current, profile(), {})[0] == 2
    current["context"]["credential_changed_at"] = NOW - timedelta(hours=25)
    assert r32(current, profile(), {}) is None
