#!/usr/bin/env python3
"""
Single source of truth for every number the paper reports.

Reads the result files produced by run_sms.py, run_baseline.py and validate.py, and writes
paper/numbers.json. Every figure quoted in the manuscript is taken from this file, and
analysis/check_paper.py re-reads it to verify the manuscript against it.
"""
import glob, json, math, os, re, statistics as st
from collections import Counter, defaultdict
from stats_ci import ci95

SMS = os.environ.get("SMS_HOME", "/home/claude/sms")
R = os.path.join(SMS, "results")
FULL_SEEDS = [1234, 2718, 3141, 4142, 5772]
ABL_SEEDS = [1234, 2718, 3141]
EVAL = ["realworld", "booking", "cloudrun", "dispatch", "any-auto-register"]


def norm(t):
    t = (t or "")[:400]
    t = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F-]{4,}", "<uuid>", t)
    t = re.sub(r"\b\d+\b", "<n>", t)
    t = re.sub(r"'[^']*'|\"[^\"]{0,60}\"", "<lit>", t)
    return re.sub(r"\s+", " ", t).strip()[:160]


def sig(target, rec):
    return (target, rec["mr"], rec["target_op"], rec["verdict"]["kind"], norm(rec["followup"].get("body", "")))


def cause(target, rec):
    """Root cause key.

    A server error carries a diagnostic message, and distinct messages are distinct faults, so
    5xx failures are grouped by (target, kind, normalised message). For every other violation the
    response body is the object the request produced and varies with the operation, carrying no
    diagnostic information; such failures are the same fault -- one property the implementation does
    not enforce -- however many operations expose it, so they are grouped by (target, relation)."""
    if rec["verdict"]["kind"] == "server_error":
        return (target, "server_error", norm(rec["followup"].get("body", "")))
    return (target, rec["mr"], "")


def load(target, variant, seed):
    p = os.path.join(R, f"{target}_{variant}_s{seed}.json")
    return json.load(open(p)) if os.path.exists(p) else None


out = {}

# ---------------------------------------------------------------- 1. target acquisition
walk = []
for line in open(os.path.join(SMS, "walk_log.jsonl")):
    line = line.strip()
    if not line:
        continue
    try: walk.append(json.loads(line))
    except Exception: pass
outcomes = Counter(w.get("outcome") for w in walk)
screen = json.load(open(os.path.join(SMS, "screen_results.json")))
frame2 = json.load(open(os.path.join(SMS, "frame2_order.json")))
out["acquisition"] = {
    "frame1_screened": len(screen),
    "frame1_pass": sum(1 for s in screen if s.get("screen_pass")),
    "frame2_eligible": len(frame2["order"]),
    "frame2_seed": frame2.get("seed"),
    "frame2_positions_walked": len(walk),
    "frame2_outcomes": dict(outcomes),
    "frame2_booted": outcomes.get("booted", 0),
}

# ---------------------------------------------------------------- 2. attempted corpus
attempted = {}
for f in sorted(glob.glob(os.path.join(R, "*_full_s1234.json"))):
    d = json.load(open(f))
    attempted[d["target"]] = {
        "repo": d["repo"], "routes": d.get("routes"), "tables": d.get("tables"),
        "db": d.get("db"), "instantiated": d["stats"]["instantiated"],
        "executed": d["stats"]["executed"], "violations": d["stats"]["violations"],
        "requests": d["stats"]["requests"], "wall_s": d["stats"]["wall_s"],
        "invariants": d.get("invariants", {}),
        "two_principals": d["bootstrap"].get("two_principals"),
        "creates": d["seeding"].get("successful_creates"),
    }
out["attempted"] = attempted
out["n_attempted"] = len(attempted)
out["n_with_relational_state"] = sum(1 for v in attempted.values() if (v["tables"] or 0) > 0)
out["n_evaluable"] = sum(1 for v in attempted.values() if v["executed"] > 0)
out["evaluable"] = sorted(t for t, v in attempted.items() if v["executed"] > 0)

