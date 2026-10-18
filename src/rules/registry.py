"""Explicit version registry for rule implementations."""

from collections.abc import Callable

from rules.configuration import ACTIVE_RULESET, RULE_CODES, RuleSetConfigurationError
from rules.epp import EPP_RULES, r24_v2
from rules.integrity import c1, c1_v2
from rules.pix_core import CORE_RULES


RuleFunction = Callable[[dict, dict, dict], tuple[int, str] | None]

# Add a reviewed alternative here under its rule code and immutable version
# name, then select that name in the active rule-set configuration.
ALTERNATE_RULE_IMPLEMENTATIONS: dict[str, dict[str, RuleFunction]] = {
    "C1": {"v2": c1_v2},
    "R24": {"v2": r24_v2},
}


def _build_registry() -> dict[str, dict[str, RuleFunction]]:
    registry: dict[str, dict[str, RuleFunction]] = {"C1": {"v1": c1}}
    for rule in (*CORE_RULES, *EPP_RULES):
        code = rule.__name__.upper()
        if code in registry:
            raise RuleSetConfigurationError(f"Duplicate base implementation registered for {code}")
        registry[code] = {"v1": rule}

    for code, alternatives in ALTERNATE_RULE_IMPLEMENTATIONS.items():
        if (
            code not in registry
            or "v1" in alternatives
            or any(not isinstance(name, str) or not name for name in alternatives)
            or any(not callable(rule) for rule in alternatives.values())
        ):
            raise RuleSetConfigurationError(f"Invalid alternate implementation registration for {code}")
        registry[code].update(alternatives)

    if set(registry) != set(RULE_CODES):
        missing = set(RULE_CODES) - set(registry)
        unknown = set(registry) - set(RULE_CODES)
        raise RuleSetConfigurationError(
            f"Rule registry/configuration mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    for code, implementation_name in ACTIVE_RULESET.implementations.items():
        if implementation_name not in registry[code]:
            raise RuleSetConfigurationError(
                f"Unknown configured implementation {implementation_name!r} for {code}"
            )
    return registry


RULE_IMPLEMENTATION_REGISTRY = _build_registry()
