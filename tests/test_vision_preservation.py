#!/usr/bin/env python3
"""The product vision, held as a CI invariant.

VISION_CONTRACT.md states what this platform is: a persistent system where a
model is temporary intelligence and the SYSTEM keeps the knowledge, tools,
experience, proof, procedures and capabilities. This file makes that
sentence falsifiable. Each check pins one non-negotiable rule from the
contract, asserted from ledgers and real executions, so an architecture
phase that quietly bends the vision goes red before it merges:

  1. an ordinary gated task needs NO procedure — the model path is reached,
     and a missing procedure never means "impossible";
  2. goals still pursue outcomes to an ACHIEVED verdict under frozen checks;
  3. workflows still chain gated stages through prospective memory;
  4. missions still refuse to exist without success criteria (done is
     defined BEFORE work), and criteria are met with evidence;
  5. an unknown capability becomes a structured CAPABILITY GAP routed to
     acquisition — not a dead end, not an exception;
  6. the model is replaceable: swap the provider and the same expert keeps
     its state, and institutional memory written before the swap reaches
     the context of work done after it;
  7. learning cannot promote itself: accepted-claimed wins without
     independent receipts leave a compiled procedure at CANDIDATE;
  8. a failed gate cannot be talked past — finish_task against a failing
     done_check produces a FAILED task, not a done one;
  9. authority stays outside cognition: a worker write into a CONTROL path
     is refused while ordinary work proceeds;
 10. the deep surfaces (teams, research, mastery, procedural learning)
     remain registered in the same suite, so their depth is re-proven by
     the very run that runs this file.

Run from the agent/ directory:  python tests/test_vision_preservation.py
"""
import io
import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet                    # noqa: E402
import loop                     # noqa: E402


def _settings(root, providers, extra=""):
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
            encoding="utf-8").write("\n".join(s) + extra)
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)


def _script(root, name, steps):
    json.dump(steps, io.open(os.path.join(root, "scripts", f"{name}.json"),
                             "w", encoding="utf-8"))


def _tasks(root):
    p = os.path.join(root, "state.json")
    if not os.path.isfile(p):
        return []
    return json.load(io.open(p, encoding="utf-8"))["tasks"]


def check_a_plain_task_needs_no_procedure(home):
    root = fleet.create(home, "Plain Work", "does ordinary gated work")
    _settings(root, ["m"])
    _script(root, "m", [
        {"tool": "write_file", "args": {"path": "out/report.md",
                                        "content": "the report\n"}},
        {"tool": "finish_task", "args": {"summary": "written"}}])
    agent = loop.Agent(root)
    agent.add_task("r_m", "write the weekly report",
                   done_check=f'"{PY}" -c "import os,sys;'
                              'sys.exit(0 if os.path.isfile(\'out/report.md\') else 1)"')
    assert run_drain(root, timeout=120) == 0
    t = _tasks(root)[0]
    assert t["status"] == "done", t
    assert not t.get("procedure_routed"), \
        "no procedure existed, and none was needed"
    assert len(t.get("steps") or []) >= 1, \
        "the MODEL was consulted — novel work always reaches reasoning"
    assert not os.path.isdir(os.path.join(root, "runbooks")) or \
        not os.listdir(os.path.join(root, "runbooks")), \
        "this expert holds no procedures; the task still completed"
    print("[task] an ordinary gated task completed through model reasoning "
          "with zero procedures on disk — a missing procedure is not a "
          "missing capability")
    return root


def check_goals_still_work(home):
    import goal
    root = fleet.create(home, "Goal Runner", "pursues outcomes to a verdict")
    trophy = os.path.join(root, "trophy.txt").replace("\\", "/")
    check = (f'"{PY}" -c "import os,sys;'
             f"sys.exit(0 if os.path.exists(r'{trophy}') else 1)\"")
    _settings(root, ["work", "judge"],
              extra='\n[roles.examiner]\nprovider = "judge"\n'
                    'model = "mock"\n')
    GD = "goals/g-vision"
    _script(root, "work", [
        {"tool": "write_file", "args": {"path": f"{GD}/plan-1.md",
         "content": f"- M1: produce the trophy CHECK: {check}\n"}},
        {"tool": "write_file", "args": {"path": "trophy.txt", "content": "real"}},
        {"tool": "write_file", "args": {"path": f"{GD}/m1-1.md",
         "content": "trophy produced and on disk\n"}},
        {"tool": "finish_task", "args": {"summary": "milestone done"}}])
    _script(root, "judge", [
        {"tool": "write_file", "args": {"path": f"{GD}/assessment-1.md",
         "content": "trophy.txt verified on disk.\nVERDICT: ACHIEVED\n"}},
        {"tool": "finish_task", "args": {"summary": "judged"}}])
    rec = goal.pursue(home, os.path.basename(root),
                      "produce the trophy artifact",
                      criteria="trophy.txt exists", cycles=2, drive=True,
                      timeout=240, gid="g-vision")
    assert rec["status"] == "achieved", rec
    assert os.path.exists(os.path.join(root, "trophy.txt"))
    print("[goal] a goal was pursued to ACHIEVED under its own frozen "
          "milestone check — outcomes, not steps")


