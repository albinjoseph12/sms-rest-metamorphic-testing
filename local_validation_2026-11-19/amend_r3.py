"""Record the 2026-11-19 R3 database check and defect assessment in validation.json."""
import json, os
V = os.path.expanduser("~/sms-research/corrected_sms/results/validation.json")
here = os.path.dirname(os.path.abspath(__file__))
r3 = json.load(open(f"{here}/results/r3_check.json"))
v = json.load(open(V)); x = next(e for e in v if e["id"] == "R3")
x["claim"] = "POST /api/accounts accepts and stores an arbitrary user_id value with no existence check"
x["confirmation_method"] = "independent_http_and_db"
x["db_check"] = {"date": "2026-11-19", "script": "local_validation_2026-11-19/r3_check.py",
                 "status": r3["status"], "inserted_accounts_rows": r3["inserted_accounts_rows"],
                 "user_tables_in_schema": list(r3["user_tables_before"])}
x["defect_assessment"] = {
    "judged_defect": False,
    "reason": ("The API has no user resource (no /users path, no user table). The FOREIGN_REFERENCE witness matched "
               "user_id through the fallback in sms/contract.py find_foreign_refs, which uses the name's stem when no "
               "collection matches. In the target's code user_id holds the account's identifier on the external platform "
               "(e.g. platforms/trae/browser_register.py), so storing an unchecked value is not a dangling reference."),
    "pending": "second, blinded adjudicator"}
json.dump(v, open(V, "w"), indent=1, ensure_ascii=False)
print(json.dumps(x, ensure_ascii=False, indent=1)[:600])
