"""Load and validate the immutable, versioned anti-fraud rule set."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from rules.parameter_schema import PARAMETER_NAMES, PARAMETER_TYPES


class RuleSetConfigurationError(ValueError):
    """Raised when the active rule set is unsafe or incomplete."""


RULE_CODES = frozenset({"C1", *(f"R{number}" for number in range(1, 34))})
FAMILY_NAMES = frozenset({"value", "fractioning", "controls", "session", "linked_destination"})
UNIT_INTERVAL_PARAMETERS = frozenset({
    "HABITUAL_MIN_FACTOR", "R13_LOWER_LIMIT_RATIO", "R13_UPPER_LIMIT_RATIO",
    "R14_MIN_AMOUNT_RATIO", "R20_MIN_BALANCE_RATIO", "R21_MIN_RELEASED_RATIO",
    "R25_MIN_OUTFLOW_RATIO", "R28_LOWER_LIMIT_RATIO",
})
ACTIVE_RULESET_PATH = Path(__file__).resolve().parents[1] / "config" / "rulesets" / "active.json"


@dataclass(frozen=True)
class RuleSetConfiguration:
    schema_version: int
    version: str
    sha256: str
    parameters: Mapping[str, int | float]
    parameter_groups: Mapping[str, Mapping[str, int | float]]
    enabled_rules: frozenset[str]
    implementations: Mapping[str, str]
    point_overrides: Mapping[str, int]
    family_caps: Mapping[str, tuple[frozenset[str], int]]
    two_factor_min_score: int
    reject_min_score: int


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuleSetConfigurationError(f"Duplicate configuration key: {key}")
        result[key] = value
    return result


def _require_exact_keys(value: object, expected: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise RuleSetConfigurationError(f"{location} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown: {', '.join(unknown)}")
        raise RuleSetConfigurationError(f"Invalid {location} keys ({'; '.join(details)})")
    return value


def _validate_parameters(raw: object) -> tuple[dict[str, int | float], dict[str, Mapping[str, int | float]]]:
    expected_groups = {"shared"} | {
        match.group(1)
        for name in PARAMETER_NAMES
        if (match := re.match(r"^(R\d+)_", name))
    }
    groups = _require_exact_keys(raw, expected_groups, "parameters")
    flattened: dict[str, int | float] = {}
    frozen_groups: dict[str, Mapping[str, int | float]] = {}

    for group_name, group_values in groups.items():
        expected_names = {
            name for name in PARAMETER_NAMES
            if ((match := re.match(r"^(R\d+)_", name)) and match.group(1) == group_name)
            or (not re.match(r"^R\d+_", name) and group_name == "shared")
        }
        values = _require_exact_keys(group_values, expected_names, f"parameters.{group_name}")
        safe_values: dict[str, int | float] = {}
        for name, value in values.items():
            expected_type = PARAMETER_TYPES[name]
            if type(value) is not expected_type:
                raise RuleSetConfigurationError(
                    f"parameters.{group_name}.{name} must be {expected_type.__name__}"
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise RuleSetConfigurationError(f"parameters.{group_name}.{name} must be finite")
            if value < 0 or (value == 0 and name != "R19_START_HOUR"):
                raise RuleSetConfigurationError(f"parameters.{group_name}.{name} must be positive")
            if name in UNIT_INTERVAL_PARAMETERS and value > 1:
                raise RuleSetConfigurationError(f"parameters.{group_name}.{name} must be at most 1")
            safe_values[name] = value
            flattened[name] = value
        frozen_groups[group_name] = MappingProxyType(safe_values)

    if flattened.get("CENTS_PER_REAL") != 100:
        raise RuleSetConfigurationError("CENTS_PER_REAL is a fixed currency representation and must equal 100")
    if flattened["R19_START_HOUR"] >= flattened["R19_END_HOUR"] or flattened["R19_END_HOUR"] > 24:
        raise RuleSetConfigurationError("R19 hour range must be increasing and end no later than 24")
    if flattened["R13_LOWER_LIMIT_RATIO"] > flattened["R13_UPPER_LIMIT_RATIO"]:
        raise RuleSetConfigurationError("R13 lower ratio cannot exceed its upper ratio")
    if flattened["R14_MIN_AMOUNT_RATIO"] > flattened["R14_MAX_AMOUNT_RATIO"]:
        raise RuleSetConfigurationError("R14 minimum ratio cannot exceed its maximum ratio")
    if flattened["HABITUAL_MIN_FACTOR"] > flattened["HABITUAL_AMOUNT_FACTOR"]:
        raise RuleSetConfigurationError("Habitual amount range is inverted")
    if flattened["R24_OPERATIONAL_PROFILE_MIN_APPROVERS"] < 2:
        raise RuleSetConfigurationError("A payroll operating profile requires at least two approvers")
    if flattened["R24_OPERATIONAL_PROFILE_MAX_AGE_DAYS"] > 365:
        raise RuleSetConfigurationError("A payroll operating profile cannot remain valid for more than 365 days")
    return flattened, frozen_groups


def _validate_rule_list(raw: object, location: str, *, require_integrity: bool = False) -> frozenset[str]:
    if not isinstance(raw, list) or any(not isinstance(code, str) for code in raw):
        raise RuleSetConfigurationError(f"{location} must be a list of rule codes")
    codes = frozenset(raw)
    if len(codes) != len(raw):
        raise RuleSetConfigurationError(f"{location} cannot contain duplicate rule codes")
    unknown = codes - RULE_CODES
    if unknown:
        raise RuleSetConfigurationError(f"{location} contains unknown rules: {', '.join(sorted(unknown))}")
    if require_integrity and "C1" not in codes:
        raise RuleSetConfigurationError("C1 is a mandatory integrity check and cannot be disabled")
    return codes


def _validate_family_caps(raw: object) -> Mapping[str, tuple[frozenset[str], int]]:
    families = _require_exact_keys(raw, set(FAMILY_NAMES), "family_caps")
    result: dict[str, tuple[frozenset[str], int]] = {}
    assigned_codes: set[str] = set()
    for family, value in families.items():
        entry = _require_exact_keys(value, {"codes", "max_points"}, f"family_caps.{family}")
        codes = _validate_rule_list(entry["codes"], f"family_caps.{family}.codes")
        cap = entry["max_points"]
        if type(cap) is not int or not 0 <= cap <= 10:
            raise RuleSetConfigurationError(f"family_caps.{family}.max_points must be an integer from 0 to 10")
        overlap = assigned_codes.intersection(codes)
        if overlap:
            raise RuleSetConfigurationError(f"Rules cannot belong to multiple score families: {', '.join(sorted(overlap))}")
        assigned_codes.update(codes)
        result[family] = (codes, cap)
    return MappingProxyType(result)


def load_ruleset(path: Path = ACTIVE_RULESET_PATH) -> RuleSetConfiguration:
    """Read a complete rule set and reject malformed or unsafe values."""
    try:
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, json.JSONDecodeError) as error:
        raise RuleSetConfigurationError(f"Cannot load rule set from {path}: {error}") from error

    root = _require_exact_keys(
        raw,
        {
            "schema_version", "ruleset_version", "parameters", "enabled_rules",
            "rule_implementations", "point_overrides", "family_caps", "score_thresholds",
        },
        "root",
    )
    schema_version = root["schema_version"]
    version = root["ruleset_version"]
    if type(schema_version) is not int or schema_version != 1:
        raise RuleSetConfigurationError("schema_version must be the supported integer 1")
    if not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+(?:\.\d+)?", version):
        raise RuleSetConfigurationError("ruleset_version must look like v7.1 or v7.1.1")

    parameters, parameter_groups = _validate_parameters(root["parameters"])
    enabled_rules = _validate_rule_list(root["enabled_rules"], "enabled_rules", require_integrity=True)

    implementations = _require_exact_keys(root["rule_implementations"], set(RULE_CODES), "rule_implementations")
    if any(not isinstance(value, str) or not value for value in implementations.values()):
        raise RuleSetConfigurationError("Every rule implementation must be a non-empty name")

    overrides = root["point_overrides"]
    if not isinstance(overrides, dict):
        raise RuleSetConfigurationError("point_overrides must be an object")
    if "C1" in overrides:
        raise RuleSetConfigurationError("C1 is an integrity result and its score cannot be overridden")
    for code, points in overrides.items():
        if code not in RULE_CODES or type(points) is not int or not 0 <= points <= 5:
            raise RuleSetConfigurationError(f"Invalid point override for {code!r}; expected a rule code and 0–5 points")

    family_caps = _validate_family_caps(root["family_caps"])
    thresholds = _require_exact_keys(
        root["score_thresholds"], {"two_factor_min_score", "reject_min_score"}, "score_thresholds"
    )
    two_factor = thresholds["two_factor_min_score"]
    reject = thresholds["reject_min_score"]
    if type(two_factor) is not int or type(reject) is not int or not 1 <= two_factor < reject <= 20:
        raise RuleSetConfigurationError("Score thresholds must satisfy 1 <= two_factor < reject <= 20")

    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return RuleSetConfiguration(
        schema_version=schema_version,
        version=version,
        sha256=hashlib.sha256(canonical).hexdigest(),
        parameters=MappingProxyType(parameters),
        parameter_groups=MappingProxyType(parameter_groups),
        enabled_rules=enabled_rules,
        implementations=MappingProxyType(dict(implementations)),
        point_overrides=MappingProxyType(dict(overrides)),
        family_caps=family_caps,
        two_factor_min_score=two_factor,
        reject_min_score=reject,
    )


# One immutable snapshot is shared by the process. All workers load the same
# committed file when the API starts; invalid configuration prevents startup.
ACTIVE_RULESET = load_ruleset()
