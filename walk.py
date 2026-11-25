#!/usr/bin/env python3
"""Walk the seeded permutation of frame F2, attempting each repository in order until the budget is met."""
import json, os, subprocess, sys, time
SMS=os.environ.get("SMS_HOME", "/home/claude/sms")
order=json.load(open(f"{SMS}/frame2_order.json"))["order"]
start=int(sys.argv[1]); n=int(sys.argv[2]); budget=int(sys.argv[3]) if len(sys.argv)>3 else 10
log=open(f"{SMS}/walk_log.jsonl","a")
port=9020+start
booted=0
for i,e in enumerate(order[start:start+n], start=start):
    t0=time.time()
    r=subprocess.run([sys.executable, f"{SMS}/harness/automanifest.py", e["repo"], str(port)],
                     capture_output=True, text=True, timeout=1500)
    try: rec=json.loads(r.stdout)
    except Exception: rec={"repo":e["repo"],"outcome":"harness_error","err":(r.stdout+r.stderr)[-400:]}
    rec["frame_pos"]=i; rec["stars"]=e["stars"]; rec["wall_s"]=round(time.time()-t0,1)
    if rec.get("outcome")!="booted":
        tid=e["repo"].split("/")[-1].lower().replace(".","-")[:24]
        subprocess.run(["rm","-rf",f"{SMS}/venvs/{tid}",f"{SMS}/targets/"+e["repo"].replace("/","_")],capture_output=True)
    log.write(json.dumps(rec)+"\n"); log.flush()
    print(f"[{i}] {e['repo']:50s} {rec.get('outcome'):14s} routes={rec.get('routes','-')} {rec['wall_s']}s", flush=True)
    port+=1
    if rec.get("outcome")=="booted":
        booted+=1
        if booted>=budget: break
