"""Tabulate the paired local re-run (original vs quiet oracle) next to the archived campaign runs."""
import json, glob, os, collections, sys
CAMP = os.path.expanduser("~/sms-research/corrected_sms/results")
def load(f):
    d = json.load(open(f)); st = d["stats"]
    viol = [(r["mr"].split("_")[0], r["target_op"], r["verdict"]["kind"]) for r in d["records"]
            if r["verdict"]["kind"] not in ("none",) and r["verdict"].get("violation", r["verdict"]["kind"] != "none")]
    return st, viol, d
cfgs = [("full", s) for s in (1234, 2718, 3141, 4142, 5772)] + [(v, s) for v in ("no-state", "no-contract") for s in (1234, 2718, 3141)]
out = []
for v, s in cfgs:
    row = {"variant": v, "seed": s}
    for tag, f in (("campaign", f"{CAMP}/any-auto-register_{v}_s{s}.json"),
                   ("original", f"results/engine/any-auto-register_{v}_s{s}_original.json"),
                   ("quiet", f"results/engine/any-auto-register_{v}_s{s}_quiet.json")):
        if not os.path.exists(f): row[tag] = None; continue
        st, viol, d = load(f)
        row[tag] = {"executed": st["executed"], "violations": st["violations"],
                    "kinds": sorted(f"{m}|{k}|{op}" for m, op, k in viol),
                    "quiescence": st.get("quiescence")}
    out.append(row)
json.dump(out, open("results/rerun_summary.json", "w"), indent=1)
for r in out:
    print(f"{r['variant']:12s} {r['seed']}  " + "  ".join(
        f"{t}: ex={r[t]['executed']} v={r[t]['violations']}" if r[t] else f"{t}: -" for t in ("campaign", "original", "quiet")))
print()
for t in ("campaign", "original", "quiet"):
    c = collections.Counter(k for r in out if r[t] and r["variant"] == "full" for k in r[t]["kinds"])
    print("==", t, "full-variant violation kinds (count over 5 seeds)")
    for k, n in sorted(c.items()): print(f"   {n}  {k}")
