# Does POST /api/lifecycle/check itself write tasks/task_events? Quiet instance, no background tasks.
import json, sys
sys.path.insert(0, "/tmp")
import check as k
k.wait_ready()
for i in range(3): k.create_account(f"lc{i}")
out = {}
for lim in (5, -5):
    a = k.snap(); r = k.req("POST", "/api/lifecycle/check", json={"limit": lim}); b = k.snap()
    out[f"limit={lim}"] = {"status": r.status_code, "resp": r.text[:200], "delta": k.counts(k.diff(a, b))}
a = k.snap(); import time; time.sleep(2); b = k.snap()
out["idle_2s"] = k.counts(k.diff(a, b))
print(json.dumps(out, ensure_ascii=False, indent=1))
