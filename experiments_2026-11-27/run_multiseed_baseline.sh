#!/usr/bin/env bash
set -u
cd /Users/albinjoseph/sms-research/local_validation_2026-11-19
OUT=results/multiseed_baseline_2026-11-27
CS=/Users/albinjoseph/sms-research/corrected_sms

# Create a wrapper that passes --seed to schemathesis
cat <<'PY' > "$OUT/run_baseline_seeded.py"
import glob, os, sys
os.environ["SMS_HOME"] = "/opt/sms"
sys.path.insert(0, "/opt/sms"); sys.path.insert(0, "/opt/sms/harness")
import boot as B, subprocess

def fresh_reset(m):
    left = glob.glob(os.path.join(m["dir"], "**/*.db"), recursive=True)
    assert not left, f"not a fresh container: {left}"
    return {"ok": True}
B.prepare = lambda m: {"ok": True}
B.reset = fresh_reset

# Patch subprocess.run to inject --seed into schemathesis invocation
_orig_run = subprocess.run
_seed = None
for i, arg in enumerate(sys.argv):
    if arg == "--seed" and i + 1 < len(sys.argv):
        _seed = sys.argv[i + 1]
def patched_run(cmd, *args, **kwargs):
    if isinstance(cmd, list) and len(cmd) > 1 and "schemathesis" in str(cmd[0]) and _seed:
        cmd = list(cmd) + ["--seed", str(_seed)]
    return _orig_run(cmd, *args, **kwargs)
subprocess.run = patched_run

import run_baseline
run_baseline.main()
PY

for s in 1234 2718 3141 4142 5772; do
  cname="sms-mb-s${s}"
  docker rm -f "$cname" >/dev/null 2>&1
  docker run -d --name "$cname" --network none sms-base:ba10042 sleep infinity >/dev/null
  for p in sms harness run_sms.py run_baseline.py; do docker cp "$CS/$p" "$cname":/opt/sms/ >/dev/null; done
  docker exec "$cname" mkdir -p /opt/sms/manifests /opt/sms/results/baseline
  docker cp "$CS/manifests/auto_any-auto-register.json" "$cname":/opt/sms/manifests/ >/dev/null
  docker cp "$OUT/run_baseline_seeded.py" "$cname":/opt/sms/run_baseline_seeded.py >/dev/null
  t0=$(date +%s)
  docker exec -w /opt/sms "$cname" /opt/harness/bin/python run_baseline_seeded.py manifests/auto_any-auto-register.json \
      --seed "$s" --budget 300 > "$OUT/s${s}.log" 2>&1
  docker cp "$cname":/opt/sms/results/baseline/any-auto-register/events.ndjson "$OUT/events_s${s}.ndjson" >/dev/null 2>&1 || echo "NO NDJSON s$s"
  docker cp "$cname":/opt/sms/results/baseline/any-auto-register_schemathesis_s${s}.json "$OUT/summary_s${s}.json" >/dev/null 2>&1 || echo "NO SUMMARY s$s"
  docker rm -f "$cname" >/dev/null
  echo "$(date +%H:%M:%S) done baseline s${s} wall=$(( $(date +%s)-t0 ))s"
done
echo "MULTISEED BASELINE COMPLETE"
