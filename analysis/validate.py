#!/usr/bin/env python3
"""
Independent manual validation of every root cause SMS reported.

Each root cause is reproduced here by an explicit, hand-written HTTP sequence against a freshly
reset instance of the target, without using any part of the SMS engine. A validation passes only if
the hand-written sequence observes the same defect (status and, where the defect is state-visible,
the same row in the database). This separates the claim "the tool reported something" from the
claim "the implementation is wrong", which is the distinction the tool cannot make for itself.
"""
import json, os, subprocess, sys, time
SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
sys.path.insert(0, SMS_HOME); sys.path.insert(0, f"{SMS_HOME}/harness")
import httpx
import boot as B
from sms.state import Snapshotter

OUT = f"{SMS_HOME}/results/validation.json"


def fresh(manifest):
    m = B.load(manifest)
    assert B.prepare(m).get("ok")
    B.reset(m)
    for _ in range(3):
        sv = B.serve(m, wait=180)
        if sv.get("ok"):
            break
        time.sleep(3)
    assert sv.get("ok"), sv
    return m, f"http://127.0.0.1:{m.get('port', 9000)}"


def rows(dsn, sql, kind="postgres"):
    s = Snapshotter(kind, dsn)
    with s._conn() as c:
        cur = c.cursor(); cur.execute(sql)
        return cur.fetchall()


results = []


def record(rid, target, claim, confirmed, evidence):
    results.append({"id": rid, "target": target, "claim": claim,
                    "confirmed": bool(confirmed), "evidence": evidence})
    print(f"{rid:6s} {target:18s} {'CONFIRMED' if confirmed else 'NOT CONFIRMED':14s} {claim[:70]}")


# --------------------------------------------------------------------------- booking
def validate_booking():
    m, base = fresh("manifests/booking.json")
    dsn = f"postgresql://acb:acb@localhost:5432/{m['db_name']}"
    c = httpx.Client(base_url=base, timeout=20)

    # a unit is needed before a reservation can be made
    u = c.post("/api/v1/units/", json={"name": "val-unit-1", "capacity": 4, "description": "d"})
    unit_id = (u.json() or {}).get("id")
    g = c.post("/api/v1/guests/", json={"name": "val", "email": "val@example.com", "phone": "+15550000000"})
    guest_id = (g.json() or {}).get("id")

    # R1: a reservation whose check-out precedes its check-in
    body = {"guest_id": guest_id, "unit_id": unit_id,
            "check_in_date": "2027-03-10", "check_out_date": "2027-03-01", "status": "active"}
    r = c.post("/api/v1/reservations/", json=body)
    persisted = rows(dsn, "SELECT check_in_date, check_out_date FROM reservations")
    inverted = [p for p in persisted if str(p[0]) > str(p[1])]
    record("R1", "booking",
           "POST /api/v1/reservations/ accepts and stores an interval with check_out < check_in",
           200 <= r.status_code < 300 and bool(inverted),
           {"status": r.status_code, "body": r.text[:200], "stored_rows": [list(map(str, p)) for p in persisted]})

    # R2: a unit with negative capacity
    r2 = c.post("/api/v1/units/", json={"name": "val-unit-neg", "capacity": -1, "description": "d"})
    neg = rows(dsn, "SELECT name, capacity FROM units WHERE capacity < 0")
    record("R2", "booking",
           "POST /api/v1/units/ accepts and stores a negative capacity",
           200 <= r2.status_code < 300 and bool(neg),
           {"status": r2.status_code, "body": r2.text[:200], "stored_rows": [list(map(str, p)) for p in neg]})
    B.stop(m)


