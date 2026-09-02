#!/usr/bin/env python3
"""LEARN-001 runner — longitudinal inference amortization, measured.

experiments/LEARN-001.md preregisters the question this instrument answers:
does accumulated verified experience reduce the marginal cognition required
for recurring work, without reducing verified reliability? Five recurring
families run 1..N with the learning loop on; after run 2 the OWNER (and
only the owner — the flag is named for who acts) seals a fresh held-out
suite and evaluates, and every later matching instance may take the
zero-model route while its own truth-recomputing gate still judges.

Everything reported is read from ledgers: task status, steps consumed,
tokens, cost, `procedure_routed`, runbook trust. The runner additionally
RE-DERIVES each run's expected artifact from its own generator and compares
bytes, so a gate that lied would surface as false_success instead of being
averaged away.

Pricing honesty: mock providers cost nothing and prove nothing about
economics — every receipt this runner writes in mock mode is stamped
`"pricing": "simulated-mock"`, and the preregistration forbids any economic
claim from such a run. Live provider spend refuses without
`--allow-provider` (an owner decision, like every spend in this platform).

    python learn_bench.py run --home <dir> --runs 20 --receipts out.json

Windows note: use a SHORT --home path. The org-boundary ledger writes
<home>/org/procedures/<64-hex>.json.<32-hex>.tmp, and a deep home pushes
that past MAX_PATH into FileNotFoundError.
"""
import argparse
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import time
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

GENERATOR_VERSION = "LEARN-001-generators-v1"
SEED = 1701
PY = sys.executable


def _rng(family, n):
    return random.Random(f"{SEED}:{family}:{n}")


def _settings(root, db_write=()):
    lines = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
             'poll_interval_seconds = 1', 'max_task_usd = 0',
             'reflect_after = []', 'max_done_rejects = 2',
             'max_task_retries = 0',
             'db_write = [' + ", ".join(f'"{p}"' for p in db_write) + ']', '',
             '[providers.m]', 'type = "mock"', 'script = "scripts/m.json"',
             '', '[roles.default]', 'provider = "m"', 'model = "mock"', '',
             '[roles.r_m]', 'provider = "m"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(lines))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)


def _script(root, steps):
    json.dump(steps, io.open(os.path.join(root, "scripts", "m.json"), "w",
                             encoding="utf-8"))


def _drain(root):
    r = subprocess.run([PY, os.path.join(HERE, "loop.py"), "run", "--drain",
                        "--root", root], capture_output=True, text=True,
                       errors="replace", timeout=420,
                       env={**os.environ, "PYTHONUTF8": "1"})
    return r.returncode


def _tasks(root):
    p = os.path.join(root, "state.json")
    if not os.path.isfile(p):
        return []
    return json.load(io.open(p, encoding="utf-8"))["tasks"]


# ------------------------------------------------------------- families
# Each family: setup(root), instance(root, n) -> (goal, done_check, inputs,
# mock_steps, expected_artifact_path, expected_bytes), suite(root) -> owner
# seal spec. Instance data is fresh every run (seed-derived), so routing
# must generalize over minted parameters — it can never replay bytes.

def _money_csv(rows):
    return "key,amount\n" + "".join(f"{k},{v}\n" for k, v in sorted(rows))


RECON_SPEC = json.dumps({"steps": [
    {"op": "join", "column": "key", "with_column": "key"},
    {"op": "filter", "column": "amount", "compare": "eq", "other": "b_amount"},
    {"op": "select", "columns": ["key", "amount"]},
    {"op": "sort", "column": "key"}]})
RECON_SCHEMA = json.dumps({"columns": {"key": "identifier",
                                       "amount": "money:USD:2"}})


