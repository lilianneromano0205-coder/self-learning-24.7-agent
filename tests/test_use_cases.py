#!/usr/bin/env python3
"""Three business-shaped use cases, end to end, held green forever.

docs/USE_CASE_EVIDENCE.md answers "can the platform do X" with named
evidence. These three rows say DEMONSTRATED, and a demonstration that ran
once in a scratch directory is a story; this file makes each one a standing
guarantee CI must keep true:

  1. RECONCILIATION DESK — the unit cell of every reconciliation mesh,
     continuous close, and AI-BPO economics. Two weeks of ordinary gated
     work, a gate that RECOMPUTES the truth from the input ledgers, and an
     unprompted candidate procedure at the end.
  2. MONITORING SENTINEL — the unit cell of the zero-manual-monitoring
     company. WHEN a log gains "ERROR" THEN gated work; a healthy drain
     queues NOTHING, the error fires exactly one task.
  3. NO-RELEARNING LOOP — the unit cell of institutional memory as an
     asset. A gate-diagnosed failure warns the very next task in that
     course, inside its compiled context, before it runs.

Mock providers stand in for the model; what is under test is the PLATFORM:
gates, capture, induction, prospective memory, institutional memory. Every
assertion reads a ledger, never prose.

Run from the agent/ directory:  python tests/test_use_cases.py
"""
import io
import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet                    # noqa: E402
import loop                     # noqa: E402


def _settings(root, providers):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0', '']
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


def check_reconciliation_desk_compiles_itself(home):
    root = fleet.create(home, "Recon Desk",
                        "reconciles the same two ledgers every week")
    _settings(root, ["wa", "wb"])
    weeks = {
        "w1": {"orders": {"A": 100, "B": 250, "C": 75},
               "bank": {"A": 100, "B": 250, "D": 40}},
        "w2": {"orders": {"E": 60, "F": 90},
               "bank": {"E": 60, "F": 91, "G": 15}},
    }
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    for wk, d in weeks.items():
        for side in ("orders", "bank"):
            io.open(os.path.join(root, "data", f"{side}-{wk}.csv"), "w",
                    encoding="utf-8").write(
                "".join(f"{k},{v}\n" for k, v in sorted(d[side].items())))
    # THE GATE RECOMPUTES THE TRUTH from the two input ledgers and demands an
    # exact match — the worker's output is re-derived, never believed.
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(
        "import io, sys\n"
        "wk = sys.argv[1]\n"
        "def load(p):\n"
        "    return {l.split(',')[0]: int(l.split(',')[1])\n"
        "            for l in io.open(p, encoding='utf-8').read().splitlines() if l}\n"
        "o = load(f'data/orders-{wk}.csv'); b = load(f'data/bank-{wk}.csv')\n"
        "truth = ''.join(f'{k},{o[k]}\\n' for k in sorted(o) if b.get(k) == o[k])\n"
        "sys.exit(0 if io.open(f'out/recon-{wk}.csv', encoding='utf-8').read() == truth else 1)\n")

    def recon(d):
        return "".join(f"{k},{d['orders'][k]}\n" for k in sorted(d["orders"])
                       if d["bank"].get(k) == d["orders"][k])

    agent = loop.Agent(root)
    for prov, wk in (("wa", "w1"), ("wb", "w2")):
        _script(root, prov, [
            {"tool": "write_file", "args": {"path": f"out/recon-{wk}.csv",
                                            "content": recon(weeks[wk])}},
            {"tool": "finish_task", "args": {"summary": "reconciled"}}])
        agent.add_task(f"r_{prov}",
                       f"reconcile the {wk} orders ledger against the bank ledger",
                       done_check=f'"{PY}" check.py {wk}', family="reconciliation")
    assert run_drain(root, timeout=180) == 0
    assert [t["status"] for t in _tasks(root)] == ["done", "done"]
    kinds = [e.get("event") for e in _events(root)]
    assert kinds.count("procedure_compiled") == 1, kinds
    rb = json.load(io.open(os.path.join(root, "runbooks",
                                        "proc-reconciliation.json"),
                           encoding="utf-8"))
    assert sorted(rb["provenance"]["inferred_parameters"]) == ["content", "path"], rb
    import runbook
    assert runbook.status(root, "proc-reconciliation") == "candidate", \
        "auto-captured evidence may propose, never trust"
    print("[recon] two verified weeks against a truth-recomputing gate became "
          "an unprompted candidate procedure with its parameters invented — "
          "and it is NOT trusted until an owner seals fresh cases")


