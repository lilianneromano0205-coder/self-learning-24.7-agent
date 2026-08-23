#!/usr/bin/env python3
"""Every loop is defined by its STOP CONDITION (M2-L1): declared on the
task, enforced by the harness, visible in context and in the panel.

1. deadline in the past -> the task fails with "stop condition", and the
   failure is filed under the budget category
2. max_attempts = 1 -> no retry, where the harness default would retry
3. max_steps = 2 -> the task fails at step 2 without finishing
4. the criteria text reaches the model (first user message) and survives
   compaction (HARNESS FACTS)
5. the panel's task action accepts a stop object and echoes it in /tasks;
   the CLI accepts --stop-criteria/--max-attempts/--deadline/--max-steps

Run from the agent/ directory:  python tests/test_stop.py
"""

import json
import os
import subprocess
import sys

from common import AGENT_DIR, LOOP, PY, agent_setting, api, make_sandbox, \
    read_state, run_drain, start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import loop
import memory

WRITE_FOREVER = [{"tool": "write_file", "args": {"path": "out/a.txt",
                                                  "content": "x"}}] * 6 + \
                [{"tool": "finish_task", "args": {"summary": "ok"}}]
FAIL_GATE = f'"{PY}" -c "import sys;sys.exit(1)"'


def main():
    # --- 1. deadline
    sb = make_sandbox("stop", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": WRITE_FOREVER})
    a = loop.Agent(sb)
    a.add_task("tester", "a job past its deadline",
               stop={"deadline": "2020-01-01T00:00:00", "criteria": "never"})
    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "failed" and "stop condition: deadline" in t["error"], t
    assert t["stop"]["deadline"] == "2020-01-01T00:00:00"
    assert memory.classify(t["error"]) == "budget"
    with open(os.path.join(sb, "logs", "agent.log"), encoding="utf-8") as f:
        assert '"stop_condition"' in f.read()
    print("[deadline] a task past its deadline fails with the stop condition "
          "named, filed as a budget failure")

    # --- 2. max_attempts = 1 beats the default retry budget
    sb2 = make_sandbox("stop_attempts", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"},
                       scripts={"s.json": [{"tool": "finish_task",
                                            "args": {"summary": "claim"}}]})
    agent_setting(sb2, "max_done_rejects = 1")
    a2 = loop.Agent(sb2)
    a2.add_task("tester", "default retries", done_check=FAIL_GATE)
    a2.add_task("tester", "single attempt", done_check=FAIL_GATE,
                stop={"max_attempts": 1})
    assert run_drain(sb2) == 0
    tasks = read_state(sb2)["tasks"]
    defaults = [t for t in tasks if "default retries" in t["goal"]]
    singles = [t for t in tasks if "single attempt" in t["goal"]]
    assert len(defaults) >= 2, "the harness default retries a failed task"
    assert len(singles) == 1, f"max_attempts=1 must forbid the retry: {len(singles)}"
    with open(os.path.join(sb2, "logs", "agent.log"), encoding="utf-8") as f:
        assert '"stop": "max_attempts"' in f.read()
    print("[attempts] max_attempts=1 stopped the retry the default budget "
          "would have made; the refusal names the stop condition")

    # --- 3. max_steps
    sb3 = make_sandbox("stop_steps", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": WRITE_FOREVER})
    agent_setting(sb3, "max_task_retries = 0")
    a3 = loop.Agent(sb3)
    a3.add_task("tester", "write until told to stop", stop={"max_steps": 2})
    assert run_drain(sb3) == 0
    t = read_state(sb3)["tasks"][0]
    assert t["status"] == "failed" and "max_steps 2" in t["error"], t
    assert len(t["steps"]) == 2, len(t["steps"])
    print("[steps] max_steps=2 ended the task at step 2 with the reason")

    # --- 4. the criteria reach the model and survive compaction
    with open(os.path.join(sb3, "contexts", t["id"] + ".json"), encoding="utf-8") as f:
        ctx = json.load(f)
    first_user = next(m["content"] for m in ctx if m["role"] == "user")
    assert "STOP CONDITION: max steps 2" in first_user, first_user[-200:]
    a3.ctx_threshold = 100
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "g"}]
    for i in range(20):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": str(i), "type": "function",
             "function": {"name": "write_file",
                          "arguments": json.dumps({"path": "o", "content": "x"})}}]})
        msgs.append({"role": "tool", "tool_call_id": str(i), "content": "ok " * 80})
    out = a3.compact_context({"id": "t-s", "role": "tester", "goal": "g", "steps": [],
                              "stop": {"criteria": "all tests green",
                                       "max_attempts": 3}}, msgs)
    note = next(m["content"] for m in out if m["role"] == "user"
                and m["content"].startswith("[Compact summary"))
    assert "Stop condition: done when: all tests green | max attempts 3" in note
    print("[context] the stop condition is in the first message and in the "
          "compaction's HARNESS FACTS")

    # --- 5. panel + CLI
    r = subprocess.run([PY, LOOP, "add", "--role", "tester", "--goal", "cli job",
                        "--root", sb3, "--stop-criteria", "file exists",
                        "--max-attempts", "2", "--max-steps", "7"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    cli = [x for x in read_state(sb3)["tasks"] if x["goal"] == "cli job"][0]
    assert cli["stop"] == {"criteria": "file exists", "max_attempts": 2,
                           "max_steps": 7}, cli["stop"]
    home = make_sandbox("stop_home", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    import fleet
    fleet.create(home, "Stopper", "x")
    proc, base = start_panel(home)
    try:
        r = api(base, "POST", "/api/experts/stopper/task",
                {"role": "practitioner", "goal": "panel job",
                 "stop": {"criteria": "report.md exists", "max_steps": 9}})
        tasks = api(base, "GET", "/api/experts/stopper/tasks")
        mine = [x for x in tasks if x["id"] == r["queued"]][0]
        assert mine["stop"]["criteria"] == "report.md exists" and \
            mine["stop"]["max_steps"] == 9, mine["stop"]
    finally:
        stop_panel(proc, base)
    print("[surface] stop conditions declared from the CLI and the panel, "
          "echoed back on the board")
    print("PASS test_stop")


if __name__ == "__main__":
    main()
