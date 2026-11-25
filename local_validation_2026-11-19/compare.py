import json, sys
def kinds(f):
    d = json.load(open(f))
    return [(r["mr"].split("_")[0], r["target_op"][:38], r["verdict"]["kind"],
             sorted(r["followup"]["delta"]["tables"]), r["followup"]["delta"].get("background_tables"))
            for r in d["records"]], d["stats"]
for f in sys.argv[1:]:
    ks, st = kinds(f)
    print("==", f.split("/")[-1], "exec", st["executed"], "viol", st["violations"], st.get("quiescence", ""))
    for k in ks:
        if k[2] != "none" or k[4]: print("  ", k)
