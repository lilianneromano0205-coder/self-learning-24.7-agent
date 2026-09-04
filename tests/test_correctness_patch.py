#!/usr/bin/env python3
"""Phase 7.1 exit benchmark — the correctness patch, held green.

docs/DESIGN-P7.1-correctness-patch.md preregistered exactly this: four
findings from the 2026-09-02 verdict, each with a property that FAILS on the
tree before its fix and passes after:

  1. STRUCTURED VERDICT  procedure.execute names a status and a reason
                         code; the route classifies applicability from the
                         code, never from the word "precondition" in prose;
                         inapplicable replays record no loss
  2. MISSING DATABASE    a guarded transaction against a database that does
                         not exist refuses and leaves NO file behind; the
                         observation paths create nothing either
  3. INVARIANT ORDER     a bare invariant without ORDER BY is refused at
                         canonicalization; an `unordered` invariant compares
                         multisets, so a re-inserted row does not fail equal
                         data; a broken unordered invariant still rolls back
  4. STREAMING HASH      byte evidence is hashed in chunks — the whole-file
                         reader is never called
  5. REGISTRATION        the test is declared

Run from the agent/ directory:  python tests/test_correctness_patch.py
"""
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import dbstate                  # noqa: E402
import fileauth                 # noqa: E402
import procedure                # noqa: E402
import runbook                  # noqa: E402


def refuses(fragment, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return str(exc)
    raise AssertionError(f"accepted what must be refused: {fragment}")


def _arena(name):
    base = os.environ.get("AGENT_TEST_TMP") or os.path.join(
        tempfile.gettempdir(), "agent-suite")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=f"p71-{name}-", dir=base)


def _wf(path, content, preconditions=None, effects=None):
    return {"kind": "deterministic",
            "action": {"tool": "write_file",
                       "args": {"path": path, "content": content}},
            "preconditions": preconditions or [],
            "effects": effects if effects is not None else [
                {"predicate": "file_equals", "path": path, "value": content}]}


def _rb(name, steps, authority=("workspace-write",)):
    return {"name": name, "triggers": [name], "procedure_version": 2,
            "steps": steps,
            "operator": {"inputs": {}, "preconditions": [], "effects": [],
                         "invariants": [], "cost_usd": 0.0,
                         "latency_seconds": 0.0,
                         "reversibility": "conditional",
                         "authority": list(authority)},
            "provenance": {"compiled": False, "family": "p71",
                           "acceptance_basis": "authored",
                           "input_hashes": [], "trajectory_ids": []}}


def _put(root, rb):
    p = runbook.path(root, rb["name"])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8").write(json.dumps(rb))


def _make(path, script):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(script)
    connection.commit()
    connection.close()


def _rows(path, sql):
    connection = sqlite3.connect(path)
    try:
        return [list(r) for r in connection.execute(sql).fetchall()]
    finally:
        connection.close()


