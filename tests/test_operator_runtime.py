#!/usr/bin/env python3
"""Phase 1 exit benchmark — the Semantic Operator Runtime, held green.

docs/DESIGN-P1-semantic-operator-runtime.md preregistered exactly this:
five materially different recurring workflows representable without
model-authored shell semantics, each demonstrated END TO END through the
learning loop — verified runs -> induced candidate -> owner-sealed fresh
suite -> PROVEN -> zero-model replay under the task's own gate — plus a
unit test for every new refusal path. This file is that benchmark.

  1. TYPED RECONCILIATION   money columns, schema-verified output
  2. CONSTRAINT REPORT      aggregate report, sum conserved across tables
  3. GATED MIGRATION        SQL with key-preservation proof
  4. TRANSACTIONAL UPSERT   read-after-write inside the commit gate
  5. CSV -> SQL LOAD        mixed pipeline with conservation check

Mock providers stand in for the model; the machinery under test is the
platform's. Every zero-model claim is enforced the hard way: the third
task's worker gets an EMPTY provider script, so consulting a model could
only have failed its gate.

Run from the agent/ directory:  python tests/test_operator_runtime.py
"""
import io
import json
import os
import sqlite3
import sys

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import dbstate                  # noqa: E402
import fleet                    # noqa: E402
import loop                     # noqa: E402
import procedure                # noqa: E402
import runbook                  # noqa: E402
import tabletypes               # noqa: E402


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


def refuses(fragment, fn, *args):
    try:
        fn(*args)
    except ValueError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return
    raise AssertionError(f"accepted what must be refused: {fragment}")


def _routed_done(root, goal, inputs, done_check, family):
    """Queue a task for the SILENT worker and drain: only the zero-model
    route can complete it, and its own gate still judges."""
    agent = loop.Agent(root)
    agent.add_task("r_silent", goal, done_check=done_check, family=family,
                   inputs=inputs)
    assert run_drain(root, timeout=120) == 0
    third = _tasks(root)[-1]
    assert third["status"] == "done" and third.get("procedure_routed"), third
    routed = [e for e in _events(root) if e.get("event") == "procedure_route"]
    assert routed and routed[-1]["model_calls"] == 0, routed
    return third


# ---------------------------------------------------------------- refusals

def check_every_new_refusal_path():
    schema = json.dumps({"columns": {"key": "identifier",
                                     "amount": "money:USD:2"}})
    refuses("not a valid money:USD:2", tabletypes.conforms, schema,
            "key,amount\nA,10.505\n")
    refuses("empty but not nullable", tabletypes.conforms, schema,
            "key,amount\nA,\n")
    refuses("does not match declared columns", tabletypes.conforms, schema,
            "key,total\nA,1\n")
    refuses("unknown column type", tabletypes.canonical_schema,
            json.dumps({"columns": {"x": "float"}}))
    unique = json.dumps({"kind": "unique", "columns": ["key"]})
    assert tabletypes.satisfies(unique, "key,v\nA,1\nB,2\n") is True
    assert tabletypes.satisfies(unique, "key,v\nA,1\nA,2\n") is False
    conserve = json.dumps({"kind": "sum_equals", "column": "v",
                           "other_column": "v"})
    assert tabletypes.satisfies(conserve, "k,v\nA,0.1\nB,0.2\n",
                                "k,v\nC,0.3\n") is True
    assert tabletypes.satisfies(conserve, "k,v\nA,0.1\n",
                                "k,v\nC,0.3\n") is False
    refuses("unknown column", tabletypes.satisfies,
            json.dumps({"kind": "unique", "columns": ["ghost"]}), "k,v\nA,1\n")

    refuses("banned construct", dbstate.canonical_statements,
            json.dumps([{"sql": "pragma journal_mode=wal"}]))
    refuses("banned construct", dbstate.canonical_statements,
            json.dumps([{"sql": "insert into t values (datetime('now'))"}]))
    refuses("banned construct", dbstate.canonical_statements,
            json.dumps([{"sql": "drop table t"}]))
    refuses("must start with", dbstate.canonical_statements,
            json.dumps([{"sql": "explain select 1"}]))
    refuses("not str | int | null", dbstate.canonical_statements,
            json.dumps([{"sql": "insert into t values (?)",
                         "params": [1.5]}]))
    refuses("no declared observable effect", dbstate.canonical_assertions,
            json.dumps([]))
    refuses("must start with", dbstate.canonical_assertions,
            json.dumps([{"query": "delete from t", "equals": []}]))
    print("[refuse] typed cells, constraints, banned SQL, floats and "
          "unasserted mutations all refuse instead of guessing")


