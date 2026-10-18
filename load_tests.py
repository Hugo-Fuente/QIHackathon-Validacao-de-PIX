#!/usr/bin/env python3
"""
Testes de carga, concorrência e consistência do motor antifraude Pix (Grupo 27).
Só biblioteca padrão (matplotlib é opcional, só para os gráficos).

  python load_tests.py --url http://localhost:8000/pix/transaction
  python load_tests.py --quick                       # rodada curta (~1 min) para conferir que tudo funciona
  python load_tests.py --levels 1,10,25,50,100,200 --stage-seconds 20
  python load_tests.py --only idempotency,conflict,hot,destination,execution

Fases (--only aceita uma lista):
  smoke        contrato básico: 201, reenvio 200 com a mesma key, GET 200/404
  ramp         degraus de concorrência (1..N) com Pix de pagadores distintos -> acha o ponto de saturação
  idempotency  N requisições IDÊNTICAS ao mesmo tempo: tem de haver exatamente 1x 201, o resto 200, uma só key
  conflict     mesmo id com payloads diferentes ao mesmo tempo: 1 vencedor, o resto 200/409, nenhum 5xx
  hot          rajada paralela do MESMO pagador: a concorrência não pode mudar o resultado (R2/velocity)
  destination  rajada de pagadores distintos para a mesma conta destino: R9 paralelo == sequencial
  execution    execuções concorrentes com o mesmo request_id: C1 permite só uma
  validation   payloads inválidos sob carga: 400/422 exatos, nenhum 5xx
  get          leitura sob carga: GET devolve a mesma key do POST; id inexistente dá 404
  mixed        mistura realista: varejo, fluxo EPP (pedido -> execução), reenvio, inválidos e GET
  soak         carga constante por um tempo: vê se a latência/erros degradam

Saídas em --out (padrão results/<data-hora>/):
  report.md      tabelas prontas para copiar na apresentação
  summary.json   todos os números
  requests.csv   uma linha por requisição (para refazer gráficos)
  *.png          gráficos (se matplotlib estiver instalado)
"""
import argparse
import csv
import http.client
import itertools
import json
import os
import random
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

FMT = "%Y-%m-%dT%H:%M:%SZ"
ALL_PHASES = ["smoke", "ramp", "idempotency", "conflict", "hot", "destination", "execution",
              "validation", "get", "mixed", "soak"]


# --------------------------------------------------------------------------- cliente HTTP
class Client:
    """Uma conexão keep-alive por thread, para medir o servidor e não o custo de abrir socket."""

    def __init__(self, url: str, timeout: float, headers=None):
        p = urlparse(url)
        self.host, self.port, self.tls = p.hostname, p.port or (443 if p.scheme == "https" else 80), p.scheme == "https"
        self.post_path = p.path or "/"
        self.timeout = timeout
        self.headers = headers or {}
        self.storm = self
        self.local = threading.local()

    def _conn(self):
        c = getattr(self.local, "c", None)
        if c is None:
            cls = http.client.HTTPSConnection if self.tls else http.client.HTTPConnection
            c = self.local.c = cls(self.host, self.port, timeout=self.timeout)
        return c

    def send(self, method: str, path: str, body=None):
        """Devolve (status, json|None, latência_ms). status 0 = erro de rede/timeout."""
        data = None
        headers = dict(self.headers)
        if body is not None:
            data = body if isinstance(body, (bytes, str)) else json.dumps(body)
            data = data.encode() if isinstance(data, str) else data
            headers["Content-Type"] = "application/json"
        t0 = time.perf_counter()
        try:
            c = self._conn()
            c.request(method, path, body=data, headers=headers)
            r = c.getresponse()
            raw = r.read()
            ms = (time.perf_counter() - t0) * 1000
            try:
                return r.status, json.loads(raw or b"{}"), ms
            except json.JSONDecodeError:
                return r.status, None, ms
        except Exception:
            self.local.c = None  # reconecta na próxima
            return 0, None, (time.perf_counter() - t0) * 1000


# --------------------------------------------------------------------------- payloads
def digits(rnd: random.Random, n: int) -> str:
    return str(rnd.randint(1, 9)) + "".join(rnd.choice("0123456789") for _ in range(n - 1))


def now_s(offset_s: int = 0) -> str:
    return (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=offset_s)).strftime(FMT)


def pix(run, tag, i, *, amount=20000, payer_doc=None, payer_acct=None, dest=None, device=None, when=None, context=None, id_=None):
    rnd = random.Random(f"{run}|{tag}|{i}")
    pdoc = payer_doc or digits(rnd, 11 if context is None else 14)
    p = {
        "id": id_ or f"{run}-{tag}-{i}",
        "amount": amount,
        "transaction_date": when or now_s(),
        "source_account": {
            "participant": "00000001", "branch": "0001",
            "account_number": payer_acct or digits(rnd, 8),
            "owner": {"document_number": pdoc},
            "opening_date": "2020-01-01T00:00:00Z",
        },
        "destination_account": {
            "participant": "00000002", "branch": "0001",
            "account_number": dest or digits(rnd, 8),
            "owner": {"document_number": digits(rnd, 11)},
            "opening_date": "2019-01-01T00:00:00Z",
        },
        "source": {"device_id": device or f"dev-{run}-{tag}-{i}", "channel": "mobile", "ip": "177.10.0.1"},
    }
    if context is not None:
        p["context"] = context
    return p


def epp_ctx(run, event, request_id=None, request_hash="hash-ok", company="emp"):
    c = {"event": event, "origin": "immediate", "company_id": f"{run}-{company}", "author_id": "socio-a",
         "account_activated_at": now_s(-200 * 86400), "request_hash": request_hash}
    if request_id:
        c["request_id"] = request_id
    return c


