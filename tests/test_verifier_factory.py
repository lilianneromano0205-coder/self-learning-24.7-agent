#!/usr/bin/env python3
"""Phase 2 exit benchmark — the Verifier Factory, held green.

docs/DESIGN-P2-verifier-factory.md preregistered eight properties before a
line was written; this file is that benchmark. The one being demonstrated
end to end: a MODEL may manufacture a gate proposal, and nothing the model
manufactures can grade the model — a verifier earns authority only through
owner-sealed FALSIFIABLE calibration (cases it must reject as well as
accept), promotion is owner-only, trust is hash-bound to the exact spec
bytes, and a trusted verifier's verdict path contains no shell and no
model: pure predicate observation, re-derived at gate time.

Run from the agent/ directory:  python tests/test_verifier_factory.py
"""
import io
import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet                    # noqa: E402
import loop                     # noqa: E402
import verifier                 # noqa: E402


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


def refuses(fragment, fn, *args, **kw):
    try:
        fn(*args, **kw)
    except ValueError as exc:
        assert fragment in str(exc), (fragment, str(exc))
        return
    raise AssertionError(f"accepted what must be refused: {fragment}")


REPORT_SCHEMA = json.dumps({"columns": {"customer": "identifier",
                                        "total": "string"}},
                           sort_keys=True, separators=(",", ":"))
CONSERVE = json.dumps({"kind": "sum_equals", "column": "total",
                       "other_column": "amount"},
                      sort_keys=True, separators=(",", ":"))
CHECKS = [
    {"predicate": "table_conforms", "path": {"input": "report"},
     "schema": REPORT_SCHEMA},
    {"predicate": "table_satisfies", "path": {"input": "report"},
     "constraint": CONSERVE, "other": {"input": "ledger"}}]
PARAMS = {"report": "path", "ledger": "path"}

LEDGER = "customer,amount\nacme,10.00\nbolt,2.50\n"
GOOD = "customer,total\nacme,10\nbolt,2.5\n"
OFF_BY_CENT = "customer,total\nacme,10\nbolt,2.51\n"
BAD_SCHEMA = "customer,total\n,10\nbolt,2.5\n"


def check_worker_proposal_has_no_authority(root):
    _script(root, "prop", [
        {"tool": "propose_verifier",
         "args": {"name": "conserved-report",
                  "criteria": "report totals exactly equal the ledger",
                  "params": json.dumps(PARAMS),
                  "checks": json.dumps(CHECKS)}},
        {"tool": "write_file", "args": {"path": "out/note.txt",
                                        "content": "proposed"}},
        {"tool": "finish_task", "args": {"summary": "filed a gate proposal"}}])
    agent = loop.Agent(root)
    agent.add_task("r_prop", "propose a mechanical gate for report work",
                   done_check=f'"{PY}" -c "import os,sys;'
                              'sys.exit(0 if os.path.isfile(\'out/note.txt\') else 1)"')
    assert run_drain(root, timeout=120) == 0
    assert _tasks(root)[-1]["status"] == "done"
    assert verifier.status(root, "conserved-report") == "candidate"
    spec = verifier.show(root, "conserved-report")
    assert spec["provenance"]["actor"] == "agent", spec["provenance"]
    assert any(e.get("event") == "verifier_proposed" for e in _events(root))

    # ...and the candidate CANNOT gate: a task naming it fails closed
    _script(root, "liar", [{"tool": "finish_task",
                            "args": {"summary": "surely done"}}] * 3)
    agent = loop.Agent(root)
    agent.add_task("r_liar", "produce the report", verifier="conserved-report",
                   verifier_params={"report": "out/r.csv",
                                    "ledger": "data/ledger.csv"})
    assert run_drain(root, timeout=120) == 0
    t = _tasks(root)[-1]
    assert t["status"] == "failed", t
    gates = [e for e in _events(root) if e.get("event") == "gate_verifier"]
    assert gates and gates[-1]["passed"] is False
    print("[factory] a worker manufactured a gate proposal — provenance "
          "stamped, status CANDIDATE — and the candidate gating a task "
          "FAILED it, fail-closed: nothing the model makes can grade the "
          "model")


def check_unfalsifiable_calibration_refuses(root):
    refuses("unfalsifiable", verifier.calibrate, root, "conserved-report",
            [{"id": "p1", "expect": "accept",
              "initial_files": [{"path": "data/ledger.csv", "content": LEDGER},
                                {"path": "out/r.csv", "content": GOOD}],
              "params": {"report": "out/r.csv", "ledger": "data/ledger.csv"}}])
    print("[falsifiable] a calibration set with nothing to REJECT was "
          "refused — a verifier that cannot fail anything is not a verifier")


def check_non_discriminating_cannot_promote(root):
    verifier.propose(root, {
        "name": "exists-only",
        "criteria": "a report file exists",
        "params": {"report": "path"},
        "checks": [{"predicate": "file_exists", "path": {"input": "report"}}]},
        proposed_by="test", actor="owner")
    record = verifier.calibrate(root, "exists-only", [
        {"id": "good", "expect": "accept",
         "initial_files": [{"path": "out/r.csv", "content": GOOD}],
         "params": {"report": "out/r.csv"}},
        {"id": "wrong-but-present", "expect": "reject",
         "initial_files": [{"path": "out/r.csv", "content": OFF_BY_CENT}],
         "params": {"report": "out/r.csv"}}])
    assert record["discriminating"] is False, record
    refuses("not discriminating", verifier.promote, root, "exists-only")
    assert verifier.status(root, "exists-only") == "candidate"
    print("[discrimination] a verifier that accepted a case it was required "
          "to reject earned nothing — promotion refused, still candidate")


