"""Compare the local PG-target re-run with the campaign (corrected_sms/results/<t>_<v>_s<s>.json).

For each target / variant / seed it reports whether the local original-oracle run matches the campaign on every
deterministic statistic (wall time excluded) and on the per-record verdict sequence, and how the quiet-oracle run
differs from the original-oracle run.
    python3 compare_pg.py [targets...]
"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
CAMP = os.path.join(HERE, "..", "..", "corrected_sms", "results")  # ~/sms-research layout
if not os.path.isdir(CAMP):  # inside the archive, local_validation_2026-11-19/ sits in corrected_sms/
    CAMP = os.path.join(HERE, "..", "..", "results")
KEYS = ["instantiated", "executed", "source_ok", "violations", "source_failed", "requests",
        "per_relation", "source_status", "not_applicable"]
CONFIGS = [("full", s) for s in (1234, 2718, 3141, 4142, 5772)] + \
          [(v, s) for v in ("no-contract", "no-state") for s in (1234, 2718, 3141)]


def load(p):
    if not os.path.exists(p):
        return None
    d = json.load(open(p))
    st = {k: d["stats"].get(k) for k in KEYS}
    recs = [(r["mr"], r["target_op"], r.get("verdict", {}).get("kind")) for r in d["records"]]
    return st, recs, d["stats"]


def main(targets):
    summary = {}
    for t in targets:
        rows = []
        for v, s in CONFIGS:
            camp = load(f"{CAMP}/{t}_{v}_s{s}.json")
            orig = load(f"{HERE}/results/{t}/{t}_{v}_s{s}_original.json")
            quiet = load(f"{HERE}/results/{t}/{t}_{v}_s{s}_quiet.json")
            row = {"config": f"{v}_s{s}", "campaign": bool(camp), "original": bool(orig), "quiet": bool(quiet)}
            if camp and orig:
                diff = {k: (camp[0][k], orig[0][k]) for k in KEYS if camp[0][k] != orig[0][k]}
                row["orig_vs_campaign_stats"] = "match" if not diff else diff
                row["orig_vs_campaign_records"] = "match" if camp[1] == orig[1] else \
                    sum(a != b for a, b in zip(camp[1], orig[1])) + abs(len(camp[1]) - len(orig[1]))
            if orig and quiet:
                diff = {k: (orig[0][k], quiet[0][k]) for k in KEYS if orig[0][k] != quiet[0][k]}
                row["quiet_vs_orig_stats"] = "match" if not diff else diff
                row["quiet_viol"] = quiet[0]["violations"]
            if orig:
                row["orig_viol"] = orig[0]["violations"]
            if camp:
                row["camp_viol"] = camp[0]["violations"]
            rows.append(row)
        summary[t] = rows
    return summary


if __name__ == "__main__":
    ts = sys.argv[1:] or ["realworld", "booking", "cloudrun", "dispatch"]
    out = main(ts)
    json.dump(out, open(os.path.join(HERE, "compare_pg.json"), "w"), indent=1)
    for t, rows in out.items():
        print(f"== {t}")
        for r in rows:
            print("  ", r["config"].ljust(18),
                  "camp" if r["campaign"] else "----", "orig" if r["original"] else "----",
                  "quiet" if r["quiet"] else "-----",
                  "| stats:", r.get("orig_vs_campaign_stats", "-"),
                  "| recs:", r.get("orig_vs_campaign_records", "-"),
                  "| viol c/o/q:", r.get("camp_viol"), r.get("orig_viol"), r.get("quiet_viol"),
                  "| quiet vs orig:", r.get("quiet_vs_orig_stats", "-"))
