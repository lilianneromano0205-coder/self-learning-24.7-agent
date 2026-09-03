#!/usr/bin/env python3
"""Phase 9a exit benchmark — reconcilers, held green.

docs/DESIGN-P9a-reconcilers.md preregistered exactly this: the
cluster-controller pattern as a standing responsibility must show, before
it becomes permanent, that

  1. CONTROL STATE   reconcilers.json is CONTROL (agent write refused,
                     harness allowed), enumerated in the harness ledgers
                     and the promotion-leakage suite; `add` refuses inside
                     an agent task; a malformed or placeholder predicate
                     refuses at `add`
  2. IN SPEC         a desired state that holds runs nothing and leaves
                     the trust ledger untouched
  3. REPAIRED        a drift under a PROVEN restore is repaired by the tick,
                     re-observed, recorded as an ACCEPTED win — with the
                     model-call ledger untouched
  4. TRUST FIRST     the same drift under a CANDIDATE restore is BLOCKED:
                     nothing runs, the state stays drifted
  5. HALT            a restore that cannot converge fails with exponential
                     backoff and halts at max_failures, asking the owner in
                     blocked.md; ticks then do nothing; resume re-arms
  6. LOOP            a --drain run repairs a drift from the idle tick with
                     zero model calls and logs reconciler_repaired
  7. REGISTRATION    run_all, evidence, proof, doctor, the manual

Run from the agent/ directory:  python tests/test_reconciler.py
"""
import io
import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import doctor                   # noqa: E402
import fileauth                 # noqa: E402
import fleet                    # noqa: E402
import harness                  # noqa: E402
import reconciler               # noqa: E402
import runbook                  # noqa: E402

PIN = '''import os, sys
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "config.txt")
os.makedirs(os.path.dirname(p), exist_ok=True)
open(p, "w", encoding="utf-8").write(sys.argv[1] + "\\n")
'''
CHECK = '''import os, sys
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "config.txt")
try:
    sys.exit(0 if open(p, encoding="utf-8").read() == sys.argv[1] + "\\n" else 1)
except OSError:
    sys.exit(1)
'''


def _settings(root, providers):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0', '']
    for name in providers:
        s += [f'[providers.{name}]', 'type = "mock"',
              f'script = "scripts/{name}.json"', '']
    s += ['[roles.default]', f'provider = "{providers[0]}"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    json.dump([], io.open(os.path.join(root, "scripts", f"{providers[0]}.json"),
                          "w", encoding="utf-8"))


def _desk(home, name):
    root = fleet.create(home, name, "keeps a config pinned")
    _settings(root, ["m"])
    io.open(os.path.join(root, "pin.py"), "w", encoding="utf-8").write(PIN)
    io.open(os.path.join(root, "checkpin.py"), "w", encoding="utf-8").write(CHECK)
    return root


def _write(root, value):
    os.makedirs(os.path.join(root, "out"), exist_ok=True)
    io.open(os.path.join(root, "out", "config.txt"), "w",
            encoding="utf-8").write(value + "\n")


def _read(root):
    try:
        return io.open(os.path.join(root, "out", "config.txt"),
                       encoding="utf-8").read()
    except OSError:
        return None


def _runbook(root, name, writes, verifies):
    os.makedirs(os.path.join(root, "runbooks"), exist_ok=True)
    with open(runbook.path(root, name), "w", encoding="utf-8") as f:
        json.dump({"name": name, "triggers": [name.replace("-", " ")],
                   "steps": [{"do": f'"{PY}" pin.py {writes}',
                              "verify": f'"{PY}" checkpin.py {verifies}'}]}, f)


def _proven(root, name, writes, verifies):
    """ACCEPTED wins promote: the caller's independent check, three times."""
    _runbook(root, name, writes, verifies)
    for _ in range(runbook.PROMOTE_WINS):
        r = runbook.run(root, name, allow_candidate=True,
                        accept=lambda: _read(root) == writes + "\n")
        assert r["ok"] and r["accepted"], r
    assert runbook.status(root, name) == "proven", runbook.status(root, name)


def _desired(value="v1"):
    return [{"predicate": "file_equals", "path": "out/config.txt",
             "value": value + "\n"}]


def _trust_bytes(root):
    p = os.path.join(root, runbook.TRUST)
    return io.open(p, encoding="utf-8").read() if os.path.isfile(p) else None


def _model_calls(root):
    p = os.path.join(root, "logs", "model-calls.jsonl")
    return io.open(p, encoding="utf-8").read() if os.path.isfile(p) else ""


