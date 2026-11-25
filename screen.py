#!/usr/bin/env python3
"""
Mechanical application of the frozen inclusion criteria to every repository in the sampling frame.

The criteria are applied by static inspection only; no repository is inspected for defects at this stage.
  C1  Python HTTP service built on FastAPI (which publishes a machine-readable OpenAPI 3 description
      without modification) or Flask with an OpenAPI-producing extension.
  C2  Persists application state to a relational database (SQLAlchemy / SQLModel / Tortoise / Gino /
      databases / sqlite3 / psycopg), so that a persistence-state oracle is definable.
  C3  Declares at least five HTTP route handlers.
  C4  Ships a dependency manifest (requirements*.txt or pyproject.toml).
  C5  Is an application, not a project generator: no cookiecutter template directories.
  C6  Working tree smaller than 300 MB (bounded environment).
Repositories passing C1-C6 proceed to the boot check (boot.py), which decides final inclusion.
"""
import json, os, re, subprocess, sys

SMS_HOME = os.environ.get("SMS_HOME", "/home/claude/sms")
ROOT = f"{SMS_HOME}/targets"
FRAME = "/tmp/frames/candidates.txt"
ROUTE_RE = re.compile(r"@\w+\.(get|post|put|patch|delete|route)\s*\(", re.I)
FASTAPI_RE = re.compile(r"from\s+fastapi\s+import|FastAPI\s*\(")
FLASK_RE = re.compile(r"from\s+flask\s+import|Flask\s*\(__name__")
DB_RE = re.compile(r"sqlalchemy|sqlmodel|tortoise|gino\b|^import databases|from databases|sqlite3|psycopg|aiosqlite|asyncpg", re.I | re.M)
SPEC_RE = re.compile(r"flask_restx|flasgger|apispec|flask_smorest|connexion", re.I)


def scan(path):
    n_routes = 0
    fastapi = flask = db = spec = False
    cookie = False
    py = 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}]
        if "{{cookiecutter" in dirpath or "{{ cookiecutter" in dirpath:
            cookie = True
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            py += 1
            fp = os.path.join(dirpath, fn)
            try:
                src = open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            n_routes += len(ROUTE_RE.findall(src))
            fastapi |= bool(FASTAPI_RE.search(src))
            flask |= bool(FLASK_RE.search(src))
            db |= bool(DB_RE.search(src))
            spec |= bool(SPEC_RE.search(src))
    return dict(py_files=py, routes=n_routes, fastapi=fastapi, flask=flask, db=db, spec=spec, cookiecutter=cookie)


def main():
    rows = []
    frame = [l.split("\t") for l in open(FRAME).read().strip().split("\n")]
    for repo, fw, kind in frame:
        d = os.path.join(ROOT, repo.replace("/", "_"))
        if not os.path.isdir(d):
            rows.append(dict(repo=repo, framework=fw, kind=kind, status="not_cloned")); continue
        size_mb = int(subprocess.run(["du", "-sm", d], capture_output=True, text=True).stdout.split()[0])
        s = scan(d)
        c1 = s["fastapi"] or (s["flask"] and s["spec"])
        c2 = s["db"]
        c3 = s["routes"] >= 5
        c4 = any(os.path.exists(os.path.join(d, f)) for f in ["requirements.txt", "pyproject.toml", "requirements/prod.txt", "requirements-dev.txt"]) \
             or bool([f for f in os.listdir(d) if f.startswith("requirements")])
        c5 = not s["cookiecutter"]
        c6 = size_mb < 300
        passed = all([c1, c2, c3, c4, c5, c6])
        rows.append(dict(repo=repo, framework=fw, kind=kind, size_mb=size_mb, **s,
                         C1=c1, C2=c2, C3=c3, C4=c4, C5=c5, C6=c6, screen_pass=passed,
                         status="screened"))
    json.dump(rows, open(f"{SMS_HOME}/screen_results.json", "w"), indent=1)
    ok = [r for r in rows if r.get("screen_pass")]
    print(f"{len(rows)} in frame, {len(ok)} pass static screening\n")
    print(f"{'repo':52s} {'fw':8s} {'routes':>6s} {'py':>5s} {'MB':>5s}")
    for r in sorted(ok, key=lambda x: -x["routes"]):
        print(f"{r['repo']:52s} {r['framework']:8s} {r['routes']:6d} {r['py_files']:5d} {r['size_mb']:5d}")
    print("\nfailed criteria tally:")
    for c in "C1 C2 C3 C4 C5 C6".split():
        print(f"  {c}: {sum(1 for r in rows if r.get('status')=='screened' and not r.get(c))} rejected")


if __name__ == "__main__":
    main()
