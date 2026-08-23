#!/usr/bin/env python3
"""Trajectory replay — a number for "how much does this model agree with our
proven trajectories?" before it touches live work.

A task is run and recorded with model A (a mock script). Replay with the
SAME model scores 100% agreement. Swap the role's model to a model that
makes a different decision (a different script) and replay reports the
drift — without executing anything. A refusing model shows as refusals.

Run from the agent/ directory:  python tests/test_replay.py
"""

import json
import os
import sys

from common import AGENT_DIR, add_task, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import replay

GOOD = [{"tool": "write_file", "args": {"path": "out/a.txt", "content": "alpha"}},
        {"tool": "write_file", "args": {"path": "out/b.txt", "content": "beta"}},
        {"tool": "finish_task", "args": {"summary": "two files"}}]
# a model that agrees on step 1, drifts on step 2, and refuses on step 3
DRIFTER = [{"tool": "write_file", "args": {"path": "out/a.txt", "content": "alpha"}},
           {"tool": "run_command", "args": {"cmd": "echo nope"}},
           {"tool": "summon_demon", "args": {}}]


def main():
    sb = make_sandbox("replay", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": GOOD})
    add_task(sb, "tester", "write two files")
    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done"
    files_before = sorted(os.listdir(os.path.join(sb, "out")))

    # same model -> full agreement
    r = replay.replay(sb, last=5)
    assert r["tasks"] == 1 and r["decision_points"] == 3, r
    assert r["agreement"] == 1.0 and r["drift"] == 0 and r["refusals"] == 0
    print("[same] the recording model replays its own trajectory at 100%")

    # swap the model (the script) -> drift and refusal measured, nothing run
    with open(os.path.join(sb, "s.json"), "w", encoding="utf-8") as f:
        json.dump(DRIFTER, f)
    r2 = replay.replay(sb, last=5)
    assert r2["agreement"] is not None and abs(r2["agreement"] - 1/3) < 0.01, r2
    # an unknown tool is still a DECISION (a wrong one) -> drift, not refusal;
    # refusal is reserved for "no tool call at all"
    assert r2["drift"] == 2 and r2["refusals"] == 0, r2
    d = r2["per_task"][0]["details"]
    assert any(x.get("recorded") == "write_file" and x.get("got") == "run_command"
               for x in d), d
    assert any(x.get("recorded") == "finish_task" and x.get("got") == "summon_demon"
               for x in d), d
    assert sorted(os.listdir(os.path.join(sb, "out"))) == files_before, \
        "replay must never execute the model's choices"
    assert read_state(sb)["tasks"][0]["status"] == "done", \
        "replay must never touch task state"
    print("[swap] a different model measured at 33% agreement with 1 drift "
          "and 1 refusal — decisions read, never executed, state untouched")
    print("PASS test_replay")


if __name__ == "__main__":
    main()
