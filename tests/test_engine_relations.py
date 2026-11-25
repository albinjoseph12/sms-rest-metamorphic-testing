#!/usr/bin/env python3
"""
Regression tests for the engine's relation-instantiation and verdict logic.

These do not boot a real target: `Engine.send` and the Snapshotter are replaced with small,
deterministic fakes so every test controls exactly what the follow-up and the control
observe, and exactly what each writes to the (fake) database. Run directly:

    python3 tests/test_engine_relations.py

Five scenarios are required by the Stage 5 protocol audit and are each covered below:
  1. false attribution      (test_mr4_no_violation_when_control_rejected)
  2. control rejection      (test_mr6_control_rejected_is_not_applicable_not_a_pass)
  3. credential substitution (test_mr2_credential_removal)
  4. permitted second-principal insertion (test_mr1_permitted_insertion_vs_interference)
  5. invalid write returning a conforming response (test_mr3_conforming_rejection_is_no_violation)
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sms.engine import Engine

FAILS = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL':4s}  {name}  {detail}")
    if not cond:
        FAILS.append(name)


class FakeSnapshotter:
    """A snapshotter over an in-process dict, mutated by FakeSend as a side effect of each call."""

    def __init__(self, world):
        self.world = world

    def snapshot(self):
        return copy.deepcopy(self.world)


class FakeSend:
    """Scripted responses, matched in call order against a list of (status, body, effect) triples.

    `effect` is applied to the FakeSnapshotter's world dict *before* the after-snapshot is taken by
    exec_with_state, exactly as a real target would already have committed its write by the time the
    harness's next snapshot runs."""

    def __init__(self, world, script):
        self.world = world
        self.script = list(script)
        self.calls = []

    def __call__(self, op, req, cred):
        self.calls.append((op["operation_id"], req.get("body"), cred))
        if not self.script:
            return {"status": 500, "body": "unscripted call", "ms": 0.1, "path": op["path"]}
        status, body, effect = self.script.pop(0)
        if effect:
            effect(self.world)
        return {"status": status, "body": body, "ms": 0.1, "path": op["path"]}


def make_engine(world, script, invariants, principals=None):
    snap = FakeSnapshotter(world)
    eng = Engine("http://example.invalid", {"paths": {}}, snap, seed=1234)
    eng.send = FakeSend(world, script)
    eng.gen.request = lambda op: {"body": copy.deepcopy(op.get("_body", {})), "path_params": {}, "query": None}
    eng.contract.invariants = lambda: invariants
    eng.principals = principals or {
        "A": {"cred": {"headers": {"Authorization": "Bearer A"}}},
        "B": {"cred": {"headers": {"Authorization": "Bearer B"}}},
    }
    return eng


def op(operation_id, path="/things", method="post", secured=True, params=None, resource="things", body=None):
    return {"operation_id": operation_id, "path": path, "method": method, "secured": secured,
            "params": params or [], "resource": resource, "_body": body or {}}


# --------------------------------------------------------------------------------- 1. false attribution
def test_mr4_no_violation_when_control_rejected():
    """MR4: the negated (follow-up) request is accepted, but the untransformed control is rejected --
    e.g. the operation always 500s regardless of input. Before the Stage 5 fix, an accepted-or-5xx
    follow-up was flagged as a violation without ever checking a control; that would have misattributed
    this target's unrelated defect to quantity negation. The corrected engine must record no violation
    for this instance at all."""
    o = op("create_order", body={"quantity": 3})
    world = {"public.orders": {}}
    # call order inside the MR4 block: follow-up (negated) first, control (positive) second
    script = [
        (201, {"id": 1}, lambda w: w["public.orders"].update({"1": {"id": 1, "quantity": -3}})),
        (500, "internal error", None),
    ]
    eng = make_engine(world, script, [{"kind": "NONNEGATIVE_QUANTITY", "op": o, "args": {"field": "quantity"}}])
    eng.run_relations()
    check("mr4 false-attribution: no record written", len(eng.records) == 0, f"records={eng.records}")
    check("mr4 false-attribution: counted as failed source, not a violation",
          eng.records == [] and "MR4:*" not in str(eng.records))


# --------------------------------------------------------------------------------- 2. control rejection
def test_mr6_control_rejected_is_not_applicable_not_a_pass():
    """MR6: the dangling-reference follow-up is correctly rejected (409), but the control (a valid
    reference, otherwise identical) is *also* rejected -- e.g. it collides with something the follow-up
    itself just wrote. The engine must not fabricate a pass (a record with verdict.violation=False) in
    this case: it cannot confirm the untransformed request was viable, so nothing should be attributed
    either way and no record should be written."""
    o = op("create_booking", body={"room_id": 7})
    world = {"public.bookings": {}}
    script = [
        (409, {"error": "conflict"}, None),   # follow-up (dangling room_id): correctly rejected
        (409, {"error": "conflict"}, None),   # control (valid room_id): also rejected -- not confirmable
    ]
    eng = make_engine(world, script, [{"kind": "FOREIGN_REFERENCE", "op": o, "args": {"field": "room_id"}}])
    eng.run_relations()
    check("mr6 control-rejected: no record fabricated as a pass", len(eng.records) == 0, f"records={eng.records}")