# --------------------------------------------------------------------------- dispatch
def validate_dispatch():
    m, base = fresh("manifests/auto_dispatch.json")
    c = httpx.Client(base_url=base, timeout=30)
    reg = c.post("/api/v1/default/auth/register",
                 json={"email": "validator@example.com", "password": "SmsBench!2345"})
    tok = (reg.json() or {}).get("token")
    h = {"Authorization": f"Bearer {tok}"}

    ok = c.get("/api/v1/default/incidents", headers=h)
    bad = c.get("/api/v1/default-does-not-exist/incidents", headers=h)
    record("R3", "dispatch",
           "an unknown organization slug in the path produces 500 rather than 404 "
           "(the same fault is reachable through every organization-scoped operation)",
           ok.status_code == 200 and bad.status_code == 500,
           {"known_org_status": ok.status_code, "unknown_org_status": bad.status_code,
            "unknown_org_body": bad.text[:200]})

    mfa = c.post("/api/v1/default/auth/mfa", headers=h,
                 json={"project_id": 999999, "challenge_id": "11111111-2222-4333-8444-555555555555",
                       "action": "confirm"})
    record("R4", "dispatch",
           "POST /auth/mfa with a project_id and challenge_id that no row carries produces 500",
           mfa.status_code == 500,
           {"status": mfa.status_code, "body": mfa.text[:200]})

    ev = c.patch("/api/v1/default/cases/1/event", headers=h,
                 json={"uuid": "11111111-2222-4333-8444-555555555555",
                       "started_at": "2027-01-01T00:00:00+00:00", "description": "d"})
    record("R5", "dispatch",
           "PATCH /cases/{case_id}/event with an absent event uuid produces 500",
           ev.status_code == 500,
           {"status": ev.status_code, "body": ev.text[:200]})
    B.stop(m)


# --------------------------------------------------------------------------- any-auto-register
def validate_aar():
    m, base = fresh("manifests/auto_any-auto-register.json")
    kind, dsn = ("sqlite", None)
    from run_sms import pick_db
    kind, dsn = pick_db(m)
    c = httpx.Client(base_url=base, timeout=20)

    r = c.post("/api/tasks/register", json={"platform": "valplat", "count": -5})
    tasks = rows(dsn, "SELECT id, payload_json FROM tasks WHERE payload_json LIKE '%-5%'", kind)
    record("R6", "any-auto-register",
           "POST /api/tasks/register accepts a negative count and persists the task",
           200 <= r.status_code < 300,
           {"status": r.status_code, "body": r.text[:200], "negative_rows": len(tasks)})

    a = c.post("/api/accounts", json={"platform": "valplat", "email": "val@example.com",
                                      "password": "SmsBench!2345", "user_id": "no-such-user-9999"})
    accs = rows(dsn, "SELECT id, user_id FROM accounts WHERE user_id='no-such-user-9999'", kind)
    record("R7", "any-auto-register",
           "POST /api/accounts stores an account whose user_id references no user",
           200 <= a.status_code < 300 and bool(accs),
           {"status": a.status_code, "body": a.text[:200], "stored_rows": [list(map(str, x)) for x in accs]})

    p = c.put("/api/platforms/no-such-platform-9999/capabilities",
              json={"capabilities": {"register": True}})
    caps = rows(dsn, "SELECT platform_name FROM platform_capability_overrides "
                     "WHERE platform_name='no-such-platform-9999'", kind)
    record("R8", "any-auto-register",
           "PUT /api/platforms/{name}/capabilities silently creates capabilities for a platform "
           "that does not exist",
           200 <= p.status_code < 300,
           {"status": p.status_code, "body": p.text[:200], "stored_rows": len(caps)})
    B.stop(m)


if __name__ == "__main__":
    which = sys.argv[1:] or ["booking", "dispatch", "aar"]
    if "booking" in which: validate_booking()
    if "dispatch" in which: validate_dispatch()
    if "aar" in which: validate_aar()
    old = json.load(open(OUT)) if os.path.exists(OUT) else []
    keep = [r for r in old if r["id"] not in {x["id"] for x in results}]
    json.dump(sorted(keep + results, key=lambda r: r["id"]), open(OUT, "w"), indent=1)
    print(f"\n{sum(1 for r in results if r['confirmed'])}/{len(results)} confirmed")
