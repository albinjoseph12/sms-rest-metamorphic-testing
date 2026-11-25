#!/usr/bin/env python3
"""
Stage 6 diagnostic: compare archived (pre-Stage-5) per-target/variant/seed stats against the
freshly regenerated ones, for the 5 original FastAPI targets. Not part of the frozen analysis
pipeline (report.py/check_paper.py) -- this is a one-off audit tool for the five-target rerun.
"""
import json, os, sys

SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
OLD = os.path.join(SMS_HOME, "results", "archived_old_engine_results")
NEW = os.path.join(SMS_HOME, "results")
TARGETS = ["realworld", "booking", "cloudrun", "dispatch", "any-auto-register"]
VARIANTS = ["full", "no-state", "no-contract"]
SEEDS = {"full": [1234, 2718, 3141, 4142, 5772], "no-state": [1234, 2718, 3141], "no-contract": [1234, 2718, 3141]}


def load(base, t, v, s):
    p = os.path.join(base, f"{t}_{v}_s{s}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def main():
    print(f"{'target':20s} {'variant':12s} {'seed':6s} {'old exec/viol/req':20s} {'new exec/viol/req':20s} {'delta'}")
    for t in TARGETS:
        for v in VARIANTS:
            for s in SEEDS[v]:
                o = load(OLD, t, v, s)
                n = load(NEW, t, v, s)
                if o is None or n is None:
                    print(f"{t:20s} {v:12s} {s:<6d} {'MISSING old' if o is None else 'old ok':20s} "
                          f"{'MISSING new' if n is None else 'new ok':20s}")
                    continue
                oe, ov, orq = o["stats"]["executed"], o["stats"]["violations"], o["stats"]["requests"]
                ne, nv, nrq = n["stats"]["executed"], n["stats"]["violations"], n["stats"]["requests"]
                mark = "" if (oe, ov) == (ne, nv) else "  <-- CHANGED"
                print(f"{t:20s} {v:12s} {s:<6d} {f'{oe}/{ov}/{orq}':20s} {f'{ne}/{nv}/{nrq}':20s}{mark}")


if __name__ == "__main__":
    main()