def check_failed_assertion_rolls_back(home):
    dbfile = os.path.join(home, "rollback.db")
    connection = sqlite3.connect(dbfile)
    connection.execute("create table t (id integer primary key, cents integer)")
    connection.execute("insert into t values (1, 100)")
    connection.commit()
    connection.close()
    refuses("rolled back", dbstate.transact, dbfile,
            json.dumps([{"sql": "update t set cents = 999 where id = 1"}]),
            json.dumps([{"query": "select cents from t where id = 1",
                         "equals": [[100]]}]))
    assert dbstate.query(dbfile, "select cents from t where id = 1") == [[100]], \
        "a failed commit gate must leave the database untouched"
    print("[rollback] a mutation whose declared effect did not hold was "
          "rolled back whole — the database is asserted or untouched, "
          "never in between")


def check_db_authority_is_owner_granted(home):
    rb = {"name": "proc-authcheck", "triggers": ["authcheck"],
          "procedure_version": 1,
          "steps": [{"id": "step-1", "depends_on": [], "kind": "deterministic",
                     "action": {"tool": "db_transaction",
                                "args": {"database": "data/x.db",
                                         "statements": dbstate.canonical_statements(
                                             json.dumps([{"sql": "create table t (id integer)"}])),
                                         "assertions": dbstate.canonical_assertions(
                                             json.dumps([{"query": "select count(*) from t",
                                                          "equals": [[0]]}]))}},
                     "preconditions": [],
                     "effects": [{"predicate": "file_exists", "path": "data/x.db"}]}],
          "operator": {"inputs": {}, "preconditions": [], "effects": [],
                       "invariants": [], "cost_usd": 0.0, "latency_seconds": 0.0,
                       "reversibility": "conditional",
                       "authority": ["workspace-write"]}}
    root = os.path.join(home, "authcheck")
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    result = procedure.execute(root, rb, {})
    assert not result["ok"] and "db-write:data/x.db" in result["why"], result
    granted = procedure.execute(root, rb, {},
                                authority={"workspace-write",
                                           "db-write:data/x.db"})
    assert granted["ok"], granted
    print("[authority] a db step demands the owner's token for exactly its "
          "file — derived from what the bound step touches, never declared "
          "away; granted, the same step runs")


# ---------------------------------------- 1. typed reconciliation (money)

RECON_SCHEMA = json.dumps({"columns": {"key": "identifier",
                                       "amount": "money:USD:2"}})
RECON_SPEC = json.dumps({"steps": [
    {"op": "join", "column": "key", "with_column": "key"},
    {"op": "filter", "column": "amount", "compare": "eq", "other": "b_amount"},
    {"op": "select", "columns": ["key", "amount"]},
    {"op": "sort", "column": "key"}]})


def _csv(rows):
    return "key,amount\n" + "".join(f"{k},{v}\n" for k, v in sorted(rows.items()))


def _recon_gate(root):
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(
        "import io, sys\n"
        "wk = sys.argv[1]\n"
        "def load(p):\n"
        "    lines = io.open(p, encoding='utf-8').read().splitlines()\n"
        "    assert lines[0] == 'key,amount'\n"
        "    return dict(l.split(',') for l in lines[1:] if l)\n"
        "o = load(f'data/orders-{wk}.csv'); b = load(f'data/bank-{wk}.csv')\n"
        "truth = 'key,amount\\n' + ''.join(f'{k},{o[k]}\\n'\n"
        "                                  for k in sorted(o) if b.get(k) == o[k])\n"
        "sys.exit(0 if io.open(f'out/recon-{wk}.csv', encoding='utf-8').read() == truth else 1)\n")


