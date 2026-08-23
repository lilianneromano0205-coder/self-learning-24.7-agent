#!/usr/bin/env python3
"""Deterministic workflows: fixed stages, each a gated task, each firing the
next only when done — the predictable lane that comes before autonomy.

1. A three-stage draft -> review -> revise workflow runs to completion on
   one idle drain: stage order is enforced by task_done intentions, every
   stage writes its deliverable, the next stage is told where to read it.
2. A failing middle stage HALTS the chain: stage 3 is never queued.
3. Variables substitute into stage goals; status reports per stage.

Run from the agent/ directory:  python tests/test_workflows.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import workflows as wf

PY = sys.executable
BAD = f'"{PY}" -c "import sys;sys.exit(1)"'

SPEC = {"name": "draft-review-revise", "stages": [
    {"role": "tester", "goal": "Draft the memo on {topic}"},
    {"role": "tester", "goal": "Review the draft for defects"},
    {"role": "tester", "goal": "Revise the memo fixing the defects"}]}


def main():
    # the mock writes whatever deliverable path its goal names: it cannot see
    # the goal, so the script writes all three stage files — the GATE of
    # each stage only checks its own file, and the chain checks order
    sb = make_sandbox("workflows", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    # a model that writes the stage file named in the current goal: the mock
    # can't read goals, so we give it a script per stage via the goal order
    # — simplest faithful approach: write ALL stage files up front in stage 1?
    # No: that would let stage 3's gate pass early. Instead each task's
    # script writes its own file; scripts replay per task, so we write the
    # file that does not exist yet.
    writer = (f'"{PY}" -c "import os,glob;'
              "d=sorted(glob.glob('workflows/*'))[0];"
              "n=1+len(glob.glob(d+'/stage-*.md'));"
              "open(f'{d}/stage-{n}.md','w').write(f'stage {n} deliverable')\"")
    with open(os.path.join(sb, "s.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "run_command", "args": {"cmd": writer}},
                   {"tool": "finish_task", "args": {"summary": "stage done"}}], f)

    rec = wf.run(sb, SPEC, {"topic": "pricing"})
    assert len(rec["stages"]) == 3 and rec["stages"][0]["task"]
    assert rec["stages"][1]["intention"] and rec["stages"][2]["intention"]
    assert run_drain(sb) == 0
    st = wf.status(sb, rec["id"])
    assert st["status"] == "complete", st
    tasks = read_state(sb)["tasks"]
    goals = [t["goal"] for t in sorted(tasks, key=lambda t: t["created"])]
    assert "stage 1 of 3" in goals[0] and "pricing" in goals[0], goals[0][:80]
    assert "stage 2 of 3" in goals[1] and "read the previous stage's deliverable" in goals[1]
    assert "stage 3 of 3" in goals[2]
    for n in (1, 2, 3):
        p = os.path.join(sb, "workflows", rec["id"], f"stage-{n}.md")
        assert os.path.exists(p), f"stage {n} deliverable missing"
    # the variable landed, and all three tasks are done in order
    assert all(t["status"] == "done" for t in tasks) and len(tasks) == 3
    print("[chain] draft -> review -> revise ran on one idle drain in order, "
          "each stage gated on its own deliverable, variables substituted")

    # --- a failing middle stage halts the chain
    sb2 = make_sandbox("workflows_halt", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": []})
    with open(os.path.join(sb2, "s.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "run_command", "args": {"cmd": writer}},
                   {"tool": "finish_task", "args": {"summary": "stage done"}}], f)
    with open(os.path.join(sb2, "settings.toml"), "a", encoding="utf-8") as f:
        f.write("\n")
    spec2 = {"name": "halts", "stages": [
        {"role": "tester", "goal": "one"},
        {"role": "tester", "goal": "two", "done_check": BAD},
        {"role": "tester", "goal": "three"}]}
    rec2 = wf.run(sb2, spec2)
    assert run_drain(sb2) == 0
    st2 = wf.status(sb2, rec2["id"])
    assert st2["status"] == "failed", st2["status"]
    assert [s["status"] for s in st2["stages"]] == ["done", "failed", "waiting"], \
        [s["status"] for s in st2["stages"]]
    # stage 2 is RETRIED by the harness (fresh context, error in hand) — those
    # are extra tasks; what must never exist is a stage-3 task
    assert not any("stage 3 of 3" in t["goal"] for t in read_state(sb2)["tasks"]), \
        "stage 3 must never be queued"
    print("[halt] a failed gate in stage 2 stopped the pipeline — stage 3 "
          "never queued; status reports exactly where evidence stopped")

    try:
        wf.run(sb2, {"name": "x", "stages": [{"role": "tester", "goal": "solo"}]})
        raise AssertionError("one stage is not a workflow")
    except SystemExit:
        pass
    assert any(w["id"] == rec2["id"] for w in wf.list_workflows(sb2))
    print("[guard] single-stage specs refused; workflows listable with status")
    print("PASS test_workflows")


if __name__ == "__main__":
    main()
