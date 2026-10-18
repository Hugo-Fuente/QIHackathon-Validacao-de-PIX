"""Compatibility facade for the active immutable rule-set configuration.

New configuration values live in ``src/config/rulesets/active.json``. The module
attribute interface keeps existing pure rule functions small while the
configuration loader remains the only component that reads and validates it.
"""

from types import MappingProxyType

from rules.configuration import ACTIVE_RULESET, RULE_CODES


RULESET_VERSION = ACTIVE_RULESET.version
RULESET_SHA256 = ACTIVE_RULESET.sha256
ENABLED_RULES = ACTIVE_RULESET.enabled_rules
RULE_IMPLEMENTATIONS = ACTIVE_RULESET.implementations
POINT_OVERRIDES = ACTIVE_RULESET.point_overrides
FAMILY_CAPS = MappingProxyType({
    name: (codes, cap) for name, (codes, cap) in ACTIVE_RULESET.family_caps.items()
})
TWO_FACTOR_MIN_SCORE = ACTIVE_RULESET.two_factor_min_score
REJECT_MIN_SCORE = ACTIVE_RULESET.reject_min_score
_RULE_PARAMETER_VIEWS = MappingProxyType({
    code: MappingProxyType({
        **ACTIVE_RULESET.parameter_groups["shared"],
        **ACTIVE_RULESET.parameter_groups.get(code, {}),
    })
    for code in RULE_CODES
})


def for_rule(code: str) -> MappingProxyType:
    """Return only the shared and rule-specific settings for ``code``."""
    try:
        return _RULE_PARAMETER_VIEWS[code]
    except KeyError as error:
        raise KeyError(f"No parameter group registered for {code}") from error


def shared() -> MappingProxyType:
    """Return the immutable settings used by profile and common helpers."""
    return ACTIVE_RULESET.parameter_groups["shared"]


def __getattr__(name: str):
    """Expose legacy named constants from the validated active rule set."""
    try:
        return ACTIVE_RULESET.parameters[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