def check_typed_reconciliation(home):
    root = fleet.create(home, "Typed Recon", "reconciles typed money ledgers")
    _settings(root, ["wa", "wb", "silent"])
    weeks = {"w1": ({"A": "100.00", "B": "9.99"}, {"A": "100.00", "B": "9.98"}),
             "w2": ({"C": "55.10"}, {"C": "55.10", "D": "1.00"})}
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    for wk, (orders, bank) in weeks.items():
        io.open(os.path.join(root, "data", f"orders-{wk}.csv"), "w",
                encoding="utf-8").write(_csv(orders))
        io.open(os.path.join(root, "data", f"bank-{wk}.csv"), "w",
                encoding="utf-8").write(_csv(bank))
    _recon_gate(root)
    agent = loop.Agent(root)
    for prov, wk in (("wa", "w1"), ("wb", "w2")):
        _script(root, prov, [
            {"tool": "transform_table",
             "args": {"source": f"data/orders-{wk}.csv",
                      "source2": f"data/bank-{wk}.csv",
                      "path": f"out/recon-{wk}.csv", "spec": RECON_SPEC,
                      "schema": RECON_SCHEMA}},
            {"tool": "finish_task", "args": {"summary": "reconciled"}}])
        agent.add_task(f"r_{prov}",
                       f"run the {wk} typedrecon of orders against bank",
                       done_check=f'"{PY}" check.py {wk}', family="typedrecon")
    assert run_drain(root, timeout=180) == 0
    rb = json.load(io.open(os.path.join(root, "runbooks", "proc-typedrecon.json"),
                           encoding="utf-8"))
    assert all(s["kind"] == "deterministic" for s in rb["steps"])
    kinds = {e["predicate"] for s in rb["steps"] for e in s["effects"]}
    assert kinds == {"file_derives", "table_conforms"}, kinds
    canon_schema = tabletypes.canonical_schema(RECON_SCHEMA)
    fresh = {"w3": ({"E": "7.25"}, {"E": "7.25"}),
             "w4": ({"F": "3.00", "G": "2.50"}, {"F": "3.00", "G": "2.51"}),
             "w5": ({"H": "1.00"}, {"J": "9.99"})}
    import tabular
    procedure.seal_suite(root, "typedrecon-fresh", {
        "family": "typedrecon",
        "cases": [{"id": wk, "edge": wk == "w5",
                   "inputs": {"source": f"data/orders-{wk}.csv",
                              "source2": f"data/bank-{wk}.csv",
                              "path": f"out/recon-{wk}.csv"}}
                  for wk in sorted(fresh)],
        "initial_files": [{"path": f"data/{side}-{wk}.csv",
                           "content": _csv(fresh[wk][0 if side == "orders" else 1])}
                          for wk in sorted(fresh) for side in ("orders", "bank")],
        "checks": [{"predicate": "file_derives", "path": {"input": "path"},
                    "spec": tabular.canonical(RECON_SPEC),
                    "source": {"input": "source"},
                    "source2": {"input": "source2"}},
                   {"predicate": "table_conforms", "path": {"input": "path"},
                    "schema": canon_schema}]})
    verdict = procedure.evaluate(root, "proc-typedrecon", "typedrecon-fresh")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    # a NEW week for the live root, then zero model calls
    io.open(os.path.join(root, "data", "orders-w9.csv"), "w",
            encoding="utf-8").write(_csv({"K": "42.42"}))
    io.open(os.path.join(root, "data", "bank-w9.csv"), "w",
            encoding="utf-8").write(_csv({"K": "42.42", "L": "0.01"}))
    _script(root, "silent", [])
    _routed_done(root, "run the w9 typedrecon of orders against bank",
                 {"source": "data/orders-w9.csv", "source2": "data/bank-w9.csv",
                  "path": "out/recon-w9.csv"},
                 f'"{PY}" check.py w9', "typedrecon")
    assert "42.42" in io.open(os.path.join(root, "out", "recon-w9.csv"),
                              encoding="utf-8").read()
    print("[1 typed-recon] money-typed reconciliation compiled with a "
          "table_conforms effect, went proven on fresh sealed weeks, and "
          "week nine cost zero model calls under its own gate")