def check_workflows_still_chain(home):
    import workflows as wf
    writer = (f'"{PY}" -c "import glob;'
              "d=sorted(glob.glob('workflows/*'))[0];"
              "n=1+len(glob.glob(d+'/stage-*.md'));"
              "open(f'{d}/stage-{n}.md','w').write(f'stage {n}')\"")
    json.dump([{"tool": "run_command", "args": {"cmd": writer}},
               {"tool": "finish_task", "args": {"summary": "stage done"}}],
              io.open(os.path.join(home, "s.json"), "w", encoding="utf-8"))
    rec = wf.run(home, {"name": "vision", "stages": [
        {"role": "tester", "goal": "draft the note"},
        {"role": "tester", "goal": "review the note"}]})
    assert rec["stages"][0]["task"] and rec["stages"][1]["intention"]
    assert run_drain(home, timeout=180) == 0
    st = wf.status(home, rec["id"])
    assert st["status"] == "complete", st
    print("[workflow] two gated stages chained through prospective memory "
          "and completed in order on one idle drain")


def check_missions_define_done_first(root):
    import mission
    try:
        mission.create(root, "improve operations", [])
        raise AssertionError("a mission with no criteria must be refused")
    except ValueError:
        pass
    rec = mission.create(root, "keep the weekly report flowing",
                         ["a report exists for the current week"])
    mid = rec["id"]
    mission.meet(root, mid, "C1", evidence="out/report.md",
                 verified_by="gate: report file exists")
    state = mission.compile_state(root, mid)
    assert any(c["state"] == "met" for c in
               mission.load(root, mid)["criteria"]), state
    print("[mission] a mission refused to exist without success criteria, "
          "and met its criterion only WITH evidence")


def check_capability_gap_not_dead_end(home, slug):
    import universal
    report = universal.assess(
        home, slug,
        "transcribe the recorded customer call and the webinar video",
        "a transcript file exists for each recording")
    gaps = report["gaps"]
    rows = [g for g in gaps if g.get("dimension") == "capability"]
    assert rows, f"a goal needing transcription/video on a machine without "\
                 f"those capabilities must surface a capability GAP, got: {gaps}"
    for g in rows:
        assert g.get("routes_to") and g.get("detail"), (
            "a capability gap must carry a remediation ROUTE and a concrete "
            "next step — a dead end is a vision violation", g)
    print("[frontier] a capability this machine does not have became a "
          "structured gap with a named remediation route — the tool "
          "universe stays open-ended, and 'cannot yet' never reads as "
          "'impossible'")


def check_the_model_is_swappable_and_memory_survives(home):
    root = fleet.create(home, "Vendor Neutral",
                        "outlives every provider it rents")
    _settings(root, ["alpha"])
    _script(root, "alpha", [
        {"tool": "write_file", "args": {"path": "out/m1.txt", "content": "one"}},
        {"tool": "finish_task", "args": {"summary": "first provider"}}])
    agent = loop.Agent(root)
    agent.add_task("r_alpha", "produce the first artifact", course="ops",
                   done_check=f'"{PY}" -c "import os,sys;'
                              'sys.exit(0 if os.path.isfile(\'out/m1.txt\') else 1)"')
    assert run_drain(root, timeout=120) == 0
    # institutional memory written while provider alpha was the brain
    os.makedirs(os.path.join(root, "courses", "ops"), exist_ok=True)
    io.open(os.path.join(root, "courses", "ops", "gotchas.md"), "w",
            encoding="utf-8").write(
        "- [2026-09-01] (environment) "
        "TRIGGER: exporting, ops, report "
        "| WHEN exporting the ops report "
        "| DO include the header row | src: task vision0001\n")
    # THE MODEL IS REPLACED: settings now know only provider beta
    _settings(root, ["beta"])
    _script(root, "beta", [
        {"tool": "write_file", "args": {"path": "out/m2.txt",
                                        "content": "header\ntwo"}},
        {"tool": "finish_task", "args": {"summary": "second provider"}}])
    agent = loop.Agent(root)
    agent.add_task("r_beta", "exporting the ops report again", course="ops",
                   done_check=f'"{PY}" -c "import os,sys;'
                              'sys.exit(0 if os.path.isfile(\'out/m2.txt\') else 1)"')
    assert run_drain(root, timeout=120) == 0
    tasks = _tasks(root)
    assert [t["status"] for t in tasks] == ["done", "done"], tasks
    second = tasks[-1]
    ctx = io.open(os.path.join(root, second["context_ref"]),
                  encoding="utf-8", errors="replace").read()
    assert "-> DO" in ctx and "include the header row" in ctx, \
        "memory written under the OLD provider must reach work done by the NEW one"
    print("[vendor] the provider was replaced outright; the expert's state, "
          "history and institutional memory carried over — intelligence is "
          "rented, experience is owned")