def _recon_rows(rng, n):
    keys = [f"K{n}{chr(65 + i)}" for i in range(rng.randint(2, 5))]
    orders = [(k, f"{rng.randint(1, 999)}.{rng.randint(0, 99):02d}")
              for k in keys]
    bank = [(k, v if rng.random() < 0.7 else f"{Decimal(v) + 1}")
            for k, v in orders] + [(f"X{n}", "1.00")]
    return orders, bank


def _recon_expected(orders, bank):
    bank_map = dict(bank)
    matched = sorted((k, v) for k, v in orders
                     if bank_map.get(k) is not None
                     and Decimal(bank_map[k]) == Decimal(v))
    return "key,amount\n" + "".join(f"{k},{v}\n" for k, v in matched)


F1_GATE = (
    "import io, sys\nfrom decimal import Decimal\n"
    "n = sys.argv[1]\n"
    "def load(p):\n"
    "    return dict(l.split(',') for l in io.open(p, encoding='utf-8')"
    ".read().splitlines()[1:] if l)\n"
    "o = load(f'data/orders-{n}.csv'); b = load(f'data/bank-{n}.csv')\n"
    "truth = 'key,amount\\n' + ''.join(\n"
    "    f'{k},{o[k]}\\n' for k in sorted(o)\n"
    "    if k in b and Decimal(b[k]) == Decimal(o[k]))\n"
    "sys.exit(0 if io.open(f'out/recon-{n}.csv', encoding='utf-8').read()"
    " == truth else 1)\n")


def f1_setup(root):
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    io.open(os.path.join(root, "check_f1.py"), "w",
            encoding="utf-8").write(F1_GATE)


def f1_instance(root, n):
    rng = _rng("f1", n)
    orders, bank = _recon_rows(rng, n)
    io.open(os.path.join(root, "data", f"orders-{n}.csv"), "w",
            encoding="utf-8").write(_money_csv(orders))
    io.open(os.path.join(root, "data", f"bank-{n}.csv"), "w",
            encoding="utf-8").write(_money_csv(bank))
    expected = _recon_expected(orders, bank)
    steps = [{"tool": "transform_table",
              "args": {"source": f"data/orders-{n}.csv",
                       "source2": f"data/bank-{n}.csv",
                       "path": f"out/recon-{n}.csv",
                       "spec": RECON_SPEC, "schema": RECON_SCHEMA}},
             {"tool": "finish_task", "args": {"summary": "reconciled"}}]
    return (f"run the r{n} f1recon of orders against bank",
            f'"{PY}" check_f1.py {n}',
            {"source": f"data/orders-{n}.csv", "source2": f"data/bank-{n}.csv",
             "path": f"out/recon-{n}.csv"},
            steps, f"out/recon-{n}.csv", expected)


def f1_suite(root):
    import tabular
    cases, files = [], []
    for i, n in enumerate((101, 102, 103)):
        rng = _rng("f1-heldout", n)
        orders, bank = _recon_rows(rng, n)
        if i == 2:                        # the edge: nothing reconciles
            bank = [(f"Z{n}", "9.99")]
        files += [{"path": f"data/orders-{n}.csv",
                   "content": _money_csv(orders)},
                  {"path": f"data/bank-{n}.csv", "content": _money_csv(bank)}]
        cases.append({"id": f"h{n}", "edge": i == 2,
                      "inputs": {"source": f"data/orders-{n}.csv",
                                 "source2": f"data/bank-{n}.csv",
                                 "path": f"out/recon-{n}.csv"}})
    return {"family": "f1recon", "cases": cases, "initial_files": files,
            "checks": [{"predicate": "file_derives", "path": {"input": "path"},
                        "spec": tabular.canonical(RECON_SPEC),
                        "source": {"input": "source"},
                        "source2": {"input": "source2"}}]}


F2_GATE = (
    "import sqlite3, sys\n"
    "i, name, cents = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])\n"
    "c = sqlite3.connect('data/crm.db')\n"
    "row = c.execute('select name, cents from contacts where id = ?',"
    " (i,)).fetchone()\n"
    "c.close()\n"
    "sys.exit(0 if row == (name, cents) else 1)\n")


