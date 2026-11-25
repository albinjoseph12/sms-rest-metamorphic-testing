#!/usr/bin/env python3
"""Run the full evaluation matrix: every target x every variant x every seed."""
import json, os, subprocess, sys, time

TARGETS = ["realworld", "booking", "cloudrun", "auto_dispatch", "auto_any-auto-register"]
SEEDS_FULL = [1234, 2718, 3141, 4142, 5772]
SEEDS_ABL = [1234, 2718, 3141]

jobs = []
for t in TARGETS:
    for s in SEEDS_FULL:
        jobs.append((t, "full", s))
    for v in ("no-state", "no-contract"):
        for s in SEEDS_ABL:
            jobs.append((t, v, s))

for t, v, s in jobs:
    mp = f"manifests/{t}.json"
    tid = json.load(open(mp))["id"]
    out = f"results/{tid}_{v}_s{s}.json"
    if os.path.exists(out):
        print(f"skip {tid} {v} {s}", flush=True); continue
    t0 = time.time()
    r = subprocess.run([sys.executable, "run_sms.py", mp, "--variant", v, "--seed", str(s)],
                       capture_output=True, text=True, timeout=5400)
    if os.path.exists(out):
        d = json.load(open(out)); st = d["stats"]
        print(f"{tid:20s} {v:12s} s={s:5d} inst={st['instantiated']:4d} exec={st['executed']:4d} "
              f"viol={st['violations']:3d} req={st['requests']:5d} {round(time.time()-t0,1)}s", flush=True)
    else:
        print(f"{tid:20s} {v:12s} s={s:5d} FAILED {(r.stdout+r.stderr)[-200:]}", flush=True)
