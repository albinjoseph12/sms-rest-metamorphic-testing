#!/usr/bin/env python3
"""
Do the two techniques find the same defects?

For every root cause SMS reports, the operations that expose it are listed, and the baseline's
record is searched for a failure on the same operation. Three outcomes are distinguished:

  matched-crash   the baseline reported a server error on the same operation, so the same fault is
                  within its reach even though it cannot say which property was broken
  matched-other   the baseline reported some other failure on the operation, which may or may not
                  correspond to the same fault; each such case is inspected by hand
  missed          the baseline reported nothing on that operation

The comparison is conservative in the baseline's favour: any baseline failure on the operation is
counted as a possible match, so the "missed" column is a lower bound on what a response-only,
schema-driven oracle cannot see.
"""
import json, os, re
from collections import defaultdict

SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
R = f"{SMS_HOME}/results"
EVAL = ["realworld", "booking", "cloudrun", "dispatch", "any-auto-register"]


def norm_op(method, path):
    p = re.sub(r"^/api/v\d+", "", path)
    p = re.sub(r"\{[^}]+\}", "{}", p).rstrip("/")
    return f"{method.upper()} {p or '/'}"


def baseline_ops(t):
    """{normalised operation: {check: count}}"""
    nd = os.path.join(R, "baseline", t, "events.ndjson")
    out = defaultdict(lambda: defaultdict(int))
    if not os.path.exists(nd):
        return out
    for line in open(nd):
        try: e = json.loads(line)
        except Exception: continue
        sf = e.get("ScenarioFinished")
        if not sf or sf.get("status") != "failure":
            continue
        for _, checks in (sf["recorder"].get("checks") or {}).items():
            for c in checks:
                if c.get("status") != "failure":
                    continue
                fi = (c.get("failure_info") or {}).get("failure") or {}
                op = fi.get("operation", "")
                if " " not in op:
                    continue
                meth, path = op.split(" ", 1)
                out[norm_op(meth, path)][c["name"]] += 1
    return out


rows = []
for t in EVAL:
    p = os.path.join(R, f"{t}_full_s1234.json")
    if not os.path.exists(p):
        continue
    d = json.load(open(p))
    bops = baseline_ops(t)
    groups = defaultdict(list)
    for r in d["records"]:
        if not r["verdict"].get("violation"):
            continue
        if r["verdict"]["kind"] == "server_error":
            msg = re.sub(r"\b\d+\b", "<n>", (r["followup"].get("body") or ""))[:120]
            msg = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{4,}", "<uuid>", msg)
            key = ("server_error", msg)
        else:
            key = (r["mr"], "")
        groups[key].append(r)
    for key, recs in sorted(groups.items()):
        ops = sorted({norm_op(r["method"], r["path"]) for r in recs})
        hit_crash = [o for o in ops if bops.get(o, {}).get("not_a_server_error")]
        hit_other = [o for o in ops if o in bops and o not in hit_crash]
        missed = [o for o in ops if o not in bops]
        verdict = ("matched-crash" if hit_crash else
                   "matched-other" if hit_other else "missed")
        rows.append({"target": t, "group": key[0], "detail": key[1], "kind": recs[0]["verdict"]["kind"],
                     "n_failing": len(recs), "n_ops": len(ops),
                     "ops_matched_crash": len(hit_crash), "ops_matched_other": len(hit_other),
                     "ops_missed": len(missed), "verdict": verdict,
                     "example_op": ops[0]})

json.dump(rows, open(os.path.join(R, "comparison.json"), "w"), indent=1)
print(f"{'target':18s} {'group':26s} {'kind':22s} {'fail':>4s} {'ops':>4s} "
      f"{'crash':>5s} {'other':>5s} {'miss':>4s}  verdict")
for r in rows:
    print(f"{r['target']:18s} {r['group'][:26]:26s} {r['kind']:22s} {r['n_failing']:4d} {r['n_ops']:4d} "
          f"{r['ops_matched_crash']:5d} {r['ops_matched_other']:5d} {r['ops_missed']:4d}  {r['verdict']}")