# --------------------------------------------------------------------------- 3. credential substitution
def test_mr2_credential_removal():
    o = op("delete_widget", method="delete", body={})
    world = {"public.widgets": {"1": {"id": 1}}}

    # 3a. correctly rejected without credential -> no violation
    script_ok = [
        (200, {"id": 1}, None),                                   # source, with credential: succeeds
        (401, {"error": "unauthorized"}, None),                   # follow-up, no credential: rejected
    ]
    eng = make_engine(world, script_ok, [{"kind": "REQUIRES_CREDENTIAL", "op": o, "args": {}}])
    eng.run_relations()
    check("mr2 credential removed and correctly rejected: no violation",
          len(eng.records) == 1 and not eng.records[0]["verdict"]["violation"],
          f"records={eng.records}")

    # 3b. wrongly accepted without credential -> violation
    world2 = {"public.widgets": {"1": {"id": 1}}}
    script_bad = [
        (200, {"id": 1}, lambda w: w["public.widgets"].__setitem__("1", {"id": 1, "status": "modified"})),
        (200, {"id": 1}, lambda w: w["public.widgets"].pop("1", None)),   # accepted without credential!
    ]
    eng2 = make_engine(world2, script_bad, [{"kind": "REQUIRES_CREDENTIAL", "op": o, "args": {}}])
    eng2.run_relations()
    check("mr2 credential removed but wrongly accepted: violation recorded",
          len(eng2.records) == 1 and eng2.records[0]["verdict"]["violation"],
          f"records={eng2.records}")


# ------------------------------------------------------------- 4. permitted second-principal insertion
def test_mr1_permitted_insertion_vs_interference():
    o = op("favorite_article", path="/articles/{id}/favorite", method="post",
           params=[{"name": "id", "in": "path", "schema": {"type": "integer"}}], resource="articles")

    # 4a. B favorites A's article: this inserts a row B owns (a join row), never modifies/deletes A's
    # article row -- must not be flagged as interference.
    world = {"public.articles": {"5": {"id": 5}}, "public.favorites": {}}
    script = [
        (200, {"id": 5}, None),                                                   # A's own source execution
        (201, {"article_id": 5, "user": "B"},
         lambda w: w["public.favorites"].update({"b5": {"article_id": 5, "user": "B"}})),  # B's follow-up: pure insert
    ]
    eng = make_engine(world, script, [{"kind": "OWNED_ITEM", "op": o, "args": {}}])
    eng.instances = [{"owner": "A", "key": "5", "table": "public.articles", "resource": "articles",
                      "row": {"id": 5}, "resp_body": None}]
    eng.run_relations()
    check("mr1 permitted insertion by B: no violation",
          len(eng.records) == 1 and not eng.records[0]["verdict"]["violation"],
          f"records={eng.records}")

    # 4b. B's follow-up instead modifies A's own article row directly -- must be flagged.
    world2 = {"public.articles": {"5": {"id": 5}}, "public.favorites": {}}
    script2 = [
        (200, {"id": 5}, None),
        (200, {"id": 5, "title": "hijacked"},
         lambda w: w["public.articles"].__setitem__("5", {"id": 5, "title": "hijacked"})),
    ]
    eng2 = make_engine(world2, script2, [{"kind": "OWNED_ITEM", "op": o, "args": {}}])
    eng2.instances = [{"owner": "A", "key": "5", "table": "public.articles", "resource": "articles",
                       "row": {"id": 5}, "resp_body": None}]
    eng2.run_relations()
    check("mr1 interference with A's row: violation recorded",
          len(eng2.records) == 1 and eng2.records[0]["verdict"]["violation"]
          and eng2.records[0]["interfered_rows"] == ["public.articles#5"],
          f"records={eng2.records}")


# ------------------------------------------------------ 5. invalid write returning a conforming response
def test_mr3_conforming_rejection_is_no_violation():
    """The inverted (invalid) follow-up is correctly rejected with a conforming 422, and the control
    (well-ordered) succeeds: this is the fully-conforming case and must produce a record with
    violation=False, not silently no record at all -- the manuscript's oracle-contribution counts
    depend on passing instances being recorded, not just violations."""
    o = op("create_booking", body={"start": "2026-01-01", "end": "2026-01-03"})
    world = {"public.bookings": {}}
    script = [
        (422, {"error": "start must precede end"}, None),                     # inverted: correctly rejected
        (201, {"id": 9}, lambda w: w["public.bookings"].update({"9": {"id": 9}})),  # control: accepted
    ]
    eng = make_engine(world, script, [{"kind": "ORDERED_TEMPORAL_PAIR", "op": o,
                                        "args": {"start": "start", "end": "end"}}])
    eng.run_relations()
    check("mr3 conforming rejection: exactly one record, no violation",
          len(eng.records) == 1 and not eng.records[0]["verdict"]["violation"],
          f"records={eng.records}")
    check("mr3 conforming rejection: control_status recorded as 201",
          eng.records[0].get("control_status") == 201, f"records={eng.records}")


if __name__ == "__main__":
    test_mr4_no_violation_when_control_rejected()
    test_mr6_control_rejected_is_not_applicable_not_a_pass()
    test_mr2_credential_removal()
    test_mr1_permitted_insertion_vs_interference()
    test_mr3_conforming_rejection_is_no_violation()
    if FAILS:
        print(f"\n{len(FAILS)} FAILED: {FAILS}")
        sys.exit(1)
    print("\nall checks passed")
