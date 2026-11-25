"""
Contract analysis: derive a resource model and candidate semantic invariants from an OpenAPI 3 document.

This stage is deterministic and uses only the served specification. It produces, for each operation:
  * the HTTP method and templated path, with path/query parameter schemas
  * a resolved request-body schema (all $ref pointers expanded)
  * whether the operation declares a security requirement (authenticated) and which scheme
  * the resource it acts on, expressed as a (collection path, item path) pair, and its role in the
    resource life cycle: create / read-collection / read-item / update-item / delete-item
  * candidate invariants attached to the operation, each of which is the applicability witness for
    one metamorphic relation:
      ORDERED_TEMPORAL_PAIR(a, b)   two body properties of date/date-time type whose names form a
                                    conventional ordered pair (start/end, from/to, check-in/check-out …)
      NONNEGATIVE_QUANTITY(p)       a numeric body property whose name denotes a count, price or amount
      FOREIGN_REFERENCE(p, r)       a body property that names the identifier of another resource r
      OWNED_ITEM                    an item operation reachable only with a credential, whose instances
                                    are created by an authenticated principal
No target source code is read at this stage.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

DATE_NAME = re.compile(r"date|time|at$|_on$|day|dt$", re.I)
START_TOK = ["start", "begin", "from", "check_in", "checkin", "check-in", "valid_from", "since",
             "open", "arrival", "departure_from", "issued", "created", "effective", "entry", "in"]
END_TOK = ["end", "finish", "to", "check_out", "checkout", "check-out", "valid_to", "until", "till",
           "close", "departure", "expiry", "expires", "expiration", "exit", "out"]
QTY_NAME = re.compile(r"^(qty|quantity|count|amount|price|cost|total|stock|balance|units?|"
                      r"num_\w+|n_\w+|\w+_count|\w+_qty|\w+_price|\w+_amount|\w+_total|capacity|"
                      r"weight|duration|size|limit|score|rating|age|guests?|adults?|children)$", re.I)
ID_NAME = re.compile(r"^(\w+?)_?id$|^id_(\w+)$", re.I)
MUTATING = {"post", "put", "patch", "delete"}


def _resolve(node, spec, depth=0):
    """Expand $ref pointers (bounded depth; cycles collapse to an empty object)."""
    if depth > 8 or not isinstance(node, dict):
        return node if not isinstance(node, dict) else {}
    if "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            return {}
        cur: Any = spec
        for part in ref[2:].split("/"):
            cur = (cur or {}).get(part, {})
        return _resolve(cur, spec, depth + 1)
    out = {}
    for k, v in node.items():
        if isinstance(v, dict):
            out[k] = _resolve(v, spec, depth + 1)
        elif isinstance(v, list):
            out[k] = [_resolve(x, spec, depth + 1) if isinstance(x, dict) else x for x in v]
        else:
            out[k] = v
    # allOf flattening keeps property discovery simple downstream
    if "allOf" in out:
        merged = {"type": "object", "properties": {}, "required": []}
        for sub in out["allOf"]:
            if isinstance(sub, dict):
                merged["properties"].update(sub.get("properties", {}))
                merged["required"] += sub.get("required", [])
        for k, v in out.items():
            if k != "allOf":
                merged.setdefault(k, v)
        merged["properties"].update(out.get("properties", {}))
        out = merged
    return out


def _norm(name: str) -> List[str]:
    return [t for t in re.split(r"[_\-\s]+|(?<=[a-z])(?=[A-Z])", name.lower()) if t]


def _role(tokens: List[str], toklist: List[str]) -> bool:
    joined = "_".join(tokens)
    return any(t == joined or t in tokens or joined.startswith(t + "_") or joined.endswith("_" + t)
               for t in toklist)


def body_properties(schema: Dict) -> Dict[str, Dict]:
    if not isinstance(schema, dict):
        return {}
    if schema.get("type") == "array":
        return body_properties(schema.get("items", {}))
    props = dict(schema.get("properties", {}) or {})
    # single-key envelopes such as {"user": {...}} used by the RealWorld spec
    if len(props) == 1:
        only = next(iter(props.values()))
        if isinstance(only, dict) and only.get("properties"):
            inner = dict(only["properties"])
            return {f"{next(iter(props))}.{k}": v for k, v in inner.items()}
    return props


def find_temporal_pairs(props: Dict[str, Dict]) -> List[Tuple[str, str]]:
    dates = []
    for name, sch in props.items():
        if not isinstance(sch, dict):
            continue
        leaf = name.split(".")[-1]
        fmt = str(sch.get("format", ""))
        typ = sch.get("type")
        anyof = " ".join(str(x.get("format", "")) for x in sch.get("anyOf", []) if isinstance(x, dict))
        is_date = fmt in ("date", "date-time") or "date" in anyof or (typ == "string" and DATE_NAME.search(leaf))
        if is_date:
            dates.append(name)
    pairs = []
    for a in dates:
        for b in dates:
            if a >= b:
                continue
            ta, tb = _norm(a.split(".")[-1]), _norm(b.split(".")[-1])
            if _role(ta, START_TOK) and _role(tb, END_TOK):
                pairs.append((a, b))
            elif _role(tb, START_TOK) and _role(ta, END_TOK):
                pairs.append((b, a))
    return pairs


def find_quantities(props: Dict[str, Dict]) -> List[str]:
    out = []
    for name, sch in props.items():
        if not isinstance(sch, dict):
            continue
        leaf = name.split(".")[-1]
        typ = sch.get("type")
        types = {typ} | {x.get("type") for x in sch.get("anyOf", []) if isinstance(x, dict)}
        if ({"integer", "number"} & types) and QTY_NAME.match(leaf):
            # a schema that already forbids negatives is not a candidate: the contract states the rule
            if sch.get("minimum") is not None or sch.get("exclusiveMinimum") is not None:
                continue
            out.append(name)
    return out


def find_foreign_refs(props: Dict[str, Dict], resources: List[str]) -> List[Tuple[str, str]]:
    out = []
    for name, sch in props.items():
        if not isinstance(sch, dict):
            continue
        leaf = name.split(".")[-1]
        m = ID_NAME.match(leaf)
        if not m:
            continue
        base = (m.group(1) or m.group(2) or "").lower()
        if not base:
            continue
        types = {sch.get("type")} | {x.get("type") for x in sch.get("anyOf", []) if isinstance(x, dict)}
        if not ({"integer", "string"} & types):
            continue
        for r in resources:
            rs = r.rstrip("s")
            if base == r or base == rs or base + "s" == r:
                out.append((name, r)); break
        else:
            out.append((name, base))
    return out


class Contract:
    def __init__(self, spec: Dict):
        self.spec = spec
        self.ops: List[Dict] = []
        self.security_schemes = (spec.get("components", {}) or {}).get("securitySchemes", {}) or {}
        self.global_security = spec.get("security", [])
        self._parse()
        self.resources = self.resource_model()

    def _parse(self):
        base = ""
        servers = self.spec.get("servers") or []
        if servers and isinstance(servers[0], dict):
            u = servers[0].get("url", "")
            if u.startswith("/"):
                base = u.rstrip("/")
        for path, item in (self.spec.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            common = item.get("parameters", [])
            for method, op in item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"} or not isinstance(op, dict):
                    continue
                params = [_resolve(p, self.spec) for p in (common + op.get("parameters", []))]
                rb = _resolve(op.get("requestBody", {}), self.spec)
                content = (rb.get("content") or {})
                schema = {}
                for ct in ("application/json", "application/x-www-form-urlencoded", "multipart/form-data"):
                    if ct in content:
                        schema = _resolve(content[ct].get("schema", {}), self.spec)
                        break
                sec = op.get("security", self.global_security)
                self.ops.append({
                    "method": method.lower(),
                    "path": base + path,
                    "raw_path": path,
                    "operation_id": op.get("operationId") or f"{method.lower()}_{path}",
                    "summary": op.get("summary", ""),
                    "tags": op.get("tags", []),
                    "params": params,
                    "body_schema": schema,
                    "body_required": bool(rb.get("required", False)),
                    "content_type": next((ct for ct in ("application/json", "application/x-www-form-urlencoded",
                                                        "multipart/form-data") if ct in content), None),
                    "secured": bool(sec),
                    "responses": sorted(str(k) for k in (op.get("responses") or {})),
                })

    # ------------------------------------------------------------------ resource model
    def resource_model(self) -> Dict[str, Dict]:
        """Group operations into resources keyed by the collection path."""
        res: Dict[str, Dict] = {}
        for op in self.ops:
            segs = [s for s in op["path"].split("/") if s]
            if not segs:
                continue
            templated = [i for i, s in enumerate(segs) if s.startswith("{")]
            # only the final segment decides the role: a templated segment earlier in the path is a
            # scope (a tenant, an owning resource), so "/{organization}/incidents" is the collection
            # of incidents within an organization and not a sub-resource lookup
            if templated and templated[-1] == len(segs) - 1:
                coll = "/" + "/".join(segs[:-1]); kind = "item"
            else:
                coll = "/" + "/".join(segs); kind = "collection"
            name = next((s for s in reversed(coll.split("/")) if s and not s.startswith("{")), coll)
            r = res.setdefault(coll, {"collection": coll, "name": name, "ops": [], "item_path": None})
            r["ops"].append(op)
            if kind == "item" and r["item_path"] is None:
                r["item_path"] = op["path"]
            op["resource"] = coll
            op["res_kind"] = kind
        return res

    # ------------------------------------------------------------------ invariants
    def invariants(self) -> List[Dict]:
        res = self.resource_model()
        names = [r["name"].lower() for r in res.values()]
        inv = []
        for op in self.ops:
            props = body_properties(op["body_schema"])
            for a, b in find_temporal_pairs(props):
                inv.append({"kind": "ORDERED_TEMPORAL_PAIR", "op": op, "args": {"start": a, "end": b}})
            for p in find_quantities(props):
                inv.append({"kind": "NONNEGATIVE_QUANTITY", "op": op, "args": {"field": p}})
            for p, r in find_foreign_refs(props, names):
                inv.append({"kind": "FOREIGN_REFERENCE", "op": op, "args": {"field": p, "resource": r}})
            # path-level foreign references (item lookups by id)
            for prm in op["params"]:
                if prm.get("in") == "path":
                    inv.append({"kind": "PATH_REFERENCE", "op": op, "args": {"field": prm.get("name")}})
            if op["secured"]:
                inv.append({"kind": "REQUIRES_CREDENTIAL", "op": op, "args": {}})
                # a mutating operation that names an existing instance anywhere in its path acts on
                # an owned item, whether the instance is named by the final segment ("/articles/{slug}")
                # or by an earlier one ("/articles/{slug}/favorite")
                if op["method"] in MUTATING and "{" in op["path"]:
                    inv.append({"kind": "OWNED_ITEM", "op": op, "args": {}})
            if op["method"] == "delete":
                inv.append({"kind": "DELETE_IDEMPOTENT", "op": op, "args": {}})
        return inv
