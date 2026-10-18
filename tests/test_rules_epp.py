from datetime import timedelta

from rules.epp import r13, r14, r15, r16, r17, r18, r19, r20, r21, r22, r23, r24, r25, r26, r27, r30, r31, r32
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