def codes_of(body) -> list:
    meta = (body or {}).get("metadata", {}) or {}
    if "reasons" in meta:
        return [r.get("code") for r in meta["reasons"]]
    return list(meta.get("rules_triggered", []))


# --------------------------------------------------------------------------- coleta e estatística
class Collector:
    def __init__(self):
        self.rows = []  # (phase, op, t_rel_s, latency_ms, status, ok)
        self.lock = threading.Lock()
        self.t0 = time.perf_counter()
        self.created = []  # (id, key) de POSTs 201, para a fase de GET
        self.checks = []  # (fase, nome, passou, detalhe)

    def add(self, row):
        with self.lock:
            self.rows.append(row)

    def check(self, phase, name, passed, detail=""):
        with self.lock:
            self.checks.append((phase, name, bool(passed), detail))
        print(f"   {'PASS' if passed else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))

    def remember(self, id_, key):
        with self.lock:
            if len(self.created) < 20000:
                self.created.append((id_, key))


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round(p / 100 * len(sorted_vals) + 0.5)) - 1))
    return sorted_vals[k]


def stats(rows, elapsed):
    lat = sorted(r[3] for r in rows)
    n = len(rows)
    codes = {}
    for r in rows:
        codes[r[4]] = codes.get(r[4], 0) + 1
    bad = sum(1 for r in rows if not r[5])
    return {
        "requests": n, "elapsed_s": round(elapsed, 2), "rps": round(n / elapsed, 1) if elapsed > 0 else 0,
        "errors": bad, "error_rate_pct": round(100 * bad / n, 2) if n else 0,
        "p50_ms": round(pct(lat, 50), 1), "p90_ms": round(pct(lat, 90), 1), "p95_ms": round(pct(lat, 95), 1),
        "p99_ms": round(pct(lat, 99), 1), "max_ms": round(lat[-1], 1) if lat else 0,
        "mean_ms": round(sum(lat) / n, 1) if n else 0, "status_codes": dict(sorted(codes.items())),
    }


# --------------------------------------------------------------------------- motor de carga
def run_load(col, client, phase, fn, concurrency, duration=None, total=None):
    """fn(i, call) faz 1+ chamadas via call(op, method, path, body, accept, check=None)."""
    counter = itertools.count()
    start = time.perf_counter()
    deadline = start + duration if duration else None
    rows_before = len(col.rows)

    def call(op, method, path, body, accept, check=None):
        status, data, ms = client.send(method, path, body)
        ok = status in accept and (check(status, data) if check else True)
        col.add((phase, op, time.perf_counter() - col.t0, ms, status, ok))
        return status, data

    def worker():
        while True:
            i = next(counter)
            if (total is not None and i >= total) or (deadline and time.perf_counter() >= deadline):
                return
            try:
                fn(i, call)
            except Exception as exc:  # erro no gerador de teste não pode derrubar a rodada
                col.add((phase, "exception", time.perf_counter() - col.t0, 0.0, -1, False))
                print(f"   exceção no teste: {exc!r}", file=sys.stderr)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(concurrency)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    elapsed = time.perf_counter() - start
    return stats(col.rows[rows_before:], elapsed), col.rows[rows_before:]


