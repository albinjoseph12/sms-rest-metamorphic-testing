"""
SMS execution engine.

Phases
  1. bootstrap   discover the authentication operations from the contract, register two principals
                 (A and B) and obtain their credentials
  2. seed        exercise every create operation as A and as B with schema-generated bodies; the
                 identity of each created row is learned from the persistence delta rather than from
                 the response body, so item paths can be resolved even when the response omits the key
  3. instantiate for every invariant produced by the contract analyser, build the source request and
                 the follow-up request prescribed by the corresponding metamorphic relation
  4. evaluate    execute source, snapshot, execute follow-up, snapshot, decide the relation
  5. report      emit one record per relation instance with requests, responses, deltas and verdict

Every instantiation is counted whether or not it can be executed and whether or not it violates the
relation, so the analysis has the full denominator and no rate is computed over a hand-picked subset.
"""
import copy
import datetime as dt
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import relations as R
from .contract import Contract
from .gen import Gen, get_in, has_in, set_in
from .state import Snapshotter, delta, summarize

AUTH_CREATE = re.compile(r"(users?|register|signup|sign-up|accounts?)$|registration", re.I)
AUTH_LOGIN = re.compile(r"login|signin|sign-in|token|session|auth", re.I)


class Engine:
    def __init__(self, base_url: str, spec: Dict, snap: Snapshotter, seed: int = 1234, timeout: float = 12.0,
                 env_creds: Optional[List[Dict[str, str]]] = None, quiet_window: Optional[float] = None):
        self.base = base_url.rstrip("/")
        # None reproduces the oracle used in the original campaign; a number (seconds) enables the
        # quiescence control in exec_with_state
        self.quiet_window = quiet_window
        self.guard_stats = {"execs": 0, "execs_with_exclusions": 0, "quiesce_timeouts": 0, "quiesce_wait_s": 0.0}
        self.contract = Contract(spec)
        self.snap = snap
        self.gen = Gen(seed)
        self.client = httpx.Client(base_url=self.base, timeout=timeout, follow_redirects=False)
        self.principals: Dict[str, Dict] = {}
        self.instances: List[Dict] = []
        self.records: List[Dict] = []
        self.n_requests = 0
        self.t_start = time.time()
        # credentials the harness itself injected into the target's environment (administrator or
        # first-superuser accounts created at start-up). They are known because the harness set them,
        # not because the target's source was read.
        self.env_creds = env_creds or []
        self._db_cache: Dict[str, Any] = {}
        self.undeclared_security: set = set()
        self._probes: Optional[List[Dict]] = None

    # ------------------------------------------------------------------ transport
    def send(self, op: Dict, req: Dict, cred: Optional[Dict]) -> Dict:
        path = op["path"]
        for k, v in (req.get("path_params") or {}).items():
            path = path.replace("{" + k + "}", str(v))
        if re.search(r"\{\w+\}", path):
            # a request whose path is not fully instantiated is a harness failure, never evidence
            # about the target; it is reported as such and never scored as a violation
            return {"status": -1, "body": None, "text": "", "harness_error": "unsubstituted_path",
                    "path": path}
        headers = dict((cred or {}).get("headers", {}))
        kw: Dict[str, Any] = {"params": req.get("query") or None, "headers": headers}
        if req.get("body") is not None and op["method"] in ("post", "put", "patch", "delete"):
            if op.get("content_type") == "application/x-www-form-urlencoded":
                kw["data"] = req["body"]
            else:
                kw["json"] = req["body"]
        t0 = time.time()
        self.n_requests += 1
        try:
            r = self.client.request(op["method"].upper(), path, **kw)
            try:
                body = r.json()
            except Exception:
                body = r.text[:400]
            return {"status": r.status_code, "body": body, "ms": round((time.time() - t0) * 1000, 1), "path": path}
        except Exception as e:
            return {"status": 0, "body": f"{type(e).__name__}: {e}"[:200],
                    "ms": round((time.time() - t0) * 1000, 1), "path": path}

    def exec_with_state(self, op: Dict, req: Dict, cred: Optional[Dict]) -> Tuple[Dict, Dict]:
        if not self.quiet_window:
            before = self.snap.snapshot()
            resp = self.send(op, req, cred)
            after = self.snap.snapshot()
            return resp, delta(before, after)
        # Quiescence control (added 2026-11-19). A target may write to its own database without being
        # asked (a background job runner, a scheduler), and the oracle would otherwise attribute those
        # writes to whichever request happened to be in flight. So: (1) wait until the database has not
        # changed for one quiet window before taking the "before" snapshot; (2) after the request, watch
        # one more window; any table that changes with no request in flight - in the last pre-request
        # window if quiescence was not reached, or in the post-request window - is treated as background
        # and excluded from the delta. This favours precision: a table the request really wrote that
        # also has background activity is excluded too, and every exclusion is recorded.
        w = self.quiet_window
        before, quiet, pre_bg, waited = self._quiesce()
        resp = self.send(op, req, cred)
        after = self.snap.snapshot()
        time.sleep(w)
        post = self.snap.snapshot()
        bg = set(pre_bg) | self._changed_tables(delta(after, post))
        d = delta(before, after)
        self.guard_stats["execs"] += 1
        self.guard_stats["quiesce_wait_s"] += waited
        if not quiet:
            self.guard_stats["quiesce_timeouts"] += 1
        if bg:
            touched = self._changed_tables(d)
            excluded = sorted(bg & touched)
            if excluded:
                self.guard_stats["execs_with_exclusions"] += 1
                d = {k: [e for e in d[k] if e["table"] not in bg] for k in ("inserted", "deleted", "modified")}
                d.update({"n_inserted": len(d["inserted"]), "n_deleted": len(d["deleted"]),
                          "n_modified": len(d["modified"]),
                          "empty": not (d["inserted"] or d["deleted"] or d["modified"])})
                d["background_tables"] = excluded
        return resp, d

    @staticmethod
    def _changed_tables(d: Dict) -> set:
        return {e["table"] for k in ("inserted", "deleted", "modified") for e in d[k]}

    def _quiesce(self, timeout: float = 20.0):
        """Wait until two snapshots one quiet window apart are identical. Returns (snapshot, reached,
        tables that changed in the last window if not reached, seconds waited)."""
        t0 = time.time()
        a = self.snap.snapshot()
        while True:
            time.sleep(self.quiet_window)
            b = self.snap.snapshot()
            d = delta(a, b)
            if d["empty"]:
                return b, True, set(), round(time.time() - t0, 2)
            if time.time() - t0 > timeout:
                return b, False, self._changed_tables(d), round(time.time() - t0, 2)
            a = b

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _flat_fields(body: Any, prefix="") -> List[str]:
        out = []
        if isinstance(body, dict):
            for k, v in body.items():
                p = f"{prefix}{k}"
                if isinstance(v, dict):
                    out += Engine._flat_fields(v, p + ".")
                else:
                    out.append(p)
        return out

    @staticmethod
    def _lookup_field(obj: Any, dotted: str) -> Any:
        v = get_in(obj, dotted)
        if v is not None:
            return v
        leaf = dotted.split(".")[-1]
        # credential correspondence: a login form names the identifier and the secret with words that
        # need not coincide with the names the registration body used ("username" for an e-mail,
        # "password" for "password_hash"), so equivalent names are searched before giving up
        syn = None
        if re.fullmatch(r"(user)?name|login|identifier|user|e?mail", leaf, re.I):
            syn = re.compile(r"^(e?mail|username|login|user|name)$", re.I)
        elif re.search(r"pass(word|wd)?|secret", leaf, re.I):
            syn = re.compile(r"pass(word|wd)?(_hash)?|secret", re.I)
        if syn is not None:
            ordered = []
            stack = [obj]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    for k, vv in cur.items():
                        if isinstance(vv, str) and syn.search(k):
                            ordered.append((0 if k.lower() == leaf.lower() else 1, k, vv))
                        elif isinstance(vv, dict):
                            stack.append(vv)
            if ordered:
                ordered.sort(key=lambda t: t[0])
                return ordered[0][2]
        stack = [obj]
        while stack:
            cur = stack.pop()
            if isinstance(cur, dict):
                for k, vv in cur.items():
                    if k == leaf and not isinstance(vv, (dict, list)):
                        return vv
                    if isinstance(vv, dict):
                        stack.append(vv)
                    elif isinstance(vv, list):
                        stack += [x for x in vv if isinstance(x, dict)][:2]
        return None

    @staticmethod
    def _find_token(obj: Any, depth=0) -> Optional[str]:
        if depth > 5:
            return None
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and len(v) > 15 and re.search(r"token|jwt|access|key|session", k, re.I):
                    return v
            for v in obj.values():
                t = Engine._find_token(v, depth + 1)
                if t:
                    return t
        return None

    def _auth_styles(self, token: str) -> List[Dict]:
        out = []
        for _, sch in (self.contract.security_schemes or {}).items():
            t = (sch.get("type") or "").lower()
            if t == "apikey" and sch.get("in") == "header":
                out.append({"headers": {sch.get("name", "X-API-Key"): token}})
            elif t in ("http", "oauth2"):
                out.append({"headers": {"Authorization": f"Bearer {token}"}})
        out += [{"headers": {"Authorization": f"Bearer {token}"}},
                {"headers": {"Authorization": f"Token {token}"}},
                {"headers": {"Authorization": token}}]
        seen, uniq = set(), []
        for s in out:
            k = json.dumps(s, sort_keys=True)
            if k not in seen:
                seen.add(k); uniq.append(s)
        return uniq

    def _discriminating_probes(self) -> List[Dict]:
        """Read-only operations that refuse an anonymous request. Only such an operation can decide
        whether a candidate credential is accepted; an operation that answers anonymously would
        pronounce every candidate, including a malformed one, to be valid."""
        if self._probes is not None:
            return self._probes
        out = []
        for o in self.contract.ops:
            if o["method"] != "get" or len(out) >= 3:
                continue
            pv = self._item_values(o, None)
            if pv is None:
                continue
            r = self.send(o, {"path_params": pv, "query": {}, "body": None}, None)
            if r["status"] in (401, 403):
                out.append({"op": o, "path_params": pv})
        self._probes = out
        return out

    def _credential_works(self, style: Dict) -> bool:
        probes = self._discriminating_probes()
        for pr in probes:
            r = self.send(pr["op"], {"path_params": pr["path_params"], "query": {}, "body": None}, style)
            if 200 <= r["status"] < 300:
                return True
        return False

    # ------------------------------------------------------------------ 1. bootstrap
    def bootstrap(self) -> Dict:
        creates = [o for o in self.contract.ops if o["method"] == "post" and o["body_schema"]
                   and AUTH_CREATE.search(o["path"])]
        logins = [o for o in self.contract.ops if o["method"] == "post" and o["body_schema"]
                  and AUTH_LOGIN.search(o["path"])]
        creates.sort(key=lambda o: (0 if re.search(r"register|signup", o["path"], re.I) else 1, len(o["path"])))
        logins.sort(key=lambda o: (0 if re.search(r"login|signin", o["path"], re.I) else 1, len(o["path"])))
        info = {"register_ops": [o["path"] for o in creates][:3],
                "login_ops": [o["path"] for o in logins][:3], "principals": {}}
        for label in ("A", "B"):
            cred, identity = None, None
            for cop in creates[:3]:
                req = self.gen.request(cop)
                pv = self._item_values(cop, None)
                if pv is None:
                    continue
                req["path_params"] = pv or req.get("path_params", {})
                resp = self.send(cop, req, None)
                if not (200 <= resp["status"] < 300):
                    continue
                identity = req["body"]
                tok = self._find_token(resp["body"])
                if not tok:
                    for lop in logins[:3]:
                        lreq = self.gen.request(lop)
                        lpv = self._item_values(lop, None)
                        if lpv is None:
                            continue
                        lreq["path_params"] = lpv or lreq.get("path_params", {})
                        for f in self._flat_fields(lreq["body"]):
                            v = self._lookup_field(identity, f)
                            if v is not None:
                                set_in(lreq["body"], f, v)
                        lresp = self.send(lop, lreq, None)
                        tok = self._find_token(lresp["body"])
                        if tok:
                            break
                if tok:
                    cred = next((s for s in self._auth_styles(tok) if self._credential_works(s)),
                                self._auth_styles(tok)[0])
                break
            if cred is None and label == "A":
                cred, identity = self._env_login(logins[:3])
            self.principals[label] = {"cred": cred, "identity": identity}
            info["principals"][label] = {"registered": identity is not None, "has_token": cred is not None}
        info["two_principals"] = bool(self.principals.get("A", {}).get("cred")
                                      and self.principals.get("B", {}).get("cred")
                                      and self.principals["A"]["cred"] != self.principals["B"]["cred"])
        return info

    def _env_login(self, logins: List[Dict]):
        """Fall back to the credentials the harness injected into the environment. Targets that
        provision a single administrator at start-up expose no registration operation, so no
        principal can be obtained by the ordinary route."""
        for creds in self.env_creds:
            for lop in logins:
                lreq = self.gen.request(lop)
                lpv = self._item_values(lop, None)
                if lpv is None:
                    continue
                lreq["path_params"] = lpv or lreq.get("path_params", {})
                for f in self._flat_fields(lreq["body"]):
                    leaf = f.split(".")[-1]
                    if re.search(r"pass(word|wd)?|secret", leaf, re.I):
                        set_in(lreq["body"], f, creds["password"])
                    elif re.fullmatch(r"(user)?name|login|identifier|user|e?mail", leaf, re.I):
                        set_in(lreq["body"], f, creds["email"] if re.search(r"mail", leaf, re.I)
                               else creds["username"])
                for q in list(lreq.get("query") or {}):
                    if re.search(r"pass(word|wd)?|secret", q, re.I):
                        lreq["query"][q] = creds["password"]
                    elif re.fullmatch(r"(user)?name|login|identifier|user|e?mail", q, re.I):
                        lreq["query"][q] = creds["username"]
                resp = self.send(lop, lreq, None)
                tok = self._find_token(resp["body"])
                if tok:
                    styles = self._auth_styles(tok)
                    return next((s for s in styles if self._credential_works(s)), styles[0]), dict(creds)
        return None, None

    # ------------------------------------------------------------------ 2. seed
    def _variants(self, op: Dict, req: Dict) -> List[Dict]:
        """Body repair variants. Properties whose schema is empty carry no type information, so a
        request that the target rejects is retried with those properties re-typed as a list and then
        with all non-required properties removed."""
        out = [req]
        sch = op.get("body_schema") or {}
        props = (sch.get("properties") or {})
        inner_key = next(iter(props)) if len(props) == 1 and isinstance(next(iter(props.values())), dict) \
            and (next(iter(props.values())).get("properties")) else None
        inner = props[inner_key]["properties"] if inner_key else props
        required = set((props[inner_key].get("required") if inner_key else sch.get("required")) or [])
        unknown = [k for k, v in inner.items() if isinstance(v, dict) and not v]
        if unknown and isinstance(req.get("body"), dict):
            v2 = copy.deepcopy(req)
            tgt = v2["body"][inner_key] if inner_key and isinstance(v2["body"].get(inner_key), dict) else v2["body"]
            for k in unknown:
                if isinstance(tgt, dict) and k in tgt:
                    tgt[k] = [str(tgt[k])] if not isinstance(tgt[k], list) else tgt[k]
            out.append(v2)
        if isinstance(req.get("body"), dict):
            v3 = copy.deepcopy(req)
            tgt = v3["body"][inner_key] if inner_key and isinstance(v3["body"].get(inner_key), dict) else v3["body"]
            if isinstance(tgt, dict):
                for k in list(tgt):
                    if k not in required:
                        tgt.pop(k, None)
            out.append(v3)
        return out

    def seed(self, per_op: int = 2) -> Dict:
        creates = [o for o in self.contract.ops if o["method"] == "post" and o.get("res_kind") == "collection"]
        made, attempted = 0, 0
        for op in creates:
            for label in ("A", "B"):
                cred = self.principals.get(label, {}).get("cred")
                if op["secured"] and not cred:
                    continue
                for _ in range(per_op):
                    for req in self._variants(op, self.gen.request(op)):
                        pv = self._item_values(op, None)
                        if pv is None:
                            continue
                        req["path_params"] = pv or req.get("path_params", {})
                        attempted += 1
                        resp, d = self.exec_with_state(op, req, cred)
                        if resp["status"] in (401, 403) and not op["secured"] and cred:
                            # the specification does not declare a security requirement the
                            # implementation nevertheless enforces; the operation is treated as
                            # secured from here on, which also makes MR2 applicable to it
                            op["secured"] = True
                            self.undeclared_security.add(op["operation_id"])
                            resp, d = self.exec_with_state(op, req, cred)
                        if 200 <= resp["status"] < 300 and d["inserted"]:
                            made += 1
                            for ins in d["inserted"]:
                                self.instances.append({"owner": label, "resource": op.get("resource"),
                                                       "table": ins["table"], "key": ins["key"], "row": ins["row"],
                                                       "req": req, "resp_body": resp["body"],
                                                       "create_op": op["operation_id"]})
                            break
        return {"create_ops": len(creates), "create_attempts": attempted, "successful_creates": made,
                "instances": len(self.instances),
                "tables_touched": sorted({i["table"] for i in self.instances})[:12]}

    # ------------------------------------------------------------------ item resolution
    def _db_value(self, name: str) -> Optional[Any]:
        """Resolve a path parameter from the persistent state.

        Some applications template every path with a tenant or scope segment ("/{organization}/...")
        whose admissible values exist in the database before any test runs. Because the oracle
        already reads the whole schema, such a parameter can be satisfied from an existing row
        instead of being declared unresolvable. The value is drawn from the table whose name matches
        the parameter, and from the column the parameter names (or a conventional identifier)."""
        if name in self._db_cache:
            return self._db_cache[name]
        base = re.sub(r"_?id$", "", name, flags=re.I).lower() or name.lower()
        col = "id" if re.search(r"_?id$", name, re.I) else None
        best = None
        for t in self.snap.tables():
            leaf = t.split(".")[-1].lower()
            if leaf not in (base, base + "s", base + "es", base.rstrip("s"), name.lower()):
                continue
            rows = self.snap.snapshot().get(t, {})
            if not rows:
                continue
            row = next(iter(rows.values()))
            for cand in ([col] if col else []) + ["slug", "name", "code", "key", "id", "uuid"]:
                if cand and row.get(cand) is not None:
                    best = row[cand]; break
            if best is not None:
                break
        self._db_cache[name] = best
        return best

    def _item_values(self, op: Dict, inst: Optional[Dict]) -> Optional[Dict[str, Any]]:
        # the path template is authoritative: a specification may omit a parameter declaration for a
        # segment it nevertheless templates, and an unsubstituted segment would otherwise be sent
        # verbatim and be mistaken for a defect
        declared = [p for p in op["params"] if p.get("in") == "path"]
        names = {p.get("name") for p in declared}
        params = list(declared) + [{"name": n, "in": "path", "schema": {"type": "string"}}
                                   for n in re.findall(r"\{(\w+)\}", op["path"]) if n not in names]
        if not params:
            return {}
        row = inst["row"] if inst else {}
        body = inst.get("resp_body") if inst else None
        out: Dict[str, Any] = {}
        for p in params:
            nm = p.get("name")
            v = self._lookup_field(body, nm) if isinstance(body, (dict, list)) else None
            if v is None and nm in row:
                v = row[nm]
            if v is None:
                v = self._db_value(nm)
            if v is None and inst:
                for cand in ("id", "uuid", "slug", "username", "pk", "key", "name", "email"):
                    if cand in row and row[cand] is not None:
                        v = row[cand]; break
                if v is None:
                    v = inst["key"].split("|")[0]
            if v is None:
                return None
            out[nm] = v
        return out

    @staticmethod
    def _is_collection_body(body: Any) -> bool:
        if isinstance(body, list):
            return True
        if isinstance(body, dict):
            if any(k.lower() in ("id", "uuid", "slug") for k in body):
                return False
            return any(isinstance(v, list) for v in body.values())
        return False

    @staticmethod
    def _absent_like(v: Any) -> Any:
        s = str(v)
        if re.fullmatch(r"\d+", s):
            return str(int(s) + 987654)
        if re.fullmatch(r"[0-9a-fA-F-]{32,36}", s):
            return "99999999-9999-4999-8999-999999999999"
        return s + "-sms-absent"

    def _owned(self, label: str, op: Optional[Dict] = None, exclude_key: Optional[str] = None) -> Optional[Dict]:
        """Prefer an instance of the resource the operation acts on; fall back to any instance."""
        cands = [x for x in self.instances
                 if x["owner"] == label and not x.get("consumed") and x["key"] != exclude_key]
        if op is not None:
            same = [x for x in cands if x.get("resource") and x["resource"] == op.get("resource")]
            if same:
                return same[0]
            # sub-resources: /api/articles/{slug}/comments is served by /api/articles instances
            pref = [x for x in cands if x.get("resource") and op.get("resource", "").startswith(x["resource"])]
            if pref:
                return pref[0]
        return cands[0] if cands else None

    # ------------------------------------------------------------------ 3/4. instantiate + evaluate
    def run_relations(self, max_per_relation: int = 40) -> Dict:
        by_kind: Dict[str, List[Dict]] = {}
        for i in self.contract.invariants():
            by_kind.setdefault(i["kind"], []).append(i)
        counts = {k: 0 for k in R.ORDER}
        stats = {"instantiated": 0, "executed": 0, "source_ok": 0, "violations": 0,
                 "not_applicable": {}, "source_status": {}, "source_failed": 0}

        def evaluate(mr, op, src, srcd, fu, fud, extra=None, state_ok_override=None):
            spec = R.CATALOGUE[mr]
            if src.get("harness_error") or fu.get("harness_error"):
                na(mr.split("_")[0], "harness_" + (src.get("harness_error") or fu.get("harness_error")))
                return
            if spec["resp_ok"] is None or spec["resp_ok"] == "no_server_error":
                resp_ok = True
            else:
                resp_ok = fu["status"] in spec["resp_ok"]
            if fu["status"] >= 500 or fu["status"] == 0:
                resp_ok = False
            if state_ok_override is not None:
                state_ok = state_ok_override
            else:
                state_ok = fud["empty"] if spec["state"] == "empty" else True
            viol = not (resp_ok and state_ok)
            rec = {"mr": mr, "target_op": op["operation_id"], "method": op["method"], "path": op["path"],
                   "source": {"status": src["status"], "delta": summarize(srcd)},
                   "followup": {"status": fu["status"], "delta": summarize(fud),
                                "body": json.dumps(fu["body"])[:300] if not isinstance(fu["body"], str) else fu["body"][:300]},
                   "verdict": {"violation": viol, "resp_ok": resp_ok, "state_ok": state_ok,
                               "kind": R.violation_kind(mr, resp_ok, state_ok, fu["status"]) if viol else "none"}}
            if extra:
                rec.update(extra)
            self.records.append(rec)
            counts[mr] += 1
            stats["executed"] += 1
            if viol:
                stats["violations"] += 1

        def note_src(st):
            k = str(st)
            stats["source_status"][k] = stats["source_status"].get(k, 0) + 1

        def na(mr, why):
            k = f"{mr}:{why}"
            stats["not_applicable"][k] = stats["not_applicable"].get(k, 0) + 1

        def prep_path(op, req, inst=None):
            pv = self._item_values(op, inst or self._owned("A", op))
            if pv is None:
                return False
            req["path_params"] = pv or req.get("path_params", {})
            return True

        # ---------------- MR1 principal substitution
        credA = self.principals.get("A", {}).get("cred")
        credB = self.principals.get("B", {}).get("cred")
        for i in by_kind.get("OWNED_ITEM", []):
            op = i["op"]
            if counts["MR1_PRINCIPAL_SUBSTITUTION"] >= max_per_relation:
                break
            if not (credA and credB and credA != credB):
                na("MR1", "no_two_principals"); continue
            inst = self._owned("A", op)
            if not inst:
                na("MR1", "no_owned_instance"); continue
            req = self.gen.request(op)
            if not prep_path(op, req, inst):
                na("MR1", "unresolvable_path"); continue
            stats["instantiated"] += 1
            src, srcd = self.exec_with_state(op, req, credA)
            if not (200 <= src["status"] < 300):
                stats["source_failed"] += 1; note_src(src["status"]); continue
            stats["source_ok"] += 1
            sib = self._owned("A", op, exclude_key=inst["key"]) or inst
            req2 = copy.deepcopy(req)
            pv2 = self._item_values(op, sib)
            if pv2:
                req2["path_params"] = pv2
            fu, fud = self.exec_with_state(op, req2, credB)
            owned_keys = {(x["table"], x["key"]) for x in self.instances if x["owner"] == "A"}
            touched = {(e["table"], e["key"]) for e in fud["deleted"] + fud["modified"]}
            interfered = sorted(f"{t}#{k}" for t, k in (touched & owned_keys))
            evaluate("MR1_PRINCIPAL_SUBSTITUTION", op, src, srcd, fu, fud,
                     {"note": "follow-up executes as principal B against an item created by A",
                      "interfered_rows": interfered},
                     state_ok_override=(len(interfered) == 0))

        # ---------------- MR2 credential removal
        for i in by_kind.get("REQUIRES_CREDENTIAL", []):
            op = i["op"]
            if counts["MR2_CREDENTIAL_REMOVAL"] >= max_per_relation:
                break
            if not credA:
                na("MR2", "no_credential"); continue
            req = self.gen.request(op)
            if not prep_path(op, req):
                na("MR2", "unresolvable_path"); continue
            stats["instantiated"] += 1
            src, srcd = self.exec_with_state(op, req, credA)
            if not (200 <= src["status"] < 300):
                stats["source_failed"] += 1; note_src(src["status"]); continue
            stats["source_ok"] += 1
            req2 = self.gen.request(op); req2["path_params"] = req["path_params"]
            fu, fud = self.exec_with_state(op, req2, None)
            evaluate("MR2_CREDENTIAL_REMOVAL", op, src, srcd, fu, fud)

        # ---------------- MR3 temporal inversion
        # Follow-up first, control second, unconditionally: the transformed (inverted) request always
        # executes first, against the state as prepared, so the control -- which always runs strictly
        # afterwards -- can never influence or collide with it. The control then always runs, and an
        # accepted-or-5xx follow-up is attributed to the inversion only once the control confirms the
        # untransformed request is itself accepted under the same preparation. If the control does not
        # succeed, nothing here can be attributed to the transformation, so the instance is counted as
        # a failed source rather than as a violation.
        for i in by_kind.get("ORDERED_TEMPORAL_PAIR", []):
            op, a, b = i["op"], i["args"]["start"], i["args"]["end"]
            if counts["MR3_TEMPORAL_INVERSION"] >= max_per_relation:
                break
            # the source execution always presents a valid credential: an operation the specification
            # leaves undeclared may still be enforced, and a relation whose source is refused for want
            # of a credential carries no information about the property under test
            cred = credA
            if not cred and op["secured"]:
                na("MR3", "no_credential"); continue
            base_req = None
            for cand in self._variants(op, self.gen.request(op)):
                if cand["body"] is not None and has_in(cand["body"], a) and has_in(cand["body"], b):
                    base_req = cand; break
            if base_req is None:
                na("MR3", "fields_absent_from_body"); continue
            if not prep_path(op, base_req):
                na("MR3", "unresolvable_path"); continue
            start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=40)).replace(microsecond=0)
            end = start + dt.timedelta(days=3)
            date_only = len(str(get_in(base_req["body"], a) or "")) <= 10
            fmt = (lambda x: x.date().isoformat()) if date_only else (lambda x: x.isoformat())
            stats["instantiated"] += 1
            fu_req = copy.deepcopy(base_req)
            set_in(fu_req["body"], a, fmt(end)); set_in(fu_req["body"], b, fmt(start))     # inverted
            fu, fud = self.exec_with_state(op, fu_req, cred)
            ctl_req = copy.deepcopy(base_req)
            set_in(ctl_req["body"], a, fmt(start)); set_in(ctl_req["body"], b, fmt(end))   # well ordered
            ctl, ctld = self.exec_with_state(op, ctl_req, cred)
            if not (200 <= ctl["status"] < 300):
                stats["source_failed"] += 1; note_src(ctl["status"]); continue
            stats["source_ok"] += 1
            evaluate("MR3_TEMPORAL_INVERSION", op, ctl, ctld, fu, fud,
                     {"fields": {"start": a, "end": b}, "control_status": ctl["status"]})

        # ---------------- MR4 quantity negation
        # Follow-up first, control second, unconditionally -- see the MR3 note above: this order
        # makes it impossible for the control to influence or collide with the follow-up, and the
        # control is now always required to succeed before a violation is attributed to the negation.
        for i in by_kind.get("NONNEGATIVE_QUANTITY", []):
            op, f = i["op"], i["args"]["field"]
            if counts["MR4_QUANTITY_NEGATION"] >= max_per_relation:
                break
            # the source execution always presents a valid credential: an operation the specification
            # leaves undeclared may still be enforced, and a relation whose source is refused for want
            # of a credential carries no information about the property under test
            cred = credA
            if not cred and op["secured"]:
                na("MR4", "no_credential"); continue
            base_req = None
            for cand in self._variants(op, self.gen.request(op)):
                if cand["body"] is not None and has_in(cand["body"], f):
                    base_req = cand; break
            if base_req is None:
                na("MR4", "field_absent_from_body"); continue
            v = get_in(base_req["body"], f)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                v = 3
            set_in(base_req["body"], f, v)
            if not prep_path(op, base_req):
                na("MR4", "unresolvable_path"); continue
            stats["instantiated"] += 1
            fu_req = copy.deepcopy(base_req); set_in(fu_req["body"], f, -abs(v))
            fu, fud = self.exec_with_state(op, fu_req, cred)
            ctl, ctld = self.exec_with_state(op, copy.deepcopy(base_req), cred)
            if not (200 <= ctl["status"] < 300):
                stats["source_failed"] += 1; note_src(ctl["status"]); continue
            stats["source_ok"] += 1
            evaluate("MR4_QUANTITY_NEGATION", op, ctl, ctld, fu, fud,
                     {"fields": {"quantity": f}, "control_status": ctl["status"]})

        # ---------------- MR5 delete idempotence
        for i in by_kind.get("DELETE_IDEMPOTENT", []):
            op = i["op"]
            if counts["MR5_DELETE_IDEMPOTENCE"] >= max_per_relation:
                break
            # the source execution always presents a valid credential: an operation the specification
            # leaves undeclared may still be enforced, and a relation whose source is refused for want
            # of a credential carries no information about the property under test
            cred = credA
            if not cred and op["secured"]:
                na("MR5", "no_credential"); continue
            inst = self._owned("A", op)
            req = self.gen.request(op)
            if not prep_path(op, req, inst):
                na("MR5", "unresolvable_path"); continue
            stats["instantiated"] += 1
            src, srcd = self.exec_with_state(op, req, cred)
            if not (200 <= src["status"] < 300):
                stats["source_failed"] += 1; note_src(src["status"]); continue
            if srcd["empty"]:
                na("MR5", "source_removed_nothing"); continue
            stats["source_ok"] += 1
            if inst:
                inst["consumed"] = True
            fu, fud = self.exec_with_state(op, copy.deepcopy(req), cred)
            evaluate("MR5_DELETE_IDEMPOTENCE", op, src, srcd, fu, fud)

        # ---------------- MR6 dangling reference
        # Follow-up first, control second, unconditionally -- see the MR3 note above.
        for i in by_kind.get("FOREIGN_REFERENCE", []):
            op, f = i["op"], i["args"]["field"]
            if counts["MR6_DANGLING_REFERENCE"] >= max_per_relation:
                break
            # the source execution always presents a valid credential: an operation the specification
            # leaves undeclared may still be enforced, and a relation whose source is refused for want
            # of a credential carries no information about the property under test
            cred = credA
            if not cred and op["secured"]:
                na("MR6", "no_credential"); continue
            base_req = None
            for cand in self._variants(op, self.gen.request(op)):
                if cand["body"] is not None and has_in(cand["body"], f):
                    base_req = cand; break
            if base_req is None:
                na("MR6", "field_absent_from_body"); continue
            ref = next((x for x in self.instances if str(x["key"].split("|")[0]).isdigit()), None)
            if ref is not None and isinstance(get_in(base_req["body"], f), int):
                set_in(base_req["body"], f, int(ref["key"].split("|")[0]))
            if not prep_path(op, base_req):
                na("MR6", "unresolvable_path"); continue
            stats["instantiated"] += 1
            fu_req = copy.deepcopy(base_req)
            set_in(fu_req["body"], f, self._absent_like(get_in(base_req["body"], f)))
            fu, fud = self.exec_with_state(op, fu_req, cred)
            ctl, ctld = self.exec_with_state(op, copy.deepcopy(base_req), cred)
            if not (200 <= ctl["status"] < 300):
                stats["source_failed"] += 1; note_src(ctl["status"]); continue
            stats["source_ok"] += 1
            evaluate("MR6_DANGLING_REFERENCE", op, ctl, ctld, fu, fud,
                     {"fields": {"reference": f}, "control_status": ctl["status"]})

        # ---------------- MR7 absent path resource
        seen = set()
        for i in by_kind.get("PATH_REFERENCE", []):
            op, f = i["op"], i["args"]["field"]
            if counts["MR7_ABSENT_PATH_RESOURCE"] >= max_per_relation or op["operation_id"] in seen:
                continue
            # the relation constrains item operations. A read of a collection scoped by an absent
            # instance may legitimately answer with an empty collection, so such operations are
            # outside the relation's applicability predicate rather than violations of it.
            short = "MR7"
            # the source execution always presents a valid credential: an operation the specification
            # leaves undeclared may still be enforced, and a relation whose source is refused for want
            # of a credential carries no information about the property under test
            cred = credA
            if not cred and op["secured"]:
                na(short, "no_credential"); continue
            inst = self._owned("A", op)
            req = self.gen.request(op)
            if not prep_path(op, req, inst) or f not in (req["path_params"] or {}):
                na(short, "unresolvable_path"); continue
            stats["instantiated"] += 1
            src, srcd = self.exec_with_state(op, req, cred)
            if not (200 <= src["status"] < 300):
                stats["source_failed"] += 1; note_src(src["status"]); continue
            stats["source_ok"] += 1
            seen.add(op["operation_id"])
            # whether the operation reads a collection is decided by what it answered, not by the
            # shape of its URL: an operation that returns a list under a valid identifier may return
            # an empty list under an absent one, so only the weaker relation MR8 applies to it
            mr_name = ("MR8_ABSENT_SCOPE_TOLERANCE"
                       if (op["method"] == "get" and self._is_collection_body(src.get("body")))
                       else "MR7_ABSENT_PATH_RESOURCE")
            if counts[mr_name] >= max_per_relation:
                continue
            req2 = copy.deepcopy(req)
            req2["path_params"][f] = self._absent_like(req["path_params"][f])
            fu, fud = self.exec_with_state(op, req2, cred)
            evaluate(mr_name, op, src, srcd, fu, fud, {"fields": {"path_param": f}})

        stats["per_relation"] = counts
        stats["requests"] = self.n_requests
        stats["wall_s"] = round(time.time() - self.t_start, 1)
        if self.quiet_window:
            stats["quiescence"] = dict(self.guard_stats, window_s=self.quiet_window,
                                       quiesce_wait_s=round(self.guard_stats["quiesce_wait_s"], 1))
        return stats
