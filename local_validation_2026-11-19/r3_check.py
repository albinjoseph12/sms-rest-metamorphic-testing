# R3 independent check with a direct database read: does POST /api/accounts store a user_id that
# references no user? Fresh offline instance.
import json, sqlite3, sys
sys.path.insert(0, "/tmp")
import check as k
k.wait_ready()
with sqlite3.connect(k.DB) as db:
    users_tables = [t for t in k.tables() if "user" in t.lower()]
    users = {t: [dict(zip([c[1] for c in db.execute(f'PRAGMA table_info("{t}")')], r)) for r in db.execute(f'SELECT * FROM "{t}"')] for t in users_tables}
a = k.snap()
r = k.req("POST", "/api/accounts", json={"platform": "anything", "email": "r3@example.com", "password": "Pw-123456", "user_id": "999999999"})
b = k.snap()
d = k.diff(a, b)
out = {"status": r.status_code, "resp": r.text[:300], "delta": k.counts(d),
       "inserted_accounts_rows": d.get("accounts", {}).get("inserted", []),
       "user_tables_before": {t: len(v) for t, v in users.items()},
       "any_user_row_with_id_999999999": any(str(row.get("id")) == "999999999" for v in users.values() for row in v)}
print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