# ------------------------------------ 2. constraint-checked report (sums)

REPORT_SPEC = json.dumps({"steps": [
    {"op": "aggregate", "group": ["customer"],
     "aggregations": {"total": {"fn": "sum", "column": "amount"}}}]})
REPORT_SCHEMA = json.dumps({"columns": {"customer": "identifier",
                                        "total": "string"}})
CONSERVE = json.dumps({"kind": "sum_equals", "column": "total",
                       "other_column": "amount"})


def _ledger(rows):
    return "customer,amount\n" + "".join(f"{c},{v}\n" for c, v in rows)


def check_constraint_report(home):
    root = fleet.create(home, "Ledger Report", "reports that conserve totals")
    _settings(root, ["wa", "wb", "silent"])
    months = {"m1": [("acme", "10.00"), ("bolt", "5.50"), ("acme", "2.00")],
              "m2": [("core", "1.25"), ("core", "1.25")]}
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    for mo, rows in months.items():
        io.open(os.path.join(root, "data", f"ledger-{mo}.csv"), "w",
                encoding="utf-8").write(_ledger(rows))
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(
        "import io, sys\n"
        "from decimal import Decimal\n"
        "mo = sys.argv[1]\n"
        "led = [l.split(',') for l in io.open(f'data/ledger-{mo}.csv',\n"
        "       encoding='utf-8').read().splitlines()[1:] if l]\n"
        "rep = [l.split(',') for l in io.open(f'out/report-{mo}.csv',\n"
        "       encoding='utf-8').read().splitlines()[1:] if l]\n"
        "sys.exit(0 if sum(Decimal(v) for _, v in led) ==\n"
        "         sum(Decimal(v) for _, v in rep) else 1)\n")
    agent = loop.Agent(root)
    for prov, mo in (("wa", "m1"), ("wb", "m2")):
        _script(root, prov, [
            {"tool": "transform_table",
             "args": {"source": f"data/ledger-{mo}.csv",
                      "path": f"out/report-{mo}.csv",
                      "spec": REPORT_SPEC, "schema": REPORT_SCHEMA}},
            {"tool": "finish_task", "args": {"summary": "reported"}}])
        agent.add_task(f"r_{prov}",
                       f"produce the {mo} ledgerreport of customer totals",
                       done_check=f'"{PY}" check.py {mo}', family="ledgerreport")
    assert run_drain(root, timeout=180) == 0
    assert runbook.status(root, "proc-ledgerreport") == "candidate"
    import tabular
    fresh = {"m3": [("dyno", "9.99")],
             "m4": [("echo", "0.01"), ("echo", "0.02")],
             "m5": []}
    procedure.seal_suite(root, "ledgerreport-fresh", {
        "family": "ledgerreport",
        "cases": [{"id": mo, "edge": mo == "m5",
                   "inputs": {"source": f"data/ledger-{mo}.csv",
                              "path": f"out/report-{mo}.csv"}}
                  for mo in sorted(fresh)],
        "initial_files": [{"path": f"data/ledger-{mo}.csv",
                           "content": _ledger(fresh[mo])}
                          for mo in sorted(fresh)],
        "checks": [{"predicate": "file_derives", "path": {"input": "path"},
                    "spec": tabular.canonical(REPORT_SPEC),
                    "source": {"input": "source"}},
                   {"predicate": "table_satisfies", "path": {"input": "path"},
                    "constraint": tabletypes.canonical_constraint(CONSERVE),
                    "other": {"input": "source"}}]})
    verdict = procedure.evaluate(root, "proc-ledgerreport", "ledgerreport-fresh")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    io.open(os.path.join(root, "data", "ledger-m9.csv"), "w",
            encoding="utf-8").write(_ledger([("zeta", "100.10"),
                                             ("zeta", "0.90")]))
    _script(root, "silent", [])
    _routed_done(root, "produce the m9 ledgerreport of customer totals",
                 {"source": "data/ledger-m9.csv", "path": "out/report-m9.csv"},
                 f'"{PY}" check.py m9', "ledgerreport")
    assert io.open(os.path.join(root, "out", "report-m9.csv"),
                   encoding="utf-8").read() == "customer,total\nzeta,101\n"
    print("[2 report] an aggregate report whose totals are EXACTLY conserved "
          "against its ledger (table_satisfies sum_equals in the sealed "
          "suite) went proven and replays with zero model calls")


