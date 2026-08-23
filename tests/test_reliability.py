#!/usr/bin/env python3
"""Corrupt-state quarantine.

A damaged state.json must never be silently discarded: it is moved to a
timestamped .corrupt-* backup, the loop starts with an empty queue, and new
tasks work immediately.

Run from the agent/ directory:  python tests/test_reliability.py
"""

import glob
import os
import sys

from common import AGENT_DIR, add_task, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import loop

SCRIPT = [{"tool": "finish_task", "args": {"summary": "ok"}}]


def main():
    sb = make_sandbox("reliability", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    with open(os.path.join(sb, "state.json"), "w", encoding="utf-8") as f:
        f.write('{"tasks": [ TORN WRITE GARBAGE')

    a = loop.Agent(sb)
    state = a.load_state()
    assert state == {"tasks": []}, "corrupt state must yield an empty queue"
    backups = glob.glob(os.path.join(sb, "state.json.corrupt-*"))
    assert len(backups) == 1, "the damaged file must be quarantined, not deleted"
    with open(backups[0], "r", encoding="utf-8") as f:
        assert "TORN WRITE GARBAGE" in f.read(), "backup must preserve the evidence"

    add_task(sb, "tester", "life after corruption")
    assert run_drain(sb) == 0
    assert read_state(sb)["tasks"][0]["status"] == "done"
    print("[quarantine] a corrupt state file was quarantined with its evidence kept and the queue rebuilt - the loop kept running")
    print("PASS test_reliability: corrupt state quarantined with evidence, queue reborn, tasks run")


if __name__ == "__main__":
    main()