def f2_setup(root):
    import sqlite3
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    connection = sqlite3.connect(os.path.join(root, "data", "crm.db"))
    connection.execute("create table contacts (id integer primary key, "
                       "name text, cents integer)")
    connection.commit()
    connection.close()
    io.open(os.path.join(root, "check_f2.py"), "w",
            encoding="utf-8").write(F2_GATE)


def _f2_payload(n):
    rng = _rng("f2", n)
    return n, f"contact{n}", rng.randint(0, 99999)


def _f2_statements(i, name, cents):
    import dbstate
    statements = dbstate.canonical_statements(json.dumps(
        [{"sql": "insert or replace into contacts values (?, ?, ?)",
          "params": [i, name, cents]}]))
    assertions = dbstate.canonical_assertions(json.dumps(
        [{"query": f"select name, cents from contacts where id = {i}",
          "equals": [[name, cents]]}]))
    return statements, assertions


def f2_instance(root, n):
    i, name, cents = _f2_payload(n)
    statements, assertions = _f2_statements(i, name, cents)
    steps = [{"tool": "db_transaction",
              "args": {"database": "data/crm.db", "statements": statements,
                       "assertions": assertions}},
             {"tool": "finish_task", "args": {"summary": "upserted"}}]
    return (f"perform the f2upsert for contact {i}",
            f'"{PY}" check_f2.py {i} {name} {cents}',
            {"statements": statements, "assertions": assertions},
            steps, None, None)


def f2_suite(root):
    cases = []
    for i, n in enumerate((901, 902, 903)):
        payload = (n, f"held{n}", 0 if i == 2 else n * 3)
        statements, assertions = _f2_statements(*payload)
        cases.append({"id": f"h{n}", "edge": i == 2,
                      "inputs": {"statements": statements,
                                 "assertions": assertions}})
    return {"family": "f2upsert", "cases": cases,
            "authority": ["db-write:data/crm.db"],
            "initial_files": [{"path": "data/crm.db",
                               "content": "create table contacts (id integer "
                                          "primary key, name text, "
                                          "cents integer);\n"}],
            "checks": [{"predicate": "db_satisfies_all",
                        "path": "data/crm.db",
                        "assertions": {"input": "assertions"}}]}


AGG_SPEC = json.dumps({"steps": [
    {"op": "aggregate", "group": ["customer"],
     "aggregations": {"total": {"fn": "sum", "column": "amount"}}}]})
TRIAGE_SPEC = json.dumps({"steps": [
    {"op": "filter", "column": "status", "compare": "eq", "value": "open"},
    {"op": "select", "columns": ["id", "status"]},
    {"op": "sort", "column": "id"}]})
NORM_SPEC = json.dumps({"steps": [
    {"op": "sort", "column": "id"},
    {"op": "rename", "columns": {"val": "value"}}]})


