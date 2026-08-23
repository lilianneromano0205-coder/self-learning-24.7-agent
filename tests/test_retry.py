#!/usr/bin/env python3
"""Failure retries (the endurance promise).

A task that fails is re-queued with a fresh context carrying the previous
error, up to max_task_retries times; then retries stop. The retry goal names
the error, the original goal is preserved un-stacked across attempts, and the
retry starts from a clean context — no tool history leaks in from the failed
attempt (each attempt fails on its own 3rd malformed strike, not an inherited
count).

Run from the agent/ directory:  python tests/test_retry.py
"""

import json
import os

from common import add_task, make_sandbox, read_state, run_drain

# a script that always emits an unknown tool -> 3 malformed strikes -> failed
BROKEN = [{"tool": "summon_demon", "args": {}}] * 5


def main():
    sb = make_sandbox("retry", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": BROKEN})
    add_task(sb, "tester", "do the impossible exercise")
    assert run_drain(sb) == 0

    tasks = read_state(sb)["tasks"]
    assert len(tasks) == 3, f"1 original + 2 retries expected, got {len(tasks)}"
    assert [t["attempt"] for t in tasks] == [1, 2, 3]
    assert all(t["status"] == "failed" for t in tasks)
    assert all("malformed" in (t["error"] or "") or "valid tool call" in (t["error"] or "")
               for t in tasks), [t["error"] for t in tasks]
    for t in tasks[1:]:
        assert t["goal"].startswith("RETRY"), t["goal"][:40]
        assert "Original goal: do the impossible exercise" in t["goal"], \
            "the base goal must not stack RETRY prefixes"
        assert t["base_goal"] == "do the impossible exercise"
        assert "unknown tool: summon_demon" in t["goal"], \
            "the previous attempt's error must be carried into the retry goal"
        # context_ref stays None on tasks that never landed a valid tool call;
        # the context file itself always exists at the task's known path
        with open(os.path.join(sb, "contexts", t["id"] + ".json"),
                  "r", encoding="utf-8") as f:
            ctx = json.load(f)
        first_user = next(m["content"] for m in ctx if m["role"] == "user")
        # the self-model leads the compiled window; the task line follows it
        assert "Task: RETRY" in first_user, \
            "retry must open on its own fresh context"
        assert "unknown tool: summon_demon" in first_user, \
            "and it must carry the previous attempt's error into the window"
        assert sum(1 for m in ctx if m["role"] == "assistant") == 3, \
            "each attempt must fail on ITS OWN 3 strikes — no history inherited"
        assert sum(1 for m in ctx if m["role"] == "tool") == 2, \
            "no tool results may leak in from the previous attempt"
    print("[retry] the failed task was retried with the error in hand and a FRESH context, exactly the configured number of times")
    print("PASS test_retry: failed task retried exactly twice with fresh context, "
          "error carried forward, base goal un-stacked, then stopped")


if __name__ == "__main__":
    main()
