#!/usr/bin/env python3
"""
Target harness: prepare, boot and health-check one system under test.

A harness manifest is a small JSON file per target that records only the information a
deployer would need anyway (entry point, dependency source, database URL, migration command).
No application logic is modified; the harness never edits target source files.

Usage:
  boot.py prepare <manifest>     create a virtualenv and install the target's dependencies
  boot.py reset   <manifest>     drop and recreate the target's database and run its migrations
  boot.py serve   <manifest>     start the server in the background and wait for /openapi.json
  boot.py stop    <manifest>
  boot.py check   <manifest>     prepare + reset + serve + report route count, then stop
"""
import json, os, shutil, signal, subprocess, sys, time, urllib.request

SMS = os.environ.get("SMS_HOME", "/home/claude/sms")
VENVS = f"{SMS}/venvs"
RUN = f"{SMS}/run"
os.makedirs(VENVS, exist_ok=True); os.makedirs(RUN, exist_ok=True)


def load(mpath):
    m = json.load(open(mpath))
    m["root"] = os.path.join(SMS, "targets", m["repo"].replace("/", "_"))
    m["dir"] = os.path.join(m["root"], m["subdir"]) if m.get("subdir") else m["root"]
    m["venv"] = os.path.join(VENVS, m["id"])
    m["py"] = os.path.join(m["venv"], "bin", "python")
    m["pip"] = [os.path.join(m["venv"], "bin", "python"), "-m", "pip"]
    return m


def sh(cmd, cwd=None, env=None, timeout=900, check=False):
    e = dict(os.environ); e.update(env or {})
    r = subprocess.run(cmd, cwd=cwd, env=e, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed ({r.returncode}): {cmd}\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}")
    return r


def target_env(m):
    env = dict(m.get("env", {}))
    if m.get("db") == "postgres":
        env.setdefault("DATABASE_URL", f"postgresql://acb:acb@localhost:5432/{m['db_name']}")
    env.setdefault("PYTHONPATH", m["dir"])
    return env


# --------------------------------------------------------------------------------------- prepare
def prepare(m):
    if not os.path.isdir(m["venv"]):
        sh(["uv", "venv", "--python", m.get("python", "3.11"), m["venv"]], check=True)
    deps = m["deps"]
    args = []
    if deps["kind"] == "requirements":
        for f in deps["files"]:
            args += ["-r", os.path.join(m["dir"], f)]
    elif deps["kind"] == "pyproject":
        args += [m["dir"]]
    elif deps["kind"] == "list":
        args += deps["packages"]
    extra = deps.get("extra", [])
    r = sh(["uv", "pip", "install", "--python", m["py"], "--quiet"] + args + extra, timeout=1800)
    if r.returncode != 0:
        return {"ok": False, "stage": "install", "err": (r.stdout + r.stderr)[-2500:]}
    for pkgs in deps.get("post_install", []):
        r = sh(["uv", "pip", "install", "--python", m["py"], "--quiet", "-U"] + pkgs, timeout=900)
        if r.returncode != 0:
            return {"ok": False, "stage": "post_install", "err": (r.stdout + r.stderr)[-2000:]}
    return {"ok": True}


# --------------------------------------------------------------------------------------- reset db
def reset(m):
    if m.get("db") == "postgres":
        # a connection left open by a previous run would make the drop fail and leave stale rows in
        # the database, so sessions are terminated first
        sh(f"""psql -U postgres -h localhost -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='{m['db_name']}' AND pid <> pg_backend_pid()" """)
        sh(f'psql -U postgres -h localhost -c "DROP DATABASE IF EXISTS {m["db_name"]}"')
        sh(f'psql -U postgres -h localhost -c "CREATE DATABASE {m["db_name"]} OWNER acb"', check=True)
    elif m.get("db") == "sqlite":
        for f in ([m["db_file"]] if m.get("db_file") else []) + ["sms_target.db"]:
            p = f if os.path.isabs(f) else os.path.join(m["dir"], f)
            if os.path.exists(p):
                os.remove(p)
    # Fix (2026-11-19): a target may ignore the database the harness configured and create its own
    # SQLite file (seven targets did, including any-auto-register, whose manifest says "postgres").
    # Such files were never removed, so state carried over between runs. Every SQLite file in the
    # target tree that git does not track was created by a run and is removed; tracked files (seed
    # databases shipped with the repository) are restored to their committed content.
    import glob as _glob
    tracked = set(sh(["git", "ls-files"], cwd=m["root"]).stdout.split())
    for pat in ("**/*.db", "**/*.sqlite", "**/*.sqlite3"):
        for p in _glob.glob(os.path.join(m["dir"], pat), recursive=True):
            rel = os.path.relpath(p, m["root"])
            if rel in tracked:
                sh(["git", "checkout", "--", rel], cwd=m["root"])
            elif os.path.isfile(p):
                os.remove(p)
    env = target_env(m)
    for cmd in m.get("migrate", []):
        r = sh(cmd, cwd=m["dir"], env={**env, "PATH": os.path.join(m["venv"], "bin") + ":" + os.environ["PATH"]}, timeout=600)
        if r.returncode != 0:
            return {"ok": False, "stage": "migrate", "cmd": cmd, "err": (r.stdout + r.stderr)[-2500:]}
    return {"ok": True}


