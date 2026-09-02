#!/usr/bin/env python3
"""Phase 3 exit benchmark — Procedure Compiler V2, held green.

docs/DESIGN-P3-procedure-compiler-v2.md preregistered nine properties
before a line was written; this file is that benchmark. The IR under test
is restricted, typed and TOTAL — IF on observed predicates, bounded
FOREACH, CHECK, capped RETRY, CALL of proven procedures, COMPENSATE that
cleans up and still fails — as data, never generated code. Every authoring
path lands as CANDIDATE; only an owner-sealed fresh suite makes PROVEN;
and the first control-flow induction rule compiles a two-way IF from
straight-line-refusing trajectory groups using a guard read from recorded
before-snapshots, refusing on ambiguity.

Run from the agent/ directory:  python tests/test_procedure_v2.py
"""
import io
import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet                    # noqa: E402
import loop                     # noqa: E402
import procedure                # noqa: E402
import runbook                  # noqa: E402


def wf(path, content):
    return {"kind": "deterministic",
            "action": {"tool": "write_file",
                       "args": {"path": path, "content": content}},
            "preconditions": [],
            "effects": [{"predicate": "file_equals", "path": path,
                         "value": content}]}


def mk_rb(name, steps, inputs=None, family="v2fam", triggers=None):
    return {"name": name, "triggers": triggers or [family],
            "procedure_version": 2, "steps": steps,
            "operator": {"inputs": inputs or {}, "preconditions": [],
                         "effects": [], "invariants": [], "cost_usd": 0.0,
                         "latency_seconds": 0.0,
                         "reversibility": "conditional",
                         "authority": ["workspace-write"]},
            "provenance": {"compiled": False, "family": family,
                           "acceptance_basis": "authored",
                           "input_hashes": [], "trajectory_ids": []}}


def put_rb(root, rb):
    os.makedirs(os.path.dirname(runbook.path(root, rb["name"])), exist_ok=True)
    io.open(runbook.path(root, rb["name"]), "w",
            encoding="utf-8").write(json.dumps(rb))


def problems_of(rb):
    return procedure.validate(rb)


def check_validator_refuses_the_unbounded(root):
    bad = [
        ({"kind": "jump"}, "unknown v2 step kind"),
        ({"kind": "foreach", "items": [], "bind": "x",
          "body": [wf("a", "b")]}, "foreach takes items, bind, max, body"),
        ({"kind": "foreach", "items": ["a"], "bind": "x", "max": 99,
          "body": [wf("a", "b")]}, "1..32"),
        ({"kind": "retry", "times": 9, "body": [wf("a", "b")]}, "1..3"),
        ({"kind": "call", "name": "proc-self", "inputs": {}},
         "may not call itself"),
        ({"kind": "model"}, "model steps cannot appear"),
    ]
    for step, why in bad:
        out = problems_of(mk_rb("proc-self", [step]))
        assert out and why in out[0], (why, out)
    nest = wf("a", "b")
    for _ in range(8):
        nest = {"kind": "retry", "times": 1, "body": [nest]}
    out = problems_of(mk_rb("proc-deep", [nest]))
    assert out and "nesting deeper" in out[0], out
    print("[validate] unknown kinds, unbounded loops, over-cap retries, "
          "self-calls, model steps and over-deep nests all refuse — the IR "
          "is closed and total")


def check_if_takes_the_observed_branch(root):
    rb = mk_rb("proc-branch", [
        {"kind": "if",
         "predicate": {"predicate": "file_exists", "path": "flag.txt"},
         "then": [wf("out/a.txt", "then")],
         "else": [wf("out/b.txt", "else")]}])
    assert not problems_of(rb)
    r1 = procedure.execute(root, rb, {})
    assert r1["ok"] and {"kind": "if", "took": "else"} in r1["steps"], r1
    assert os.path.isfile(os.path.join(root, "out", "b.txt"))
    io.open(os.path.join(root, "flag.txt"), "w", encoding="utf-8").write("x")
    r2 = procedure.execute(root, rb, {})
    assert r2["ok"] and {"kind": "if", "took": "then"} in r2["steps"], r2
    assert os.path.isfile(os.path.join(root, "out", "a.txt"))
    print("[if] the predicate was OBSERVED at run time and both arms were "
          "exercised — branching is a fact about the world, not a guess")


