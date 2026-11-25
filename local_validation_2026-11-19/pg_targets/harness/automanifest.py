#!/usr/bin/env python3
"""
Automatic harness synthesis: given a repository slug, derive a boot manifest without human input.

  1. shallow-clone the repository
  2. apply the static screen (C1-C6 of screen.py)
  3. locate module-level ASGI applications: assignments of the form `<name> = FastAPI(...)`
     and zero-argument factories returning a FastAPI instance
  4. locate a dependency manifest (requirements*.txt, pyproject.toml)
  5. emit a manifest per candidate entry point and try each under a small matrix of standard
     deployment environments (PostgreSQL or SQLite database URL under the usual variable names,
     placeholder secrets); the first combination that serves a valid OpenAPI document wins

Only deployment configuration is synthesised. No target source file is read for defect content at
this stage and no target source file is ever modified.
"""
import base64, hashlib, itertools, json, os, re, subprocess, sys, time

SMS = os.environ.get("SMS_HOME", "/home/claude/sms")
sys.path.insert(0, os.path.join(SMS, "harness"))
import boot as B

APP_RE = re.compile(r"^(\w+)\s*(?::\s*[\w\.\[\]\"']+\s*)?=\s*FastAPI\s*\(", re.M)
FACTORY_RE = re.compile(r"^def\s+(\w+)\s*\(\s*\)\s*(?:->\s*[^:]+)?:\s*$", re.M)
SECRETS = {"SECRET_KEY": "smsbench", "API_SECRET_KEY": "smsbench", "JWT_SECRET_KEY": "smsbench",
           "JWT_SECRET": "smsbench", "SECRET": "smsbench", "ENVIRONMENT": "local", "ENV": "test",
           "API_ENV": "test", "DEBUG": "False", "PROJECT_NAME": "sms", "BACKEND_CORS_ORIGINS": "[]",
           "FIRST_SUPERUSER": "admin@example.com", "FIRST_SUPERUSER_PASSWORD": "smsbench123",
           "POSTGRES_USER": "acb", "POSTGRES_PASSWORD": "acb", "POSTGRES_SERVER": "localhost",
           "POSTGRES_HOST": "localhost", "POSTGRES_PORT": "5432", "REDIS_URL": "redis://localhost:6379/2",
           "OPENAI_API_KEY": "sk-not-used", "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
           "ADMIN_USERNAME": "smsadmin", "ADMIN_PASSWORD": "SmsBench!2345",
           "ADMIN_EMAIL": "smsadmin@example.com", "ADMIN_TOKEN": "smsbench",
           "DEFAULT_USER": "smsadmin", "DEFAULT_PASSWORD": "SmsBench!2345"}


def clone(slug):
    d = os.path.join(SMS, "targets", slug.replace("/", "_"))
    if not os.path.isdir(d):
        r = subprocess.run(["timeout", "300", "git", "clone", "--depth", "1", "--quiet",
                            f"https://github.com/{slug}.git", d], capture_output=True)
        if r.returncode != 0:
            return None
    return d


# --------------------------------------------------------------------------- boot repair
DIST = {"mangum": "mangum", "jose": "python-jose", "jwt": "pyjwt", "dotenv": "python-dotenv",
        "multipart": "python-multipart", "yaml": "pyyaml", "psycopg2": "psycopg2-binary",
        "sqlalchemy_utils": "sqlalchemy-utils", "dateutil": "python-dateutil", "PIL": "pillow",
        "bs4": "beautifulsoup4", "attr": "attrs", "pkg_resources": "setuptools", "cv2": "opencv-python",
        "redis": "redis", "magic": "python-magic", "slugify": "python-slugify", "email_validator": "email-validator"}
MISSING_MOD = re.compile(r"No module named '([A-Za-z_][\w.]*)'")
MISSING_CFG = re.compile(r"Config '([A-Z0-9_]+)' is missing")
MISSING_DB = re.compile(r'database "([\w.-]+)" does not exist')
FERNET_NAME = re.compile(r"ENCRYPTION|FERNET|CRYPT", re.I)


def _fernet_key():
    return base64.urlsafe_b64encode(hashlib.sha256(b"smsbench").digest()).decode()


def _config_value(key: str, m: dict) -> str:
    """A value whose shape matches what the name announces. Credentials are pairs, host names are
    host names, ports are numbers; anything else is an opaque secret."""
    k = key.upper()
    if FERNET_NAME.search(k):
        return _fernet_key()
    if "CREDENTIAL" in k:
        return "acb:acb"
    if "HOSTNAME" in k or k.endswith("_HOST"):
        return "localhost"
    if k.endswith("_PORT"):
        return "5432"
    if "DATABASE_NAME" in k or k.endswith("_DB"):
        return m.get("db_name", "sms_target")
    if k.endswith("_USER") or k.endswith("_USERNAME"):
        return "acb"
    if "PASSWORD" in k:
        return "acb"
    if k.endswith("_URL") or k.endswith("_URI"):
        return "http://localhost"
    if "EMAIL" in k:
        return "smsadmin@example.com"
    return "smsbench"


