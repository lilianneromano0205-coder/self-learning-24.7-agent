#!/usr/bin/env python3
"""SUBQUERY — recursive sub-calls: the material never enters the window.

Recursive Language Models (Zhang, Kraska & Khattab, MIT CSAIL 2025,
arXiv:2512.24601) showed the strongest long-context strategy is not a
bigger window: keep the material OUT of the orchestrating context, let
the model query slices through disposable sub-calls, and combine the
distilled answers. RLM(GPT-5-mini) beat full GPT-5 by 34+ points on
OOLONG that way, cheaper per query. This platform's `subquery` tool is
that strategy under the house laws, and this file pins them:

  1. THE MATERIAL NEVER ENTERS THE TOP WINDOW: a task subqueries a
     corpus carrying a poison marker; the sub-answer reaches the task's
     recorded step, while the marker text appears NOWHERE in the task's
     persisted context or steps — only the distilled reply travels.
  2. the sub-call rides its own [roles.subquery] rail when one is
     defined — sub-calls go to the cheapest model by configuration.
  3. every sub-call is metered through the model gateway with
     purpose="subquery" — recursion is never free-floating spend.
  4. an oversized slice is refused NAMING the cap and the remedy
     (smaller ranges), never silently truncated.
  5. the sub-answer returns fenced as UNTRUSTED, and the sub-call's
     system prompt orders instructions inside the material to be
     reported as data, never followed.
  6. path containment holds: a subquery outside the root is an ERROR,
     not a read.

Run from the agent/ directory:  python tests/test_subquery.py
"""

import json
import os
import sys

from common import (AGENT_DIR, add_task, make_sandbox, read_state,
                    run_drain)

sys.path.insert(0, AGENT_DIR)
import loop                    # noqa: E402

POISON = "XYLO77-MARKER-THAT-MUST-NEVER-REACH-THE-TOP-WINDOW"


def main():
    sb = make_sandbox(
        "subquery",
        providers={"m": {"script": "scripts/top.json"},
                   "sub": {"script": "scripts/sub.json",
                           "fake_usage": {"prompt_tokens": 900,
                                          "completion_tokens": 40}}},
        roles={"tester": "m", "subquery": "sub"},
        scripts={
            "scripts/top.json": [
                {"tool": "subquery",
                 "args": {"instruction": "How many WIDGET lines are there?",
                          "path": "corpus/big.txt",
                          "start_line": 1, "end_line": 2000}},
                {"tool": "subquery",                      # oversized slice
                 "args": {"instruction": "summarize",
                          "path": "corpus/huge.txt"}},
                {"tool": "subquery",                      # escape attempt
                 "args": {"instruction": "read it",
                          "path": "../../outside.txt"}},
                {"tool": "finish_task", "args": {"summary": "map-reduced"}},
            ],
            "scripts/sub.json": [
                {"content": "There are 3 WIDGET lines. NOT IN THIS SLICE: "
                            "anything else."},
            ],
        })
    # the corpus: 2000 lines, 3 WIDGETs, poison on every 10th line
    os.makedirs(os.path.join(sb, "corpus"), exist_ok=True)
    with open(os.path.join(sb, "corpus", "big.txt"), "w",
              encoding="utf-8") as f:
        for i in range(2000):
            tag = " WIDGET" if i in (7, 700, 1400) else ""
            poison = f" {POISON}" if i % 10 == 0 else ""
            f.write(f"line {i}{tag}{poison}\n")
    with open(os.path.join(sb, "corpus", "huge.txt"), "w",
              encoding="utf-8") as f:
        f.write("x" * (loop.SUBQUERY_MAX_CHARS + 100) + "\n")

    add_task(sb, "tester", "count the WIDGET lines in corpus/big.txt")
    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done", t
    results = [s.get("result") or "" for s in t["steps"]]

    # 1. the distilled answer arrived; the poison never did
    assert any("3 WIDGET lines" in r for r in results), results
    joined = json.dumps(t) + json.dumps(results)
    assert POISON not in joined, (
        "the corpus reached the task record — the whole point of subquery "
        "is that only the distilled reply travels")
    ctx_dir = os.path.join(sb, "contexts")
    for fn in os.listdir(ctx_dir):
        p = os.path.join(ctx_dir, fn)
        if os.path.isfile(p):
            assert POISON not in open(p, encoding="utf-8",
                                      errors="replace").read(), (
                f"the corpus leaked into the top window: contexts/{fn}")

    # 2+5. the sub answer is fenced untrusted and rode the sub rail
    sub_result = next(r for r in results if "3 WIDGET lines" in r)
    assert "UNTRUSTED" in sub_result and "lines 1-2000" in sub_result, \
        sub_result

    # 3. metered with its own purpose
    metered = ""
    for base, _dirs, files in os.walk(os.path.join(sb, "logs")):
        for fn in files:
            try:
                metered += open(os.path.join(base, fn), encoding="utf-8",
                                errors="replace").read()
            except OSError:
                pass
    assert '"subquery"' in metered, (
        "no gateway row with purpose=subquery — recursive calls must be "
        "metered like every other call")

    # 4. the oversized slice was refused naming cap and remedy
    assert any("keep slices under" in r for r in results), results
    # 6. containment
    assert any("ERROR" in r and ("escapes" in r or "outside" in r
                                 or "path" in r.lower())
               for r in results), results

    print("[subquery] a 2000-line corpus was map-reduced through a "
          "disposable sub-call on its own cheap rail: the distilled answer "
          "reached the task while the corpus text reached NEITHER the task "
          "record nor any persisted context window; the sub-call was "
          "metered as purpose=subquery; an oversized slice was refused "
          "naming the cap; a path escape was refused — recursion under "
          "the same laws as everything else")
    print("PASS test_subquery")


if __name__ == "__main__":
    main()