# ------------------------------------------- 3. gated migration (SQL keys)

def _mig_db(path, ids):
    connection = sqlite3.connect(path)
    connection.execute("create table staging (id integer primary key, cents integer)")
    connection.execute("create table archive (id integer, cents integer)")
    for i in ids:
        connection.execute("insert into staging values (?, ?)", (i, i * 10))
    connection.commit()
    connection.close()


def _mig_assertions(ids):
    return dbstate.canonical_assertions(json.dumps([
        {"query": "select count(*) from archive", "equals": [[len(ids)]]},
        {"query": "select id from archive order by id",
         "equals": [[i] for i in ids]}]))


MIG_STATEMENTS = json.dumps([{"sql": "insert into archive "
                                     "select id, cents from staging"}])
MIG_GATE = (
    "import sqlite3, sys\n"
    "wk = sys.argv[1]\n"
    "c = sqlite3.connect(f'data/mig-{wk}.db')\n"
    "s = c.execute('select id, cents from staging order by id').fetchall()\n"
    "a = c.execute('select id, cents from archive order by id').fetchall()\n"
    "c.close()\n"
    "sys.exit(0 if s == a else 1)\n")


def check_gated_migration(home):
    root = fleet.create(home, "Migration Desk", "migrates with key proofs")
    dbs = [f"data/mig-w{n}.db" for n in (1, 2, 3)]
    _settings(root, ["wa", "wb", "silent"], db_write=dbs)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    weeks = {"w1": [1, 2, 3], "w2": [10, 11]}
    for wk, ids in weeks.items():
        _mig_db(os.path.join(root, "data", f"mig-{wk}.db"), ids)
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(MIG_GATE)
    agent = loop.Agent(root)
    for prov, wk in (("wa", "w1"), ("wb", "w2")):
        _script(root, prov, [
            {"tool": "db_transaction",
             "args": {"database": f"data/mig-{wk}.db",
                      "statements": MIG_STATEMENTS,
                      "assertions": _mig_assertions(weeks[wk])}},
            {"tool": "finish_task", "args": {"summary": "migrated"}}])
        agent.add_task(f"r_{prov}",
                       f"run the {wk} dbmigration of staging into archive",
                       done_check=f'"{PY}" check.py {wk}', family="dbmigration")
    assert run_drain(root, timeout=180) == 0
    rb = json.load(io.open(os.path.join(root, "runbooks", "proc-dbmigration.json"),
                           encoding="utf-8"))
    assert rb["steps"][0]["kind"] == "deterministic"
    assert rb["steps"][0]["effects"][0]["predicate"] == "db_satisfies_all"
    assert isinstance(rb["steps"][0]["action"]["args"]["statements"], str), \
        "the HOW is constant; only the database and its proof vary"
    fresh = {"w4": [4, 5], "w5": [7], "w6": []}
    script = ("create table staging (id integer primary key, cents integer);\n"
              "create table archive (id integer, cents integer);\n")
    procedure.seal_suite(root, "dbmigration-fresh", {
        "family": "dbmigration",
        "authority": [f"db-write:data/mig-{wk}.db" for wk in sorted(fresh)],
        "cases": [{"id": wk, "edge": wk == "w6",
                   "inputs": {"database": f"data/mig-{wk}.db",
                              "assertions": _mig_assertions(fresh[wk])}}
                  for wk in sorted(fresh)],
        "initial_files": [{"path": f"data/mig-{wk}.db",
                           "content": script + "".join(
                               f"insert into staging values ({i}, {i * 10});\n"
                               for i in fresh[wk])}
                          for wk in sorted(fresh)],
        "checks": [{"predicate": "db_satisfies_all", "path": {"input": "database"},
                    "assertions": {"input": "assertions"}}]})
    verdict = procedure.evaluate(root, "proc-dbmigration", "dbmigration-fresh")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    _mig_db(os.path.join(root, "data", "mig-w3.db"), [20, 21, 22])
    _script(root, "silent", [])
    _routed_done(root, "run the w3 dbmigration of staging into archive",
                 {"database": "data/mig-w3.db",
                  "assertions": _mig_assertions([20, 21, 22])},
                 f'"{PY}" check.py w3', "dbmigration")
    print("[3 migration] a SQL migration whose commit is gated on key "
          "preservation went proven on sealed fresh databases (materialized "
          "from owner-sealed scripts) and replayed week three with zero "
          "model calls — the gate re-diffed staging against archive itself")