def check_foreach_is_bounded(root):
    rb = mk_rb("proc-each", [
        {"kind": "foreach", "items": {"input": "names"}, "bind": "n",
         "max": 3,
         "body": [{"kind": "deterministic",
                   "action": {"tool": "write_file",
                              "args": {"path": {"item": "n"},
                                       "content": "x"}},
                   "preconditions": [],
                   "effects": [{"predicate": "file_equals",
                                "path": {"item": "n"}, "value": "x"}]}]}],
        inputs={"names": "strings"})
    assert not problems_of(rb)
    ok = procedure.execute(root, rb, {"names": ["out/e1.txt", "out/e2.txt"]})
    assert ok["ok"] and {"kind": "foreach", "iterations": 2} in ok["steps"]
    assert os.path.isfile(os.path.join(root, "out", "e2.txt"))
    over = procedure.execute(root, rb, {"names": [f"out/o{i}.txt"
                                                 for i in range(4)]})
    assert not over["ok"] and "over its declared bound" in over["why"], over
    assert not os.path.isfile(os.path.join(root, "out", "o0.txt")), \
        "an over-bound loop must refuse BEFORE any side effect"
    print("[foreach] a typed list input iterated within its bound; an "
          "over-bound list refused before touching anything")


def check_check_stops_and_retry_is_capped(root):
    rb = mk_rb("proc-checked", [
        {"kind": "check",
         "predicate": {"predicate": "file_exists", "path": "nope.txt"}}])
    r = procedure.execute(root, rb, {})
    assert not r["ok"] and "CHECK failed" in r["why"], r
    guarded = wf("out/r.txt", "y")
    guarded = dict(guarded, preconditions=[
        {"predicate": "file_exists", "path": "never.txt"}])
    rb2 = mk_rb("proc-retry", [{"kind": "retry", "times": 3,
                                "body": [guarded]}])
    r2 = procedure.execute(root, rb2, {})
    assert not r2["ok"] and "retry exhausted after 3 attempts" in r2["why"]
    assert {"kind": "retry", "attempts": 3, "ok": False} in r2["steps"]
    print("[check/retry] a false CHECK stopped the run with the predicate "
          "named; RETRY attempted exactly its cap and failed honestly")


def check_compensate_cleans_up_and_still_fails(root):
    rb = mk_rb("proc-comp", [
        {"kind": "compensate",
         "body": [wf("out/half.txt", "partial"),
                  {"kind": "check", "predicate": {"predicate": "file_exists",
                                                  "path": "nope.txt"}}],
         "on_failure": [wf("out/cleanup.txt", "cleaned")]}])
    r = procedure.execute(root, rb, {})
    assert not r["ok"] and "compensation ran" in r["why"], r
    assert io.open(os.path.join(root, "out", "cleanup.txt"),
                   encoding="utf-8").read() == "cleaned"
    assert {"kind": "compensate", "compensated": True} in r["steps"]
    print("[compensate] the cleanup ran, its own effects verified — and the "
          "procedure STILL failed: compensation is never success")


def _prove(root, rb, suite_id, cases, checks, initial_files=None):
    put_rb(root, rb)
    procedure.seal_suite(root, suite_id, {
        "family": rb["provenance"]["family"], "cases": cases,
        "initial_files": initial_files or [], "checks": checks})
    verdict = procedure.evaluate(root, rb["name"], suite_id)
    assert verdict["accepted"] and verdict["status"] == "proven", verdict


def check_call_composes_only_proven(root):
    leafy = mk_rb("proc-leafy", [wf({"input": "path"}, "leafy")],
                  inputs={"path": "path"}, family="leafy")
    leafy["steps"][0]["effects"] = [{"predicate": "file_equals",
                                     "path": {"input": "path"},
                                     "value": "leafy"}]
    _prove(root, leafy, "leafy-suite",
           [{"id": f"c{i}", "edge": i == 2,
             "inputs": {"path": f"out/leafy-{i}.txt"}} for i in range(3)],
           [{"predicate": "file_equals", "path": {"input": "path"},
             "value": "leafy"}])
    caller = mk_rb("proc-caller", [
        {"kind": "call", "name": "proc-leafy",
         "inputs": {"path": "out/called.txt"}}])
    r = procedure.execute(root, caller, {})
    assert r["ok"] and {"kind": "call", "name": "proc-leafy", "ok": True} \
        in r["steps"], r
    assert os.path.isfile(os.path.join(root, "out", "called.txt"))
    put_rb(root, mk_rb("proc-cand", [wf("out/c.txt", "c")], family="cand"))
    caller2 = mk_rb("proc-caller2", [
        {"kind": "call", "name": "proc-cand", "inputs": {}}])
    r2 = procedure.execute(root, caller2, {})
    assert not r2["ok"] and "not PROVEN" in r2["why"], r2
    print("[call] composition stood on a PROVEN callee and executed; a "
          "candidate callee refused fail-closed at the call site")