def _transform_family(key, spec, header, rowgen, gate_expected):
    """F3/F4/F5 share one shape: derive a report from one CSV, gate
    recomputes independently in plain Python."""
    def setup(root):
        os.makedirs(os.path.join(root, "data"), exist_ok=True)
        io.open(os.path.join(root, f"check_{key}.py"), "w",
                encoding="utf-8").write(
            "import io, json, sys\n"
            "sys.path.insert(0, json.load(io.open('learnmeta.json'))['agent'])\n"
            "n = sys.argv[1]\n"
            + gate_expected +
            "\nsys.exit(0 if io.open(f'out/" + key + "-{n}.csv', "
            "encoding='utf-8').read() == truth else 1)\n")
        json.dump({"agent": HERE},
                  io.open(os.path.join(root, "learnmeta.json"), "w",
                          encoding="utf-8"))

    def instance(root, n):
        rng = _rng(key, n)
        body = header + "".join(rowgen(rng, n))
        io.open(os.path.join(root, "data", f"{key}-{n}.csv"), "w",
                encoding="utf-8").write(body)
        import tabular
        expected = tabular.apply(spec, body)
        steps = [{"tool": "transform_table",
                  "args": {"source": f"data/{key}-{n}.csv",
                           "path": f"out/{key}-{n}.csv", "spec": spec}},
                 {"tool": "finish_task", "args": {"summary": key}}]
        return (f"produce the r{n} {key} report",
                f'"{PY}" check_{key}.py {n}',
                {"source": f"data/{key}-{n}.csv",
                 "path": f"out/{key}-{n}.csv"},
                steps, f"out/{key}-{n}.csv", expected)

    def suite(root):
        import tabular
        cases, files = [], []
        for i, n in enumerate((101, 102, 103)):
            rng = _rng(f"{key}-heldout", n)
            body = header + ("" if i == 2 else "".join(rowgen(rng, n)))
            files.append({"path": f"data/{key}-{n}.csv", "content": body})
            cases.append({"id": f"h{n}", "edge": i == 2,
                          "inputs": {"source": f"data/{key}-{n}.csv",
                                     "path": f"out/{key}-{n}.csv"}})
        return {"family": key, "cases": cases, "initial_files": files,
                "checks": [{"predicate": "file_derives",
                            "path": {"input": "path"},
                            "spec": tabular.canonical(spec),
                            "source": {"input": "source"}}]}
    return setup, instance, suite


F3 = _transform_family(
    "f3report", AGG_SPEC, "customer,amount\n",
    lambda rng, n: [f"c{rng.randint(1, 3)},{rng.randint(1, 99)}."
                    f"{rng.randint(0, 99):02d}\n" for _ in range(4)],
    "import tabular\n"
    "truth = tabular.apply(" + json.dumps(AGG_SPEC) + ", "
    "io.open(f'data/f3report-{n}.csv', encoding='utf-8').read())")
F4 = _transform_family(
    "f4triage", TRIAGE_SPEC, "id,status,note\n",
    lambda rng, n: [f"t{n}{i},{rng.choice(['open', 'done'])},x\n"
                    for i in range(5)],
    "import tabular\n"
    "truth = tabular.apply(" + json.dumps(TRIAGE_SPEC) + ", "
    "io.open(f'data/f4triage-{n}.csv', encoding='utf-8').read())")
F5 = _transform_family(
    "f5normalize", NORM_SPEC, "id,val\n",
    lambda rng, n: [f"n{n}{rng.randint(10, 99)}{i},{rng.randint(0, 9)}\n"
                    for i in range(3)],
    "import tabular\n"
    "truth = tabular.apply(" + json.dumps(NORM_SPEC) + ", "
    "io.open(f'data/f5normalize-{n}.csv', encoding='utf-8').read())")

FAMILIES = {
    "f1recon": (f1_setup, f1_instance, f1_suite, ()),
    "f2upsert": (f2_setup, f2_instance, f2_suite, ("data/crm.db",)),
    "f3report": (F3[0], F3[1], F3[2], ()),
    "f4triage": (F4[0], F4[1], F4[2], ()),
    "f5normalize": (F5[0], F5[1], F5[2], ()),
}


def _promote(root, family, suite_spec):
    """THE OWNER'S ONLY ACTION, labeled as such: seal a fresh held-out
    suite and evaluate the induced candidate against it."""
    import procedure
    name = "proc-" + family
    procedure.seal_suite(root, f"learn-{family}", suite_spec)
    return procedure.evaluate(root, name, f"learn-{family}")


