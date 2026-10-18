from datetime import timedelta

from rules.pix_core import (
    r1, r2, r3, r4, r5, r6, r7, r8, r9, r10, r11, r12, r28, r29, r33,
)
from tests.rule_support import NOW, event, profile, transaction


def test_r1_uses_profile_limit_and_reduces_habitual_value():
    four = [transaction(amount=200_000, days_ago=i) for i in range(1, 5)]
    five = [transaction(amount=200_000, days_ago=i) for i in range(1, 6)]
    assert r1(event(500_000), profile(successful_profile=four, successful_profile_count=4, mature=False), {})[0] == 2
    assert r1(event(500_000), profile(successful_profile=five, successful_profile_count=5, mature=False), {})[0] == 2
    mature = profile(successful_profile=five, median_amount=200_000, mature=True, limit=600_000)
    assert r1(event(580_000), mature, {}) is None  # 2.9× median
    assert r1(event(600_000), mature, {})[0] == 2  # 3× median
    habitual = profile(mature=True, limit=500_000, habitual=True)
    assert r1(event(500_000), habitual, {})[0] == 1
    assert r1(event(499_999), profile(), {}) is None
    assert r1(event(1_000_000, context={"event": "request"}), profile(), {}) is None


def test_r2_fires_on_fifth_pix_in_sixty_seconds():
    history = [transaction(minutes_ago=1, amount=1_000) for _ in range(4)]
    assert r2(event(1_000), profile(source_history=history), {})[0] == 2
    assert r2(event(1_000), profile(source_history=history[:3]), {}) is None


def test_r3_sums_two_or_more_pix_in_ten_minutes():
    previous = transaction(minutes_ago=5, amount=500_000)
    assert r3(event(500_000), profile(source_history=[previous], limit=500_000), {})[0] == 2
    assert r3(event(500_000), profile(source_history=[], limit=500_000), {}) is None


def test_r3_uses_twice_the_mature_profile_limit():
    previous = transaction(minutes_ago=5, amount=2_399_999)
    mature_profile = profile(source_history=[previous], limit=2_400_000)
    assert r3(event(2_400_000), mature_profile, {}) is None
    previous["amount"] = 2_400_000
    assert r3(event(2_400_000), mature_profile, {})[0] == 2


def test_r4_requires_five_history_events_and_five_times_median():
    history = [transaction(amount=10_000, days_ago=day) for day in range(1, 6)]
    p = profile(trusted_history=history, successful_profile=history, median_amount=10_000)
    assert r4(event(50_000), p, {})[0] == 2
    assert r4(event(49_999), p, {}) is None
    assert r4(event(50_000), profile(trusted_history=history[:4]), {}) is None


def test_r5_new_destination_has_history_and_median_floor():
    history = [transaction(amount=20_000, days_ago=day) for day in range(1, 6)]
    p = profile(trusted_history=history, median_amount=20_000)
    assert r5(event(100_000), p, {})[0] == 1
    assert r5(event(99_999), p, {}) is None
    assert r5(event(100_000), profile(trusted_history=history[:2]), {}) is None


def test_r6_destination_age_and_r8_aggregate_boundary():
    current = event(100_000)
    current["destination_account"]["opening_date"] = NOW - timedelta(days=30)
    assert r6(current, profile(), {})[0] == 2
    current["destination_account"]["opening_date"] = NOW - timedelta(days=30, seconds=1)
    assert r6(current, profile(), {}) is None
    current["destination_account"]["opening_date"] = None
    assert r6(current, profile(), {}) is None


def test_r7_requires_three_trusted_events_and_new_device():
    history = [transaction(days_ago=day, device=f"old-{day}") for day in (1, 2, 3)]
    p = profile(trusted_history=history)
    assert r7(event(50_000), p, {})[0] == 2
    assert r7(event(49_999), p, {}) is None
    assert r7(event(50_000), profile(trusted_history=history[:2]), {}) is None