def check_lifecycle_and_zero_model_if(home):
    root = fleet.create(home, "Summary Desk", "extends or creates summaries")
    io.open(os.path.join(root, "settings.toml"), "w", encoding="utf-8").write(
        "\n".join(['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
                   'poll_interval_seconds = 1', 'max_task_usd = 0',
                   'reflect_after = []', 'max_done_rejects = 2',
                   'max_task_retries = 0', '',
                   '[providers.silent]', 'type = "mock"',
                   'script = "scripts/silent.json"', '',
                   '[roles.default]', 'provider = "silent"', 'model = "mock"',
                   '', '[roles.r_silent]', 'provider = "silent"',
                   'model = "mock"', '']))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    json.dump([], io.open(os.path.join(root, "scripts", "silent.json"), "w",
                          encoding="utf-8"))
    rb = mk_rb("proc-summarize", [
        {"kind": "if",
         "predicate": {"predicate": "file_exists", "path": {"input": "path"}},
         "then": [wf({"input": "path"}, "extended\n")],
         "else": [wf({"input": "path"}, "created\n")]},
        {"kind": "check", "predicate": {"predicate": "file_exists",
                                        "path": {"input": "path"}}}],
        inputs={"path": "path"}, family="summarize",
        triggers=["summarize"])
    for arm in ("then", "else"):
        content = "extended\n" if arm == "then" else "created\n"
        rb["steps"][0][arm][0]["effects"] = [
            {"predicate": "file_equals", "path": {"input": "path"},
             "value": content}]
    _prove(root, rb, "summarize-suite",
           [{"id": "fresh1", "edge": False,
             "inputs": {"path": "out/s1.txt"}},
            {"id": "fresh2", "edge": False,
             "inputs": {"path": "out/s2.txt"}},
            {"id": "existing-edge", "edge": True,
             "inputs": {"path": "out/pre.txt"}}],
           [{"predicate": "file_exists", "path": {"input": "path"}}],
           initial_files=[{"path": "out/pre.txt", "content": "old\n"}])

    gate = (f'"{PY}" -c "import io,sys;'
            "sys.exit(0 if io.open(sys.argv[1],encoding='utf-8').read() "
            "in ('created\\n','extended\\n') else 1)\"")
    agent = loop.Agent(root)
    agent.add_task("r_silent", "summarize the live notes",
                   done_check=gate + " out/live.txt",
                   family="summarize", inputs={"path": "out/live.txt"})
    assert run_drain(root, timeout=120) == 0
    io.open(os.path.join(root, "out", "live2.txt"), "w",
            encoding="utf-8").write("old\n")
    agent = loop.Agent(root)
    agent.add_task("r_silent", "summarize the other live notes",
                   done_check=gate + " out/live2.txt",
                   family="summarize", inputs={"path": "out/live2.txt"})
    assert run_drain(root, timeout=120) == 0
    tasks = json.load(io.open(os.path.join(root, "state.json"),
                              encoding="utf-8"))["tasks"]
    assert [t["status"] for t in tasks] == ["done", "done"], tasks
    assert all(t.get("procedure_routed") == "proc-summarize" for t in tasks)
    assert io.open(os.path.join(root, "out", "live.txt"),
                   encoding="utf-8").read() == "created\n"
    assert io.open(os.path.join(root, "out", "live2.txt"),
                   encoding="utf-8").read() == "extended\n"
    print("[lifecycle] an authored IF procedure went candidate -> sealed "
          "fresh suite (edge: pre-existing file) -> PROVEN, then replayed "
          "BOTH branches on live tasks with zero model calls (empty "
          "provider script) under each task's own gate")


