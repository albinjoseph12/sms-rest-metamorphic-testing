"""
The metamorphic relation catalogue.

Every relation is a quadruple

    MR = < P , T , R_resp , R_state >

where, for a source execution x = (req, resp, delta) of operation o:

    P(o, x)        applicability predicate; the relation is instantiated only where it holds and
                   only where the source execution succeeded (2xx), so that a violation cannot be
                   an artefact of an invalid source request;
    T(req)         the follow-up request, which differs from the source request in exactly one
                   controlled respect;
    R_resp(y)      the admissible response class of the follow-up execution y;
    R_state(y)     the admissible persistence-state delta of the follow-up execution.

A violation is recorded when the source execution satisfies P and succeeds, the follow-up executes,
and either R_resp or R_state is false. The relations below are fixed before any target is selected
(protocol freeze, Section IV) and are evaluated identically on every target.

Rejection classes
    REJECT_AUTH      {401, 403}                 the request must not be authorised
    REJECT_AUTHZ     {401, 403, 404}            not authorised, or the resource must not be revealed
    REJECT_VALID     {400, 409, 422}            the request must be refused as semantically invalid
    REJECT_MISSING   {400, 404, 409, 422}       the referenced resource does not exist
Any 5xx response is a violation for every relation: the contract never declares an internal error
as the correct answer to a well-formed request.
"""
from typing import Dict, List

REJECT_AUTH = {401, 403}
REJECT_AUTHZ = {401, 403, 404}
REJECT_VALID = {400, 409, 422}
REJECT_MISSING = {400, 404, 409, 422}

