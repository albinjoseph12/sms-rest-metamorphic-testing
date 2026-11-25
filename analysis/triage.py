#!/usr/bin/env python3
"""
Failing tests -> unique failure signatures -> unique root causes.

A relation that fails many times is not many defects. Three counts are reported and kept distinct
throughout the paper:

  failing tests        every executed relation instance whose verdict is a violation
  failure signatures   equivalence classes of failing tests under
                       (target, relation, operation, violation kind, normalised response message)
  root causes          equivalence classes of signatures under (target, violation kind, normalised
                       message), i.e. the distinct ways the implementation goes wrong, irrespective
                       of how many operations expose them

Normalisation removes the parts of a message that vary with the request (identifiers, quoted
literals, numbers), so that the same fault reached through twenty operations is one signature per
operation and one root cause overall.
"""
import glob, json, os, re, sys
from collections import Counter, defaultdict

RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def norm(text: str) -> str:
    t = (text or "")[:400]
    t = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{4,}", "<uuid>", t)
    t = re.sub(r"\b\d+\b", "<n>", t)
    t = re.sub(r"'[^']*'|\"[^\"]{0,60}\"", "<lit>", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:160]


def load(variant="full", seed=1234):
    return [json.load(open(f)) for f in sorted(glob.glob(os.path.join(RESULTS, f"*_{variant}_s{seed}.json")))]


def triage(runs):
    tests = 0
    sigs, causes = set(), set()
    per_target = defaultdict(lambda: {"tests": 0, "sigs": set(), "causes": set()})
    rows = []
    for d in runs:
        t = d["target"]
        for r in d.get("records", []):
            if not r["verdict"].get("violation"):
                continue
            kind = r["verdict"]["kind"]
            msg = norm(r["followup"].get("body", ""))
            sig = (t, r["mr"], r["target_op"], kind, msg)
            cause = (t, "server_error", msg) if kind == "server_error" else (t, r["mr"], "")
            tests += 1
            sigs.add(sig); causes.add(cause)
            per_target[t]["tests"] += 1
            per_target[t]["sigs"].add(sig); per_target[t]["causes"].add(cause)
            rows.append({"target": t, "mr": r["mr"], "op": r["target_op"], "method": r["method"],
                         "path": r["path"], "kind": kind, "status": r["followup"]["status"],
                         "msg": msg,
                         "state": r["followup"]["delta"]["n_inserted"] + r["followup"]["delta"]["n_modified"]
                                  + r["followup"]["delta"]["n_deleted"]})
    return tests, sigs, causes, per_target, rows


if __name__ == "__main__":
    variant = sys.argv[1] if len(sys.argv) > 1 else "full"
    runs = load(variant)
    tests, sigs, causes, per_target, rows = triage(runs)
    print(f"variant={variant}  targets={len(runs)}  failing tests={tests}  "
          f"signatures={len(sigs)}  root causes={len(causes)}\n")
    print(f"{'target':16s} {'routes':>6s} {'tbl':>4s} {'inst':>5s} {'exec':>5s} {'fail':>5s} {'sig':>4s} {'cause':>5s}")
    for d in runs:
        t = d["target"]; s = d["stats"]; p = per_target[t]
        print(f"{t:16s} {d.get('routes',0):6d} {d.get('tables',0):4d} {s['instantiated']:5d} "
              f"{s['executed']:5d} {p['tests']:5d} {len(p['sigs']):4d} {len(p['causes']):5d}")
    print("\nroot causes")
    for c in sorted(causes):
        sel = [r for r in rows if (r["target"], r["kind"], r["msg"]) == c]
        ops = sorted({r["op"] for r in sel}); mrs = sorted({r["mr"] for r in sel})
        print(f"  [{c[0]}] {c[1]:22s} tests={len(sel):3d} ops={len(ops):3d} "
              f"mrs={','.join(m.split('_')[0] for m in mrs)}")
        print(f"      {c[2][:150]}")
