"""Immutable plain-data snapshot assembled by the repository."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PixHistory:
    source_events: tuple[dict[str, Any], ...] = ()
    trusted_events: tuple[dict[str, Any], ...] = ()
    source_event_count: int = 0
    trusted_event_count: int = 0
    successful_profile_count: int = 0
    profile_median: float | None = None
    source_metrics: dict[str, int] = field(default_factory=dict)
    seen_destination_account: bool = False
    destination_account_activity: dict[str, Any] = field(default_factory=dict)
    device_payer_count: int = 0
    device_author_companies: frozenset[tuple[str, str]] = frozenset()
    recent_payer_count: int = 0
    destination_document_activity: dict[str, Any] = field(default_factory=dict)
    partner_company_counts: dict[str, int] = field(default_factory=dict)
    request_event: dict[str, Any] | None = None
    request_status: str | None = None
    has_prior_execution: bool = False