CATALOGUE = {
    "MR1_PRINCIPAL_SUBSTITUTION": {
        "witness": "OWNED_ITEM",
        "informal": "A mutating item operation executed by a principal B must not modify or delete any "
                    "row that principal A created. B may legitimately create rows of its own (following "
                    "a profile, casting its own vote), so the relation constrains interference with A's "
                    "rows rather than the absence of any state change or any particular status code.",
        "P": "o is a mutating item operation declaring a security requirement; the item instance was "
             "created by A; B is a distinct principal holding a valid credential; the source execution "
             "by A succeeded",
        "T": "execute o as B against a sibling item that A created",
        "R_resp": "unconstrained: a cross-principal write may legitimately be accepted when it only "
                  "creates rows belonging to B",
        "R_state": "delta(follow-up) contains no modification or deletion of a row created by A",
        "resp_ok": None,
        "state": "no_interference",
    },
    "MR2_CREDENTIAL_REMOVAL": {
        "witness": "REQUIRES_CREDENTIAL",
        "informal": "An operation that declares a security requirement, replayed without any credential, "
                    "must be refused; if it mutates, it must not change stored state.",
        "P": "o declares a security requirement and the source execution with a valid credential succeeded",
        "T": "remove the credential header",
        "R_resp": "status in {401,403}",
        "R_state": "delta = empty",
        "resp_ok": REJECT_AUTH,
        "state": "empty",
    },
    "MR3_TEMPORAL_INVERSION": {
        "witness": "ORDERED_TEMPORAL_PAIR",
        "informal": "A request carrying an ordered pair of instants (t_start, t_end) that the source "
                    "execution accepted must be refused when the two values are exchanged so that "
                    "t_start > t_end, and must not persist an inverted interval.",
        "P": "the body of o contains a conventional ordered temporal pair (a, b), both present in the "
             "source request, with source value a < b",
        "T": "exchange the values of a and b",
        "R_resp": "status in {400,409,422}",
        "R_state": "delta = empty",
        "resp_ok": REJECT_VALID,
        "state": "empty",
        "control": "the inverted follow-up executes first; the untransformed request (same fields, "
                   "well ordered) always executes second, strictly after, so it can supply no "
                   "information the follow-up did not already produce and cannot collide with or "
                   "otherwise influence it. An accepted-or-5xx follow-up is attributed to the "
                   "inversion only if the control is itself accepted; a control that is not accepted "
                   "means nothing here can be attributed to the transformation, and the instance is "
                   "counted as a failed source rather than as a violation.",
    },
    "MR4_QUANTITY_NEGATION": {
        "witness": "NONNEGATIVE_QUANTITY",
        "informal": "A numeric body field denoting a count, price or amount, accepted with a positive "
                    "value, must be refused when replaced by its negation.",
        "P": "the body of o contains a numeric field whose name denotes a quantity, the schema does not "
             "already constrain it to be non-negative, and the source value is > 0",
        "T": "replace the value v by -v",
        "R_resp": "status in {400,409,422}",
        "R_state": "delta = empty",
        "resp_ok": REJECT_VALID,
        "state": "empty",
        "control": "the negated follow-up executes first; the untransformed (positive-value) request "
                   "always executes second, strictly after, and cannot influence or collide with it. "
                   "An accepted-or-5xx follow-up is attributed to the negation only if the control is "
                   "itself accepted.",
    },
    "MR5_DELETE_IDEMPOTENCE": {
        "witness": "DELETE_IDEMPOTENT",
        "informal": "Re-executing a delete that has already succeeded must not change stored state a "
                    "second time.",
        "P": "o is a delete whose source execution succeeded and removed at least one row",
        "T": "re-execute the identical request",
        "R_resp": "any status; only the state relation is constrained",
        "R_state": "delta = empty",
        "resp_ok": None,
        "state": "empty",
    },
    "MR6_DANGLING_REFERENCE": {
        "witness": "FOREIGN_REFERENCE",
        "informal": "A body field that names the identifier of another resource, replaced by a "
                    "syntactically valid identifier that no instance carries, must be refused and must "
                    "not create a row referring to the absent instance.",
        "P": "the body of o contains a field of the form <resource>_id whose source value referenced an "
             "existing instance, and the source execution succeeded",
        "T": "replace the value by an identifier of the same type that is absent from the database",
        "R_resp": "status in {400,404,409,422}",
        "R_state": "delta = empty",
        "resp_ok": REJECT_MISSING,
        "state": "empty",
        "control": "the dangling follow-up executes first; the untransformed (existing-reference) "
                   "request always executes second, strictly after, and cannot influence or collide "
                   "with it. An accepted-or-5xx follow-up is attributed to the dangling reference only "
                   "if the control is itself accepted.",
    },
    "MR7_ABSENT_PATH_RESOURCE": {
        "witness": "PATH_REFERENCE",
        "informal": "An item operation whose path identifier is replaced by one that no instance "
                    "carries must be refused and must not change stored state.",
        "P": "o is an item operation (or any mutating operation) that takes a path parameter which "
             "identified an existing instance in the source execution, and the source execution "
             "succeeded. A read of a collection scoped by the parameter is excluded: an empty "
             "collection is a legitimate answer to an absent scope.",
        "T": "replace the path parameter by an identifier of the same type that is absent",
        "R_resp": "status in {400,404,409,422}",
        "R_state": "delta = empty",
        "resp_ok": REJECT_MISSING,
        "state": "empty",
    },
    "MR8_ABSENT_SCOPE_TOLERANCE": {
        "witness": "PATH_REFERENCE",
        "informal": "A read of a collection scoped by a path identifier that no instance carries may "
                    "legitimately answer with an empty collection, but must not fail internally and "
                    "must not change stored state. The relation therefore constrains only the absence "
                    "of an internal error, which is the part of the contract every implementation owes "
                    "regardless of how it represents an absent scope.",
        "P": "o is a read of a collection whose path is scoped by a parameter that identified an "
             "existing instance in the source execution, and the source execution succeeded",
        "T": "replace the scoping path parameter by an identifier of the same type that is absent",
        "R_resp": "status < 500",
        "R_state": "delta = empty",
        "resp_ok": "no_server_error",
        "state": "empty",
    },
}

ORDER = list(CATALOGUE)


def violation_kind(mr: str, resp_ok: bool, state_ok: bool, status: int) -> str:
    if status >= 500:
        return "server_error"
    if not resp_ok and not state_ok:
        return "accepted_and_persisted"
    if not state_ok:
        return "state_changed"
    return "response_class"