def check_learning_cannot_promote_itself(root):
    import runbook
    rb = {"name": "proc-vision", "triggers": ["vision"],
          "procedure_version": 1,
          "steps": [{"id": "step-1", "depends_on": [],
                     "kind": "deterministic",
                     "action": {"tool": "write_file",
                                "args": {"path": "out/v.txt", "content": "x"}},
                     "preconditions": [],
                     "effects": [{"predicate": "file_equals",
                                  "path": "out/v.txt", "value": "x"}]}],
          "operator": {"inputs": {}, "preconditions": [], "effects": [],
                       "invariants": [], "cost_usd": 0.0,
                       "latency_seconds": 0.0,
                       "reversibility": "conditional",
                       "authority": ["workspace-write"]}}
    problems = runbook.validate(rb)
    assert not problems, problems
    os.makedirs(os.path.dirname(runbook.path(root, "proc-vision")),
                exist_ok=True)
    io.open(runbook.path(root, "proc-vision"), "w",
            encoding="utf-8").write(json.dumps(rb))
    for _ in range(4):
        runbook.record(root, "proc-vision", True, accepted=True,
                       why="caller CLAIMS acceptance, brings no receipt")
    assert runbook.status(root, "proc-vision") == "candidate", \
        "accepted-claimed wins without independent sealed receipts must " \
        "never promote a compiled procedure"
    print("[learning] four accepted-claimed wins with no independent receipt "
          "left the procedure at CANDIDATE — trust is bought with fresh "
          "sealed evaluation, never with self-report")


def check_a_failed_gate_cannot_be_bypassed(home):
    root = fleet.create(home, "Honest Failure", "keeps its failures")
    _settings(root, ["liar"])
    _script(root, "liar",
            [{"tool": "finish_task", "args": {"summary": "trust me"}}] * 3)
    agent = loop.Agent(root)
    agent.add_task("r_liar", "produce the artifact",
                   done_check=f'"{PY}" -c "import sys;sys.exit(1)"')
    assert run_drain(root, timeout=120) == 0
    t = _tasks(root)[0]
    assert t["status"] == "failed", t
    assert (t.get("verification") or {}).get("passed") is not True
    print("[gate] a worker that only ever said 'done' against a failing "
          "gate produced a FAILED task on the record — models never judge "
          "their own work")
    return root


def check_authority_stays_outside_cognition(root):
    _script(root, "liar", [
        {"tool": "write_file", "args": {"path": "skills/graph.json",
                                        "content": "{\"forged\": true}"}},
        {"tool": "write_file", "args": {"path": "out/ok.txt", "content": "y"}},
        {"tool": "finish_task", "args": {"summary": "done"}}])
    agent = loop.Agent(root)
    agent.add_task("r_liar", "do the work and also improve the skill graph",
                   done_check=f'"{PY}" -c "import os,sys;'
                              'sys.exit(0 if os.path.isfile(\'out/ok.txt\') else 1)"')
    assert run_drain(root, timeout=120) == 0
    t = _tasks(root)[-1]
    assert t["status"] == "done", t
    graph = os.path.join(root, "skills", "graph.json")
    assert not os.path.isfile(graph) or \
        "forged" not in io.open(graph, encoding="utf-8").read(), \
        "a worker wrote into the CONTROL zone — authority entered cognition"
    print("[authority] the CONTROL-zone write was refused while ordinary "
          "work completed — permissions live outside the model")


def check_deep_surfaces_stay_registered():
    import mastery                # noqa: F401  (import proves the surface)
    import research
    import team
    assert callable(team.run_team) and callable(research.investigate)
    registry = io.open(os.path.join(AGENT_DIR, "tests", "run_all.py"),
                       encoding="utf-8").read()
    for deep in ("test_team.py", "test_research.py", "test_mastery.py",
                 "test_goal.py", "test_workflows.py", "test_memory.py",
                 "test_procedural_learning.py", "test_use_cases.py"):
        assert deep in registry, \
            f"{deep} left the suite — the vision loses its depth evidence"
    print("[depth] teams, research, mastery, memory, goals, workflows and "
          "procedural learning keep their deep tests registered in this "
          "same suite run — this file pins the vision, those prove the depth")


def main():
    home = make_sandbox("vision", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    plain_root = check_a_plain_task_needs_no_procedure(home)
    check_goals_still_work(home)
    check_workflows_still_chain(home)
    check_missions_define_done_first(plain_root)
    check_capability_gap_not_dead_end(home, os.path.basename(plain_root))
    check_the_model_is_swappable_and_memory_survives(home)
    check_learning_cannot_promote_itself(plain_root)
    liar_root = check_a_failed_gate_cannot_be_bypassed(home)
    check_authority_stays_outside_cognition(liar_root)
    check_deep_surfaces_stay_registered()
    print("PASS test_vision_preservation")


if __name__ == "__main__":
    main()
