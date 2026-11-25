#!/usr/bin/env python3
"""
Baseline: property-based/fuzzing test generation with Schemathesis, run under the same conditions
as SMS.

Conditions held equal: the same target build, the same freshly reset database, the same credential
that SMS obtained during bootstrap, the same host and specification, and a wall-clock budget at
least as large as the one SMS consumed on that target. Failures are grouped into signatures and
root causes with the same normalisation used for SMS, so that the two techniques are compared on
distinct defects rather than on failing test counts.
"""
import argparse, json, os, subprocess, sys, time
SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
sys.path.insert(0, SMS_HOME); sys.path.insert(0, f"{SMS_HOME}/harness")
import httpx
import boot as B
from sms.engine import Engine
from sms.state import Snapshotter, delta, summarize
from run_sms import pick_db, env_credentials

ST = f"{SMS_HOME}/venvs/_baseline/bin/schemathesis"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest"); ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--seed", type=int, default=1234)
    a = ap.parse_args()
    m = B.load(a.manifest)
    tid = m["id"]
    sms_path = f"{SMS_HOME}/results/{tid}_full_s{a.seed}.json"
    sms = json.load(open(sms_path)) if os.path.exists(sms_path) else {}
    budget = a.budget or max(120.0, float(sms.get("stats", {}).get("wall_s", 0)) * 3 + 60)

    assert B.prepare(m).get("ok")
    B.reset(m)
    for _ in range(3):
        sv = B.serve(m, wait=120)
        if sv.get("ok"):
            break
        time.sleep(3)
    assert sv.get("ok"), sv
    base = f"http://127.0.0.1:{m.get('port', 9000)}"
    spec_url = base + m.get("openapi", "/openapi.json")
    spec = httpx.get(spec_url, timeout=30).json()
    kind, dsn = pick_db(m)
    snap = Snapshotter(kind, dsn)

    # the baseline is given the same credential SMS used, obtained the same way
    eng = Engine(base, spec, snap, seed=a.seed, env_creds=env_credentials(m))
    boots = eng.bootstrap()
    cred = (eng.principals.get("A") or {}).get("cred") or {}
    headers = list((cred.get("headers") or {}).items())

    kind, dsn = pick_db(m)
    snap = Snapshotter(kind, dsn)
    before = snap.snapshot()

    outdir = f"{SMS_HOME}/results/baseline/{tid}"
    os.makedirs(outdir, exist_ok=True)
    nd = os.path.join(outdir, "events.ndjson")
    cmd = [ST, "run", spec_url, "-u", base, "--checks", "all", "--continue-on-failure",
           "-w", "1", "--report", "ndjson", "--report-dir", outdir,
           "--report-ndjson-path", nd, "--warnings", "off", "--request-timeout", "10"]
    for k, v in headers:
        cmd += ["-H", f"{k}: {v}"]
    # the target must still be serving when the baseline starts
    hc = httpx.get(spec_url, timeout=10)
    assert hc.status_code == 200, hc.status_code
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=budget)
        rc, tail = r.returncode, (r.stdout + r.stderr)[-3000:]
        timed_out = False
    except subprocess.TimeoutExpired as e:
        rc, tail, timed_out = None, str(e.stdout or b"")[-2000:], True
    wall = round(time.time() - t0, 1)
    after = snap.snapshot()
    d = delta(before, after)
    B.stop(m)

    ev = []
    if os.path.exists(nd):
        for line in open(nd):
            line = line.strip()
            if line:
                try: ev.append(json.loads(line))
                except Exception: pass
    out = {"target": tid, "repo": m["repo"], "tool": "schemathesis", "budget_s": budget,
           "wall_s": wall, "timed_out": timed_out, "returncode": rc,
           "credentialed": bool(headers), "bootstrap": boots,
           "state_delta": summarize(d), "events": len(ev), "stdout_tail": tail[-1500:]}
    json.dump(out | {"raw_events_file": nd}, open(f"{SMS_HOME}/results/baseline/{tid}_schemathesis_s{a.seed}.json", "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("target", "wall_s", "timed_out", "returncode", "credentialed", "events")}))


if __name__ == "__main__":
    main()
