#!/usr/bin/env python3
"""
Independent re-check of SMS root causes R4 (MR7, absent platform accepted) and R5 (MR5, repeated
delete has side effects) on any-auto-register @ ba1004241f4be7b0bb11b705b7c88a684e42b3db.

Deliberately does NOT import anything from the SMS engine: plain HTTP (httpx) and a direct read of
the target's SQLite file (sqlite3, `SELECT rowid, *`). Run inside the target's container, which has
no network access, against a freshly started instance:

    python independent_check_r4_r5.py <experiment>     experiment = r4 | r5_quiet | r5_tasks

Prints one JSON document with every request, status and row-level difference.
"""
import json, sqlite3, sys, time
import httpx

DB = "/app/account_manager.db"
BASE = "http://127.0.0.1:9110"
# no keep-alive: a request that crashes the server's handler must not poison the next request
c = httpx.Client(base_url=BASE, timeout=20, limits=httpx.Limits(max_keepalive_connections=0))
log = []


def tables():
    with sqlite3.connect(DB) as db:
        return sorted(r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))


def snap():
    out = {}
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        for t in tables():
            out[t] = {r["rowid"]: dict(r) for r in db.execute(f'SELECT rowid AS rowid, * FROM "{t}"')}
    return out


def diff(a, b):
    d = {}
    for t in sorted(set(a) | set(b)):
        x, y = a.get(t, {}), b.get(t, {})
        ins = [y[k] for k in y if k not in x]
        dele = [x[k] for k in x if k not in y]
        mod = [{"before": x[k], "after": y[k]} for k in x if k in y and x[k] != y[k]]
        if ins or dele or mod:
            d[t] = {"inserted": ins, "deleted": dele, "modified": mod}
    return d


def counts(d):
    return {t: {k: len(v) for k, v in e.items()} for t, e in d.items()}


def req(method, path, **kw):
    r = c.request(method, path, **kw)
    entry = {"req": f"{method} {path}", "body": kw.get("json"), "status": r.status_code, "resp": r.text[:300]}
    log.append(entry)
    return r


def wait_ready():
    for _ in range(60):
        try:
            if c.get("/openapi.json").status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise SystemExit("target not ready")


def create_account(tag):
    r = req("POST", "/api/accounts", json={"platform": "anything", "email": f"{tag}@example.com",
                                           "password": "Pw-123456"})
    return r.json()["id"]


def r5(with_tasks):
    res = {"experiment": "r5_tasks" if with_tasks else "r5_quiet"}
    if with_tasks:
        # the SMS bootstrap used POST /api/tasks/register; the target's background task runtime then
        # executes those tasks (they fail without network) and writes tasks / task_events on its own
        for i in range(3):
            req("POST", "/api/tasks/register", json={"platform": "anything", "count": 2})
        time.sleep(1.0)
    acct = create_account("r5")
    # idle control: no request at all between two snapshots
    s_idle0 = snap(); time.sleep(1.0); s_idle1 = snap()
    res["idle_1s_no_request"] = counts(diff(s_idle0, s_idle1))
    # read-only control: a GET between two snapshots
    s_g0 = snap(); req("GET", "/api/platforms"); s_g1 = snap()
    res["readonly_get"] = counts(diff(s_g0, s_g1))
    s0 = snap(); r1 = req("DELETE", f"/api/accounts/{acct}"); s1 = snap()
    r2 = req("DELETE", f"/api/accounts/{acct}"); s2 = snap()
    res["first_delete"] = {"status": r1.status_code, "delta": counts(diff(s0, s1))}
    d2 = diff(s1, s2)
    res["second_delete"] = {"status": r2.status_code, "body": r2.text, "delta": counts(d2),
                            "inserted_or_modified_rows": {t: e["inserted"][:5] + [m["after"] for m in e["modified"][:5]]
                                                          for t, e in d2.items()}}
    # does any row written during the second delete mention the deleted account?
    blob = json.dumps(d2, ensure_ascii=False, default=str)
    res["second_delete_rows_mention_account"] = (f'"account_id": {acct}' in blob) or (f"r5@example.com" in blob)
    # repeat the second-delete measurement 10 times to see how often a delta appears
    hits = 0
    for _ in range(10):
        a = snap(); req("DELETE", f"/api/accounts/{acct}"); b = snap()
        hits += bool(diff(a, b))
    res["repeat_missing_delete_with_delta"] = f"{hits}/10"
    hits = 0
    for _ in range(10):
        a = snap(); req("GET", "/api/platforms"); b = snap()
        hits += bool(diff(a, b))
    res["repeat_readonly_get_with_delta"] = f"{hits}/10"
    return res


