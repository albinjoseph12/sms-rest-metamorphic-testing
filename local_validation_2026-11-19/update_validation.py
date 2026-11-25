"""Apply the 2026-11-19 independent checks to corrected_sms/results/validation.json.
R4 -> fully independent (HTTP + direct SQLite read); R2 -> add fresh-instance evidence;
R5 -> removed from the confirmed list and recorded in validation_withdrawn.json (oracle false positive)."""
import json, os
V = os.path.expanduser("~/sms-research/corrected_sms/results/validation.json")
W = os.path.expanduser("~/sms-research/corrected_sms/results/validation_withdrawn.json")
here = os.path.dirname(os.path.abspath(__file__))
r4 = json.load(open(f"{here}/results/r4.json")); r2 = json.load(open(f"{here}/results/r2_check.json"))
r5q = json.load(open(f"{here}/results/r5_quiet.json")); r5a = json.load(open(f"{here}/results/r5_active.json"))
v = json.load(open(V)); by = {x["id"]: x for x in v}
by["R2"]["fresh_instance_check"] = {
    "date": "2026-11-19", "script": "local_validation_2026-11-19/r2_check.py",
    "setup": "fresh offline container, 12 accounts, no background tasks",
    "limit=5": r2["limit=5"]["resp"], "limit=0": r2["limit=0"]["resp"], "limit=-5": r2["limit=-5"]["resp"],
    "cause_in_code": "core/lifecycle.py passes limit to SQL LIMIT unchecked; SQLite treats a negative LIMIT as no limit"}
by["R2"]["note"] = ("The original evidence (error 205 for limit=-5) was gathered on a database that had accumulated state "
                    "across runs; the fresh-instance check reproduces the behaviour: -5 acts on all 12 accounts, 5 on five.")
x = by["R4"]; x["confirmation_method"] = "independent_http_and_db"; x.pop("note", None)
x["evidence"] = {
    "control": {"path": "PUT /api/platforms/anything/capabilities", **{k: r4["control_put_real_platform"][k] for k in ("status", "body")}},
    "followup": {"path": "PUT /api/platforms/sms-absent-platform-7f3a/capabilities",
                 **{k: r4["followup_put_absent_platform"][k] for k in ("status", "body", "delta")}},
    "absent_name_listed_after_put": r4["absent_name_listed_after_put"],
    "other_endpoint_on_absent_name": r4["other_endpoint_on_absent_name"],
    "script": "local_validation_2026-11-19/independent_check_r4_r5.py r4", "date": "2026-11-19"}
w = by.pop("R5")
w.update({"confirmed": False, "status": "withdrawn_oracle_false_positive", "withdrawn_on": "2026-11-19",
          "reason": ("The state delta seen around the second, already-failed DELETE came from the target's background "
                     "task_runtime (registration tasks queued by the SMS bootstrap), not from the request. "
                     "AccountsRepository.delete returns before any write when the account is absent."),
          "evidence": {"no_background_tasks_repeat_missing_delete_with_delta": r5q["repeat_missing_delete_with_delta"],
                       "busy_runtime_trials_with_state_delta": r5a["trials_with_state_delta"],
                       "trials_per_kind": r5a["trials_per_kind"],
                       "any_row_mentions_deleted_account": r5a["any_row_mentions_deleted_account"],
                       "script": "local_validation_2026-11-19/independent_check_r4_r5.py r5_quiet|r5_tasks|r5_active"},
          "consequence": "The engine now takes snapshots under a quiescence control (--quiet-window); under it the MR5 test is not flagged."})
json.dump(list(by.values()), open(V, "w"), indent=1, ensure_ascii=False)
json.dump([w], open(W, "w"), indent=1, ensure_ascii=False)
print([ (x["id"], x["confirmation_method"]) for x in by.values()])
