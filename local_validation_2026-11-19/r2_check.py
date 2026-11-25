# R2 independent check: does a negative "limit" on POST /api/lifecycle/check act on MORE accounts than
# a positive one? core/lifecycle.py passes the value straight to SQL LIMIT; SQLite treats a negative
# LIMIT as "no limit". Fresh offline instance, 12 accounts, no background tasks.
import json, sys
sys.path.insert(0, "/tmp")
import check as k
k.wait_ready()
for i in range(12): k.create_account(f"r2_{i}")
out = {"accounts_created": 12}
for lim in (5, 0, -5):
    a = k.snap(); r = k.req("POST", "/api/lifecycle/check", json={"limit": lim}); b = k.snap()
    out[f"limit={lim}"] = {"status": r.status_code, "resp": r.text[:200], "delta": k.counts(k.diff(a, b))}
print(json.dumps(out, ensure_ascii=False, indent=1))