# --------------------------------------- 4. transactional upsert (r-a-w)

def check_transactional_upsert(home):
    root = fleet.create(home, "CRM Desk", "upserts under read-after-write")
    _settings(root, ["wa", "wb", "silent"], db_write=["data/crm.db"])
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    connection = sqlite3.connect(os.path.join(root, "data", "crm.db"))
    connection.execute("create table contacts "
                       "(id integer primary key, name text, cents integer)")
    connection.execute("insert into contacts values (1, 'ada', 100)")
    connection.commit()
    connection.close()

    def upsert(i, name, cents):
        statements = dbstate.canonical_statements(json.dumps([
            {"sql": "insert or replace into contacts values (?, ?, ?)",
             "params": [i, name, cents]}]))
        assertions = dbstate.canonical_assertions(json.dumps([
            {"query": f"select name, cents from contacts where id = {i}",
             "equals": [[name, cents]]}]))
        return statements, assertions

    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(
        "import sqlite3, sys\n"
        "i, name, cents = sys.argv[1:4]\n"
        "c = sqlite3.connect('data/crm.db')\n"
        "row = c.execute('select name, cents from contacts where id = ?',\n"
        "                (int(i),)).fetchone()\n"
        "c.close()\n"
        "sys.exit(0 if row == (name, int(cents)) else 1)\n")
    agent = loop.Agent(root)
    for prov, (i, name, cents) in (("wa", (1, "ada lovelace", 150)),
                                   ("wb", (2, "grace", 200))):
        statements, assertions = upsert(i, name, cents)
        _script(root, prov, [
            {"tool": "db_transaction",
             "args": {"database": "data/crm.db", "statements": statements,
                      "assertions": assertions}},
            {"tool": "finish_task", "args": {"summary": "upserted"}}])
        agent.add_task(f"r_{prov}", f"perform the dbupsert for contact {i}",
                       done_check=f'"{PY}" check.py {i} "{name}" {cents}',
                       family="dbupsert")
    assert run_drain(root, timeout=180) == 0
    assert runbook.status(root, "proc-dbupsert") == "candidate"
    fresh = {"c4": (4, "vera", 40), "c5": (5, "wu", 50), "c6": (6, "x", 0)}
    procedure.seal_suite(root, "dbupsert-fresh", {
        "family": "dbupsert",
        "authority": ["db-write:data/crm.db"],
        "cases": [{"id": cid, "edge": cid == "c6",
                   "inputs": dict(zip(("statements", "assertions"),
                                      upsert(*fresh[cid])))}
                  for cid in sorted(fresh)],
        "initial_files": [{"path": "data/crm.db",
                           "content": "create table contacts (id integer "
                                      "primary key, name text, cents integer);\n"}],
        "checks": [{"predicate": "db_satisfies_all", "path": "data/crm.db",
                    "assertions": {"input": "assertions"}}]})
    verdict = procedure.evaluate(root, "proc-dbupsert", "dbupsert-fresh")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    statements, assertions = upsert(9, "zoe", 900)
    _script(root, "silent", [])
    _routed_done(root, "perform the dbupsert for contact 9",
                 {"statements": statements, "assertions": assertions},
                 f'"{PY}" check.py 9 zoe 900', "dbupsert")
    assert dbstate.query(os.path.join(root, "data", "crm.db"),
                         "select name from contacts where id = 9") == [["zoe"]]
    print("[4 upsert] a parameterized upsert with read-after-write inside "
          "the commit gate went proven on a sealed fresh database and "
          "replayed contact nine with zero model calls")


