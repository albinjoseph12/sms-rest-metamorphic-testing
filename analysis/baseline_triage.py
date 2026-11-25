#!/usr/bin/env python3
"""
Triage of the Schemathesis baseline, using the same three-level counting as SMS.

Each failing check instance is a failing test. A signature is (target, check, operation, normalised
message); a root cause is (target, check, normalised message). Checks are additionally partitioned
into two classes, because they answer different questions:

  conformance   the response does not match what the document promises (undocumented status code,
                schema violation, missing Allow header, unsupported method). These are defects of
                the specification-implementation pair and are frequently properties of the document.
  behavioural   the implementation behaves incorrectly irrespective of the document
                (server error, authentication ignored, use-after-free, resource availability).

Only the behavioural class is comparable with the semantic properties SMS tests.
"""
import glob, json, os, re, sys
from collections import defaultdict

SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
RES = f"{SMS_HOME}/results/baseline"
BEHAVIOURAL = {"not_a_server_error", "ignored_auth", "use_after_free", "ensure_resource_availability",
               "negative_data_rejection", "positive_data_acceptance"}


def norm(t):
    t = (t or "")[:400]
    t = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{4,}", "<uuid>", t)
    t = re.sub(r"\b\d+\b", "<n>", t)
    t = re.sub(r"'[^']*'|\"[^\"]{0,60}\"", "<lit>", t)
    return re.sub(r"\s+", " ", t).strip()[:160]


def parse(target):
    nd = os.path.join(RES, target, "events.ndjson")
    tests, sigs, causes = 0, set(), set()
    by_check = defaultdict(int)
    if not os.path.exists(nd):
        return None
    for line in open(nd):
        try: e = json.loads(line)
        except Exception: continue
        sf = e.get("ScenarioFinished")
        if not sf or sf.get("status") != "failure":
            continue
        for case_id, checks in (sf["recorder"].get("checks") or {}).items():
            for c in checks:
                if c.get("status") != "failure":
                    continue
                fi = (c.get("failure_info") or {}).get("failure") or {}
                op = fi.get("operation", "?")
                msg = norm(fi.get("message", ""))
                tests += 1
                by_check[c["name"]] += 1
                sigs.add((c["name"], op, msg))
                causes.add((c["name"], msg))
    return {"tests": tests, "signatures": len(sigs), "causes": len(causes),
            "by_check": dict(sorted(by_check.items(), key=lambda kv: -kv[1])),
            "behavioural_tests": sum(v for k, v in by_check.items() if k in BEHAVIOURAL),
            "behavioural_causes": len({c for c in causes if c[0] in BEHAVIOURAL}),
            "conformance_causes": len({c for c in causes if c[0] not in BEHAVIOURAL}),
            "cause_list": sorted(causes)}


if __name__ == "__main__":
    rows = []
    missing = []
    for f in sorted(glob.glob(os.path.join(RES, "*_schemathesis_s*.json"))):
        meta = json.load(open(f))
        t = meta["target"]
        p = parse(t)
        if p is None:
            missing.append(f"{t}: summary {f} exists but {os.path.join(RES, t, 'events.ndjson')} is missing")
            continue
        rows.append((t, meta, p))
    if missing:
        raise SystemExit(
            "baseline_triage.py: cannot triage " + str(len(missing)) + " target(s) — the raw event "
            "stream is missing, which is not the same fact as \"no failures\":\n  " +
            "\n  ".join(missing)
        )
    print(f"{'target':16s} {'wall_s':>7s} {'fail':>5s} {'sig':>5s} {'cause':>5s} {'behav':>6s} {'bcause':>6s}")
    for t, meta, p in rows:
        print(f"{t:16s} {meta['wall_s']:7.1f} {p['tests']:5d} {p['signatures']:5d} {p['causes']:5d} "
              f"{p['behavioural_tests']:6d} {p['behavioural_causes']:6d}")
    for t, meta, p in rows:
        print(f"\n{t} by check: {p['by_check']}")
        for c in p["cause_list"]:
            if c[0] in BEHAVIOURAL:
                print(f"   behavioural: {c[0]:28s} {c[1][:110]}")
