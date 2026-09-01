#!/usr/bin/env python3
"""Did the fix actually WORK? — the half a failure log never records.

A failure record answers "what went wrong". Experience needs the second half:
what fixed it, and did the fix hold. This is the difference between a system
that has failed 184 times and one that knows what works.

1. a failed task opens a case with its cause
2. a later task that PASSES ITS GATE closes it — mechanically, on the same
   evidence that let the work finish, never on an opinion
3. the same failure AFTER a fix is recorded as RECURRED, which is the most
   valuable state in the ledger: it says the fix was wrong
4. a matching later task carries the history into its context — "this failed
   here before, and this is what fixed it"
5. an unrelated task carries nothing
6. confidence is measured from what the harness checked, and a task that
   fought its gate scores lower than one that sailed through

Run from the agent/ directory:  python tests/test_cases.py
"""

import json
import os
import sys

from common import AGENT_DIR, PY, agent_setting, make_sandbox, read_state, \
    run_drain

sys.path.insert(0, AGENT_DIR)
import cases
import confidence
import context
import fleet
import loop

FAIL_GATE = f'"{PY}" -c "import sys;sys.exit(1)"'
PASS_GATE = f'"{PY}" -c "import sys;sys.exit(0)"'


def main():
    home = make_sandbox("cases", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Fixer", "learns what actually works")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\nsandbox = "host"\nallow_unsafe_host = true\n'
                'poll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\nmax_task_retries = 0\nmax_done_rejects = 1\n\n'
                '[providers.m]\ntype = "mock"\nscript = "script.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n')
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "finish_task", "args": {"summary": "claimed"}}] * 6, f)

    # --- 1. a failure opens a case
    a = loop.Agent(root)
    a.add_task("practitioner", "fix the kafka broker lag on the orders topic",
               done_check=FAIL_GATE)
    assert run_drain(root) == 0
    rows = cases.load(root)
    assert len(rows) == 1, rows
    case = rows[0]
    assert case["status"] == "open" and case["cause"], case
    assert "kafka" in " ".join(case["terms"]), case["terms"]
    print(f"[open] a failed task opened case {case['case']} with its cause "
          f"recorded, not just a log line")

    # --- 2. work that passes its gate closes it
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "write_file",
                    "args": {"path": "out/fix.md", "content": "raised the "
                                                              "partition count"}},
                   {"tool": "finish_task",
                    "args": {"summary": "raised the partition count on the "
                                        "orders topic"}}] * 6, f)
    loop.Agent(root).add_task(
        "practitioner", "fix the kafka broker lag on the orders topic properly",
        done_check=PASS_GATE)
    assert run_drain(root) == 0
    solved = [c for c in cases.load(root) if c["case"] == case["case"]][0]
    assert solved["status"] == "fixed", solved
    assert "partition count" in solved["fix"], solved["fix"]
    assert solved["verified_by"] == PASS_GATE, solved["verified_by"]
    with open(os.path.join(root, "logs", "agent.log"), encoding="utf-8") as f:
        assert '"case_fixed"' in f.read()
    print(f"[fixed] a later task that passed its gate closed the case, and "
          f"what it did is recorded as the fix — verified by the gate, not by "
          f"an opinion")

    # --- 3. the same failure after a fix is the most valuable event
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "finish_task", "args": {"summary": "claimed"}}] * 6, f)
    loop.Agent(root).add_task(
        "practitioner", "fix the kafka broker lag on the orders topic",
        done_check=FAIL_GATE)
    assert run_drain(root) == 0
    back = [c for c in cases.load(root) if c["case"] == case["case"]][0]
    assert back["status"] == "recurred", back
    assert back["recurrences"] == 1 and "fix was wrong" in back["note"]
    with open(os.path.join(root, "logs", "agent.log"), encoding="utf-8") as f:
        assert '"case_recurred"' in f.read()
    print("[recurred] the same failure after a fix was recorded as RECURRED — "
          "the ledger now says the obvious fix already failed once")

    # --- 4 + 5. the history reaches the work that needs it
    hits = cases.matching(root, "the kafka broker lag is back on orders")
    assert hits and hits[0]["case"] == case["case"], hits
    text = cases.render(hits)
    assert "PRIOR CASES" in text and "partition count" in text
    assert "RECURRED" in text
    assert not cases.matching(root, "write the quarterly budget report")
    msgs, man = context.compile(loop.Agent(root), {
        "id": "t-ctx", "role": "practitioner", "course": None,
        "goal": "the kafka broker lag is back on the orders topic",
        "memory_files": []})
    assert "PRIOR CASES" in msgs[1]["content"]
    csrc = [s for s in man["sources"] if s["name"] == "cases"][0]
    assert csrc["used_tokens"] > 0
    msgs2, _ = context.compile(loop.Agent(root), {
        "id": "t-other", "role": "practitioner", "course": None,
        "goal": "write the quarterly budget report", "memory_files": []})
    assert "PRIOR CASES" not in msgs2[1]["content"]
    print("[recall] the returning problem carried its own history into the "
          "window, including what was tried and that it did not hold; an "
          "unrelated task carried nothing")

    # --- 6. confidence follows the evidence, not the mood
    tasks = read_state(root)["tasks"]
    passed = next(t for t in tasks if t["status"] == "done")
    failed = next(t for t in tasks if t["status"] == "failed")
    agent = loop.Agent(root)
    good = confidence.score(agent, passed)
    bad = confidence.score(agent, failed)
    assert 0.0 <= good["confidence"] <= 1.0
    assert bad["confidence"] < good["confidence"], (bad, good)
    assert bad["band"] in ("low", "medium"), bad
    assert bad["action"] in ("escalate", "more_compute"), bad
    assert good["why"] and bad["why"], "confidence must say what was weakest"
    assert "confidence" in passed, "the band is recorded on the task itself"
    assert passed["confidence"]["band"] in ("high", "medium", "low")
    print(f"[confidence] the task that passed scored "
          f"{good['confidence']:.0%} ({good['band']}) and the one that failed "
          f"its gate {bad['confidence']:.0%} ({bad['band']} -> "
          f"{bad['action']})")

    st = cases.stats(root)
    assert st["total"] == 1 and st["recurred"] == 1
    print(f"[ledger] {st['total']} case(s), {st['recurred']} that came back "
          f"after a 'fix' — the number a team actually needs to see")
    print("PASS test_cases")


if __name__ == "__main__":
    main()
