"""
Schema-driven request synthesis.

Values are generated from the OpenAPI schema with a fixed random seed so that a source test and its
follow-up differ only in the transformation under test. Name-aware heuristics (emails, passwords,
dates, identifiers) raise the proportion of requests the target accepts, which matters because a
metamorphic relation can only be evaluated when the source execution succeeds.
"""
import datetime as dt
import random
import re
import string
from typing import Any, Dict, List, Optional

EMAIL = re.compile(r"e?mail", re.I)
PASSWORD = re.compile(r"pass(word|wd)?|secret", re.I)
URLF = re.compile(r"url|uri|link|href|image|photo|avatar", re.I)
NAMEF = re.compile(r"name|title|label|slug|username|login", re.I)
PHONE = re.compile(r"phone|mobile|tel", re.I)


class Gen:
    def __init__(self, seed: int = 1234):
        self.rng = random.Random(seed)
        self.n = 0

    def token(self, k=8):
        return "".join(self.rng.choice(string.ascii_lowercase) for _ in range(k))

    def unique(self, prefix="sms"):
        self.n += 1
        return f"{prefix}{self.n}{self.token(4)}"

    # ------------------------------------------------------------------ scalars
    def value(self, name: str, schema: Dict, depth=0) -> Any:
        if not isinstance(schema, dict):
            return self.unique()
        if "enum" in schema and schema["enum"]:
            return schema["enum"][0]
        if "default" in schema and schema["default"] is not None:
            return schema["default"]
        if "const" in schema:
            return schema["const"]
        for key in ("anyOf", "oneOf"):
            if key in schema and isinstance(schema[key], list):
                opts = [s for s in schema[key] if isinstance(s, dict) and s.get("type") != "null"]
                if opts:
                    return self.value(name, opts[0], depth + 1)
        t = schema.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), "string")
        fmt = schema.get("format", "")
        leaf = (name or "").split(".")[-1]
        # an anchored literal pattern states the only admissible value (OAuth2 "grant_type": "^password$")
        pat = schema.get("pattern")
        if isinstance(pat, str) and re.fullmatch(r"\^[A-Za-z0-9_.\- ]+\$", pat or ""):
            return pat[1:-1]

        if t == "object" or (t is None and schema.get("properties")):
            return self.body(schema, depth + 1)
        if t == "array":
            if depth > 3:
                return []
            return [self.value(leaf, schema.get("items", {"type": "string"}), depth + 1)]
        if t == "boolean":
            return True
        if t == "integer":
            lo = schema.get("minimum", 1)
            return int(max(1, lo if isinstance(lo, (int, float)) else 1))
        if t == "number":
            lo = schema.get("minimum", 1)
            return float(max(1.0, lo if isinstance(lo, (int, float)) else 1.0))
        # strings
        if fmt == "date":
            return (dt.date.today() + dt.timedelta(days=3)).isoformat()
        if fmt == "date-time":
            return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)).replace(microsecond=0).isoformat()
        if fmt == "uuid":
            return "11111111-2222-4333-8444-555555555555"
        if fmt in ("email", "idn-email") or EMAIL.search(leaf):
            return f"{self.unique('u')}@example.com"
        if PASSWORD.search(leaf):
            return "SmsBench!2345"
        if fmt in ("uri", "url") or URLF.search(leaf):
            return "https://example.com/" + self.token(5)
        if PHONE.search(leaf):
            return "+15550000000"
        if NAMEF.search(leaf):
            return self.unique("n")
        mn = schema.get("minLength", 1) or 1
        v = self.unique("s")
        return v if len(v) >= mn else v + "x" * (mn - len(v))

    def body(self, schema: Dict, depth=0) -> Any:
        if not isinstance(schema, dict):
            return {}
        if schema.get("type") == "array":
            return [self.body(schema.get("items", {}), depth + 1)]
        props = schema.get("properties") or {}
        req = set(schema.get("required") or [])
        out = {}
        for k, s in props.items():
            # every declared property is populated; the required-only body is offered separately as a
            # repair variant, so acceptance does not depend on a coin flip
            out[k] = self.value(k, s, depth + 1)
        return out

    # ------------------------------------------------------------------ whole request
    def request(self, op: Dict) -> Dict:
        path = op["path"]
        path_vals, query = {}, {}
        for p in op.get("params", []):
            if not isinstance(p, dict):
                continue
            loc, nm = p.get("in"), p.get("name")
            if not nm:
                continue
            sch = p.get("schema", {"type": "string"})
            if loc == "path":
                path_vals[nm] = self.value(nm, sch)
            elif loc == "query" and (p.get("required") or self.rng.random() < 0.25):
                query[nm] = self.value(nm, sch)
        body = self.body(op["body_schema"]) if op.get("body_schema") else None
        return {"path_params": path_vals, "query": query, "body": body}


def set_in(body: Any, dotted: str, value: Any) -> None:
    """Assign into a possibly enveloped body ('user.email' -> body['user']['email'])."""
    parts = dotted.split(".")
    cur = body
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return
        cur = cur[p]
    if isinstance(cur, dict) and parts[-1] in cur:
        cur[parts[-1]] = value


def get_in(body: Any, dotted: str) -> Any:
    cur = body
    for p in dotted.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def has_in(body: Any, dotted: str) -> bool:
    cur = body
    for p in dotted.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    return True
