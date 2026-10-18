from rules.combine import combine_hits, status_for_score
from rules.integrity import c1
from tests.rule_support import epp_event


def test_combine_applies_value_and_fractioning_family_caps():
    hits = [
        {"code": "R1", "points": 2},
        {"code": "R3", "points": 2},
        {"code": "R4", "points": 2},
        {"code": "R28", "points": 2},
        {"code": "R8", "points": 2},
        {"code": "R29", "points": 2},
        {"code": "R2", "points": 1},
    ]
    assert combine_hits(hits) == 3 + 2 + 1


def test_combine_score_bands_at_one_two_four_and_five_points():
    assert status_for_score(1, []) == "approved"
    assert status_for_score(2, []) == "two_factor_required"
    assert status_for_score(4, []) == "two_factor_required"
    assert status_for_score(5, []) == "rejected"


def test_c1_rejects_a_missing_request():
    assert c1(epp_event("vote"), {}, {})[0] == 0


def test_c1_rejects_a_rejected_request():
    request = {"payload": {"context": {"event": "request", "request_hash": "hash-a"}}}
    assert c1(
        epp_event("vote", request_hash="hash-a"),
        {},
        {"request_event": request, "request_status": "rejected"},
    )[0] == 0


def test_c1_rejects_a_request_hash_mismatch():
    request = {"payload": {"context": {"event": "request", "request_hash": "hash-a"}}}
    assert c1(
        epp_event("execution", request_hash="hash-b"),
        {},
        {"request_event": request, "request_status": "approved"},
    )[0] == 0


def test_c1_accepts_matching_request_hash_and_status():
    request = {"payload": {"context": {"event": "request", "request_hash": "hash-a"}}}
    assert c1(
        epp_event("vote", request_hash="hash-a"),
        {},
        {"request_event": request, "request_status": "approved"},
    ) is None
