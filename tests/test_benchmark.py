#!/usr/bin/env python3
"""The lift benchmark: measuring what the harness adds, instead of asserting it.

The scripted model here behaves like a real mediocre one: its FIRST attempt at
each task is wrong in a realistic way (missing key, forbidden word present, no
citation), and it only gets it right after being told the check failed. That
is precisely the difference between the two arms:

  bare arm     takes the first answer and ships it -> wrong, and it CLAIMS done
  harness arm  refuses finish_task until the check passes -> the same model
               produces a correct artifact

Proven here: the benchmark measures both arms with the same mechanical checks,
computes the lift honestly, reports sample size, and refuses to divide by zero
when the bare arm scores nothing.

Run from the agent/ directory:  python tests/test_benchmark.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import benchmark
import fleet

PY = sys.executable

# Attempt 1 of each task is wrong; attempt 2 is right. A task's context is
# fresh per task, so the sequence replays for every task the same way.
SLOPPY = [
    # --- first attempt: plausible but wrong
    {"tool": "write_file", "args": {"path": "bench/out/config.json",
     "content": '{"name": "svc", "retries": 3, "extra": true}'}},
    {"tool": "finish_task", "args": {"summary": "config written"}},
    # --- after the gate refuses, it fixes the real problem
    {"tool": "write_file", "args": {"path": "bench/out/config.json",
     "content": '{"name": "svc", "retries": 5}'}},
    {"tool": "finish_task", "args": {"summary": "config corrected"}},
]
SLOPPY2 = [
    {"tool": "write_file", "args": {"path": "bench/out/notice.txt",
     "content": "DRAFT — APPROVED pending review"}},
    {"tool": "finish_task", "args": {"summary": "notice written"}},
    {"tool": "write_file", "args": {"path": "bench/out/notice.txt",
     "content": "APPROVED"}},
    {"tool": "finish_task", "args": {"summary": "notice corrected"}},
]
SLOPPY3 = [
    {"tool": "write_file", "args": {"path": "bench/out/claim.md",
     "content": "Backoff doubles the wait."}},
    {"tool": "finish_task", "args": {"summary": "claim written"}},
    {"tool": "write_file", "args": {"path": "bench/out/claim.md",
     "content": "Backoff doubles the wait [src: transcript 00:01]."}},
    {"tool": "finish_task", "args": {"summary": "claim cited"}},
]

SETTINGS = """[agent]
poll_interval_seconds = 1
max_task_usd = 0
reflect_after = []
max_done_rejects = 4
max_task_retries = 0

[providers.m]
type = "mock"
script = "script.json"
input_per_mtok = 1.0
output_per_mtok = 1.0
fake_usage = {prompt_tokens = 1000, completion_tokens = 500}

[roles.default]
provider = "m"
model = "mock"

[roles.practitioner]
provider = "m"
model = "mock"
"""


def main():
    home = make_sandbox("benchmark", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Bench Subject", "measuring the harness")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(SETTINGS)

    # one script per trial: swap it between trials so each task's "sloppy
    # first attempt" is realistic for that task
    scripts = {"T1-artifact": SLOPPY, "T2-constraint": SLOPPY2,
               "T3-evidence": SLOPPY3}
    rows = []
    import loop
    for trial in benchmark.SUITE:
        with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
            json.dump(scripts[trial["id"]], f)
        agent = loop.Agent(root)
        rows.append(benchmark.bare_arm(agent, root, trial))
        rows.append(benchmark.harness_arm(agent, root, trial, timeout=120))

    bare = [r for r in rows if r["arm"] == "bare"]
    harn = [r for r in rows if r["arm"] == "harness"]

    # the bare arm ships its first answer: wrong on every trial, and it says done
    assert all(not r["passed"] for r in bare), \
        f"the sloppy first answer should fail every check: {bare}"
    assert all(r["claimed_done"] for r in bare), \
        "…while claiming success — that is the dangerous failure mode"
    assert all(r["false_success"] for r in bare)
    print("[bare] the model's first answer failed all 3 mechanical checks — "
          "and reported success on every one of them")

    # the SAME model inside the harness produces correct artifacts
    assert all(r["passed"] for r in harn), \
        f"the harness must convert the same model into passing work: {harn}"
    assert all(not r["false_success"] for r in harn), \
        "a gated task can never claim done while its check fails"
    assert all(r["refusals"] >= 1 for r in harn), \
        f"each trial should show the gate refusing the wrong answer: {harn}"
    print(f"[harness] same model, same tasks: 3/3 passed, 0 false 'done', "
          f"gate refused {sum(r['refusals'] for r in harn)} wrong answers "
          f"before accepting correct ones")

    # the report is honest about what it measured
    s = benchmark.summarize(rows)
    assert s["arms"]["bare"]["pass_rate"] == 0.0
    assert s["arms"]["harness"]["pass_rate"] == 1.0
    assert s["lift"]["pass_rate_multiplier"] is None, \
        "dividing by a zero baseline must not fabricate a multiplier"
    assert s["lift"]["false_success_removed"] == 1.0
    assert s["n"] == 3, s["n"]
    assert s["arms"]["harness"]["cost_usd"] > s["arms"]["bare"]["cost_usd"], \
        "the lift costs tokens and the report must say so"
    print(f"[honest] with a zero baseline the multiplier is reported as "
          f"undefined, not infinite; false-'done' eliminated "
          f"{s['lift']['false_success_removed']:+.0%}; the lift cost "
          f"{s['arms']['harness']['cost_usd']:.3f} vs "
          f"{s['arms']['bare']['cost_usd']:.3f} USD, and n=3 is printed")
    print("PASS test_benchmark")


if __name__ == "__main__":
    main()