def repair(err: str, m: dict, mm: dict):
    """One mechanical repair step derived from the target's own start-up error.

    Two classes of failure are repaired, both stated by the interpreter or the settings library
    itself and neither requiring the target's source to be read: an import of a distribution the
    dependency manifest omits, and a mandatory configuration value with no default. Every repair is
    recorded in the manifest, so a booted target's environment is reproducible."""
    mo = MISSING_MOD.search(err or "")
    if mo:
        top = mo.group(1).split(".")[0]
        dist = DIST.get(top, top)
        r = subprocess.run(["uv", "pip", "install", "--python", mm["py"], "--quiet", dist],
                           capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            m["deps"].setdefault("post_install", []).append([dist])
            return f"installed:{dist}"
        return None
    md = MISSING_DB.search(err or "")
    if md and md.group(1) != m.get("db_name"):
        name = md.group(1)
        r = subprocess.run(f'psql -U postgres -h localhost -c \'CREATE DATABASE "{name}" OWNER acb\'',
                           shell=True, capture_output=True, text=True, timeout=120)
        if r.returncode == 0 or "already exists" in (r.stderr or ""):
            m.setdefault("extra_databases", []).append(name)
            return f"createdb:{name}"
        return None
    mc = MISSING_CFG.search(err or "")
    if mc:
        key = mc.group(1)
        if key in m["env"]:
            return None
        m["env"][key] = _config_value(key, m)
        return f"config:{key}"
    return None


def modpath(root, fp):
    rel = os.path.relpath(fp, root)[:-3].replace(os.sep, ".")
    return rel[:-9] if rel.endswith(".__init__") else rel


def find_apps(root):
    """Return [(module, attr, subdir)] candidate ASGI entry points, most likely first."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", ".venv", "venv", "__pycache__", "tests", "test", "frontend", "dist", "build", "migrations", "alembic"}]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                src = open(fp, encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if "FastAPI(" not in src:
                continue
            for name in APP_RE.findall(src):
                out.append((fp, name, False))
            if re.search(r"->\s*(?:fastapi\.)?FastAPI", src):
                for fname in FACTORY_RE.findall(src):
                    if re.search(rf"def\s+{fname}\s*\(\s*\)\s*->\s*(?:fastapi\.)?FastAPI", src):
                        out.append((fp, fname, True))
            # an application built by a helper ("app = create_app()") is not matched by either
            # pattern, so the conventional module-level names are offered as further candidates and
            # discarded by the boot attempt if they do not exist
            for conv in ("app", "api", "application", "server"):
                if re.search(rf"^{conv}\s*=\s*\w", src, re.M) and not any(
                        o[0] == fp and o[1] == conv for o in out):
                    out.append((fp, conv, False))
    # rank: shallower path, and file named main/app/application first
    def rank(t):
        fp = t[0]
        depth = fp.count(os.sep)
        base = os.path.basename(fp)
        pref = {"main.py": 0, "app.py": 1, "application.py": 2, "__init__.py": 4, "__main__.py": 5}.get(base, 3)
        return (pref, depth)
    out.sort(key=rank)
    return out[:8]


def dep_spec(root, sub):
    d = os.path.join(root, sub) if sub else root
    reqs = sorted([f for f in os.listdir(d) if re.fullmatch(r"requirements.*\.txt", f)])
    if reqs:
        return {"kind": "requirements", "files": [reqs[0]], "extra": ["uvicorn", "httpx"]}
    if os.path.exists(os.path.join(d, "pyproject.toml")):
        return {"kind": "pyproject", "extra": ["uvicorn", "httpx"]}
    for f in ["requirements/base.txt", "requirements/prod.txt", "requirements/requirements.txt"]:
        if os.path.exists(os.path.join(d, f)):
            return {"kind": "requirements", "files": [f], "extra": ["uvicorn", "httpx"]}
    return None


def try_target(slug, port, budget_s=900):
    t0 = time.time()
    root = clone(slug)
    rec = {"repo": slug, "cloned": bool(root), "attempts": []}
    if not root:
        rec["outcome"] = "clone_failed"; return rec
    apps = find_apps(root)
    if not apps:
        rec["outcome"] = "no_asgi_app"; return rec
    tid = slug.split("/")[-1].lower().replace(".", "-")[:24]
    for fp, name, is_factory in apps:
        sub = os.path.dirname(os.path.relpath(fp, root))
        # package root is the highest ancestor dir that still has __init__.py chain broken
        parts = sub.split(os.sep) if sub else []
        pkgroot = ""
        for i in range(len(parts)):
            if not os.path.exists(os.path.join(root, *parts[:i + 1], "__init__.py")):
                pkgroot = os.path.join(*parts[:i + 1]) if i else parts[0] if parts else ""
            else:
                break
        for subdir in dict.fromkeys([""] + ([pkgroot] if pkgroot else []) + ([parts[0]] if parts else [])):
            base = os.path.join(root, subdir) if subdir else root
            if not os.path.isdir(base):
                continue
            try:
                mp = modpath(base, fp)
            except ValueError:
                continue
            if mp.startswith(".."):
                continue
            deps = dep_spec(root, subdir)
            if deps is None:
                continue
            pyver = "3.11"
            for dbkind in ["postgres", "sqlite"]:
                if time.time() - t0 > budget_s:
                    rec["outcome"] = "timeout"; return rec
                dbname = "sms_" + re.sub(r"\W", "_", tid)
                env = dict(SECRETS)
                if dbkind == "postgres":
                    url = f"postgresql://acb:acb@localhost:5432/{dbname}"
                    env.update({"DATABASE_URL": url, "DB_DSN": url, "SQLALCHEMY_DATABASE_URI": url,
                                "POSTGRES_DB": dbname, "DB_URL": url, "DATABASE_URI": url,
                                "DATABASE_URL_ASYNC": url.replace("postgresql://", "postgresql+asyncpg://")})
                else:
                    url = f"sqlite:///{base}/sms_target.db"
                    env.update({"DATABASE_URL": url, "DB_DSN": url, "SQLALCHEMY_DATABASE_URI": url, "DB_URL": url})
                m = {"id": tid, "repo": slug, "app": f"{mp}:{name}", "port": port, "python": pyver,
                     "db": dbkind, "db_name": dbname, "deps": deps, "env": env, "migrate": [],
                     "factory": is_factory}
                if subdir:
                    m["subdir"] = subdir
                mp_file = os.path.join(SMS, "manifests", f"auto_{tid}.json")
                json.dump(m, open(mp_file, "w"), indent=1)
                mm = B.load(mp_file)
                pr = B.prepare(mm)
                if not pr.get("ok"):
                    mreq = re.search(r"Python>=3\.(\d+)", pr.get("err", ""))
                    retried = False
                    if mreq:
                        want = f"3.{mreq.group(1)}"
                        if want in {"3.12", "3.13", "3.14"} and want != pyver:
                            subprocess.run(["uv", "python", "install", want], capture_output=True)
                            pyver = want
                            m["python"] = pyver
                            json.dump(m, open(mp_file, "w"), indent=1)
                            subprocess.run(["rm", "-rf", os.path.join(SMS, "venvs", tid)])
                            mm = B.load(mp_file)
                            pr = B.prepare(mm)
                            retried = True
                    if not pr.get("ok"):
                        rec["attempts"].append({"app": m["app"], "db": dbkind, "py": pyver,
                                                "fail": "install", "retried": retried, "err": pr.get("err", "")[-300:]})
                        break   # install failure is per-repo, not per-entry-point
                B.reset(mm)
                sv = B.serve(mm, wait=45)
                repairs = []
                for _ in range(6):
                    if sv.get("ok") or time.time() - t0 > budget_s:
                        break
                    step = repair(sv.get("err") or "", m, mm)
                    if not step:
                        break
                    repairs.append(step)
                    json.dump(m, open(mp_file, "w"), indent=1)
                    mm = B.load(mp_file)
                    B.stop(mm)
                    sv = B.serve(mm, wait=45)
                rec["attempts"].append({"app": m["app"], "subdir": subdir, "db": dbkind,
                                        "ok": sv.get("ok"), "routes": sv.get("routes"),
                                        "repairs": repairs, "err": (sv.get("err") or "")[-220:]})
                B.stop(mm)
                if sv.get("ok") and sv.get("openapi") and sv["openapi"] != m.get("openapi"):
                    m["openapi"] = sv["openapi"]; json.dump(m, open(mp_file, "w"), indent=1)
                if sv.get("ok") and sv.get("routes", 0) >= 5:
                    rec["outcome"] = "booted"; rec["manifest"] = mp_file
                    rec["routes"] = sv["routes"]; rec["title"] = sv.get("title")
                    rec["elapsed_s"] = round(time.time() - t0, 1)
                    return rec
    rec["outcome"] = "boot_failed"; rec["elapsed_s"] = round(time.time() - t0, 1)
    return rec


if __name__ == "__main__":
    slug, port = sys.argv[1], int(sys.argv[2])
    rec = try_target(slug, port)
    print(json.dumps(rec))
