#!/usr/bin/env python3
"""Phase 7 exit benchmark — transactional contracts, held green.

docs/DESIGN-P7-transactional-contracts.md preregistered exactly this: the
SQL substrate must show, before the widening becomes permanent, that

  1. PRECONDITION     a guarded transfer whose guard is false refuses with
                      nothing mutated
  2. INVARIANT        a mutation that breaks "sum unchanged" rolls back
                      whole; one that conserves it commits; `equals` pins
                      the total both before and after
  3. TWO FILES        ledger and audit written in ONE commit; a failing
                      assertion on the audit side leaves both untouched
  4. READ ATTACH      writes to a read-attached file fail and roll back;
                      WAL refuses; worker ATTACH is still screened out;
                      bad aliases refuse
  5. AUTHORITY        a write attach demands db-write:<that path> per leaf
                      (v2) and per static walk (v1); the worker tool honours
                      the allowlist; a read attach demands nothing more
  6. END TO END       guarded transfers -> candidate carrying a
                      db_satisfies_all PRECONDITION -> PROVEN on a sealed
                      fresh suite -> zero-model replay under an independent
                      sqlite3 gate -> and a replay whose guard no longer
                      holds is refused BEFORE any mutation
  7. REGISTRATION     the predicate accepts attach; the test is declared

Run from the agent/ directory:  python tests/test_transactional_contracts.py
"""
import io
import json
import os
import sqlite3
import sys
import tempfile

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import dbstate                  # noqa: E402
import fleet                    # noqa: E402
import loop                     # noqa: E402
import operators                # noqa: E402
import procedure                # noqa: E402
import runbook                  # noqa: E402

FAMILY = "guardedtransfer"
LEDGER_DDL = ("create table balances (acct text primary key, cents integer);\n"
              "insert into balances values ('A', 500), ('B', 100);\n")
AUDIT_DDL = "create table log (id integer primary key, note text);\n"


