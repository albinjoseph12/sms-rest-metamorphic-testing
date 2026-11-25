#!/usr/bin/env python3
"""
Verify the manuscript against paper/numbers.json.

Every claim below names a number that appears in the text and recomputes it from the result files.
The script exits non-zero if any check fails, so the manuscript cannot drift from the data.
"""
import json, math, os, re, statistics as st, sys
from stats_ci import ci95

SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
N = json.load(open(f"{SMS_HOME}/paper/numbers.json"))
TXT = open(f"{SMS_HOME}/paper/sms_paper.md").read()
fails, checks = [], 0


def ck(name, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        fails.append(f"{name}: {detail}")
    print(f"{'PASS' if ok else 'FAIL':4s}  {name}  {detail}")


def in_text(s):
    return s in TXT


A = N["acquisition"]; T = N["totals_seed1234"]; M = N["main"]; B = N["baseline"]

ck("frame1 screened = 62", A["frame1_screened"] == 62 and in_text("62 repositories"))
ck("frame1 pass = 10", A["frame1_pass"] == 10 and in_text("of which 10 satisfy C1"))
ck("frame2 eligible = 699", A["frame2_eligible"] == 699 and in_text("699 are eligible"))
ck("frame2 seed", str(A["frame2_seed"]) == "20260906" and in_text("seed 20260906"))
ck("positions walked = 271", A["frame2_positions_walked"] == 271 and in_text("271 positions"))
o = A["frame2_outcomes"]
ck("outcomes 29/132/67/40/3",
   (o.get("booted"), o.get("boot_failed"), o.get("no_asgi_app"), o.get("clone_failed"),
    o.get("harness_error")) == (29, 132, 67, 40, 3) and
   in_text("29 booted, 132 failed to boot, 67 exposed no module-level ASGI application, 40 failed to clone, and 3"))
ck("attempted = 24", N["n_attempted"] == 24 and in_text("24 targets that booted"))
ck("with tables = 13", N["n_with_relational_state"] == 13 and in_text("13 exposed at least one application table"))
ck("evaluable = 5", N["n_evaluable"] == 5 and in_text("5 satisfied the scope condition"))

ck("instantiated = 677", T["instantiated"] == 677 and in_text("| **677** |"))
ck("executed = 75", T["executed"] == 75 and in_text("executed 75 relation instances"))
ck("failing tests = 46", T["failing_tests"] == 46 and in_text("46 failing tests"))
ck("signatures = 46", T["signatures"] == 46 and in_text("46 signatures"))
ck("root causes = 4", T["causes"] == 4 and in_text("4 root causes"))
ck("requests = 1552", T["requests"] == 1552 and in_text("1,552 requests"))
ck("wall = 1017.8", abs(T["wall_s"] - 1017.8) < 0.5 and in_text("1,017.8 s of wall-clock") and in_text("| **1,017.8** |"))

for t, row in [("realworld", (19, 40, 7, 0, 91, 8.8)), ("cloudrun", (14, 22, 7, 0, 66, 6.5)),
               ("booking", (9, 8, 1, 0, 30, 2.9)), ("any-auto-register", (75, 30, 14, 6, 252, 499.8)),
               ("dispatch", (290, 577, 46, 40, 1113, 499.8))]:
    p = M[t]["per_seed"][0]
    got = (M[t]["routes"], p["instantiated"], p["executed"], p["failing_tests"], p["requests"], p["wall_s"])
    ck(f"table IV row {t}", got == row, f"{got} vs {row}")

ck("dispatch 40 -> 1 cause", M["dispatch"]["per_seed"][0]["causes"] == 1 and
   in_text("40 failing tests on Netflix Dispatch reduce to a single root cause"))
ck("40 organisation-scoped operations",
   sum(1 for r in json.load(open(f"{SMS_HOME}/results/dispatch_full_s1234.json"))["records"]
       if r["verdict"].get("violation") and "Unknown database schema name" in (r["followup"].get("body") or "")) == 40
   and in_text("reachable through 40 organisation-scoped operations"))

oc = N["oracle_contribution"]
kd = {**N["main"]["dispatch"]["kinds_union"], **N["main"]["any-auto-register"]["kinds_union"]}
ck("response-only / both / state-only = 43 / 3 / 0",
   (oc["response_only"], oc["both"], oc["state_only"]) == (43, 3, 0) and
   in_text("none was detected by the state relation alone (response correct, state wrong), 43 by the response relation alone, and 3 by both"))
ck("violation kinds 40 server_error / 3 response_class / 3 accepted_and_persisted / 0 state_changed",
   (kd["server_error"], kd["response_class"], kd["accepted_and_persisted"], kd.get("state_changed", 0)) == (40, 3, 3, 0) and
   in_text("40 of the 46 failing tests are server errors (all on Dispatch), 3 are `response_class`") and
   in_text("3 are `accepted_and_persisted`") and in_text("None is `state_changed`"))
ck("Table III executed counts match Table IV (dispatch 46, booking 1; sum over rows = 75)",
   in_text("| dispatch | Netflix/dispatch | 290 | 206 | 577 | 46 |") and
   in_text("| booking | guduchango/fastapi-booking | 9 | 3 | 8 | 1 |"))
ck("state-only detections = 0", oc["state_only"] == 0 and
   in_text("No failing test is visible only as a state delta"))

v = N["validation"]
ck("validation 4/4", v["n"] == 4 and v["confirmed"] == 4 and in_text("All four behaviours were confirmed"))
ck("validation: all independent", all(x["confirmation_method"].startswith("independent") for x in v["records"]))
ck("R3 not judged a defect", next(x for x in v["records"] if x["id"] == "R3")["defect_assessment"]["judged_defect"] is False
   and in_text("**not judged a defect**") and in_text("three of the four root causes as defects"))
W = json.load(open(f"{SMS_HOME}/results/validation_withdrawn.json"))
ck("R5 withdrawn and disclosed", [w["id"] for w in W] == ["R5"] and W[0]["confirmed"] is False and
   in_text("One further candidate was withdrawn at this stage"))

for t, row in [("realworld", (56.5, 1956, 26, 12, 14)), ("cloudrun", (48.3, 1192, 19, 6, 13)),
               ("booking", (25.1, 984, 8, 6, 2)), ("any-auto-register", (50.4, 3293, 31, 17, 14)),
               ("dispatch", (1559.6, 22737, 6, 2, 4))]:
    b = B[t]
    got = (round(b["wall_s"], 1), b["failing_tests"], b["causes"], b["behavioural_causes"], b["conformance_causes"])
    ck(f"table VI row {t}", got == row, f"{got} vs {row}")

tot_b = sum(b["failing_tests"] for b in B.values())
ck("baseline ratio", round(tot_b / T["failing_tests"]) == round(sum(B[t]["failing_tests"] for t in B) / T["failing_tests"]) and
   in_text(f"{round(tot_b / T['failing_tests'])} times as many"))
ck("baseline wall", abs(sum(b["wall_s"] for b in B.values()) - sum(B[t]["wall_s"] for t in B)) < 0.6 and
   in_text(f"baseline consumed {round(sum(b['wall_s'] for b in B.values()), 1):,} s".replace(".0 s", " s")))
ck("realworld baseline counts",
   B["realworld"]["failing_tests"] == 1956 and B["realworld"]["causes"] == 26 and
   in_text("1,956 failing tests and 26 root causes"))

ab = N["ablations"]


def mci(rows, key):
    m, hw = ci95([r[key] for r in rows])
    return round(m, 1), round(hw, 1)


for t, exp in [("cloudrun", (1.0, 0.0)), ("booking", (3.0, 0.0)),
               ("any-auto-register", (47.0, 0.0)), ("dispatch", (40.0, 4.3))]:
    got = mci(ab["no-contract"][t]["rows"], "failing_tests")
    ck(f"no-contract failing {t}", got == exp, f"{got} vs {exp}")
for t, exp in [("any-auto-register", (32.0, 0.0)), ("dispatch", (9.7, 3.8))]:
    got = mci(ab["no-contract"][t]["rows"], "not_in_full")
    ck(f"no-contract not-in-full {t}", got == exp, f"{got} vs {exp}")
pct = [round(100 * st.mean([r["not_in_full"] for r in d["rows"]]) /
             max(1, st.mean([r["failing_tests"] for r in d["rows"]])))
       for t, d in ab["no-contract"].items() if st.mean([r["failing_tests"] for r in d["rows"]]) > 0]
ck("no-contract spurious range", min(pct) == 24 and max(pct) == 100 and
   in_text("between 24% and 100%"), str(sorted(pct)))
ck("no-state unchanged on all five targets",
   all(mci(ab["no-state"][t]["rows"], "failing_tests")[0] == M[t]["per_seed"][0]["failing_tests"]
       for t in ("realworld", "booking", "cloudrun", "dispatch", "any-auto-register")) and
   in_text("unchanged on all five targets"))

aar = M["any-auto-register"]
ck("aar exactly reproducible over 5 seeds",
   aar["executed_mean_ci"] == [14, 0.0] or tuple(aar["executed_mean_ci"]) == (14, 0.0))
ck("all five targets reproducible (half-width 0)",
   all(M[t][k][1] == 0 for t in M for k in ("executed_mean_ci", "failing_mean_ci", "causes_mean_ci")) and
   in_text("All five targets are exactly reproducible over five seeds"))
ck("aar quiescence stats", (lambda q: (q["execs"], q["execs_with_exclusions"], q["quiesce_timeouts"], round(q["quiesce_wait_s"], 1)) == (245, 19, 0, 249.0))(
   json.load(open(f"{SMS_HOME}/results/any-auto-register_full_s1234.json"))["stats"]["quiescence"]) and
   in_text("19 of 245 executions had a table excluded") and in_text("249.0 s in total spent waiting for quiescence"))
ck("baseline budget exhausted on one target", sum(1 for b in B.values() if b["timed_out"]) == 1 and B["dispatch"]["timed_out"]
   and in_text("exhausted its budget on one of the five targets"))
ck("baseline ratios 549 / 568", round(B["any-auto-register"]["failing_tests"] / M["any-auto-register"]["per_seed"][0]["failing_tests"]) == 549
   and round(B["dispatch"]["failing_tests"] / 40) == 568 and in_text("549 and 568 times"))

ck("cost per root cause",
   in_text(f"{round(T['wall_s'] / T['causes'], 1)} s and {T['requests'] // T['causes']} requests"))
ck("references have DOIs", all("doi:" in ln for ln in TXT.split("\n") if re.match(r"^\[\d+\] ", ln)))
ck("36 references", len([ln for ln in TXT.split("\n") if re.match(r"^\[\d+\] ", ln)]) == 36)

print(f"\n{checks - len(fails)}/{checks} checks passed")
for f in fails:
    print("  FAILED:", f)
sys.exit(1 if fails else 0)
