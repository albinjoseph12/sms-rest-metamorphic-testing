#!/usr/bin/env python3
"""Run the SMS engine (run_sms.main) inside the target container. The container is started fresh for
every run, which is the database reset; prepare is a no-op because the image already holds the
target's dependencies. Everything else - serve, bootstrap, seeding, relations - is run_sms.py as is."""
import glob, os, sys
os.environ["SMS_HOME"] = "/opt/sms"
sys.path.insert(0, "/opt/sms"); sys.path.insert(0, "/opt/sms/harness")
import boot as B
import run_sms

def fresh_reset(m):
    left = glob.glob(os.path.join(m["dir"], "**/*.db"), recursive=True)
    assert not left, f"not a fresh container: {left}"
    return {"ok": True}

B.prepare = lambda m: {"ok": True}
B.reset = fresh_reset
run_sms.main()