def _rows(root):
    p = os.path.join(root, "logs", "reconciler.jsonl")
    if not os.path.isfile(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


# ------------------------------------------------------------ 1 control
def check_control_state(root):
    assert fileauth.zone_of("reconcilers.json") == fileauth.ZONE_CONTROL
    try:
        fileauth.resolve(root, "reconcilers.json", "write", "agent")
    except fileauth.Denied:
        pass
    else:
        raise AssertionError("the agent may write the reconciler declarations")
    assert fileauth.resolve(root, "reconcilers.json", "write", "harness")
    assert any(rel == "reconcilers.json" for rel, _w in harness.LEDGERS)
    suite = io.open(os.path.join(AGENT_DIR, "tests", "test_promotion_leakage.py"),
                    encoding="utf-8").read()
    assert "reconcilers.json" in suite
    os.environ["AGENT_TASK_ID"], os.environ["AGENT_ROLE"] = "t1", "practitioner"
    try:
        try:
            reconciler.add(root, "inside-task", _desired(), "pin-config")
        except SystemExit as exc:
            assert "REFUSED" in str(exc), exc
        else:
            raise AssertionError("a declaration from inside an agent task was accepted")
    finally:
        os.environ.pop("AGENT_TASK_ID", None)
        os.environ.pop("AGENT_ROLE", None)
    for bad, why in (([{"predicate": "file_is_nice", "path": "x"}], "refused"),
                     ([{"predicate": "file_equals", "path": {"input": "p"},
                        "value": "v"}], "input"),
                     ([], "1..32")):
        try:
            reconciler.add(root, "bad-one", bad, "pin-config")
        except ValueError as exc:
            assert why in str(exc), (why, str(exc))
        else:
            raise AssertionError(f"accepted a malformed declaration: {bad}")
    assert reconciler.load(root) == [], "a refused declaration must not land"
    print("[control] reconcilers.json is CONTROL (agent refused, harness "
          "allowed), enumerated in the harness ledgers and the leakage suite; "
          "declaring inside an agent task, a bad predicate, a placeholder and "
          "an empty desired state all refuse and leave nothing behind")


# ------------------------------------------------------------ 2 in spec
def check_in_spec_runs_nothing(root):
    _proven(root, "pin-config", "v1", "v1")
    _write(root, "v1")
    before = _trust_bytes(root)
    item = reconciler.add(root, "config-pinned", _desired(), "pin-config",
                          every_s=60, max_failures=3,
                          backoff={"base_s": 60, "max_s": 3600})
    s = reconciler.tick(root, None, now=1000.0)
    assert s["evaluated"] == 1 and s["in_spec"] == 1 and s["repaired"] == 0, s
    assert _trust_bytes(root) == before, "an in-spec tick must not touch trust"
    row = reconciler.load(root)[0]
    assert row["status"] == "armed" and row["last_outcome"] == "in_spec"
    assert row["next_due"] == 1060.0, row
    s2 = reconciler.tick(root, None, now=1030.0)
    assert s2["evaluated"] == 0, "not due yet — nothing is evaluated"
    print("[in-spec] a desired state that holds is observed, nothing runs, the "
          "trust ledger is untouched, and the next look is one period away")
    return item


# ------------------------------------------------------------ 3 repaired
def check_drift_is_repaired(root, item):
    _write(root, "v0")
    calls = _model_calls(root)
    before = _trust_bytes(root)
    s = reconciler.tick(root, None, now=2000.0)
    assert s["repaired"] == 1 and s["failed"] == 0, s
    assert _read(root) == "v1\n", _read(root)
    row = reconciler.load(root)[0]
    assert row["repairs"] == 1 and row["failures"] == 0 \
        and row["last_outcome"] == "repaired", row
    assert _trust_bytes(root) != before and "pin-config" in _trust_bytes(root), \
        "the repair must be recorded against the procedure's trust"
    assert runbook.status(root, "pin-config") == "proven"
    assert _model_calls(root) == calls, "a repair must not touch a model"
    assert any(r["event"] == "reconciler_repaired" and r["model_calls"] == 0
               for r in _rows(root)), _rows(root)
    print("[repaired] a drifted file was observed, restored by the PROVEN "
          "procedure under the owner's grant, re-observed true, recorded as an "
          "accepted win — and the model-call ledger did not change")


# ------------------------------------------------------------ 4 trust
def check_unproven_restore_is_blocked(home):
    root = _desk(home, "Cautious Keeper")
    _runbook(root, "pin-candidate", "v1", "v1")          # written, never run
    assert runbook.status(root, "pin-candidate") == "candidate"
    _write(root, "v0")
    reconciler.add(root, "config-pinned", _desired(), "pin-candidate",
                   every_s=60, backoff={"base_s": 60, "max_s": 600})
    s = reconciler.tick(root, None, now=1000.0)
    assert s["blocked"] == 1 and s["repaired"] == 0, s
    assert _read(root) == "v0\n", "an unproven restore must not act"
    row = reconciler.load(root)[0]
    assert row["status"] == "armed" and "candidate" in row["last_outcome"], row
    assert row["next_due"] == 1060.0, row
    print("[trust] a drift whose restore is only a CANDIDATE is BLOCKED: "
          "nothing ran, the state stayed drifted, the controller backed off")


# ------------------------------------------------------------ 5 halt
def check_backoff_and_halt(home):
    root = _desk(home, "Stubborn Keeper")
    _proven(root, "pin-wrong", "v2", "v2")               # proven — at the wrong thing
    _write(root, "v0")
    item = reconciler.add(root, "config-pinned", _desired("v1"), "pin-wrong",
                          every_s=60, max_failures=3,
                          backoff={"base_s": 60, "max_s": 3600})
    s1 = reconciler.tick(root, None, now=1000.0)
    assert s1["failed"] == 1, s1
    row = reconciler.load(root)[0]
    assert row["failures"] == 1 and row["next_due"] == 1060.0, row
    assert reconciler.tick(root, None, now=1030.0)["evaluated"] == 0
    s2 = reconciler.tick(root, None, now=1100.0)
    assert s2["failed"] == 1, s2
    row = reconciler.load(root)[0]
    assert row["failures"] == 2 and row["next_due"] == 1220.0, \
        "backoff must double: 60, then 120"
    s3 = reconciler.tick(root, None, now=1300.0)
    assert s3["halted"] == 1 and s3["failed"] == 0, s3
    row = reconciler.load(root)[0]
    assert row["status"] == "halted" and row["failures"] == 3, row
    blocked = io.open(os.path.join(root, "blocked.md"), encoding="utf-8").read()
    assert "HALTED" in blocked and item["id"] in blocked and "resume" in blocked
    assert reconciler.tick(root, None, now=9000.0)["evaluated"] == 0, \
        "a halted controller must do nothing until the owner resumes it"
    back = reconciler.resume(root, item["id"])
    assert back["status"] == "armed" and back["failures"] == 0
    s4 = reconciler.tick(root, None, now=9100.0)
    assert s4["failed"] == 1 and reconciler.load(root)[0]["failures"] == 1
    assert _read(root) == "v2\n", "the wrong procedure kept writing v2 — visible, never hidden"
    print("[halt] a restore that cannot converge failed with doubling backoff "
          "(60s, 120s), HALTED at three failures with the question in "
          "blocked.md, did nothing while halted, and resumed with a clean count")


# ------------------------------------------------------------ 6 loop
def check_loop_repairs_from_idle(home):
    root = _desk(home, "Idle Keeper")
    _proven(root, "pin-config", "v1", "v1")
    _write(root, "v0")
    reconciler.add(root, "config-pinned", _desired(), "pin-config", every_s=60)
    calls = _model_calls(root)
    assert run_drain(root, timeout=120) == 0
    assert _read(root) == "v1\n", _read(root)
    log = io.open(os.path.join(root, "logs", "agent.log"), encoding="utf-8",
                  errors="replace").read()
    assert '"event": "reconciler_repaired"' in log and '"model_calls": 0' in log
    assert _model_calls(root) == calls
    print("[loop] with no task queued, the loop's idle tick observed the drift, "
          "restored it with the proven procedure and logged the repair — zero "
          "model calls, no task, no person")


# ------------------------------------------------------------ 7 registration
def check_registration():
    me = os.path.basename(__file__)
    for name in ("tests/run_all.py", "evidence.py", "proof.py"):
        text = io.open(os.path.join(AGENT_DIR, name), encoding="utf-8").read()
        assert me in text, f"{me} is not declared in {name}"
    manual = io.open(os.path.join(AGENT_DIR, "MANUAL.md"), encoding="utf-8").read()
    assert "python reconciler.py add" in manual
    assert "reconciler" in doctor.CORE_MODULES
    print("[registration] the benchmark is declared in run_all, evidence and "
          "proof; the manual names the command; the doctor imports the module")


def main():
    home = make_sandbox("reconciler", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = _desk(home, "Config Keeper")
    check_control_state(root)
    item = check_in_spec_runs_nothing(root)
    check_drift_is_repaired(root, item)
    check_unproven_restore_is_blocked(home)
    check_backoff_and_halt(home)
    check_loop_repairs_from_idle(home)
    check_registration()
    print("PASS test_reconciler")


if __name__ == "__main__":
    main()