def check_if_induction_and_ambiguity(home):
    root = fleet.create(home, "Sync Desk", "creates or backs up then updates")
    io.open(os.path.join(root, "settings.toml"), "w", encoding="utf-8").write(
        "\n".join(['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
                   'poll_interval_seconds = 1', 'max_task_usd = 0',
                   'reflect_after = []', 'max_done_rejects = 2',
                   'max_task_retries = 0', '',
                   '[providers.wa]', 'type = "mock"',
                   'script = "scripts/wa.json"', '',
                   '[providers.wb]', 'type = "mock"',
                   'script = "scripts/wb.json"', '',
                   '[roles.default]', 'provider = "wa"', 'model = "mock"', '',
                   '[roles.r_wa]', 'provider = "wa"', 'model = "mock"', '',
                   '[roles.r_wb]', 'provider = "wb"', 'model = "mock"', '']))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    gate = (f'"{PY}" -c "import os,sys;'
            'sys.exit(0 if os.path.isfile(\'out/sync.txt\') else 1)"')
    # shape A: the target is ABSENT -> one step creates it
    json.dump([{"tool": "write_file", "args": {"path": "out/sync.txt",
                                               "content": "fresh"}},
               {"tool": "finish_task", "args": {"summary": "created"}}],
              io.open(os.path.join(root, "scripts", "wa.json"), "w",
                      encoding="utf-8"))
    agent = loop.Agent(root)
    agent.add_task("r_wa", "run the syncjob", done_check=gate,
                   family="syncjob")
    assert run_drain(root, timeout=120) == 0
    # shape B: the target EXISTS -> back up, then update (sync.txt now
    # exists from shape A's run, which is exactly the discriminating state)
    json.dump([{"tool": "write_file", "args": {"path": "out/sync-backup.txt",
                                               "content": "b1"}},
               {"tool": "write_file", "args": {"path": "out/sync.txt",
                                               "content": "updated"}},
               {"tool": "finish_task", "args": {"summary": "updated"}}],
              io.open(os.path.join(root, "scripts", "wb.json"), "w",
                      encoding="utf-8"))
    agent = loop.Agent(root)
    agent.add_task("r_wb", "run the syncjob again", done_check=gate,
                   family="syncjob")
    assert run_drain(root, timeout=120) == 0
    rb = json.load(io.open(runbook.path(root, "proc-syncjob"),
                           encoding="utf-8"))
    assert rb["procedure_version"] == 2, rb
    assert rb["steps"][0]["kind"] == "if"
    assert rb["steps"][0]["predicate"] == {"predicate": "file_exists",
                                           "path": "out/sync.txt"}
    assert rb["provenance"]["induced_structure"] == "if"
    assert len(rb["steps"][0]["then"]) == 2 and \
        len(rb["steps"][0]["else"]) == 1
    assert runbook.status(root, "proc-syncjob") == "candidate", \
        "induced structure is still only a CANDIDATE"

    # ambiguity: two shapes with NO discriminating guard refuse with the why
    gate2 = (f'"{PY}" -c "import os,sys;'
             'sys.exit(0 if os.path.isfile(\'out/amb.txt\') else 1)"')
    json.dump([{"tool": "write_file", "args": {"path": "out/amb.txt",
                                               "content": "one"}},
               {"tool": "finish_task", "args": {"summary": "a"}}],
              io.open(os.path.join(root, "scripts", "wa.json"), "w",
                      encoding="utf-8"))
    agent = loop.Agent(root)
    agent.add_task("r_wa", "run the ambjob", done_check=gate2, family="ambjob")
    assert run_drain(root, timeout=120) == 0
    os.remove(os.path.join(root, "out", "amb.txt"))
    json.dump([{"tool": "write_file", "args": {"path": "out/x.txt",
                                               "content": "x"}},
               {"tool": "write_file", "args": {"path": "out/amb.txt",
                                               "content": "two"}},
               {"tool": "finish_task", "args": {"summary": "b"}}],
              io.open(os.path.join(root, "scripts", "wb.json"), "w",
                      encoding="utf-8"))
    agent = loop.Agent(root)
    agent.add_task("r_wb", "run the ambjob again", done_check=gate2,
                   family="ambjob")
    assert run_drain(root, timeout=120) == 0
    refusals = []
    for line in io.open(os.path.join(root, "logs", "agent.log"),
                        encoding="utf-8", errors="replace"):
        if "procedure_compile_refused" in line and "ambjob" in line:
            refusals.append(line)
    assert refusals and "if-induction refused" in refusals[-1], refusals
    assert not os.path.isfile(runbook.path(root, "proc-ambjob"))
    print("[induction] two run shapes with a discriminating existence guard "
          "compiled into a CANDIDATE IF procedure; an ambiguous split (no "
          "guard) refused with the reason on the record")


def main():
    home = make_sandbox("procedure-v2", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = os.path.join(home, "v2lab")
    os.makedirs(os.path.join(root, "out"), exist_ok=True)
    check_validator_refuses_the_unbounded(root)
    check_if_takes_the_observed_branch(root)
    check_foreach_is_bounded(root)
    check_check_stops_and_retry_is_capped(root)
    check_compensate_cleans_up_and_still_fails(root)
    check_call_composes_only_proven(root)
    check_lifecycle_and_zero_model_if(home)
    check_if_induction_and_ambiguity(home)
    print("PASS test_procedure_v2")


if __name__ == "__main__":
    main()