# ---------------------------------------------------------------- 3. main results (full, 5 seeds)
main = {}
for t in EVAL:
    per_seed = []
    for s in FULL_SEEDS:
        d = load(t, "full", s)
        if not d:
            continue
        vs = [r for r in d["records"] if r["verdict"].get("violation")]
        per_seed.append({
            "seed": s, "instantiated": d["stats"]["instantiated"], "executed": d["stats"]["executed"],
            "source_ok": d["stats"]["source_ok"], "failing_tests": len(vs),
            "signatures": len({sig(t, r) for r in vs}), "causes": len({cause(t, r) for r in vs}),
            "requests": d["stats"]["requests"], "wall_s": d["stats"]["wall_s"],
            "kinds": dict(Counter(r["verdict"]["kind"] for r in vs)),
            "per_relation": d["stats"]["per_relation"],
        })
    if not per_seed:
        continue
    d0 = load(t, "full", 1234)
    allv = [r for r in d0["records"] if r["verdict"].get("violation")]
    main[t] = {
        "repo": d0["repo"], "routes": d0.get("routes"), "tables": d0.get("tables"),
        "per_seed": per_seed,
        "executed_mean_ci": ci95([p["executed"] for p in per_seed]),
        "failing_mean_ci": ci95([p["failing_tests"] for p in per_seed]),
        "causes_mean_ci": ci95([p["causes"] for p in per_seed]),
        "wall_mean_ci": ci95([p["wall_s"] for p in per_seed]),
        "requests_mean_ci": ci95([p["requests"] for p in per_seed]),
        "causes_union": sorted({cause(t, r)[1:] for r in allv}),
        "kinds_union": dict(Counter(r["verdict"]["kind"] for r in allv)),
    }
out["main"] = main
out["totals_seed1234"] = {
    "failing_tests": sum(m["per_seed"][0]["failing_tests"] for m in main.values()),
    "signatures": sum(m["per_seed"][0]["signatures"] for m in main.values()),
    "causes": sum(m["per_seed"][0]["causes"] for m in main.values()),
    "executed": sum(m["per_seed"][0]["executed"] for m in main.values()),
    "instantiated": sum(m["per_seed"][0]["instantiated"] for m in main.values()),
    "requests": sum(m["per_seed"][0]["requests"] for m in main.values()),
    "wall_s": round(sum(m["per_seed"][0]["wall_s"] for m in main.values()), 1),
}

# ---------------------------------------------------------------- 4. ablations
abl = {}
for variant in ("no-state", "no-contract"):
    per_target = {}
    for t in EVAL:
        rows = []
        for s in ABL_SEEDS:
            d = load(t, variant, s)
            if not d:
                continue
            vs = [r for r in d["records"] if r["verdict"].get("violation")]
            full = load(t, "full", s)
            # the ablation is compared with the full configuration on which relation instance was
            # flagged, not on how it was classified: switching off the state oracle changes the
            # violation kind of a test that both configurations flag
            fullsigs = {(r["mr"], r["target_op"]) for r in full["records"]
                        if r["verdict"].get("violation")} if full else set()
            tp = [r for r in vs if (r["mr"], r["target_op"]) in fullsigs]
            rows.append({"seed": s, "executed": d["stats"]["executed"], "failing_tests": len(vs),
                         "causes": len({cause(t, r) for r in vs}),
                         "agreeing_with_full": len(tp),
                         "not_in_full": len(vs) - len(tp)})
        if rows:
            per_target[t] = {"rows": rows,
                             "failing_mean_ci": ci95([r["failing_tests"] for r in rows]),
                             "not_in_full_mean_ci": ci95([r["not_in_full"] for r in rows])}
    abl[variant] = per_target
out["ablations"] = abl