# --------------------------------------------------------------------------------------- serve
def pidfile(m):
    return os.path.join(RUN, m["id"] + ".pid")


def serve(m, wait=60):
    stop(m)
    env = target_env(m)
    env["PATH"] = os.path.join(m["venv"], "bin") + ":" + os.environ["PATH"]
    port = str(m.get("port", 9000))
    log = open(os.path.join(RUN, m["id"] + ".log"), "w")
    cmd = [m["py"], "-m", "uvicorn", m["app"], "--host", "127.0.0.1", "--port", port, "--log-level", "warning"]
    p = subprocess.Popen(cmd, cwd=m["dir"], env={**os.environ, **env}, stdout=log, stderr=subprocess.STDOUT,
                         preexec_fn=os.setsid)
    open(pidfile(m), "w").write(str(p.pid))
    # an application may mount its specification somewhere other than the FastAPI default, so a small
    # fixed set of conventional locations is probed; the one that answers is recorded in the manifest
    cands = [m["openapi"]] if m.get("openapi") else ["/openapi.json", "/api/openapi.json",
             "/api/v1/openapi.json", "/docs/openapi.json", "/api/v1/docs/openapi.json",
             "/v1/openapi.json", "/swagger.json", "/api/docs/openapi.json"]
    t0 = time.time()
    while time.time() - t0 < wait:
        if p.poll() is not None:
            return {"ok": False, "stage": "serve", "err": open(os.path.join(RUN, m['id'] + '.log')).read()[-2500:]}
        for cand in cands:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}{cand}", timeout=3) as r:
                    spec = json.loads(r.read())
            except Exception:
                continue
            if not isinstance(spec, dict) or "paths" not in spec:
                continue
            n = sum(len([k for k in v if k in ("get", "post", "put", "patch", "delete")]) for v in spec.get("paths", {}).values())
            return {"ok": True, "routes": n, "boot_s": round(time.time() - t0, 1),
                    "openapi": cand, "title": spec.get("info", {}).get("title", "")}
        time.sleep(1)
    return {"ok": False, "stage": "health", "err": open(os.path.join(RUN, m['id'] + '.log')).read()[-2500:]}


def stop(m):
    # a server left behind by an interrupted run keeps the port bound, which would make the next
    # start fail silently while the health check is answered by the stale process
    port = str(m.get("port", 9000))
    subprocess.run(f"fuser -k -TERM {port}/tcp", shell=True, capture_output=True)
    pf = pidfile(m)
    if os.path.exists(pf):
        try:
            os.killpg(int(open(pf).read()), signal.SIGKILL)
        except Exception:
            pass
        os.remove(pf)
    subprocess.run(f"pkill -f 'uvicorn {m['app']}'", shell=True, capture_output=True)


def check(m):
    out = {"id": m["id"], "repo": m["repo"]}
    for stage, fn in [("prepare", prepare), ("reset", reset), ("serve", serve)]:
        r = fn(m)
        out[stage] = r
        if not r.get("ok"):
            stop(m); out["ok"] = False; return out
    out["ok"] = True
    stop(m)
    return out


if __name__ == "__main__":
    action, mpath = sys.argv[1], sys.argv[2]
    m = load(mpath)
    print(json.dumps(globals()[action](m), indent=1)[:4000])