def r4():
    res = {"experiment": "r4"}
    names = [p["name"] for p in req("GET", "/api/platforms").json()]
    absent = "sms-absent-platform-7f3a"
    assert absent not in names
    res["absent_name_is_not_a_platform"] = True
    body = {"capabilities": ["sms-check"]}
    s0 = snap(); rc = req("PUT", "/api/platforms/anything/capabilities", json=body); s1 = snap()
    rf = req("PUT", f"/api/platforms/{absent}/capabilities", json=body); s2 = snap()
    res["control_put_real_platform"] = {"status": rc.status_code, "body": rc.text, "delta": counts(diff(s0, s1))}
    df = diff(s1, s2)
    res["followup_put_absent_platform"] = {"status": rf.status_code, "body": rf.text, "delta": counts(df),
                                           "inserted": {t: e["inserted"] for t, e in df.items()}}
    names_after = [p["name"] for p in req("GET", "/api/platforms").json()]
    res["absent_name_listed_after_put"] = absent in names_after
    try:
        r404 = req("GET", f"/api/actions/{absent}/capabilities")
        res["other_endpoint_on_absent_name"] = {"status": r404.status_code, "body": r404.text[:200]}
    except httpx.HTTPError as e:
        res["other_endpoint_on_absent_name"] = {"error": type(e).__name__}
        wait_ready()
    absent2 = "sms-absent-platform-9c1d"
    s3 = snap(); rd = req("DELETE", f"/api/platforms/{absent2}/capabilities"); s4 = snap()
    res["delete_absent_platform_never_written"] = {"status": rd.status_code, "body": rd.text, "delta": counts(diff(s3, s4))}
    s5 = snap(); rd2 = req("DELETE", f"/api/platforms/{absent}/capabilities"); s6 = snap()
    res["delete_absent_platform_after_put"] = {"status": rd2.status_code, "body": rd2.text, "delta": counts(diff(s5, s6))}
    return res


def r5_active():
    """Same comparison while the background task runtime is busy: if the delta seen around an
    already-failed delete comes from the background runtime, a read-only GET sees deltas at a
    similar rate and the rows written do not refer to the deleted account."""
    res = {"experiment": "r5_active"}
    acct = create_account("r5a")
    req("DELETE", f"/api/accounts/{acct}")
    for i in range(6):
        req("POST", "/api/tasks/register", json={"platform": "anything", "count": 5})
    n = 30
    tally = {"missing_delete": 0, "readonly_get": 0, "no_request": 0}
    samples = {}
    for i in range(n):
        for kind in ("missing_delete", "readonly_get", "no_request"):
            a = snap()
            if kind == "missing_delete":
                r = req("DELETE", f"/api/accounts/{acct}")
                assert r.status_code == 404
            elif kind == "readonly_get":
                req("GET", "/api/platforms")
            else:
                time.sleep(0.01)
            b = snap()
            d = diff(a, b)
            if d:
                tally[kind] += 1
                samples.setdefault(kind, {"delta": counts(d), "rows": {t: (e["inserted"] + [m["after"] for m in e["modified"]])[:3]
                                                                      for t, e in d.items()}})
    res["trials_per_kind"] = n
    res["trials_with_state_delta"] = tally
    res["example_delta"] = samples
    blob = json.dumps(samples, ensure_ascii=False, default=str)
    res["any_row_mentions_deleted_account"] = (f'"account_id": {acct}' in blob) or ("r5a@example.com" in blob)
    return res


if __name__ == "__main__":
    wait_ready()
    exp = sys.argv[1]
    out = r4() if exp == "r4" else r5_active() if exp == "r5_active" else r5(exp == "r5_tasks")
    out["requests"] = log
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
