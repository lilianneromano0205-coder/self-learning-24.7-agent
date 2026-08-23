#!/usr/bin/env python3
"""Acceptance test F analog (Part 12): skills compounding, the plumbing half.

Run 1's Reflector writes a skills/ playbook; a later task whose goal matches
the skill's name/keywords must get that playbook loaded into its context
automatically. Non-matching tasks must not.

Run from the agent/ directory:  python tests/test_skills.py
"""

import json
import os

from common import add_task, make_sandbox, read_state, run_drain

SKILL = ("KEYWORDS: deploy, staging, rollout\n"
         "# Skill: deploy-site\n"
         "1. build  2. upload  3. verify with curl -sf /health\n"
         "Pitfall from last run: clear the CDN cache or the check sees stale content.\n")

WORK = [{"tool": "finish_task", "args": {"summary": "work complete"}}]
REFLECT = [
    {"tool": "write_file", "args": {"path": "skills/deploy-site.md", "content": SKILL}},
    {"tool": "finish_task", "args": {"summary": "skill recorded"}},
]


def first_user_message(sb, task):
    with open(os.path.join(sb, task["context_ref"]), "r", encoding="utf-8") as f:
        msgs = json.load(f)
    return next(m["content"] for m in msgs if m["role"] == "user")


def main():
    sb = make_sandbox(
        "skills",
        providers={"mockw": {"script": "scripts/w.json"},
                   "mockr": {"script": "scripts/r.json"}},
        roles={"tester": "mockw", "reflector": "mockr"},
        scripts={"scripts/w.json": WORK, "scripts/r.json": REFLECT},
        reflect_after='"tester"',
    )

    # run 1: work task -> reflector writes the playbook
    add_task(sb, "tester", "deploy the site for the first time")
    assert run_drain(sb) == 0
    assert os.path.exists(os.path.join(sb, "skills", "deploy-site.md"))

    # run 2: a matching goal loads the skill into context
    add_task(sb, "tester", "deploy the site to staging again")
    # and a non-matching goal must not
    add_task(sb, "tester", "summarize lesson twelve")
    assert run_drain(sb) == 0

    tasks = [t for t in read_state(sb)["tasks"] if t["role"] == "tester"]
    matching, non_matching = tasks[1], tasks[2]
    ctx = first_user_message(sb, matching)
    assert "clear the CDN cache" in ctx, \
        "run 2 must load the playbook run 1 wrote (pitfalls included)"
    ctx2 = first_user_message(sb, non_matching)
    assert "clear the CDN cache" not in ctx2, \
        "unrelated tasks must not get the skill (context is scarce)"
    print("[skills] run 2 loaded the playbook run 1 wrote, and an unrelated task did not - procedural memory compounds without leaking")
    print("PASS test_skills: run 2 loaded run 1's playbook; unrelated task did not")


if __name__ == "__main__":
    main()