def check_sentinel_fires_only_on_the_condition(home):
    root = fleet.create(home, "Ops Sentinel",
                        "watches state and reacts only to exceptions")
    _settings(root, ["inv"])
    _script(root, "inv", [
        {"tool": "write_file", "args": {"path": "out/diagnosis.md",
                                        "content": "root cause: disk full on worker-3\n"}},
        {"tool": "finish_task", "args": {"summary": "diagnosed"}}])
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    io.open(os.path.join(root, "data", "status.log"), "w",
            encoding="utf-8").write("boot ok\nall services healthy\n")
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(
        "import io,os,sys\n"
        "p='out/diagnosis.md'\n"
        "sys.exit(0 if os.path.isfile(p) and 'root cause' in "
        "io.open(p,encoding='utf-8').read() else 1)\n")
    import prospective
    prospective.add(root,
                    {"kind": "file_contains", "path": "data/status.log",
                     "needle": "ERROR"},
                    {"role": "r_inv",
                     "goal": "investigate the error in the status log",
                     "done_check": f'"{PY}" check.py'})
    assert run_drain(root, timeout=120) == 0
    assert _tasks(root) == [], "a healthy log must queue NOTHING"
    with io.open(os.path.join(root, "data", "status.log"), "a",
                 encoding="utf-8") as f:
        f.write("ERROR: worker-3 heartbeat lost\n")
    assert run_drain(root, timeout=120) == 0
    after = _tasks(root)
    assert len(after) == 1 and after[0]["status"] == "done", after
    fired = [e for e in _events(root) if e.get("event") == "prospective_fired"]
    assert len(fired) == 1, fired
    print("[sentinel] a healthy drain queued nothing; the ERROR line fired "
          "exactly one gated investigation, which passed its own mechanical "
          "gate — no model watched anything")


def check_a_diagnosed_failure_warns_the_next_task(home):
    root = fleet.create(home, "Ops Memory",
                        "never rediscovers a failure it already diagnosed")
    _settings(root, ["fx"])
    _script(root, "fx",
            [{"tool": "finish_task", "args": {"summary": "claimed"}}] * 3)
    io.open(os.path.join(root, "check.py"), "w", encoding="utf-8").write(
        "import os,sys\nsys.exit(0 if os.path.isfile('out/export.csv') else 1)\n")
    agent = loop.Agent(root)
    agent.add_task("r_fx", "export the vendor catalog to csv",
                   course="vendor-ops", done_check=f'"{PY}" check.py')
    assert run_drain(root, timeout=120) == 0
    assert [t["status"] for t in _tasks(root)] == ["failed"]
    gpath = os.path.join(root, "courses", "vendor-ops", "gotchas.md")
    lines = [l for l in io.open(gpath, encoding="utf-8").read().splitlines()
             if "WHEN " in l]
    assert lines, "the harness must file the failure it diagnosed"
    warn = lines[0].split("WHEN ", 1)[1].split("|")[0].strip()

    agent = loop.Agent(root)
    agent.add_task("r_fx", "export the vendor catalog to csv again",
                   course="vendor-ops", done_check=f'"{PY}" check.py')
    assert run_drain(root, timeout=120) == 0
    second = _tasks(root)[-1]
    ctx = io.open(os.path.join(root, second["context_ref"]),
                  encoding="utf-8", errors="replace").read()
    assert "-> DO" in ctx and warn[:30] in ctx, \
        "the diagnosed failure must be injected into the successor's context"
    print("[memory] the gate-diagnosed failure was filed by the harness and "
          "injected into the NEXT task's compiled context before it ran — "
          "nobody had to remember")


def main():
    home = make_sandbox("use-cases", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    check_reconciliation_desk_compiles_itself(home)
    check_sentinel_fires_only_on_the_condition(home)
    check_a_diagnosed_failure_warns_the_next_task(home)
    print("PASS test_use_cases")


if __name__ == "__main__":
    main()