def run(args):
    import fleet
    import runbook
    home = os.path.abspath(args.home)
    os.makedirs(home, exist_ok=True)
    families = [f.strip() for f in args.families.split(",") if f.strip()]
    roots = {}
    for family in families:
        setup, _instance, _suite, db_write = FAMILIES[family]
        root = fleet.create(home, f"Learn {family}",
                            f"recurring {family} work, measured")
        _settings(root, db_write=db_write)
        setup(root)
        roots[family] = root
    rows = []
    for n in range(1, args.runs + 1):
        for family in families:
            _setup, instance, suite, _db = FAMILIES[family]
            root = roots[family]
            goal, gate, inputs, steps, artifact, expected = instance(root, n)
            _script(root, steps)
            sys.path.insert(0, HERE)
            import loop
            agent = loop.Agent(root)
            agent.add_task("r_m", goal, done_check=gate, family=family,
                           inputs=inputs)
            started = time.time()
            _drain(root)
            task = _tasks(root)[-1]
            false_success = bool(
                task["status"] == "done" and artifact and expected is not None
                and io.open(os.path.join(root, artifact), encoding="utf-8",
                            errors="replace").read() != expected)
            rows.append({
                "family": family, "run": n, "task": task["id"],
                "verified": task["status"] == "done",
                "false_success": false_success,
                "model_calls": len(task.get("steps") or []),
                "tokens_in": task.get("tokens_in", 0),
                "tokens_out": task.get("tokens_out", 0),
                "cost_usd": task.get("cost_usd", 0.0),
                "routed": bool(task.get("procedure_routed")),
                "human_interruptions": sum(
                    1 for s in (task.get("steps") or [])
                    if s.get("tool") == "ask_human"),
                "seconds": round(time.time() - started, 2),
                "procedure_status": runbook.status(root, "proc-" + family),
            })
            print(f"  r{n:>2} {family:<12} "
                  f"{'ok  ' if rows[-1]['verified'] else 'FAIL'} "
                  f"calls={rows[-1]['model_calls']} "
                  f"routed={rows[-1]['routed']} "
                  f"proc={rows[-1]['procedure_status']}", flush=True)
            if n == args.promote_after:
                verdict = _promote(root, family, suite(root))
                print(f"      owner promotion {family}: "
                      f"accepted={verdict['accepted']} "
                      f"status={verdict['status']}", flush=True)
    receipts = {
        "experiment": "LEARN-001", "generator": GENERATOR_VERSION,
        "generator_hash": hashlib.sha256(
            GENERATOR_VERSION.encode()).hexdigest(),
        "seed": SEED, "runs": args.runs, "families": families,
        "pricing": "simulated-mock", "rows": rows,
        "checkpoints": {
            str(c): {
                family: next((r for r in rows if r["family"] == family
                              and r["run"] == c), None)
                for family in families}
            for c in (1, 2, 5, 10, 20) if c <= args.runs}}
    with io.open(args.receipts, "w", encoding="utf-8") as f:
        json.dump(receipts, f, indent=1)
    total = len(rows)
    verified = sum(1 for r in rows if r["verified"])
    routed = sum(1 for r in rows if r["routed"])
    false_successes = sum(1 for r in rows if r["false_success"])
    print(f"\n{total} runs: {verified} verified, {routed} routed "
          f"zero-model, {false_successes} false successes "
          f"(pricing: simulated-mock — economics NOT claimable)")
    return 0 if verified == total and false_successes == 0 else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="execute the longitudinal schedule")
    r.add_argument("--home", required=True)
    r.add_argument("--runs", type=int, default=20)
    r.add_argument("--families", default=",".join(FAMILIES))
    r.add_argument("--promote-after", type=int, default=2)
    r.add_argument("--receipts", required=True)
    r.add_argument("--provider", default="mock")
    r.add_argument("--allow-provider", action="store_true")
    args = ap.parse_args()
    if args.provider != "mock":
        if not args.allow_provider:
            print("REFUSED: live provider spend requires --allow-provider "
                  "(an owner decision).")
            return 2
        print("live-provider mode is wired at the settings level: point the "
              "family experts' settings.toml at the priced provider and "
              "re-run; the fixtures and gates are provider-agnostic.")
        return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