def check_discriminating_verifier_gates_live_work(root):
    record = verifier.calibrate(root, "conserved-report", [
        {"id": "p1", "expect": "accept",
         "initial_files": [{"path": "data/l.csv", "content": LEDGER},
                           {"path": "out/r.csv", "content": GOOD}],
         "params": {"report": "out/r.csv", "ledger": "data/l.csv"}},
        {"id": "p2", "expect": "accept",
         "initial_files": [{"path": "data/l.csv",
                            "content": "customer,amount\nzeta,1.00\n"},
                           {"path": "out/r.csv",
                            "content": "customer,total\nzeta,1\n"}],
         "params": {"report": "out/r.csv", "ledger": "data/l.csv"}},
        {"id": "n1-off-by-cent", "expect": "reject",
         "initial_files": [{"path": "data/l.csv", "content": LEDGER},
                           {"path": "out/r.csv", "content": OFF_BY_CENT}],
         "params": {"report": "out/r.csv", "ledger": "data/l.csv"}},
        {"id": "n2-untyped", "expect": "reject",
         "initial_files": [{"path": "data/l.csv", "content": LEDGER},
                           {"path": "out/r.csv", "content": BAD_SCHEMA}],
         "params": {"report": "out/r.csv", "ledger": "data/l.csv"}}])
    assert record["discriminating"] is True, record
    assert record["accepted_positives"] == 2 and record["rejected_negatives"] == 2
    verifier.promote(root, "conserved-report")
    assert verifier.status(root, "conserved-report") == "trusted"

    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    io.open(os.path.join(root, "data", "ledger.csv"), "w",
            encoding="utf-8").write(LEDGER)
    _script(root, "good", [
        {"tool": "write_file", "args": {"path": "out/report.csv",
                                        "content": GOOD}},
        {"tool": "finish_task", "args": {"summary": "reported"}}])
    agent = loop.Agent(root)
    agent.add_task("r_good", "produce the conserved report",
                   verifier="conserved-report",
                   verifier_params={"report": "out/report.csv",
                                    "ledger": "data/ledger.csv"})
    assert run_drain(root, timeout=120) == 0
    t = _tasks(root)[-1]
    assert t["status"] == "done", t
    assert (t.get("verification") or {}).get("passed") is True
    events = _events(root)
    opened = [e for e in events if e.get("event") == "trajectory_opened"
              and e.get("task") == t["id"]]
    assert opened and opened[0]["basis"] == "harness_gate", \
        "a verifier-gated task must enter the learning loop"

    _script(root, "bad", [
        {"tool": "write_file", "args": {"path": "out/report2.csv",
                                        "content": OFF_BY_CENT}},
        {"tool": "finish_task", "args": {"summary": "reported"}}] * 2)
    agent = loop.Agent(root)
    agent.add_task("r_bad", "produce the conserved report again",
                   verifier="conserved-report",
                   verifier_params={"report": "out/report2.csv",
                                    "ledger": "data/ledger.csv"})
    assert run_drain(root, timeout=120) == 0
    t2 = _tasks(root)[-1]
    assert t2["status"] == "failed", t2
    assert (t2.get("verification") or {}).get("passed") is not True
    gates = [e for e in _events(root) if e.get("event") == "gate_verifier"
             and e.get("task") == t2["id"]]
    assert gates and all(g["passed"] is False for g in gates)
    print("[gates] the trusted verifier passed a correct report and FAILED "
          "an off-by-one-cent one, live, with verification recorded and the "
          "verdict path free of shell and model — and the gated task opened "
          "a learning trajectory")


def check_trust_is_hash_bound(root):
    spec = verifier.show(root, "conserved-report")
    spec["criteria"] = "report totals equal the ledger (edited wording)"
    verifier.propose(root, spec, proposed_by="owner edit", actor="owner")
    assert verifier.status(root, "conserved-report") == "candidate", \
        "trust must not survive an edit to the spec bytes"
    ok, why = verifier.gate(root, "conserved-report",
                            {"report": "out/report.csv",
                             "ledger": "data/ledger.csv"})
    assert ok is False and "candidates cannot gate" in why, (ok, why)
    print("[hash-bound] editing the trusted spec demoted it to candidate "
          "and gating refused again — trust binds to exact bytes")


def check_worker_cannot_take_a_name(root):
    refuses("taken", verifier.propose, root, {
        "name": "conserved-report", "criteria": "something else entirely",
        "params": {"x": "path"},
        "checks": [{"predicate": "file_exists", "path": {"input": "x"}}]},
        proposed_by="task t-rogue", actor="agent")
    print("[names] a worker proposing over an existing name was refused — "
          "no proposal can shadow another's gate")


def main():
    home = make_sandbox("verifier-factory",
                        providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Gate Works", "manufactures gates, never trust")
    _settings(root, ["prop", "liar", "good", "bad"])
    check_worker_proposal_has_no_authority(root)
    check_unfalsifiable_calibration_refuses(root)
    check_non_discriminating_cannot_promote(root)
    check_discriminating_verifier_gates_live_work(root)
    check_trust_is_hash_bound(root)
    check_worker_cannot_take_a_name(root)
    assert len(verifier.suggest("reconcile typed migration totals")) == 3
    print("PASS test_verifier_factory")


if __name__ == "__main__":
    main()
