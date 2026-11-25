#!/usr/bin/env python3
"""Run the campaign's baseline script (run_baseline.main) unchanged inside a fresh offline container;
the fresh container is the database reset (see run_local.py)."""
import glob, os, sys
os.environ["SMS_HOME"] = "/opt/sms"
sys.path.insert(0, "/opt/sms"); sys.path.insert(0, "/opt/sms/harness")
import boot as B
def fresh_reset(m):
    left = glob.glob(os.path.join(m["dir"], "**/*.db"), recursive=True)
    assert not left, f"not a fresh container: {left}"
    return {"ok": True}
B.prepare = lambda m: {"ok": True}
B.reset = fresh_reset
import run_baseline
run_baseline.main()
