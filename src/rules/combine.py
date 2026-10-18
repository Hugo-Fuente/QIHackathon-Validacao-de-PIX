"""Family caps and score bands for Pix rule results."""

from rules.params import FAMILY_CAPS, REJECT_MIN_SCORE, TWO_FACTOR_MIN_SCORE


def combine_hits(hits: list[dict]) -> int:
    """Sum raw rule points after applying the RFC v7 family caps."""
    grouped_codes: set[str] = set()
    score = 0
    for codes, cap in FAMILY_CAPS.values():
        grouped_codes.update(codes)
        score += min(cap, sum(hit["points"] for hit in hits if hit["code"] in codes))
    score += sum(hit["points"] for hit in hits if hit["code"] not in grouped_codes)
    return score


def status_for_score(score: int, hits: list[dict]) -> str:
    if any(hit["code"] == "C1" for hit in hits) or score >= REJECT_MIN_SCORE:
        return "rejected"
    if score >= TWO_FACTOR_MIN_SCORE:
        return "two_factor_required"
    return "approved"

