#!/usr/bin/env python3
"""Teams: chosen specialists collaborate — lead decomposes, workers run
isolated inside their own memories, handoffs happen through written files,
lead synthesizes. Every deliverable is gated by a done_check.

Run from the agent/ directory:  python tests/test_team.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import fleet
import team

RUN = "t-test"
WS = f"teamwork/{RUN}"

PLAN = (f"# plan\n- S1 [beta-writer]: draft the backoff explainer\n"
        f"- S2 [gamma-coder]: implement the retry client\n")

EXPERT_SETTINGS = """[agent]
poll_interval_seconds = 1
inbox_settle_seconds = 0
max_task_usd = 0
reflect_after = []

[providers.work]
type = "mock"
script = "scripts/work.json"

[providers.synth]
type = "mock"
script = "scripts/synth.json"

[roles.default]
provider = "work"
model = "mock"

[roles.practitioner]
provider = "work"
model = "mock"

[roles.librarian]
provider = "synth"
model = "mock"
"""


def wire(root, work_script, synth_script=None):
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(EXPERT_SETTINGS)
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    with open(os.path.join(root, "scripts", "work.json"), "w", encoding="utf-8") as f:
        json.dump(work_script, f)
    with open(os.path.join(root, "scripts", "synth.json"), "w", encoding="utf-8") as f:
        json.dump(synth_script or [], f)


def main():
    home = make_sandbox("team", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    alpha = fleet.create(home, "Alpha Lead", "planning and synthesis")
    beta = fleet.create(home, "Beta Writer", "technical writing")
    gamma = fleet.create(home, "Gamma Coder", "python clients")

    wire(alpha,
         [{"tool": "write_file", "args": {"path": f"{WS}/plan.md", "content": PLAN}},
          {"tool": "finish_task", "args": {"summary": "planned"}}],
         [{"tool": "write_file", "args": {"path": f"{WS}/result.md",
           "content": "# Result\nExplainer [C-0101] + client, combined.\n"}},
          {"tool": "finish_task", "args": {"summary": "synthesized"}}])
    wire(beta,
         [{"tool": "write_file", "args": {"path": f"{WS}/output-S1.md",
           "content": "Backoff doubles the wait [C-0101].\n"}},
          {"tool": "finish_task", "args": {"summary": "S1 delivered"}}])
    wire(gamma,
         [{"tool": "write_file", "args": {"path": f"{WS}/output-S2.md",
           "content": "def retry(): ...  # per P-0102\n"}},
          {"tool": "finish_task", "args": {"summary": "S2 delivered"}}])

    record = team.run_team(home, "Produce a cited backoff explainer with a client",
                           ["alpha-lead", "beta-writer", "gamma-coder"],
                           lead="alpha-lead", run_id=RUN, drive=True, timeout=180)

    assert record["status"] == "done", record
    ws = os.path.join(home, "teamwork", RUN)
    for f in ("brief.md", "plan.md", "output-S1.md", "output-S2.md",
              "result.md", "team.json"):
        assert os.path.exists(os.path.join(ws, f)), f"missing {f} in the workspace"
    assert [s["status"] for s in record["subtasks"]] == ["done", "done"]
    assert record["subtasks"][0]["expert"] == "beta-writer"
    assert record["subtasks"][1]["expert"] == "gamma-coder"
    print("[flow] lead planned, both specialists delivered, lead synthesized — all gated")

    # the roster reached each specialist, with identities
    with open(os.path.join(ws, "brief.md"), "r", encoding="utf-8") as f:
        brief = f.read()
    assert "technical writing" in brief and "python clients" in brief
    # handoff through files: the SECOND worker received the first's output…
    assert os.path.exists(os.path.join(gamma, WS, "output-S1.md")), \
        "gamma must receive beta's output as a file handoff"
    # …and the FIRST worker never saw the second's (it ran earlier, isolated)
    assert not os.path.exists(os.path.join(beta, WS, "output-S2.md")), \
        "beta ran first and must not contain later outputs"
    print("[handoff] outputs flowed forward as files; no shared mutable state")

    # each expert did its own work in its own state, nothing bled
    def statuses(root):
        with open(os.path.join(root, "state.json"), "r", encoding="utf-8") as f:
            return [(t["role"], t["status"]) for t in json.load(f)["tasks"]]
    assert statuses(beta) == [("practitioner", "done")]
    assert statuses(gamma) == [("practitioner", "done")]
    assert statuses(alpha) == [("practitioner", "done"), ("librarian", "done")]
    print("[isolation] beta:1 task, gamma:1 task, alpha:plan+synthesis — memories separate")

    # the synthesis kept the specialists' citations
    with open(os.path.join(ws, "result.md"), "r", encoding="utf-8") as f:
        assert "C-0101" in f.read(), "citations must survive synthesis"
    assert team.list_runs(home)[0]["id"] == RUN
    print("[result] one deliverable, citations preserved, run listed")
    print("PASS test_team")


if __name__ == "__main__":
    main()