# state-only detections: relations whose response class was satisfied but whose state was not
state_only = 0
resp_only = 0
both = 0
for t in EVAL:
    d = load(t, "full", 1234)
    for r in d["records"]:
        v = r["verdict"]
        if not v.get("violation"):
            continue
        if v["resp_ok"] and not v["state_ok"]:
            state_only += 1
        elif not v["resp_ok"] and v["state_ok"]:
            resp_only += 1
        else:
            both += 1
out["oracle_contribution"] = {"state_only": state_only, "response_only": resp_only, "both": both}

# ---------------------------------------------------------------- 5. baseline
#
# Baseline counts must come from real Schemathesis event streams. A missing summary file or a
# missing events.ndjson is not the same fact as "the baseline found nothing" and must never be
# silently rendered as zero: that conflation is exactly how a rerun with absent evidence could
# be mistaken for a rerun that observed no baseline failures. Every target this report expects a
# baseline for is checked explicitly, and the report refuses to produce a numbers.json at all if
# any of that evidence is missing, naming every missing path so the gap can be fixed or the run
# re-launched, not guessed away.
base = {}
BEHAVIOURAL = {"not_a_server_error", "ignored_auth", "use_after_free", "ensure_resource_availability",
               "negative_data_rejection", "positive_data_acceptance"}
missing = []
for t in EVAL:
    summaries = sorted(glob.glob(os.path.join(R, "baseline", f"{t}_schemathesis_s*.json")))
    if not summaries:
        missing.append(f"{t}: no results/baseline/{t}_schemathesis_s*.json summary file")
        continue
    for f in summaries:
        meta = json.load(open(f))
        nd = os.path.join(R, "baseline", t, "events.ndjson")
        if not os.path.exists(nd):
            missing.append(f"{t}: summary {f} exists but {nd} is missing")
            continue
        if os.path.getsize(nd) == 0:
            missing.append(f"{t}: {nd} exists but is empty")
            continue
        tests = 0; sigs = set(); causes = set(); by_check = Counter()
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
                    tests += 1; by_check[c["name"]] += 1
                    sigs.add((c["name"], fi.get("operation", "?"), norm(fi.get("message", ""))))
                    causes.add((c["name"], norm(fi.get("message", ""))))
        base[t] = {"wall_s": meta["wall_s"], "timed_out": meta["timed_out"],
                   "credentialed": meta["credentialed"], "failing_tests": tests,
                   "signatures": len(sigs), "causes": len(causes),
                   "by_check": dict(by_check.most_common()),
                   "behavioural_causes": len({c for c in causes if c[0] in BEHAVIOURAL}),
                   "conformance_causes": len({c for c in causes if c[0] not in BEHAVIOURAL}),
                   "server_error_causes": len({c for c in causes if c[0] == "not_a_server_error"})}

if missing:
    raise SystemExit(
        "report.py: refusing to write paper/numbers.json — baseline evidence is missing for "
        f"{len(missing)} target(s), and a missing event stream must never be counted as zero "
        "baseline failures:\n  " + "\n  ".join(missing) +
        "\nRe-run run_baseline.py for the listed targets (or restore their events.ndjson) before "
        "regenerating numbers.json."
    )
out["baseline"] = base

# ---------------------------------------------------------------- 6. validation
vp = os.path.join(R, "validation.json")
if os.path.exists(vp):
    v = json.load(open(vp))
    out["validation"] = {"records": v, "n": len(v), "confirmed": sum(1 for x in v if x["confirmed"])}

os.makedirs(os.path.join(SMS, "paper"), exist_ok=True)
json.dump(out, open(os.path.join(SMS, "paper", "numbers.json"), "w"), indent=1, default=str)
print(json.dumps({k: out[k] for k in ("n_attempted", "n_with_relational_state", "n_evaluable",
                                      "evaluable", "totals_seed1234", "oracle_contribution")}, indent=1))
print("acquisition:", json.dumps(out["acquisition"]))
print("validation:", out.get("validation", {}).get("confirmed"), "/", out.get("validation", {}).get("n"))
