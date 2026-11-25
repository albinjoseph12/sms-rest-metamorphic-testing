"""
Persistence-state oracle.

Snapshots every application table of the target's database and computes a row-level delta between
two snapshots. The delta is the observable the metamorphic relations constrain: for the relations
used here the follow-up execution must leave the persistent state unchanged, which is a strictly
stronger and more diagnostic condition than "the response had an error status".

Volatile columns (timestamps that the application maintains automatically, sequence-allocated
identifiers) are retained in the delta but are not required to be equal by any relation; the
relations quantify over row identity (insert/delete) and over the set of modified rows.
"""
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
import sqlite3


def _norm(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray, memoryview)):
        return hashlib.sha1(bytes(v)).hexdigest()[:16]
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, default=str)
    return None if v is None else str(v)


class Snapshotter:
    """Reads all application tables. `kind` is 'postgres' or 'sqlite'."""

    def __init__(self, kind: str, dsn: str, max_rows_per_table: int = 20000):
        self.kind = kind
        self.dsn = dsn
        self.max_rows = max_rows_per_table
        self._tables: Optional[List[str]] = None

    # -------------------------------------------------------------- connections
    def _conn(self):
        if self.kind == "postgres":
            return psycopg2.connect(self.dsn)
        return sqlite3.connect(self.dsn)

    def tables(self, refresh: bool = False) -> List[str]:
        # the catalogue is re-read rather than cached: a target may create its schema lazily, on the
        # first request it serves, and a cached empty catalogue would make the oracle blind to every
        # subsequent write
        if self._tables is not None and not refresh:
            return self._tables
        with self._conn() as c:
            cur = c.cursor()
            if self.kind == "postgres":
                cur.execute("""SELECT table_schema||'.'||table_name FROM information_schema.tables
                               WHERE table_type='BASE TABLE' AND table_schema NOT IN
                               ('pg_catalog','information_schema')""")
            else:
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            self._tables = sorted(r[0] for r in cur.fetchall())
        # migration bookkeeping is not application state
        self._tables = [t for t in self._tables
                        if not re.search(r"alembic_version|django_migrations|schema_migrations", t)]
        return self._tables

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> Dict[str, Dict[str, Dict]]:
        """{table: {row_key: {col: value}}}. row_key is the primary key when one exists,
        otherwise a hash of the whole row."""
        snap: Dict[str, Dict[str, Dict]] = {}
        with self._conn() as c:
            cur = c.cursor()
            for t in self.tables(refresh=True):
                try:
                    if self.kind == "postgres":
                        sch, name = t.split(".", 1)
                        cur.execute("""SELECT a.attname FROM pg_index i
                                       JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey)
                                       WHERE i.indrelid = %s::regclass AND i.indisprimary""", (t,))
                        pk = [r[0] for r in cur.fetchall()]
                        cur.execute(f'SELECT * FROM {sch}."{name}" LIMIT {self.max_rows}')
                    else:
                        cur.execute(f'PRAGMA table_info("{t}")')
                        info = cur.fetchall()
                        pk = [r[1] for r in info if r[5]]
                        cur.execute(f'SELECT * FROM "{t}" LIMIT {self.max_rows}')
                    cols = [d[0] for d in cur.description]
                    rows = cur.fetchall()
                except Exception:
                    continue
                tbl: Dict[str, Dict] = {}
                for r in rows:
                    d = {cols[i]: _norm(r[i]) for i in range(len(cols))}
                    if pk and all(k in d for k in pk):
                        key = "|".join(str(d[k]) for k in pk)
                    else:
                        key = hashlib.sha1(json.dumps(d, sort_keys=True).encode()).hexdigest()[:20]
                    tbl[key] = d
                snap[t] = tbl
        return snap


def delta(before: Dict, after: Dict) -> Dict:
    """Row-level difference between two snapshots."""
    ins, dele, mod = [], [], []
    for t in sorted(set(before) | set(after)):
        b, a = before.get(t, {}), after.get(t, {})
        for k in a.keys() - b.keys():
            ins.append({"table": t, "key": k, "row": a[k]})
        for k in b.keys() - a.keys():
            dele.append({"table": t, "key": k, "row": b[k]})
        for k in a.keys() & b.keys():
            if a[k] != b[k]:
                changed = {c: [b[k].get(c), a[k].get(c)] for c in set(a[k]) | set(b[k]) if a[k].get(c) != b[k].get(c)}
                mod.append({"table": t, "key": k, "changed": changed})
    return {"inserted": ins, "deleted": dele, "modified": mod,
            "n_inserted": len(ins), "n_deleted": len(dele), "n_modified": len(mod),
            "empty": not (ins or dele or mod)}


def summarize(d: Dict, limit=6) -> Dict:
    """Compact form for logs: table-level counts plus a few example keys."""
    per: Dict[str, Dict[str, int]] = {}
    for kind in ("inserted", "deleted", "modified"):
        for e in d[kind]:
            per.setdefault(e["table"], {"inserted": 0, "deleted": 0, "modified": 0})[kind] += 1
    out = {"tables": per,
           "examples": [f"{e['table']}#{e['key']}" for kind in ("inserted", "deleted", "modified")
                        for e in d[kind]][:limit],
           "n_inserted": d["n_inserted"], "n_deleted": d["n_deleted"], "n_modified": d["n_modified"]}
    if d.get("background_tables"):
        out["background_tables"] = d["background_tables"]
    return out