def burst(client, calls):
    """Dispara todas as chamadas ao mesmo tempo (barreira). calls = [(method, path, body)]."""
    n = len(calls)
    barrier = threading.Barrier(n)
    out = [None] * n

    def go(k):
        barrier.wait()
        out[k] = client.send(*calls[k])

    ts = [threading.Thread(target=go, args=(k,)) for k in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return out


# --------------------------------------------------------------------------- fases
def phase_smoke(a, col, client, run, res):
    print("\n[smoke] contrato básico")
    p = pix(run, "smoke", 0)
    s1, b1, _ = client.send("POST", client.post_path, p)
    s2, b2, _ = client.send("POST", client.post_path, p)
    s3, b3, _ = client.send("GET", f"{client.post_path}/{p['id']}")
    s4, _, _ = client.send("GET", f"{client.post_path}/{run}-inexistente")
    col.check("smoke", "POST válido devolve 201 com key e status", s1 == 201 and b1 and b1.get("key") and b1.get("status"), f"http {s1}")
    col.check("smoke", "reenvio idêntico devolve 200 com a mesma key", s2 == 200 and b2 and b1 and b2.get("key") == b1.get("key"), f"http {s2}")
    col.check("smoke", "GET devolve 200 com a mesma key", s3 == 200 and b3 and b1 and b3.get("key") == b1.get("key"), f"http {s3}")
    col.check("smoke", "GET de id inexistente devolve 404", s4 == 404, f"http {s4}")
    if s1 != 201:
        print("\nO servidor não respondeu como esperado no smoke. Confira a URL e se a API está de pé.")
        sys.exit(2)


def phase_ramp(a, col, client, run, res):
    print("\n[ramp] degraus de concorrência (Pix de pagadores distintos, sem contenção de lock)")
    out = []
    for c in a.levels:
        def fn(i, call, c=c):
            p = pix(run, f"ramp{c}", i)
            st, body = call("POST retail", "POST", client.post_path, p, {201}, lambda s, d: bool(d and d.get("key")))
            if st == 201 and body:
                col.remember(p["id"], body["key"])
        st, _ = run_load(col, client, f"ramp c={c}", fn, c, duration=a.stage_seconds)
        sustained = st["error_rate_pct"] <= a.max_error_pct and st["p95_ms"] <= a.sla_ms
        st.update(concurrency=c, within_sla=sustained)
        out.append(st)
        print(f"   c={c:<4} {st['rps']:>8} req/s  p50={st['p50_ms']:>7}ms  p95={st['p95_ms']:>7}ms  p99={st['p99_ms']:>7}ms  "
              f"erros={st['error_rate_pct']}%  {'dentro do SLA' if sustained else 'FORA do SLA'}")
    ok = [s for s in out if s["within_sla"]]
    best = max(ok, key=lambda s: s["rps"]) if ok else None
    peak = max(out, key=lambda s: s["rps"])
    res["ramp"] = {"stages": out, "sla_ms": a.sla_ms, "max_error_pct": a.max_error_pct,
                   "capacity_within_sla": best, "peak_throughput": peak}
    col.check("ramp", f"existe ao menos um degrau dentro do SLA (p95 ≤ {a.sla_ms} ms, erros ≤ {a.max_error_pct}%)", best is not None)
    if best:
        print(f"   >> capacidade sustentada dentro do SLA: {best['rps']} req/s (concorrência {best['concurrency']}); pico bruto: {peak['rps']} req/s")


def phase_idempotency(a, col, client, run, res):
    print(f"\n[idempotency] {a.storm_ids} rajadas de {a.storm_concurrency} requisições idênticas simultâneas")
    bad, lat, dup_keys, consecutive, aborted = [], [], 0, 0, None
    for k in range(a.storm_ids):
        p = pix(run, "idem", k)
        outs = burst(client.storm, [("POST", client.post_path, p)] * a.storm_concurrency)
        codes = [o[0] for o in outs]
        lat += [o[2] for o in outs]
        consecutive = consecutive + 1 if codes.count(0) >= len(codes) // 2 else 0
        if consecutive >= a.max_consecutive_fail:
            aborted = f"ABORTADA na rajada {k + 1}: {consecutive} rajadas seguidas com timeouts (possível lock preso/deadlock)"
            bad.append({"id": p["id"], "reason": aborted})
            break
        keys = {o[1].get("key") for o in outs if o[1] and o[0] in (200, 201)}
        ok = codes.count(201) == 1 and codes.count(200) == a.storm_concurrency - 1 and len(keys) == 1
        if not ok:
            bad.append({"id": p["id"], "codes": {c: codes.count(c) for c in sorted(set(codes))}, "keys": len(keys)})
        dup_keys += max(0, len(keys) - 1)
        gs, gb, _ = client.storm.send("GET", f"{client.post_path}/{p['id']}")
        if gs != 200 or (keys and gb.get("key") not in keys):
            bad.append({"id": p["id"], "get": gs})
    lat.sort()
    res["idempotency"] = {"storms": a.storm_ids, "concurrency": a.storm_concurrency, "requests": a.storm_ids * a.storm_concurrency,
                          "violations": len(bad), "aborted": aborted, "extra_keys": dup_keys, "p50_ms": round(pct(lat, 50), 1),
                          "p95_ms": round(pct(lat, 95), 1), "max_ms": round(lat[-1], 1), "examples": bad[:5]}
    col.check("idempotency", f"{a.storm_ids} rajadas: exatamente 1x 201, o resto 200, uma única key", not bad, aborted or f"{len(bad)} violações")


def phase_conflict(a, col, client, run, res):
    print(f"\n[conflict] {a.storm_ids} rajadas: mesmo id, metade com payload A e metade com payload B")
    bad, five, consecutive, aborted = [], 0, 0, None
    for k in range(a.storm_ids):
        base = pix(run, "conf", k)
        other = json.loads(json.dumps(base))
        other["amount"] += 100
        m = a.storm_concurrency
        calls = [("POST", client.post_path, base if j % 2 == 0 else other) for j in range(m)]
        outs = burst(client.storm, calls)
        codes = [o[0] for o in outs]
        five += sum(1 for c in codes if c >= 500 or c == 0)
        consecutive = consecutive + 1 if codes.count(0) >= len(codes) // 2 else 0
        if consecutive >= a.max_consecutive_fail:
            aborted = f"ABORTADA na rajada {k + 1}: {consecutive} rajadas seguidas com timeouts (possível lock preso/deadlock)"
            bad.append({"id": base["id"], "reason": aborted})
            break
        winners = [j for j, c in enumerate(codes) if c == 201]
        if len(winners) != 1:
            bad.append({"id": base["id"], "reason": "vencedores != 1", "codes": codes})
            continue
        w = winners[0] % 2
        keys = {o[1].get("key") for o in outs if o[0] in (200, 201) and o[1]}
        for j, c in enumerate(codes):
            expected = 200 if j % 2 == w else 409
            if j != winners[0] and c != expected:
                bad.append({"id": base["id"], "reason": f"req {j}: {c}, esperado {expected}"})
                break
        if len(keys) != 1:
            bad.append({"id": base["id"], "reason": "mais de uma key"})
    res["conflict"] = {"storms": a.storm_ids, "violations": len(bad), "server_errors": five, "examples": bad[:5]}
    col.check("conflict", "1 vencedor; mesmo payload = 200; payload diferente = 409; uma key", not bad, f"{len(bad)} violações")
    col.check("conflict", "nenhum 5xx nem erro de rede (violação de UNIQUE não pode vazar)", five == 0, f"{five} erros")


def phase_hot(a, col, client, run, res):
    n_ev, n_pay = a.hot_events, a.hot_payers
    print(f"\n[hot] {n_pay} pagadores × {n_ev} Pix simultâneos do MESMO pagador (compara com execução sequencial)")
    expected = max(0, n_ev - 4)  # R2: ≥ 5 Pix em 60 s, contando o atual
    when = now_s(-5)
    conc_hits, seq_hits, errors, failure_examples = [], [], 0, []
    for k in range(n_pay):
        for mode, bucket in (("conc", conc_hits), ("seq", seq_hits)):
            payer_doc, payer_acct = digits(random.Random(f"{run}|hot|{mode}|{k}"), 11), digits(random.Random(f"{run}|hotA|{mode}|{k}"), 8)
            calls = [("POST", client.post_path, pix(run, f"hot-{mode}-{k}", j, payer_doc=payer_doc, payer_acct=payer_acct,
                                                    amount=1000 + j, when=when)) for j in range(n_ev)]
            if mode == "seq":
                # Drop a stale keep-alive socket before the first serial request.
                client.local.c = None
            outs = burst(client.storm, calls) if mode == "conc" else [client.send(*c) for c in calls]
            errors += sum(1 for o in outs if o[0] != 201)
            failure_examples.extend(
                {
                    "mode": mode, "payer_index": k, "id": calls[index][2]["id"],
                    "transaction_date": calls[index][2]["transaction_date"],
                    "http": response[0], "body": response[1],
                }
                for index, response in enumerate(outs) if response[0] != 201
            )
            bucket.append(sum(1 for o in outs if o[0] == 201 and "R2" in codes_of(o[1])))
    res["hot"] = {"payers": n_pay, "events_per_payer": n_ev, "expected_r2_hits_per_payer": expected,
                  "concurrent_r2_hits": conc_hits, "sequential_r2_hits": seq_hits, "non_201": errors,
                  "failure_examples": failure_examples[:5]}
    col.check("hot", "todas as requisições da rajada retornam 201", errors == 0, f"{errors} diferentes de 201")
    col.check("hot", "concorrente == sequencial em todos os pagadores (lock evita ler histórico incompleto)",
              conc_hits == seq_hits, f"concorrente={sorted(set(conc_hits))} sequencial={sorted(set(seq_hits))}")
    col.check("hot", f"R2 acionado em {expected} dos {n_ev} Pix (do 5º em diante)", all(h == expected for h in conc_hits),
              f"observado={sorted(set(conc_hits))}")
    # latência sob contenção, para comparar com o ramp
    def fn(i, call):
        pdoc = digits(random.Random(f"{run}|hotlat"), 11)
        call("POST mesmo pagador", "POST", client.post_path,
             pix(run, "hotlat", i, payer_doc=pdoc, payer_acct="12345678", amount=1000 + i % 500), {201})
    st, _ = run_load(col, client, "hot latência", fn, a.hot_latency_concurrency, duration=a.stage_seconds)
    res["hot"]["contention_latency"] = dict(st, concurrency=a.hot_latency_concurrency)
    print(f"   contenção total (1 pagador, c={a.hot_latency_concurrency}): {st['rps']} req/s p95={st['p95_ms']}ms erros={st['error_rate_pct']}%")
    col.check("hot", f"contenção de um só pagador dentro do SLA (p95 ≤ {a.sla_ms} ms)", st["p95_ms"] <= a.sla_ms, f"p95={st['p95_ms']}ms, {st['rps']} req/s")


def phase_destination(a, col, client, run, res):
    print("\n[destination] cinco pagadores concorrentes para a mesma conta (R9)")
    result = {}
    errors = {}
    for mode in ("conc", "seq"):
        account = f"{run}-{mode}-r9"
        when = now_s(-5)
        calls = []
        for index in range(5):
            payer_doc = digits(random.Random(f"{run}|destination|{mode}|{index}"), 11)
            payload = pix(
                run, f"destination-{mode}", index, amount=250_000,
                payer_doc=payer_doc, dest=account, when=when,
            )
            payload["destination_account"]["owner"]["document_number"] = "33333333333"
            calls.append(("POST", client.post_path, payload))
        if mode == "seq":
            client.local.c = None
        responses = burst(client.storm, calls) if mode == "conc" else [client.send(*call) for call in calls]
        errors[mode] = sum(1 for status, _, _ in responses if status != 201)
        result[mode] = sum(1 for status, body, _ in responses if status == 201 and "R9" in codes_of(body))
        if errors[mode]:
            result.setdefault("failure_examples", {})[mode] = [
                {
                    "id": calls[index][2]["id"],
                    "transaction_date": calls[index][2]["transaction_date"],
                    "http": response[0],
                    "body": response[1],
                }
                for index, response in enumerate(responses) if response[0] != 201
            ]
    res["destination"] = {"r9_hits": result, "non_201": errors, "expected_r9_hits": 1}
    col.check("destination", "conta destino serializa o perfil: R9 dispara no quinto pagador", result == {"conc": 1, "seq": 1},
              f"concorrente={result.get('conc')}, sequencial={result.get('seq')}")
    col.check("destination", "todos os Pix da rajada são gravados", errors == {"conc": 0, "seq": 0}, str(errors))


def phase_execution(a, col, client, run, res):
    print("\n[execution] execuções simultâneas com o mesmo request_id (C1)")
    request_hash = f"{run}-execution-hash"
    request = pix(
        run, "execution-request", 0, amount=50_000,
        context=epp_ctx(run, "request", request_hash=request_hash, company="execution-company"),
    )
    request_status, request_body, _ = client.send("POST", client.post_path, request)
    if request_status != 201 or "C1" in codes_of(request_body):
        res["execution"] = {"request_status": request_status, "violations": ["request creation failed"]}
        col.check("execution", "pedido EPP de base criado sem C1", False, f"HTTP {request_status}")
        return
    calls = []
    for index in range(5):
        execution = pix(
            run, "execution-duplicate", index, amount=50_000,
            payer_doc=request["source_account"]["owner"]["document_number"],
            context=epp_ctx(
                run, "execution", request_id=request["id"],
                request_hash=request_hash, company="execution-company",
            ),
        )
        calls.append(("POST", client.post_path, execution))
    responses = burst(client.storm, calls)
    statuses = [status for status, _, _ in responses]
    c1_hits = sum(1 for status, body, _ in responses if status == 201 and "C1" in codes_of(body))
    allowed = sum(1 for status, body, _ in responses if status == 201 and "C1" not in codes_of(body))
    violations = sum(1 for status in statuses if status != 201) + max(0, allowed - 1) + max(0, c1_hits - 4)
    res["execution"] = {
        "request_status": request_status, "execution_statuses": statuses,
        "first_execution_without_c1": allowed, "duplicate_execution_c1": c1_hits,
        "violations": violations,
    }
    col.check("execution", "uma execução passa e as outras quatro acionam C1", allowed == 1 and c1_hits == 4,
              f"sem C1={allowed}, com C1={c1_hits}, HTTP={statuses}")
    col.check("execution", "todas as execuções duplicadas recebem resposta normal", all(status == 201 for status in statuses),
              f"HTTP={statuses}")


def phase_validation(a, col, client, run, res):
    print("\n[validation] payloads inválidos sob carga")

    def broken(mut):
        def build(i):
            p = pix(run, "val", i)
            mut(p)
            return p
        return build

    cases = [
        ("amount ausente → 422", 422, broken(lambda p: p.pop("amount"))),
        ("amount negativo → 422", 422, broken(lambda p: p.update(amount=-1))),
        ("amount decimal → 422", 422, broken(lambda p: p.update(amount=10.5))),
        ("data sem fuso → 422", 422, broken(lambda p: p.update(transaction_date="2026-01-01T10:00:00"))),
        ("documento com 10 dígitos → 422", 422, broken(lambda p: p["source_account"]["owner"].update(document_number="1234567890"))),
        ("context com event inválido → 422", 422, broken(lambda p: p.update(context=epp_ctx(run, "foo")))),
        ("vote sem request_id → 422", 422, broken(lambda p: p.update(context=epp_ctx(run, "vote")))),
        ("JSON malformado → 400", 400, lambda i: "{ isto não é json"),
    ]
    out = []
    for name, want, build in cases:
        def fn(i, call, build=build, want=want, name=name):
            call(name, "POST", client.post_path, build(i), {want})
        st, rows = run_load(col, client, f"validation: {name}", fn, a.validation_concurrency, total=a.validation_requests)
        out.append(dict(st, case=name, expected_http=want))
        col.check("validation", name, st["errors"] == 0, f"{st['requests']} req, p95={st['p95_ms']}ms, códigos={st['status_codes']}")
    res["validation"] = out


def phase_get(a, col, client, run, res):
    print("\n[get] leitura sob carga")
    if not col.created:  # roda isolada: cria massa mínima
        for i in range(200):
            p = pix(run, "getseed", i)
            s, b, _ = client.send("POST", client.post_path, p)
            if s == 201:
                col.remember(p["id"], b["key"])
    pool = list(col.created)

    def fn(i, call):
        if i % 10 == 0:
            call("GET inexistente", "GET", f"{client.post_path}/{run}-nao-existe-{i}", None, {404})
        else:
            id_, key = pool[i % len(pool)]
            call("GET existente", "GET", f"{client.post_path}/{id_}", None, {200}, lambda s, d: bool(d) and d.get("key") == key)
    st, _ = run_load(col, client, "get", fn, a.get_concurrency, duration=a.stage_seconds)
    res["get"] = dict(st, concurrency=a.get_concurrency, pool=len(pool))
    col.check("get", "todo GET devolve a mesma key do POST (200) ou 404 se inexistente", st["errors"] == 0, f"{st['requests']} req, erros={st['errors']}, p95={st['p95_ms']}ms")


def phase_mixed(a, col, client, run, res):
    print(f"\n[mixed] mistura realista, concorrência {a.mixed_concurrency}")
    pool, lock = [], threading.Lock()

    def fn(i, call):
        r = i % 10
        if r <= 5:  # 60% varejo
            p = pix(run, "mixed", i)
            st, b = call("POST retail", "POST", client.post_path, p, {201})
            if st == 201 and b:
                with lock:
                    pool.append(p)
        elif r == 6:  # 10% fluxo EPP: pedido -> execução com o mesmo hash
            req = pix(run, "mixedreq", i, context=epp_ctx(run, "request", request_hash=f"h{i}", company=f"emp{i}"))
            call("POST epp request", "POST", client.post_path, req, {201}, lambda s, d: "C1" not in codes_of(d))
            ex = pix(run, "mixedex", i, payer_doc=req["source_account"]["owner"]["document_number"],
                     context=epp_ctx(run, "execution", request_id=req["id"], request_hash=f"h{i}", company=f"emp{i}"))
            call("POST epp execution", "POST", client.post_path, ex, {201}, lambda s, d: "C1" not in codes_of(d))
        elif r == 7:  # 10% reenvio (retry do cliente)
            with lock:
                p = pool[i % len(pool)] if pool else None
            if p:
                call("POST reenvio", "POST", client.post_path, p, {200})
        elif r == 8:  # 10% inválido
            bad = pix(run, "mixedbad", i)
            bad.pop("amount")
            call("POST inválido", "POST", client.post_path, bad, {422})
        else:  # 10% GET
            with lock:
                p = pool[i % len(pool)] if pool else None
            if p:
                call("GET", "GET", f"{client.post_path}/{p['id']}", None, {200})
    st, rows = run_load(col, client, "mixed", fn, a.mixed_concurrency, duration=a.stage_seconds)
    per_op = {}
    for op in sorted({r[1] for r in rows}):
        per_op[op] = stats([r for r in rows if r[1] == op], st["elapsed_s"])
    res["mixed"] = dict(st, concurrency=a.mixed_concurrency, per_operation=per_op)
    col.check("mixed", "mistura sem erros (201/200/422 nos casos esperados, C1 não dispara no fluxo legítimo)", st["errors"] == 0,
              f"{st['requests']} req, erros={st['errors']}, {st['rps']} req/s, p95={st['p95_ms']}ms")
    col.check("mixed", f"mistura dentro do SLA (p95 ≤ {a.sla_ms} ms)", st["p95_ms"] <= a.sla_ms, f"p95={st['p95_ms']}ms, {st['rps']} req/s")


def phase_soak(a, col, client, run, res):
    if a.soak_seconds <= 0:
        return
    print(f"\n[soak] {a.soak_seconds}s a concorrência {a.soak_concurrency}")

    def fn(i, call):
        call("POST retail", "POST", client.post_path, pix(run, "soak", i), {201})
    st, rows = run_load(col, client, "soak", fn, a.soak_concurrency, duration=a.soak_seconds)
    # janelas de 10 s para ver degradação ao longo do tempo
    t0 = min(r[2] for r in rows) if rows else 0
    windows = {}
    for r in rows:
        windows.setdefault(int((r[2] - t0) // 10), []).append(r)
    series = []
    # The final requests can finish just after the 60 s deadline. Exclude a
    # partial tail window so it cannot look like a 10 s degradation interval.
    complete_windows = int(a.soak_seconds // 10)
    for w in range(complete_windows):
        s = stats(windows.get(w, []), 10)
        series.append({"window_start_s": w * 10, "rps": s["rps"], "p95_ms": s["p95_ms"], "errors": s["errors"]})
    first, last = series[0], series[-1]
    drift = (last["p95_ms"] / first["p95_ms"]) if first["p95_ms"] else 1
    res["soak"] = dict(st, concurrency=a.soak_concurrency, windows=series, p95_drift_ratio=round(drift, 2))
    col.check("soak", "sem erros e p95 da última janela ≤ 2× o da primeira (sem degradação)", st["errors"] == 0 and drift <= 2,
              f"erros={st['errors']}, p95 {first['p95_ms']}→{last['p95_ms']} ms")


PHASES = {"smoke": phase_smoke, "ramp": phase_ramp, "idempotency": phase_idempotency, "conflict": phase_conflict,
          "hot": phase_hot, "destination": phase_destination, "execution": phase_execution,
          "validation": phase_validation, "get": phase_get, "mixed": phase_mixed, "soak": phase_soak}


# --------------------------------------------------------------------------- placar
PERF_HINT = ("Criar índices compostos (coluna, transaction_date) em source_document, destination_account_key, destination_document, "
             "device_id, company_id e author_id; trocar as consultas que trazem milhares de linhas para o Python por agregações em SQL "
             "(COUNT/SUM/MAX/percentile_cont com filtro de janela e LIMIT 20 para a mediana); conferir com EXPLAIN ANALYZE que não há Seq Scan; "
             "subir mais workers só depois disso.")
HINTS = {
    "smoke": "Contrato básico quebrado: conferir URL, INTERNAL-TOKEN (--header) e se a API subiu pelo README.",
    "idempotency": "Idempotência falhou: conferir o lock do id antes do SELECT, o UNIQUE em id/transaction_id e o tratamento do IntegrityError (rollback, reler, devolver 200).",
    "conflict": "Conflito falhou: mesmo id com hash diferente deve dar 409; nenhum 5xx pode vazar do UNIQUE.",
    "hot": "Rajada do mesmo pagador: o lock do pagador precisa ser obtido na mesma transação que lê o histórico e grava; senão o R2 não dispara.",
    "destination": "Rajada por conta destino: a chave de lock da conta deve serializar a consulta agregada do R9 entre pagadores.",
    "execution": "Execuções duplicadas: o lock do pagador deve serializar a consulta por request_id e a C1 deve rejeitar reenvios.",
    "validation": "Validação: o status esperado (400/422) mudou; conferir o validador e o handler de erro.",
    "get": "GET: devolver a mesma key do POST e 404 para id inexistente, sem criar registro.",
    "mixed": "Fluxo EPP: C1 não pode disparar quando pedido e execução têm o mesmo request_hash; reenvio deve dar 200.",
}


def scorecard_lines(col, res, a):
    """Proximidade da 'Solução funcional' vista pelo teste de carga: corretude e desempenho (SLA 'poucos segundos')."""
    def is_perf(c):
        return c[0] in ("ramp", "soak") or "SLA" in c[1]
    correct = [c for c in col.checks if not is_perf(c)]
    perf = [c for c in col.checks if is_perf(c)]

    def pct_of(cs):
        return None if not cs else round(100 * sum(1 for c in cs if c[2]) / len(cs), 1)

    def fmt(v):
        return "-" if v is None else f"{v}%"

    def level(v):
        return "sem dados" if v is None else "pronto" if v >= 100 else "perto" if v >= 70 else "distante"
    L = ["", "## Proximidade do critério SOLUÇÃO FUNCIONAL (visão do teste de carga)", "",
         "| Dimensão | Nota | Situação | Itens |", "|---|---|---|---|",
         f"| Corretude (idempotência, 409, lock, validação, GET, fluxo EPP) | {fmt(pct_of(correct))} | {level(pct_of(correct))} | {sum(1 for c in correct if c[2])}/{len(correct)} |",
         f"| Desempenho (SLA p95 ≤ {a.sla_ms:g} ms, sem degradação) | {fmt(pct_of(perf))} | {level(pct_of(perf))} | {sum(1 for c in perf if c[2])}/{len(perf)} |",
         "", "Este teste não valida se a decisão bate com as regras (isso é o `run_api_tests.py` / `audit_projeto.py --scenarios`) "
         "nem o padrão de código (`audit_projeto.py`). Passe o `summary.json` ao auditor com `--load-summary` para somar tudo em uma nota.",
         "", "## O que falta ajustar", ""]
    failed = [c for c in col.checks if not c[2]]
    if not failed:
        L.append("- Nada pendente nas fases executadas.")
    for i, (phase, name, _, detail) in enumerate(failed, 1):
        L.append(f"{i}. **{phase}** — {name} ({detail})")
        L.append(f"   - Como resolver: {PERF_HINT if is_perf((phase, name)) else HINTS.get(phase, 'Ver o detalhe da verificação.')}")
    skipped = [p for p in ALL_PHASES if p not in res and p != "smoke"]
    if skipped:
        L += ["", f"Fases não executadas nesta rodada (a nota não as cobre): {', '.join(skipped)}."]
    return L


# --------------------------------------------------------------------------- relatório
def write_report(a, col, res, out_dir, run, started, total_s):
    with open(os.path.join(out_dir, "requests.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["phase", "operation", "t_rel_s", "latency_ms", "http_status", "ok"])
        w.writerows([(r[0], r[1], round(r[2], 4), round(r[3], 2), r[4], int(r[5])) for r in col.rows])
    all_stats = stats(col.rows, total_s)
    summary = {"run": run, "url": a.url, "started_at": started, "duration_s": round(total_s, 1), "overall": all_stats,
               "checks": [{"phase": p, "name": n, "passed": ok, "detail": d} for p, n, ok, d in col.checks], "phases": res}
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    L = [f"# Resultados dos testes de carga — Motor antifraude Pix (Grupo 27)", "",
         f"- Rodada `{run}` em {started} · alvo `{a.url}` · duração total {round(total_s)} s",
         f"- Total: **{all_stats['requests']}** requisições, **{all_stats['rps']} req/s** médios, p95 {all_stats['p95_ms']} ms, "
         f"p99 {all_stats['p99_ms']} ms, erros inesperados {all_stats['errors']} ({all_stats['error_rate_pct']}%)",
         f"- SLA usado: p95 ≤ {a.sla_ms} ms e erros ≤ {a.max_error_pct}%", ""]
    L += scorecard_lines(col, res, a)
    passed = sum(1 for c in col.checks if c[2])
    L += ["", f"## Verificações de corretude: {passed}/{len(col.checks)} passaram", "", "| Fase | Verificação | Resultado | Detalhe |", "|---|---|---|---|"]
    L += [f"| {p} | {n} | {'✅' if ok else '❌'} | {d} |" for p, n, ok, d in col.checks]
    if "ramp" in res:
        r = res["ramp"]
        L += ["", "## Capacidade (degraus de concorrência)", "",
              "| Concorrência | req/s | p50 ms | p95 ms | p99 ms | máx ms | erros % | no SLA |", "|---|---|---|---|---|---|---|---|"]
        L += [f"| {s['concurrency']} | {s['rps']} | {s['p50_ms']} | {s['p95_ms']} | {s['p99_ms']} | {s['max_ms']} | {s['error_rate_pct']} | {'sim' if s['within_sla'] else 'não'} |" for s in r["stages"]]
        if r["capacity_within_sla"]:
            c = r["capacity_within_sla"]
            L += ["", f"**Capacidade sustentada dentro do SLA: {c['rps']} req/s** (concorrência {c['concurrency']}). Pico bruto: {r['peak_throughput']['rps']} req/s (concorrência {r['peak_throughput']['concurrency']})."]
    if "idempotency" in res:
        i = res["idempotency"]
        L += ["", "## Idempotência sob concorrência", "",
              f"- {i['storms']} rajadas × {i['concurrency']} requisições idênticas simultâneas = {i['requests']} requisições",
              f"- Violações (≠ 1× 201 + resto 200 + uma key): **{i['violations']}**; keys duplicadas: **{i['extra_keys']}**",
              f"- Latência na rajada: p50 {i['p50_ms']} ms · p95 {i['p95_ms']} ms · máx {i['max_ms']} ms"]
    if "conflict" in res:
        c = res["conflict"]
        L += ["", "## Conflito (mesmo id, payload diferente)", "", f"- {c['storms']} rajadas · violações: **{c['violations']}** · erros 5xx/rede: **{c['server_errors']}**"]
    if "hot" in res:
        h = res["hot"]
        L += ["", "## Rajada do mesmo pagador (corrida de histórico)", "",
              f"- {h['payers']} pagadores × {h['events_per_payer']} Pix simultâneos; R2 esperado em {h['expected_r2_hits_per_payer']} por pagador",
              f"- R2 acionado, concorrente: `{h['concurrent_r2_hits']}` · sequencial: `{h['sequential_r2_hits']}`",
              f"- Contenção total (1 pagador, c={h['contention_latency']['concurrency']}): {h['contention_latency']['rps']} req/s, p95 {h['contention_latency']['p95_ms']} ms"]
    if "destination" in res:
        d = res["destination"]
        L += ["", "## Concorrência por conta destino (R9)", "",
              f"- Acionamentos R9: concorrente {d['r9_hits']['conc']} · sequencial {d['r9_hits']['seq']} · esperado {d['expected_r9_hits']}",
              f"- Respostas diferentes de 201: {d['non_201']}"]
    if "execution" in res:
        e = res["execution"]
        L += ["", "## Execuções repetidas do mesmo pedido (C1)", "",
              f"- Execuções sem C1: {e['first_execution_without_c1']} · execuções rejeitadas por C1: {e['duplicate_execution_c1']}",
              f"- Status HTTP: {e['execution_statuses']}"]
    if "validation" in res:
        L += ["", "## Validação sob carga", "", "| Caso | req | p95 ms | códigos |", "|---|---|---|---|"]
        L += [f"| {v['case']} | {v['requests']} | {v['p95_ms']} | {v['status_codes']} |" for v in res["validation"]]
    if "get" in res:
        g = res["get"]
        L += ["", "## Leitura (GET)", "", f"- c={g['concurrency']}: **{g['rps']} req/s**, p50 {g['p50_ms']} ms, p95 {g['p95_ms']} ms, p99 {g['p99_ms']} ms, erros {g['errors']}"]
    if "mixed" in res:
        m = res["mixed"]
        L += ["", "## Mistura realista", "", f"- c={m['concurrency']}: **{m['rps']} req/s**, p95 {m['p95_ms']} ms, erros {m['errors']}", "",
              "| Operação | req | p50 ms | p95 ms | p99 ms |", "|---|---|---|---|---|"]
        L += [f"| {op} | {s['requests']} | {s['p50_ms']} | {s['p95_ms']} | {s['p99_ms']} |" for op, s in m["per_operation"].items()]
    if "soak" in res:
        s = res["soak"]
        L += ["", "## Estabilidade (soak)", "", f"- {s['elapsed_s']} s a c={s['concurrency']}: **{s['rps']} req/s**, p95 {s['p95_ms']} ms, erros {s['errors']}, deriva do p95 (última/primeira janela) {s['p95_drift_ratio']}×"]
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    charts(res, out_dir)


def charts(res, out_dir):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        print("   (matplotlib não instalado: gráficos ignorados; `pip install matplotlib` para gerá-los)")
        return
    if "ramp" in res:
        st = res["ramp"]["stages"]
        x = [s["concurrency"] for s in st]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot(x, [s["rps"] for s in st], "o-", color="#2a5a9b", label="req/s")
        ax.set_xlabel("concorrência (clientes simultâneos)"); ax.set_ylabel("req/s", color="#2a5a9b")
        ax2 = ax.twinx()
        ax2.plot(x, [s["p95_ms"] for s in st], "s--", color="#b8732b", label="p95")
        ax2.plot(x, [s["p99_ms"] for s in st], "^:", color="#6c4c9a", label="p99")
        ax2.axhline(res["ramp"]["sla_ms"], color="red", lw=0.8, ls="-.")
        ax2.set_ylabel("latência (ms)")
        ax.set_title("Vazão e latência por nível de concorrência"); ax2.legend(loc="upper left")
        fig.tight_layout(); fig.savefig(os.path.join(out_dir, "ramp.png"), dpi=160); plt.close(fig)
    if "soak" in res:
        w = res["soak"]["windows"]
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot([s["window_start_s"] for s in w], [s["p95_ms"] for s in w], "o-", color="#b8732b")
        ax.set_xlabel("tempo (s)"); ax.set_ylabel("p95 (ms)"); ax.set_title("Estabilidade: p95 ao longo do tempo")
        fig.tight_layout(); fig.savefig(os.path.join(out_dir, "soak.png"), dpi=160); plt.close(fig)


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8000/pix/transaction")
    ap.add_argument("--only", default="", help=f"fases separadas por vírgula ({','.join(ALL_PHASES)})")
    ap.add_argument("--quick", action="store_true", help="rodada curta para conferir que tudo funciona")
    ap.add_argument("--levels", default="1,5,10,25,50,100", help="degraus de concorrência do ramp")
    ap.add_argument("--stage-seconds", type=int, default=15, help="duração de cada degrau/fase temporizada")
    ap.add_argument("--sla-ms", type=float, default=2000, help="p95 máximo aceito ('poucos segundos')")
    ap.add_argument("--max-error-pct", type=float, default=1.0)
    ap.add_argument("--storm-ids", type=int, default=50)
    ap.add_argument("--storm-concurrency", type=int, default=20)
    ap.add_argument("--hot-payers", type=int, default=10)
    ap.add_argument("--hot-events", type=int, default=10)
    ap.add_argument("--hot-latency-concurrency", type=int, default=20)
    ap.add_argument("--validation-requests", type=int, default=200)
    ap.add_argument("--validation-concurrency", type=int, default=10)
    ap.add_argument("--get-concurrency", type=int, default=50)
    ap.add_argument("--mixed-concurrency", type=int, default=25)
    ap.add_argument("--soak-seconds", type=int, default=60, help="0 desliga")
    ap.add_argument("--soak-concurrency", type=int, default=25)
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--storm-timeout", type=float, default=10, help="timeout das rajadas (um lock preso vira falha em segundos, não minutos)")
    ap.add_argument("--max-consecutive-fail", type=int, default=3, help="aborta idempotency/conflict após N rajadas seguidas com timeout")
    ap.add_argument("--header", action="append", default=[], help='cabeçalho extra, ex.: --header "INTERNAL-TOKEN: abc" (repetível)')
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.quick:
        a.levels, a.stage_seconds, a.storm_ids, a.hot_payers, a.validation_requests, a.soak_seconds = "1,5,10", 4, 10, 3, 40, 12
    a.levels = [int(x) for x in a.levels.split(",") if x.strip()]
    phases = [p.strip() for p in a.only.split(",") if p.strip()] or ALL_PHASES
    if "smoke" not in phases:
        phases.insert(0, "smoke")
    unknown = [p for p in phases if p not in PHASES]
    if unknown:
        ap.error(f"fase desconhecida: {unknown}")

    run = uuid.uuid4().hex[:8]
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out_dir = a.out or os.path.join("results", datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    headers = {"INTERNAL-TOKEN": os.getenv("INTERNAL_TOKEN", "default_token")}
    headers.update({k.strip(): v.strip() for k, v in (h.split(":", 1) for h in a.header)})
    client, col, res = Client(a.url, a.timeout, headers), Collector(), {}
    client.storm = Client(a.url, a.storm_timeout, headers)
    print(f"Rodada {run} contra {a.url}")
    t0 = time.perf_counter()
    try:
        for name in [p for p in ALL_PHASES if p in phases]:
            try:
                PHASES[name](a, col, client, run, res)
            except SystemExit:
                raise
            except Exception as exc:
                col.check(name, f"fase '{name}' terminou com exceção", False, repr(exc))
            write_report(a, col, res, out_dir, run, started, time.perf_counter() - t0)  # parcial: nada se perde se travar depois
    except KeyboardInterrupt:
        col.check("geral", "execução interrompida pelo usuário (relatório parcial gravado)", False)
    total = time.perf_counter() - t0
    write_report(a, col, res, out_dir, run, started, total)
    failed = [c for c in col.checks if not c[2]]
    print("\n".join(scorecard_lines(col, res, a)))
    print(f"\nRelatório em {out_dir}/report.md · {len(col.checks) - len(failed)}/{len(col.checks)} verificações passaram")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