def _settings(root, providers, db_write=()):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0',
         'db_write = [' + ", ".join(f'"{p}"' for p in db_write) + ']', '']
    for name in providers:
        s += [f'[providers.{name}]', 'type = "mock"',
              f'script = "scripts/{name}.json"', '']
    s += ['[roles.default]', f'provider = "{providers[0]}"', 'model = "mock"', '']
    for name in providers:
        s += [f'[roles.r_{name}]', f'provider = "{name}"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)


def _script(root, name, steps):
    json.dump(steps, io.open(os.path.join(root, "scripts", f"{name}.json"),
                             "w", encoding="utf-8"))


def _events(root):
    out = []
    for line in io.open(os.path.join(root, "logs", "agent.log"),
                        encoding="utf-8", errors="replace"):
        if "{" in line and line.rstrip().endswith("}"):
            try:
                out.append(json.loads(line[line.index("{"):]))
            except ValueError:
                pass
    return out


def _tasks(root):
    p = os.path.join(root, "state.json")
    if not os.path.isfile(p):
        return []
    return json.load(io.open(p, encoding="utf-8"))["tasks"]


def refuses(fragment, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return
    raise AssertionError(f"accepted what must be refused: {fragment}")


def _arena(name):
    base = os.environ.get("AGENT_TEST_TMP") or os.path.join(
        tempfile.gettempdir(), "agent-suite")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix=f"txn-{name}-", dir=base)


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


def _pair(arena):
    ledger = os.path.join(arena, "data", "ledger.db")
    audit = os.path.join(arena, "data", "audit.db")
    _make(ledger, LEDGER_DDL)
    _make(audit, AUDIT_DDL)
    return ledger, audit


def statements(amount, audit=True):
    steps = [{"sql": "update balances set cents = cents - ? where acct = 'A'",
              "params": [amount]},
             {"sql": "update balances set cents = cents + ? where acct = 'B'",
              "params": [amount]}]
    if audit:
        steps.append({"sql": "insert into aud.log (note) values (?)",
                      "params": [f"transfer {amount}"]})
    return dbstate.canonical_statements(json.dumps(steps))


def guard(amount):
    return dbstate.canonical_conditions(json.dumps([
        {"query": f"select count(*) from balances where acct = 'A' "
                  f"and cents >= {amount}", "equals": [[1]]}]))


CONSERVED = dbstate.canonical_invariants(json.dumps(
    [{"query": "select sum(cents) from balances"}]))


def after(a, b, log=None):
    items = [{"query": "select acct, cents from balances order by acct",
              "equals": [["A", a], ["B", b]]}]
    if log is not None:
        items.append({"query": "select count(*) from aud.log", "equals": [[log]]})
    return dbstate.canonical_assertions(json.dumps(items))


def attach(audit_abs, mode="write"):
    return {"aud": {"path": audit_abs, "mode": mode}}


# ------------------------------------------------------- 7. registration

def check_registration():
    operators.validate_predicate({
        "predicate": "db_satisfies_all", "path": "data/ledger.db",
        "assertions": "[]",
        "attach": dbstate.canonical_attach(json.dumps(
            {"aud": {"path": "data/audit.db", "mode": "read"}}))})
    refuses("attach must be", operators.validate_predicate, {
        "predicate": "db_satisfies_all", "path": "data/ledger.db",
        "assertions": "[]", "attach": {"aud": "data/audit.db"}})
    print("[registration] db_satisfies_all carries an optional canonical attach; "
          "preconditions, invariants and attach have canonical screened forms")


# --------------------------------------------------- 1. precondition

def check_precondition_refuses_before_mutation():
    ledger, audit = _pair(_arena("guard"))
    refuses("precondition did not hold", dbstate.transact, ledger,
            statements(1000), after(-500, 1100, 1),
            preconditions=guard(1000), invariants=CONSERVED,
            attach=attach(audit))
    assert _rows(ledger, "select acct, cents from balances order by acct") == \
        [["A", 500], ["B", 100]]
    assert _rows(audit, "select count(*) from log") == [[0]]
    # the guard true: the same transfer commits, both files
    dbstate.transact(ledger, statements(100), after(400, 200, 1),
                     preconditions=guard(100), invariants=CONSERVED,
                     attach=attach(audit))
    assert _rows(ledger, "select cents from balances where acct = 'A'") == [[400]]
    assert _rows(audit, "select note from log") == [["transfer 100"]]
    print("[precondition] a transfer whose guard was false refused with "
          "nothing mutated in either file; the guarded transfer committed")


# ------------------------------------------------------ 2. invariant

def check_invariant_rolls_back():
    ledger, audit = _pair(_arena("inv"))
    debit_only = dbstate.canonical_statements(json.dumps([
        {"sql": "update balances set cents = cents - 100 where acct = 'A'"}]))
    refuses("invariant", dbstate.transact, ledger, debit_only,
            dbstate.canonical_assertions(json.dumps([
                {"query": "select cents from balances where acct = 'A'",
                 "equals": [[400]]}])),
            invariants=CONSERVED)
    assert _rows(ledger, "select sum(cents) from balances") == [[600]]
    pinned = dbstate.canonical_invariants(json.dumps(
        [{"query": "select sum(cents) from balances", "equals": [[600]]}]))
    dbstate.transact(ledger, statements(50, audit=False), after(450, 150),
                     invariants=pinned)
    assert _rows(ledger, "select acct, cents from balances order by acct") == \
        [["A", 450], ["B", 150]]
    wrong_pin = dbstate.canonical_invariants(json.dumps(
        [{"query": "select sum(cents) from balances", "equals": [[999]]}]))
    refuses("invariant did not hold before", dbstate.transact, ledger,
            statements(1, audit=False), after(449, 151), invariants=wrong_pin)
    assert _rows(ledger, "select cents from balances where acct = 'A'") == [[450]]
    print("[invariant] a debit without a credit broke 'sum unchanged' and "
          "rolled back whole; a conserving transfer committed; an equals "
          "invariant pinned the total before and after")


# ------------------------------------------------------- 3. two files

def check_two_files_one_commit():
    ledger, audit = _pair(_arena("two"))
    refuses("rolled back", dbstate.transact, ledger, statements(100),
            after(400, 200, 7), attach=attach(audit))
    assert _rows(ledger, "select cents from balances where acct = 'A'") == [[500]]
    assert _rows(audit, "select count(*) from log") == [[0]], \
        "the audit row must not survive a ledger-side rollback"
    dbstate.transact(ledger, statements(100), after(400, 200, 1),
                     attach=attach(audit))
    assert _rows(audit, "select count(*) from log") == [[1]]
    ok, why = dbstate.check_assertions(ledger, after(400, 200, 1),
                                       attach=attach(audit, "read"))
    assert ok, why
    print("[two-files] ledger and audit were written in one commit; a failing "
          "assertion on the audit side left both files untouched")


# ------------------------------------------------------ 4. read attach

def check_read_attach_is_read_only():
    ledger, audit = _pair(_arena("ro"))
    refuses("rolled back", dbstate.transact, ledger, statements(10),
            after(490, 110, 1), attach=attach(audit, "read"))
    assert _rows(ledger, "select cents from balances where acct = 'A'") == [[500]]
    assert _rows(audit, "select count(*) from log") == [[0]]
    wal = os.path.join(os.path.dirname(audit), "wal.db")
    connection = sqlite3.connect(wal)
    connection.execute("pragma journal_mode=wal")
    connection.execute("create table t (x integer)")
    connection.commit()
    connection.close()
    refuses("WAL", dbstate.transact, ledger, statements(10, audit=False),
            after(490, 110), attach={"w": {"path": wal, "mode": "read"}})
    refuses("banned construct", dbstate.canonical_statements, json.dumps(
        [{"sql": "attach database 'x.db' as y"}]))
    for alias in ("main", "temp", "x;y", "Aud", "1a", "a" * 17):
        refuses("alias", dbstate.canonical_attach, json.dumps(
            {alias: {"path": "data/audit.db", "mode": "read"}}))
    refuses("mode", dbstate.canonical_attach, json.dumps(
        {"aud": {"path": "data/audit.db", "mode": "rw"}}))
    print("[read-attach] a write to a read-attached file failed and rolled "
          "back; WAL refused; worker ATTACH is still screened out; bad "
          "aliases and modes refuse")


# --------------------------------------------------------- 5. authority

def check_authority_per_attached_file(home):
    root = os.path.join(home, "txnauth")
    ledger, audit = _pair(root)
    rel_attach = dbstate.canonical_attach(json.dumps(
        {"aud": {"path": "data/audit.db", "mode": "write"}}))
    leaf = {"kind": "deterministic", "id": "step-1", "depends_on": [],
            "action": {"tool": "db_transaction",
                       "args": {"database": "data/ledger.db",
                                "statements": statements(10),
                                "assertions": after(490, 110, 1),
                                "attach": rel_attach}},
            "preconditions": [],
            "effects": [{"predicate": "db_satisfies_all", "path": "data/ledger.db",
                         "assertions": after(490, 110, 1), "attach": rel_attach}]}
    for version in (1, 2):
        rb = {"name": f"proc-txnauth{version}", "triggers": ["txnauth"],
              "procedure_version": version, "steps": [leaf],
              "operator": {"inputs": {}, "preconditions": [], "effects": [],
                           "invariants": [], "cost_usd": 0.0,
                           "latency_seconds": 0.0,
                           "reversibility": "conditional",
                           "authority": ["workspace-write"]},
              "provenance": {"compiled": False, "family": "txnauth",
                             "acceptance_basis": "authored",
                             "input_hashes": [], "trajectory_ids": []}}
        assert procedure.validate(rb) == [], procedure.validate(rb)
        result = procedure.execute(root, rb, {},
                                   authority={"workspace-write",
                                              "db-write:data/ledger.db"})
        assert not result["ok"] and "db-write:data/audit.db" in result["why"], \
            result
        assert _rows(audit, "select count(*) from log") == [[0]]
        # restore the ledger for the second version's run
        _make(ledger, "drop table balances;\n" + LEDGER_DDL) if version == 2 \
            else None
    granted = procedure.execute(root, rb, {},
                                authority={"workspace-write",
                                           "db-write:data/ledger.db",
                                           "db-write:data/audit.db"})
    assert granted["ok"], granted
    assert _rows(audit, "select count(*) from log") == [[1]]
    # read attach demands nothing more than workspace read
    reader = dict(leaf)
    reader["action"] = {"tool": "db_transaction",
                        "args": {"database": "data/ledger.db",
                                 "statements": statements(1, audit=False),
                                 "assertions": after(489, 111),
                                 "attach": dbstate.canonical_attach(json.dumps(
                                     {"aud": {"path": "data/audit.db",
                                              "mode": "read"}}))}}
    reader["effects"] = [{"predicate": "db_satisfies_all",
                          "path": "data/ledger.db", "assertions": after(489, 111)}]
    rb["steps"] = [reader]
    rb["procedure_version"] = 2
    result = procedure.execute(root, rb, {},
                               authority={"workspace-write",
                                          "db-write:data/ledger.db"})
    assert result["ok"], result
    # the worker tool honours the allowlist for every write-attached file
    desk = fleet.create(home, "Txn Desk", "checks attach authority")
    _settings(desk, ["m"], db_write=["data/ledger.db"])
    _script(desk, "m", [])
    _pair(desk)
    agent = loop.Agent(desk)
    probe = {"id": "txn-probe", "role": "r_m", "goal": "probe"}
    out = agent._exec_tool(probe, "db_transaction", {
        "database": "data/ledger.db", "statements": statements(10),
        "assertions": after(490, 110, 1), "attach": rel_attach})
    assert "db_write allowlist" in out and "data/audit.db" in out, out
    assert _rows(os.path.join(desk, "data", "audit.db"),
                 "select count(*) from log") == [[0]]
    out = agent._exec_tool(probe, "db_transaction", {
        "database": "data/ledger.db", "statements": statements(10, audit=False),
        "assertions": after(490, 110), "preconditions": guard(10),
        "invariants": CONSERVED,
        "attach": dbstate.canonical_attach(json.dumps(
            {"aud": {"path": "data/audit.db", "mode": "read"}}))})
    assert out.startswith("ok, transaction committed"), out
    print("[authority] a write attach demanded the owner's token for exactly "
          "its file (v1 walk and v2 leaf); the worker tool refused an attach "
          "outside db_write; a read attach demanded nothing more")


# --------------------------------------------- 6. end to end (learning)

GATE = r'''import sqlite3, sys
a, b, n = (int(x) for x in sys.argv[1:4])
c = sqlite3.connect("data/ledger.db")
got = c.execute("select acct, cents from balances order by acct").fetchall()
c.close()
c = sqlite3.connect("data/audit.db")
count = c.execute("select count(*) from log").fetchone()[0]
c.close()
sys.exit(0 if got == [("A", a), ("B", b)] and count == n else 1)
'''

ATTACH_REL = None


def _inputs(amount, a_after, b_after, log_after):
    return {"statements": statements(amount), "preconditions": guard(amount),
            "assertions": after(a_after, b_after, log_after)}


def _steps(inp):
    return [{"tool": "db_transaction",
             "args": {"database": "data/ledger.db",
                      "statements": inp["statements"],
                      "assertions": inp["assertions"],
                      "preconditions": inp["preconditions"],
                      "invariants": CONSERVED, "attach": ATTACH_REL}},
            {"tool": "finish_task", "args": {"summary": "transferred"}}]


def check_end_to_end_learning(home):
    global ATTACH_REL
    ATTACH_REL = dbstate.canonical_attach(json.dumps(
        {"aud": {"path": "data/audit.db", "mode": "write"}}))
    root = fleet.create(home, "Ledger Desk", "moves money under guard")
    _settings(root, ["wa", "wb", "silent"],
              db_write=["data/ledger.db", "data/audit.db"])
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(GATE)
    ledger, audit = _pair(root)
    agent = loop.Agent(root)
    runs = (("wa", 100, 400, 200, 1), ("wb", 50, 350, 250, 2))
    for prov, amount, a_after, b_after, log_after in runs:
        inp = _inputs(amount, a_after, b_after, log_after)
        _script(root, prov, _steps(inp))
        agent.add_task(f"r_{prov}", f"perform the {FAMILY} of {amount} cents",
                       done_check=f'"{PY}" check.py {a_after} {b_after} {log_after}',
                       family=FAMILY, inputs=inp)
    assert run_drain(root, timeout=240) == 0
    assert all(t["status"] == "done" for t in _tasks(root)[-2:]), _tasks(root)[-2:]
    assert runbook.status(root, f"proc-{FAMILY}") == "candidate"
    rb = runbook.load(root, f"proc-{FAMILY}")
    assert rb["operator"]["inputs"] == {"statements": "string",
                                        "preconditions": "string",
                                        "assertions": "string"}, rb["operator"]
    step = rb["steps"][0]
    assert step["action"]["args"]["attach"] == ATTACH_REL, "constants stay literal"
    assert step["action"]["args"]["invariants"] == CONSERVED
    assert {"predicate": "db_satisfies_all", "path": "data/ledger.db",
            "assertions": {"input": "preconditions"}, "attach": ATTACH_REL} \
        in step["preconditions"], step["preconditions"]
    assert step["effects"][0] == {"predicate": "db_satisfies_all",
                                  "path": "data/ledger.db",
                                  "assertions": {"input": "assertions"},
                                  "attach": ATTACH_REL}, step["effects"]
    fresh = {"c4": (10, 490, 110, 1), "c5": (250, 250, 350, 1),
             "c6": (500, 0, 600, 1)}
    procedure.seal_suite(root, f"{FAMILY}-fresh", {
        "family": FAMILY,
        "authority": ["db-write:data/ledger.db", "db-write:data/audit.db"],
        "cases": [{"id": cid, "edge": cid == "c6", "inputs": _inputs(*fresh[cid])}
                  for cid in sorted(fresh)],
        "initial_files": [{"path": "data/ledger.db", "content": LEDGER_DDL},
                          {"path": "data/audit.db", "content": AUDIT_DDL}],
        "checks": [{"predicate": "db_satisfies_all", "path": "data/ledger.db",
                    "assertions": {"input": "assertions"}, "attach": ATTACH_REL},
                   {"predicate": "db_satisfies_all", "path": "data/audit.db",
                    "assertions": dbstate.canonical_assertions(json.dumps(
                        [{"query": "select count(*) from log",
                          "equals": [[1]]}]))}]})
    verdict = procedure.evaluate(root, f"proc-{FAMILY}", f"{FAMILY}-fresh")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    _script(root, "silent", [])
    agent = loop.Agent(root)
    agent.add_task("r_silent", f"perform the {FAMILY} of 75 cents",
                   done_check=f'"{PY}" check.py 275 325 3', family=FAMILY,
                   inputs=_inputs(75, 275, 325, 3))
    assert run_drain(root, timeout=180) == 0
    routed = _tasks(root)[-1]
    assert routed["status"] == "done" and routed.get("procedure_routed"), routed
    events = [e for e in _events(root) if e.get("event") == "procedure_route"]
    assert events and events[-1]["model_calls"] == 0, events
    assert _rows(ledger, "select acct, cents from balances order by acct") == \
        [["A", 275], ["B", 325]]
    assert _rows(audit, "select count(*) from log") == [[3]]
    # THE GUARD ON REPLAY: a transfer the ledger can no longer cover is
    # refused at the step precondition, before any mutation — and with a
    # silent worker there is no model to fall back on, so the task does
    # not complete and the files stay exactly as they were
    agent = loop.Agent(root)
    agent.add_task("r_silent", f"perform the {FAMILY} of 1000 cents",
                   done_check=f'"{PY}" check.py -725 1325 4', family=FAMILY,
                   inputs=_inputs(1000, -725, 1325, 4))
    run_drain(root, timeout=180)
    last = _tasks(root)[-1]
    assert last["status"] != "done" and not last.get("procedure_routed"), last
    refused = [e for e in _events(root)
               if e.get("event") == "procedure_route_refused"
               and e.get("task") == last["id"]]
    assert refused and "precondition" in refused[-1]["why"] and \
        refused[-1]["applicable"] is False, refused
    assert runbook.status(root, f"proc-{FAMILY}") == "proven", \
        "declining correctly must not count against the procedure"
    assert _rows(ledger, "select acct, cents from balances order by acct") == \
        [["A", 275], ["B", 325]], "a refused replay must touch nothing"
    assert _rows(audit, "select count(*) from log") == [[3]]
    print("[end-to-end] guarded transfers compiled a candidate whose step "
          "carries a db_satisfies_all PRECONDITION, went PROVEN on a sealed "
          "fresh suite (edge: the exact balance), replayed 75 cents with zero "
          "model calls under an independent sqlite3 gate — and a transfer the "
          "ledger could not cover was refused before any mutation")


def main():
    home = make_sandbox("transactional-contracts",
                        providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    check_registration()
    check_precondition_refuses_before_mutation()
    check_invariant_rolls_back()
    check_two_files_one_commit()
    check_read_attach_is_read_only()
    check_authority_per_attached_file(home)
    check_end_to_end_learning(home)
    print("PASS test_transactional_contracts")


if __name__ == "__main__":
    main()