# --------------------------------------------------------------- 1 verdict
def check_structured_verdict(root):
    # (a) a false step precondition -> inapplicable, and NOTHING was written
    guard = _rb("p71-guard", [_wf("out/a.txt", "x", preconditions=[
        {"predicate": "file_exists", "path": "flag.txt"}])])
    assert not procedure.validate(guard), procedure.validate(guard)
    r = procedure.execute(root, guard, {})
    assert not r["ok"] and r["status"] == "inapplicable" \
        and r["reason_code"] == "PRECONDITION_MISMATCH", r
    assert not os.path.exists(os.path.join(root, "out", "a.txt"))
    # (b) an effect that cannot verify -> failed
    broken = _rb("p71-broken", [_wf("out/b.txt", "x", effects=[
        {"predicate": "file_equals", "path": "out/b.txt", "value": "y"}])])
    r = procedure.execute(root, broken, {})
    assert not r["ok"] and r["status"] == "failed" \
        and r["reason_code"] == "EFFECT_FAILED", r
    # (c) a db step without its token -> inapplicable, before any db access
    statements = dbstate.canonical_statements(json.dumps(
        [{"sql": "update t set v = 1", "params": []}]))
    assertions = dbstate.canonical_assertions(json.dumps(
        [{"query": "select v from t order by v", "equals": [[1]]}]))
    dbstep = {"kind": "deterministic",
              "action": {"tool": "db_transaction",
                         "args": {"database": "data/x.db",
                                  "statements": statements,
                                  "assertions": assertions}},
              "preconditions": [],
              "effects": [{"predicate": "db_satisfies_all",
                           "path": "data/x.db", "assertions": assertions}]}
    nodb = _rb("p71-nodb", [dbstep])
    assert not procedure.validate(nodb), procedure.validate(nodb)
    r = procedure.execute(root, nodb, {})
    assert not r["ok"] and r["status"] == "inapplicable" \
        and r["reason_code"] == "AUTHORITY_MISSING", r
    assert not os.path.exists(os.path.join(root, "data", "x.db")), \
        "an authority refusal must happen before any database is touched"
    # (d) the route reads the CODE, never the prose
    prose = {"ok": False, "status": "failed", "reason_code": "EFFECT_FAILED",
             "why": "the precondition held, then the precondition-shaped "
                    "effect did not verify"}
    assert procedure.route_verdict(prose) == (False, "EFFECT_FAILED")
    assert procedure.route_verdict(
        {"ok": False, "status": "inapplicable",
         "reason_code": "PRECONDITION_MISMATCH", "why": "step changed"}) == \
        (True, "PRECONDITION_MISMATCH")
    assert procedure.route_verdict({"ok": False, "why": "precondition"}) == \
        (False, "EXECUTION_ERROR"), "a verdict with no status fails closed"
    assert procedure.route_verdict({"ok": True, "status": "ok",
                                    "reason_code": None}) == (False, None)
    # (e) two inapplicable replays through runbook.run record no loss
    _put(root, guard)
    for _ in range(runbook.QUARANTINE_LOSSES + 1):
        out = runbook.run(root, "p71-guard", allow_candidate=True)
        assert out.get("status") == "inapplicable", out
    assert runbook.status(root, "p71-guard") != "quarantined", \
        "a guard that says 'not now' must never quarantine a procedure"
    print("[verdict] a false guard is INAPPLICABLE with its code, a broken "
          "effect is FAILED, a missing token is inapplicable before any db "
          "access, the route classifies from the code (prose containing "
          "'precondition' stays a failure; no status fails closed), and "
          "inapplicable replays record no loss")


# ------------------------------------------------------------ 2 missing db
def check_missing_database_creates_nothing(root):
    missing = os.path.join(root, "data", "nope.db")
    os.makedirs(os.path.dirname(missing), exist_ok=True)
    statements = dbstate.canonical_statements(json.dumps(
        [{"sql": "create table t (v integer)", "params": []}]))
    assertions = dbstate.canonical_assertions(json.dumps(
        [{"query": "select count(*) from t", "equals": [[0]]}]))
    refuses("does not exist", dbstate.transact, missing, statements,
            assertions)
    assert not os.path.exists(missing), \
        "a refused guarded transaction left a database behind"
    refuses("does not exist", dbstate.query, missing, "select 1")
    assert not os.path.exists(missing)
    # creation is a separate, explicit operation — and then the same
    # transaction commits
    dbstate.run_script(missing, "create table t (v integer);")
    assert os.path.isfile(missing)
    dbstate.transact(missing, dbstate.canonical_statements(json.dumps(
        [{"sql": "insert into t (v) values (7)", "params": []}])),
        dbstate.canonical_assertions(json.dumps(
            [{"query": "select v from t order by v", "equals": [[7]]}])))
    assert _rows(missing, "select v from t") == [[7]]
    print("[missing-db] a guarded transaction against a database that does "
          "not exist refuses and leaves nothing behind; observation creates "
          "nothing; creation is explicit and the transaction then commits")


