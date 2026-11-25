#!/usr/bin/env python3
"""Run the SMS engine (run_sms.main) inside an offline container that holds the target, PostgreSQL and Redis.
prepare is a no-op (dependencies are baked into the image); reset is the harness's own (drop/create the database,
run the manifest's migrations), exactly as on the campaign VM. Everything else is run_sms.py unchanged."""
import os, sys
os.environ["SMS_HOME"] = "/opt/sms"
sys.path.insert(0, "/opt/sms"); sys.path.insert(0, "/opt/sms/harness")
import boot as B
import run_sms
B.prepare = lambda m: {"ok": True}
run_sms.main()