# ------------------------------------------ 5. CSV -> SQL load (conserve)

LOAD_SPEC = json.dumps({"steps": [{"op": "sort", "column": "id"},
                                  {"op": "select", "columns": ["id", "cents"]}]})
LOAD_SCHEMA = json.dumps({"columns": {"id": "identifier", "cents": "integer"}})


def _load_fixture(rows):
    return "id,cents\n" + "".join(f"{i},{c}\n" for i, c in rows)


def _load_statements(rows):
    ordered = sorted(rows)
    return dbstate.canonical_statements(json.dumps(
        [{"sql": "insert into ledger values (?, ?)", "params": [i, c]}
         for i, c in ordered] or
        [{"sql": "select 1"}]))


def _load_assertions(rows):
    total = sum(c for _, c in rows)
    return dbstate.canonical_assertions(json.dumps([
        {"query": "select coalesce(sum(cents), 0) from ledger",
         "equals": [[total]]},
        {"query": "select count(*) from ledger", "equals": [[len(rows)]]}]))


LOAD_GATE = (
    "import io, sqlite3, sys\n"
    "wk = sys.argv[1]\n"
    "rows = [l.split(',') for l in io.open(f'data/raw-{wk}.csv',\n"
    "        encoding='utf-8').read().splitlines()[1:] if l]\n"
    "want = sum(int(c) for _, c in rows)\n"
    "c = sqlite3.connect(f'data/load-{wk}.db')\n"
    "got = c.execute('select coalesce(sum(cents), 0), count(*) "
    "from ledger').fetchone()\n"
    "c.close()\n"
    "sys.exit(0 if got == (want, len(rows)) else 1)\n")