def test_r8_requires_three_small_pix_same_account_and_two_thousand_total():
    history = [transaction(amount=75_000, minutes_ago=i, dest_acct="d-1") for i in (1, 2)]
    assert r8(event(50_000, dest_acct="d-1"), profile(source_history=history), {})[0] == 2
    assert r8(event(49_999, dest_acct="d-1"), profile(source_history=history), {}) is None
    wrong_account = [transaction(amount=80_000, minutes_ago=i, dest_acct=f"d-{i}") for i in (1, 2)]
    assert r8(event(50_000, dest_acct="d-1"), profile(source_history=wrong_account), {}) is None


def test_r9_counts_distinct_senders_and_total_on_destination_account():
    p = profile()
    context = {"destination_account_activity": {"sender_count": 4, "amount_total": 500_000, "current_sender_present": False}}
    assert r9(event(500_000), p, context)[0] == 3
    assert r9(event(499_999), p, {"destination_account_activity": {"sender_count": 4, "amount_total": 499_999}}) is None


def test_r10_two_vs_three_prior_pix_changes_points():
    current = event(200_000)
    current["source_account"]["opening_date"] = NOW - timedelta(days=30)
    assert r10(current, profile(trusted_history=[transaction() for _ in range(2)]), {}) == (2, "Payer account is 30 days old with 2 prior events.")
    assert r10(current, profile(trusted_history=[transaction() for _ in range(3)]), {})[0] == 1


def test_r11_uses_latest_prior_geolocation_within_sixty_minutes():
    prior = transaction(minutes_ago=5, geolocation={"latitude": 0.0, "longitude": 0.0})
    current = event(1_000, offset_minutes=0)
    current["source"]["geolocation"] = {"latitude": 0.0, "longitude": 10.0}
    assert r11(current, profile(source_history=[prior]), {})[0] == 3
    prior["payload"]["source"].pop("geolocation")
    assert r11(current, profile(source_history=[prior]), {}) is None


def test_r12_shared_device_threshold_is_three_documents():
    assert r12(event(context=None), profile(), {"device_payer_count": 3})[0] == 2
    assert r12(event(context=None), profile(), {"device_payer_count": 2}) is None
    epp = event(context={"event": "request", "author_id": "a3", "company_id": "c2"})
    assert r12(epp, profile(), {"device_author_companies": frozenset({("a1", "c1"), ("a2", "c2")})})[0] == 2


def test_r28_lower_band_and_two_vs_three_pix():
    two = [transaction(amount=450_000, minutes_ago=60 - i) for i in (1, 2)]
    p = profile(source_history=two, limit=500_000)
    assert r28(event(450_000), p, {})[0] == 2
    assert r28(event(449_999), p, {}) is None
    assert r28(event(500_000), p, {}) is None
    assert r28(event(450_000), profile(source_history=two[:1], limit=500_000), {}) is None
    established_high_median = profile(source_history=two, limit=600_000)
    assert r28(event(450_000), established_high_median, {}) is None


def test_r28_band_tracks_mature_profile_limit():
    history = [transaction(amount=1_100_000, minutes_ago=i) for i in (1, 2)]
    p = profile(source_history=history, mature=True, limit=1_200_000)
    assert r28(event(1_079_999), p, {}) is None
    assert r28(event(1_080_000), p, {})[0] == 2


def test_r29_requires_four_pix_and_limit_sum_to_same_document():
    prior = [transaction(amount=125_000, minutes_ago=i, dest_doc="22222222222", dest_acct=f"acct-{i}") for i in (1, 2, 3)]
    p = profile(source_history=prior, limit=500_000)
    assert r29(event(125_000), p, {})[0] == 2
    assert r29(event(124_999), p, {}) is None
    assert r29(event(125_000), profile(source_history=prior[:2], limit=500_000), {}) is None


def test_r33_cold_start_step_for_older_account():
    current = event(200_000)
    current["source_account"]["opening_date"] = NOW - timedelta(days=31)
    assert r33(current, profile(mature=False, habitual=False), {})[0] == 1
    current["source_account"]["opening_date"] = NOW - timedelta(days=30)
    assert r33(current, profile(mature=False, habitual=False), {}) is None
