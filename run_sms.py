#!/usr/bin/env python3
"""
Run SMS against one target.

  run_sms.py <manifest> [--seed N] [--out FILE] [--variant full|no-state|no-contract] [--budget SEC]

variants
  full         the complete method
  no-state     ablation: the persistence-state oracle is disabled and only the response class is
               checked, which is what a response-only differential oracle can observe
  no-contract  ablation: relations are instantiated without contract-derived witnesses, i.e. the
               transformations are applied to every operation whose request happens to carry a field
               of the right primitive type; this measures what the invariant extraction contributes
"""
import argparse, glob, json, os, sys, time
SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
sys.path.insert(0, SMS_HOME)
sys.path.insert(0, f"{SMS_HOME}/harness")

import httpx
import boot as B
from sms.engine import Engine
from sms.state import Snapshotter


def candidates(m):
    """Every database the target could be writing to: the one the harness configured, plus any
    SQLite file the application created for itself. Which of them the application actually uses is
    decided empirically, after the target has served its first requests, by counting tables."""
    out = []
    if m.get("db") == "postgres":
        out.append(("postgres", f"postgresql://acb:acb@localhost:5432/{m['db_name']}"))
    seen = set()
    for pat in ("*.db", "*.sqlite", "*.sqlite3", "*/*.db", "*/*.sqlite", "*/*.sqlite3",
                "*/*/*.db", "*/*/*.sqlite3"):
        for p in glob.glob(os.path.join(m["dir"], pat)):
            rp = os.path.realpath(p)
            if rp not in seen and os.path.getsize(rp) > 0:
                seen.add(rp); out.append(("sqlite", rp))
    out.append(("sqlite", os.path.join(m["dir"], "sms_target.db")))
    return out


def pick_db(m):
    best, best_n = None, -1
    for kind, dsn in candidates(m):
        try:
            n = len(Snapshotter(kind, dsn).tables(refresh=True))
        except Exception:
            continue
        if n > best_n:
            best, best_n = (kind, dsn), n
    return best if best else ("sqlite", os.path.join(m["dir"], "sms_target.db"))


def env_credentials(m):
    """The administrator credentials the harness injected into the target's environment."""
    env = m.get("env", {}) or {}
    out = []
    for u, pw in (("ADMIN_USERNAME", "ADMIN_PASSWORD"), ("FIRST_SUPERUSER", "FIRST_SUPERUSER_PASSWORD"),
                  ("DEFAULT_USER", "DEFAULT_PASSWORD")):
        if env.get(u) and env.get(pw):
            out.append({"username": env[u], "password": env[pw],
                        "email": env.get("ADMIN_EMAIL") or (env[u] if "@" in env[u] else env[u] + "@example.com")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest"); ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--out", default=None); ap.add_argument("--variant", default="full")
    ap.add_argument("--max-per-relation", type=int, default=40)
    ap.add_argument("--keep-running", action="store_true")
    ap.add_argument("--quiet-window", type=float, default=None,
                    help="enable the oracle's quiescence control with this window in seconds (default: off, "
                         "which reproduces the oracle of the original campaign)")
    a = ap.parse_args()

    m = B.load(a.manifest)
    t0 = time.time()
    pr = B.prepare(m)
    assert pr.get("ok"), pr
    B.reset(m)
    sv = B.serve(m, wait=60)
    if not sv.get("ok"):
        print(json.dumps({"target": m["id"], "error": "boot", "detail": sv})); return
    base = f"http://127.0.0.1:{m.get('port', 9000)}"
    spec = httpx.get(base + m.get("openapi", "/openapi.json"), timeout=20).json()
    kind, dsn = pick_db(m)
    snap = Snapshotter(kind, dsn)

    env_creds = env_credentials(m)
    eng = Engine(base, spec, snap, seed=a.seed, env_creds=env_creds, quiet_window=a.quiet_window)
    if a.variant == "no-state":
        # ablation: the persistence-state oracle is switched off, leaving the response class as the
        # only observable, which is what a response-only differential oracle can see
        import sms.relations as R
        for name in R.CATALOGUE:
            R.CATALOGUE[name]["state"] = "unconstrained"
    if a.variant == "no-contract":
        import sms.contract as C
        # drop the name-based witnesses: every string field is treated as a possible temporal field,
        # every numeric field as a possible quantity, every *_id-shaped field as a possible reference
        C.QTY_NAME = C.re.compile(r".*")
        C.DATE_NAME = C.re.compile(r".*")
        C.ID_NAME = C.re.compile(r"^(\w+)$")
        eng = Engine(base, spec, snap, seed=a.seed, env_creds=env_creds, quiet_window=a.quiet_window)

    out = {"target": m["id"], "repo": m["repo"], "variant": a.variant, "seed": a.seed,
           "db": kind, "tables": len(snap.tables()), "routes": sv.get("routes"),
           "spec_title": sv.get("title"), "oracle": {"quiet_window_s": a.quiet_window}}
    out["bootstrap"] = eng.bootstrap()
    # the application has now served requests, so any lazily created schema exists: re-select the
    # database if a different candidate now holds more application tables
    k2, d2 = pick_db(m)
    if (k2, d2) != (kind, dsn) and len(Snapshotter(k2, d2).tables(refresh=True)) > len(snap.tables(refresh=True)):
        kind, dsn = k2, d2
        snap = Snapshotter(kind, dsn)
        eng.snap = snap
        out["db"] = kind
    out["db_dsn"] = dsn
    out["seeding"] = eng.seed()
    inv = eng.contract.invariants()
    out["invariants"] = {}
    for i in inv:
        out["invariants"][i["kind"]] = out["invariants"].get(i["kind"], 0) + 1
    out["stats"] = eng.run_relations(max_per_relation=a.max_per_relation)
    out["records"] = eng.records
    out["tables"] = len(snap.tables(refresh=True))
    out["total_wall_s"] = round(time.time() - t0, 1)
    if not a.keep_running:
        B.stop(m)
    path = a.out or f"{SMS_HOME}/results/{m['id']}_{a.variant}_s{a.seed}.json"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(out, open(path, "w"), indent=1)
    v = out["stats"]["violations"]
    print(json.dumps({k: out[k] for k in ("target", "variant", "routes", "tables", "invariants", "seeding")} |
                     {"stats": {k: out["stats"][k] for k in ("instantiated", "executed", "source_ok", "violations", "per_relation", "requests", "wall_s")}}, indent=1))


if __name__ == "__main__":
    main()