def check_csv_to_sql_load(home):
    root = fleet.create(home, "Load Desk", "loads csv into sql, conserving sums")
    dbs = [f"data/load-w{n}.db" for n in (1, 2, 3)]
    _settings(root, ["wa", "wb", "silent"], db_write=dbs)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    weeks = {"w1": [("b", 20), ("a", 10)], "w2": [("z", 5)]}
    ledger_ddl = "create table ledger (id text, cents integer);\n"
    for wk, rows in weeks.items():
        io.open(os.path.join(root, "data", f"raw-{wk}.csv"), "w",
                encoding="utf-8").write(_load_fixture(rows))
        connection = sqlite3.connect(os.path.join(root, "data", f"load-{wk}.db"))
        connection.executescript(ledger_ddl)
        connection.commit()
        connection.close()
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(LOAD_GATE)
    agent = loop.Agent(root)
    for prov, wk in (("wa", "w1"), ("wb", "w2")):
        _script(root, prov, [
            {"tool": "transform_table",
             "args": {"source": f"data/raw-{wk}.csv",
                      "path": f"out/clean-{wk}.csv",
                      "spec": LOAD_SPEC, "schema": LOAD_SCHEMA}},
            {"tool": "db_transaction",
             "args": {"database": f"data/load-{wk}.db",
                      "statements": _load_statements(weeks[wk]),
                      "assertions": _load_assertions(weeks[wk])}},
            {"tool": "finish_task", "args": {"summary": "loaded"}}])
        agent.add_task(f"r_{prov}",
                       f"run the {wk} csvload of the raw ledger into sql",
                       done_check=f'"{PY}" check.py {wk}', family="csvload")
    assert run_drain(root, timeout=180) == 0
    rb = json.load(io.open(os.path.join(root, "runbooks", "proc-csvload.json"),
                           encoding="utf-8"))
    assert [s["kind"] for s in rb["steps"]] == ["deterministic", "deterministic"]
    kinds = sorted(e["predicate"] for s in rb["steps"] for e in s["effects"])
    assert kinds == ["db_satisfies_all", "file_derives", "table_conforms"], kinds
    import tabular
    fresh = {"w4": [("m", 1), ("n", 2)], "w5": [("p", 100)], "w6": []}
    procedure.seal_suite(root, "csvload-fresh", {
        "family": "csvload",
        "authority": [f"db-write:data/load-{wk}.db" for wk in sorted(fresh)],
        "cases": [{"id": wk, "edge": wk == "w6",
                   "inputs": {"source": f"data/raw-{wk}.csv",
                              "path": f"out/clean-{wk}.csv",
                              "database": f"data/load-{wk}.db",
                              "statements": _load_statements(fresh[wk]),
                              "assertions": _load_assertions(fresh[wk])}}
                  for wk in sorted(fresh)],
        "initial_files": (
            [{"path": f"data/raw-{wk}.csv", "content": _load_fixture(fresh[wk])}
             for wk in sorted(fresh)]
            + [{"path": f"data/load-{wk}.db", "content": ledger_ddl}
               for wk in sorted(fresh)]),
        "checks": [{"predicate": "file_derives", "path": {"input": "path"},
                    "spec": tabular.canonical(LOAD_SPEC),
                    "source": {"input": "source"}},
                   {"predicate": "db_satisfies_all",
                    "path": {"input": "database"},
                    "assertions": {"input": "assertions"}}]})
    verdict = procedure.evaluate(root, "proc-csvload", "csvload-fresh")
    assert verdict["accepted"] and verdict["status"] == "proven", verdict
    rows9 = [("q", 42), ("r", 58)]
    io.open(os.path.join(root, "data", "raw-w3.csv"), "w",
            encoding="utf-8").write(_load_fixture(rows9))
    connection = sqlite3.connect(os.path.join(root, "data", "load-w3.db"))
    connection.executescript(ledger_ddl)
    connection.commit()
    connection.close()
    _script(root, "silent", [])
    _routed_done(root, "run the w3 csvload of the raw ledger into sql",
                 {"source": "data/raw-w3.csv", "path": "out/clean-w3.csv",
                  "database": "data/load-w3.db",
                  "statements": _load_statements(rows9),
                  "assertions": _load_assertions(rows9)},
                 f'"{PY}" check.py w3', "csvload")
    assert dbstate.query(os.path.join(root, "data", "load-w3.db"),
                         "select coalesce(sum(cents), 0) from ledger") == [[100]]
    print("[5 csv->sql] a two-step mixed pipeline — typed normalize, then "
          "gated load whose sum is conserved — went proven and replayed "
          "with zero model calls across BOTH state domains in one procedure")


def main():
    home = make_sandbox("operator-runtime",
                        providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    check_every_new_refusal_path()
    check_failed_assertion_rolls_back(home)
    check_db_authority_is_owner_granted(home)
    check_typed_reconciliation(home)
    check_constraint_report(home)
    check_gated_migration(home)
    check_transactional_upsert(home)
    check_csv_to_sql_load(home)
    print("PASS test_operator_runtime")


if __name__ == "__main__":
    main()