# ----------------------------------------------------------- 3 invariants
def check_invariant_ordering(root):
    db = os.path.join(root, "data", "names.db")
    _make(db, "create table t (name text);\n"
              "insert into t values ('a'), ('b');\n")
    # (i) the rule: an ORDERED comparison is claimed only by a query that
    # carries ORDER BY; every other query is a multiset
    assert dbstate._is_unordered({"query": "select name from t"}) is True
    assert dbstate._is_unordered(
        {"query": "select name from t order by name"}) is False
    assert dbstate._is_unordered(
        {"query": "select name from t order by name", "unordered": True}) \
        is True
    canon = dbstate.canonical_invariants(
        json.dumps([{"query": "select name from t"}]))
    assert json.loads(canon) == [{"query": "select name from t"}], canon
    refuses("unordered must be true", dbstate.canonical_invariants,
            json.dumps([{"query": "select name from t", "unordered": 1}]))
    refuses("each invariant", dbstate.canonical_invariants,
            json.dumps([{"query": "select name from t", "ordered": True}]))
    assert dbstate._same_rows([["a"], ["b"]], [["b"], ["a"]]) is False
    assert dbstate._same_rows([["a"], ["b"]], [["b"], ["a"]], True) is True
    # (ii) delete-and-reinsert flips SQLite's natural scan order; a BARE
    # invariant (no ORDER BY) still holds and the transaction commits —
    # before the fix this was a false "invariant broken" on equal data
    flip = dbstate.canonical_statements(json.dumps(
        [{"sql": "delete from t where name = 'a'", "params": []},
         {"sql": "insert into t (name) values ('a')", "params": []}]))
    count2 = dbstate.canonical_assertions(json.dumps(
        [{"query": "select count(*) from t", "equals": [[2]]}]))
    dbstate.transact(db, flip, count2, invariants=json.dumps(
        [{"query": "select name from t"}]))
    assert _rows(db, "select name from t") == [["b"], ["a"]], \
        "the natural order did not flip — the witness is missing"
    # (iii) the ORDER BY form (an ordered claim) commits on the same
    # mutation, and so does the explicit unordered declaration
    dbstate.transact(db, flip, count2, invariants=json.dumps(
        [{"query": "select name from t order by name"}]))
    dbstate.transact(db, flip, count2, invariants=json.dumps(
        [{"query": "select name from t", "unordered": True},
         {"query": "select name from t order by name",
          "equals": [["a"], ["b"]]}]))
    assert sorted(_rows(db, "select name from t")) == [["a"], ["b"]]
    # (iv) a bare invariant that is actually broken still rolls back whole
    drop = dbstate.canonical_statements(json.dumps(
        [{"sql": "delete from t where name = 'a'", "params": []}]))
    count1 = dbstate.canonical_assertions(json.dumps(
        [{"query": "select count(*) from t", "equals": [[1]]}]))
    refuses("invariant broken", dbstate.transact, db, drop, count1,
            invariants=json.dumps([{"query": "select name from t"}]))
    assert sorted(_rows(db, "select name from t")) == [["a"], ["b"]], \
        "a broken invariant must roll back the whole transaction"
    print("[invariants] an ordered comparison is claimed only by ORDER BY; "
          "a re-inserted row flips the natural order (witnessed by sqlite3) "
          "yet a bare invariant commits on equal data, the ORDER BY and "
          "pinned forms commit, and a genuinely broken invariant rolls back")


# --------------------------------------------------------- 4 streaming hash
def check_streaming_hash(root):
    content = (b"0123456789abcdef" * 65536 * 3) + b"tail-bytes-17\n\x00\xff"
    with open(os.path.join(root, "blob.bin"), "wb") as f:
        f.write(content)
    expected = hashlib.sha256(content).hexdigest()
    assert fileauth.sha256_bytes(root, "blob.bin") == expected
    original = fileauth.read_bytes

    def never(*args, **kwargs):
        raise AssertionError("sha256_bytes loaded the whole file")
    fileauth.read_bytes = never
    try:
        assert fileauth.sha256_bytes(root, "blob.bin") == expected
    finally:
        fileauth.read_bytes = original
    print("[hash] a 3 MiB file hashes identically to hashlib over its "
          "bytes, and still does when the whole-file reader is replaced "
          "with one that raises — evidence is streamed, never loaded")


# ------------------------------------------------------------ 5 registration
def check_registration():
    me = os.path.basename(__file__)
    for name in ("tests/run_all.py", "evidence.py", "proof.py"):
        text = io.open(os.path.join(AGENT_DIR, name), encoding="utf-8").read()
        assert me in text, f"{me} is not declared in {name}"
    doc = io.open(os.path.join(AGENT_DIR, "docs",
                               "DESIGN-P7.1-correctness-patch.md"),
                  encoding="utf-8").read()
    for code in ("PRECONDITION_MISMATCH", "AUTHORITY_MISSING",
                 "MODEL_REQUIRED", "EFFECT_FAILED", "CHECK_FAILED",
                 "BOUND_EXCEEDED", "CALL_FAILED", "EXECUTION_ERROR"):
        assert code in doc and code in (procedure.INAPPLICABLE_CODES
                                        + procedure.FAILURE_CODES), code
    print("[registration] the benchmark is declared in run_all, evidence "
          "and proof, and every reason code in the design is the code's "
          "closed set")


def main():
    check_structured_verdict(_arena("verdict"))
    check_missing_database_creates_nothing(_arena("missingdb"))
    check_invariant_ordering(_arena("invariants"))
    check_streaming_hash(_arena("hash"))
    check_registration()
    print("PASS test_correctness_patch")


if __name__ == "__main__":
    main()
