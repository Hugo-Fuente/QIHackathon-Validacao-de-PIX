"""Run API scenarios from pix_api_tests.json against a live service."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PLACEHOLDER = re.compile(r"\{\{([^{}]+)\}\}")


def resolve_string(value: str, scenario_id: str, run_id: str, aliases: dict) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token == "run":
            return run_id
        if token == "now":
            key = ("time", "now")
            if key not in aliases:
                aliases[key] = datetime.now(timezone.utc).replace(microsecond=0)
            return aliases[key].isoformat().replace("+00:00", "Z")
        found = re.fullmatch(r"now([+-]\d+)([dhms])", token)
        if found:
            key = ("time", token)
            if key in aliases:
                return aliases[key].isoformat().replace("+00:00", "Z")
            amount, unit = int(found.group(1)), found.group(2)
            delta = {
                "d": timedelta(days=abs(amount)),
                "h": timedelta(hours=abs(amount)),
                "m": timedelta(minutes=abs(amount)),
                "s": timedelta(seconds=abs(amount)),
            }[unit]
            anchor = aliases.setdefault(("time", "now"), datetime.now(timezone.utc).replace(microsecond=0))
            aliases[key] = anchor + delta if amount > 0 else anchor - delta
            return aliases[key].isoformat().replace("+00:00", "Z")
        if token.startswith("brt:"):
            found = re.fullmatch(r"brt:(\d{2}):(\d{2})(?:([+-]\d+)([smhd]))?", token)
            if not found:
                raise ValueError(f"Invalid BRT placeholder: {token}")
            hour, minute, amount, unit = found.groups()
            now_brt = aliases.setdefault(
                ("time", "now"), datetime.now(timezone.utc).replace(microsecond=0)
            ).astimezone(ZoneInfo("America/Sao_Paulo"))
            result = now_brt.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
            if amount:
                magnitude = abs(int(amount))
                delta = {
                    "d": timedelta(days=magnitude),
                    "h": timedelta(hours=magnitude),
                    "m": timedelta(minutes=magnitude),
                    "s": timedelta(seconds=magnitude),
                }[unit]
                result += delta if int(amount) > 0 else -delta
            elif result > now_brt:
                result -= timedelta(days=1)
            return result.isoformat()
        if ":" not in token:
            raise ValueError(f"Unknown placeholder: {token}")
        kind, label = token.split(":", 1)
        key = (kind, label)
        if key not in aliases:
            seed = f"{run_id}:{scenario_id}:{kind}:{label}"
            if kind == "id":
                aliases[key] = str(uuid.uuid5(uuid.NAMESPACE_URL, seed))
            elif kind == "acct":
                aliases[key] = f"{run_id}-{scenario_id}-{label}"
            elif kind in ("doc", "cnpj"):
                digits = 11 if kind == "doc" else 14
                aliases[key] = str(zlib.crc32(seed.encode()) % (10**digits)).zfill(digits)
            else:
                raise ValueError(f"Unknown placeholder: {token}")
        return aliases[key]

    return PLACEHOLDER.sub(replace, value)


def resolve(value: Any, scenario_id: str, run_id: str, aliases: dict) -> Any:
    if isinstance(value, dict):
        return {key: resolve(item, scenario_id, run_id, aliases) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, scenario_id, run_id, aliases) for item in value]
    if isinstance(value, str):
        return resolve_string(value, scenario_id, run_id, aliases)
    return value


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamps in repeat bounds must include a timezone: {value}")
    return parsed


def expand_step(step: dict, scenario_id: str, run_id: str, aliases: dict) -> list[dict]:
    request = resolve(step["request"], scenario_id, run_id, aliases)
    if "repeat" not in step:
        request.setdefault("transaction_date", resolve_string("{{now}}", scenario_id, run_id, aliases))
        return [{"name": step.get("name", "step"), "request": request, "expect": step.get("expect")}]

    count = int(step["repeat"])
    start = parse_time(resolve_string(step["from"], scenario_id, run_id, aliases))
    end = parse_time(resolve_string(step["to"], scenario_id, run_id, aliases))
    expanded = []
    for index in range(count):
        fraction = index / max(count - 1, 1)
        transaction_date = start + (end - start) * fraction
        repeated_request = dict(request)
        repeated_request["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{scenario_id}:{step['name']}:{index}"))
        repeated_request["transaction_date"] = transaction_date.isoformat()
        expanded.append({"name": f"{step.get('name', 'step')} #{index + 1}", "request": repeated_request, "expect": step.get("expect") if index == count - 1 else None})
    return expanded


def send_request(base_url: str, token: str, payload: dict) -> tuple[int, dict]:
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/pix/transaction"):
        endpoint += "/pix/transaction"
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "INTERNAL-TOKEN": token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            status, content = response.status, response.read()
    except HTTPError as error:
        status, content = error.code, error.read()
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"API request failed: {error}") from error
    try:
        body = json.loads(content) if content else {}
    except json.JSONDecodeError:
        body = {"_raw": content.decode("utf-8", errors="replace")}
    return status, body


def actual_rules(metadata: dict) -> list[str]:
    if "rules" in metadata:
        return metadata["rules"]
    if "rules_triggered" in metadata:
        return metadata["rules_triggered"]
    return [reason.get("rule", reason.get("code")) for reason in metadata.get("reasons", [])]


def check_expectation(expected: dict, status: int, body: dict, prior: list) -> list[str]:
    errors = []
    if "http" in expected and status != expected["http"]:
        errors.append(f"HTTP {status}, expected {expected['http']}")
    if expected.get("http", status) not in (200, 201):
        return errors
    if "status" in expected and body.get("status") != expected["status"]:
        errors.append(f"status {body.get('status')}, expected {expected['status']}")
    metadata = body.get("metadata") or {}
    if "rules" in expected and actual_rules(metadata) != expected["rules"]:
        errors.append(f"rules {actual_rules(metadata)}, expected {expected['rules']}")
    if "score" in expected and metadata.get("risk_score") != expected["score"]:
        errors.append(f"score {metadata.get('risk_score')}, expected {expected['score']}")
    if "actions" in expected and metadata.get("recommended_actions", []) != expected["actions"]:
        errors.append(f"actions {metadata.get('recommended_actions', [])}, expected {expected['actions']}")
    if "same_key_as_step" in expected:
        reference_index = expected["same_key_as_step"]
        reference = prior[reference_index][1] if reference_index < len(prior) else None
        if not reference or body.get("key") != reference.get("key"):
            errors.append(f"key does not match step {reference_index}")
    return errors


def run_scenario(
    scenario: dict,
    base_url: str,
    token: str,
    run_id: str,
    only: set[str] | None = None,
    skip_requires: bool = False,
) -> list[str]:
    aliases = {}
    responses = []
    failures = []
    for step in scenario["steps"]:
        expanded = expand_step(step, scenario["id"], run_id, aliases)
        for item in expanded:
            try:
                status, body = send_request(base_url, token, item["request"])
            except RuntimeError as error:
                failures.append(f"{item['name']}: {error}")
                responses.append((None, None))
                continue
            responses.append((status, body))
            expected = item["expect"]
            if expected:
                failures.extend(
                    f"{item['name']}: {message}"
                    for message in check_expectation(expected, status, body, responses)
                )
            elif status >= 400:
                failures.append(f"{item['name']}: HTTP {status}, expected success")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_file", nargs="?", help="Path to a pix_api_tests.json file")
    parser.add_argument("--file", dest="file_option", help="Path to a pix_api_tests.json file")
    parser.add_argument("--base-url", default=os.getenv("API_BASE_URL", "http://localhost:3000"))
    parser.add_argument("--url", help="Full transaction endpoint URL (alternative to --base-url)")
    parser.add_argument("--token", default=os.getenv("INTERNAL_TOKEN", "default_token"))
    parser.add_argument("--only", default="", help="Scenario ids or rules, comma-separated")
    parser.add_argument("--skip-requires", action="store_true", help="Skip scenarios with unmet repository requirements")
    args = parser.parse_args()

    json_file = args.file_option or args.json_file or "pix_api_tests.json"
    with open(json_file, encoding="utf-8") as source:
        scenarios = json.load(source)["scenarios"]
    only = {value.strip() for value in args.only.split(",") if value.strip()} or None
    run_id = uuid.uuid4().hex[:12]
    failures_by_scenario = []
    skipped = 0
    selected = 0
    configured_url = args.base_url.rstrip("/")
    base_url = args.url or (
        configured_url
        if configured_url.endswith("/pix/transaction")
        else f"{configured_url}/pix/transaction"
    )
    for scenario in scenarios:
        if only and scenario["id"] not in only and scenario.get("rule") not in only:
            continue
        selected += 1
        if args.skip_requires and scenario.get("requires"):
            skipped += 1
            print(f"SKIP {scenario['id']:<22} requires {', '.join(scenario['requires'])}")
            continue
        failures = run_scenario(scenario, base_url, args.token, run_id, only, args.skip_requires)
        if failures:
            failures_by_scenario.append((scenario["id"], failures))

    passed = selected - len(failures_by_scenario) - skipped
    total = selected
    print(f"Scenarios: {passed} passed, {len(failures_by_scenario)} failed, {skipped} skipped, {total} selected")
    for scenario_id, failures in failures_by_scenario:
        print(f"\n[{scenario_id}]")
        for failure in failures:
            print(f"  - {failure}")
    return 1 if failures_by_scenario else 0


if __name__ == "__main__":
    sys.exit(main())
