"""Triage a Schemathesis events.ndjson exactly as analysis/report.py does (same norm, same classes)."""
import json, re, sys
from collections import Counter
BEHAVIOURAL = {"not_a_server_error", "ignored_auth", "use_after_free", "ensure_resource_availability",
               "negative_data_rejection", "positive_data_acceptance"}
def norm(t):
    t = (t or "")[:400]
    t = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{4,}", "<uuid>", t)
    t = re.sub(r"\b\d+\b", "<n>", t)
    t = re.sub(r"'[^']*'|\"[^\"]{0,60}\"", "<lit>", t)
    return re.sub(r"\s+", " ", t).strip()[:160]
def triage(nd):
    tests = 0; causes = set(); by = Counter(); ops = Counter()
    for line in open(nd):
        try: e = json.loads(line)
        except Exception: continue
        sf = e.get("ScenarioFinished")
        if not sf or sf.get("status") != "failure": continue
        for _, checks in (sf["recorder"].get("checks") or {}).items():
            for c in checks:
                if c.get("status") != "failure": continue
                fi = (c.get("failure_info") or {}).get("failure") or {}
                tests += 1; by[c["name"]] += 1
                causes.add((c["name"], norm(fi.get("message", ""))))
    return {"failing_tests": tests, "causes": len(causes),
            "behavioural_causes": len({c for c in causes if c[0] in BEHAVIOURAL}),
            "conformance_causes": len({c for c in causes if c[0] not in BEHAVIOURAL}),
            "by_check": dict(by.most_common())}
for p in sys.argv[1:]:
    print(p.split("/")[-3:], json.dumps(triage(p)))
