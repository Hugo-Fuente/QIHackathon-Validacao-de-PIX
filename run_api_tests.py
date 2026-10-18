#!/usr/bin/env python3
"""
Executa pix_api_tests.json contra POST /pix/transaction.

  python run_api_tests.py --url http://localhost:8000/pix/transaction
  python run_api_tests.py --only R1,R30,C1_hash
  python run_api_tests.py --skip-requires      # pula R12/R27 se o repositório não tem as consultas

Placeholders aceitos no JSON (resolvidos a cada execução, com valores únicos por cenário,
para que o histórico de uma rodada não contamine a seguinte):
  {{now}} {{now-30s}} {{now-3d}} {{now+5m}}      instante relativo ao início da rodada (UTC)
  {{brt:14:00}} {{brt:02:30-5d}}                 última ocorrência passada de HH:MM no fuso de Brasília
  {{doc:nome}}   CPF (11 dígitos)   {{cnpj:nome}}  CNPJ (14 dígitos)   {{acct:nome}}  conta (8 dígitos)
  {{id:nome}}    id único do evento                {{run}}          id da rodada

Um step com "repeat": N gera N requisições (id sufixado -0..-N+1) com datas igualmente espaçadas
entre "from" e "to". Um step com "expect" é conferido; sem "expect" só é enviado (preparação de histórico).
"""
import argparse
import copy
import json
import random
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))
UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
FMT = "%Y-%m-%dT%H:%M:%SZ"
PLACEHOLDER = re.compile(r"\{\{([^}]+)\}\}")


class Resolver:
    def __init__(self, scenario_id: str, run: str, now: datetime):
        self.sid, self.run, self.now = scenario_id, run, now

    def _digits(self, kind: str, name: str, size: int) -> str:
        rnd = random.Random(f"{self.run}|{self.sid}|{kind}|{name}")
        return str(rnd.randint(1, 9)) + "".join(rnd.choice("0123456789") for _ in range(size - 1))

    @staticmethod
    def _offset(sign_num, unit) -> timedelta:
        return timedelta(seconds=int(sign_num) * UNIT[unit]) if sign_num else timedelta(0)

    def dt(self, expr: str) -> datetime:
        expr = expr.strip("{} ")
        m = re.fullmatch(r"now(?:([+-]\d+)([smhd]))?", expr)
        if m:
            return self.now + self._offset(m.group(1), m.group(2))
        m = re.fullmatch(r"brt:(\d\d):(\d\d)(?:([+-]\d+)([smhd]))?", expr)
        if m:
            local = self.now.astimezone(BRT).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
            if local > self.now.astimezone(BRT):
                local -= timedelta(days=1)
            return local.astimezone(timezone.utc) + self._offset(m.group(3), m.group(4))
        raise ValueError(f"placeholder de data inválido: {expr}")

    def value(self, expr: str) -> str:
        if expr == "run":
            return self.run
        if expr.startswith("doc:"):
            return self._digits("doc", expr[4:], 11)
        if expr.startswith("cnpj:"):
            return self._digits("cnpj", expr[5:], 14)
        if expr.startswith("acct:"):
            return self._digits("acct", expr[5:], 8)
        if expr.startswith("id:"):
            return f"{self.run}-{self.sid}-{expr[3:]}"
        return self.dt(expr).strftime(FMT)

    def resolve(self, obj):
        if isinstance(obj, str):
            return PLACEHOLDER.sub(lambda m: self.value(m.group(1)), obj)
        if isinstance(obj, list):
            return [self.resolve(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.resolve(v) for k, v in obj.items()}
        return obj

    def expand(self, step: dict) -> list:
        """Devolve a lista de requisições (já resolvidas) de um step."""
        if "repeat" not in step:
            return [self.resolve(step["request"])]
        n, t0, t1 = step["repeat"], self.dt(step["from"]), self.dt(step["to"])
        out = []
        for i in range(n):
            req = self.resolve(copy.deepcopy(step["request"]))
            when = t0 + (t1 - t0) * (i / (n - 1) if n > 1 else 0)
            req["id"] = f"{req['id']}-{i}"
            req["transaction_date"] = when.strftime(FMT)
            out.append(req)
        return out


def codes_of(body: dict) -> list:
    meta = (body or {}).get("metadata", {})
    if "reasons" in meta:
        return [r["code"] for r in meta["reasons"]]
    return list(meta.get("rules_triggered", []))


def check(expect: dict, http: int, body: dict, history: list) -> list:
    errors = []
    want_http = expect.get("http", 201)
    if http != want_http:
        errors.append(f"http {http} (esperado {want_http})")
    if want_http not in (200, 201):
        return errors
    meta = (body or {}).get("metadata", {})
    if "status" in expect and body.get("status") != expect["status"]:
        errors.append(f"status {body.get('status')} (esperado {expect['status']})")
    if "rules" in expect and set(codes_of(body)) != set(expect["rules"]):
        errors.append(f"regras {sorted(set(codes_of(body)))} (esperado {sorted(expect['rules'])})")
    if "score" in expect and meta.get("risk_score") != expect["score"]:
        errors.append(f"risk_score {meta.get('risk_score')} (esperado {expect['score']})")
    if "actions" in expect and set(meta.get("recommended_actions", [])) != set(expect["actions"]):
        errors.append(f"recommended_actions {meta.get('recommended_actions')} (esperado {expect['actions']})")
    if "same_key_as_step" in expect:
        other = history[expect["same_key_as_step"]]
        if other is None or other.get("key") != body.get("key"):
            errors.append("key diferente da análise original (idempotência)")
    return errors


def run_scenarios(scenarios: list, send, now: datetime, run: str, only=None, skip_requires=False) -> int:
    failed = 0
    for sc in scenarios:
        if only and sc["id"] not in only and sc.get("rule") not in only:
            continue
        if skip_requires and sc.get("requires"):
            print(f"SKIP {sc['id']:<22} (requer {', '.join(sc['requires'])})")
            continue
        resolver = Resolver(sc["id"], run, now)
        errors, history = [], []
        for step in sc["steps"]:
            for req in resolver.expand(step):
                http, body = send(req)
                history.append(body if http in (200, 201) else None)
                if "expect" in step:
                    errors += [f"[{step['name']}] {e}" for e in check(step["expect"], http, body, history)]
        mark = "FAIL" if errors else "OK  "
        failed += bool(errors)
        print(f"{mark} {sc['id']:<22} {sc['title']}")
        for e in errors:
            print(f"       - {e}")
    return failed


def http_sender(url: str):
    def send(payload: dict):
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except json.JSONDecodeError:
                return exc.code, {}
    return send


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000/pix/transaction")
    ap.add_argument("--file", default="pix_api_tests.json")
    ap.add_argument("--only", default="", help="ids ou regras separados por vírgula (ex.: R1,R30,C1_hash)")
    ap.add_argument("--skip-requires", action="store_true")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as fh:
        scenarios = json.load(fh)["scenarios"]
    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    failed = run_scenarios(
        scenarios, http_sender(args.url), datetime.now(timezone.utc).replace(microsecond=0),
        uuid.uuid4().hex[:8], only, args.skip_requires,
    )
    print(f"\n{'Todos os cenários passaram.' if not failed else f'{failed} cenário(s) falharam.'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
