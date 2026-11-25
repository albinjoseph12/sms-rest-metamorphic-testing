#!/usr/bin/env python3
import json, os, subprocess, sys, time
TARGETS = sys.argv[1:]
for t in TARGETS:
    mp = f"manifests/{t}.json"
    if not os.path.exists(mp):
        print(f"{t}: no manifest"); continue
    tid = json.load(open(mp))["id"]
    t0 = time.time()
    r = subprocess.run([sys.executable, "run_sms.py", mp], capture_output=True, text=True, timeout=3600)
    out = f"results/{tid}_full_s1234.json"
    if os.path.exists(out):
        d = json.load(open(out))
        s = d["stats"]
        print(f"{tid:24s} routes={d.get('routes')} tables={d.get('tables')} inst={s['instantiated']} exec={s['executed']} viol={s['violations']} {round(time.time()-t0,1)}s")
    else:
        print(f"{tid:24s} FAILED {(r.stdout + r.stderr).strip()[-300:]}")
