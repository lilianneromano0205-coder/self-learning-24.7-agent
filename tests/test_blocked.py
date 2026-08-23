#!/usr/bin/env python3
"""Blocked-task resume (ask_human round trip).

ask_human must block the task and record the question in blocked.md; the
`answer` command must inject the human's reply into the task's context and
requeue it; the resumed task must complete.

Run from the agent/ directory:  python tests/test_blocked.py
"""

import json
import os
import subprocess
import sys

from common import LOOP, PY, add_task, make_sandbox, read_state, run_drain

SCRIPT = [
    {"tool": "ask_human", "args": {"question": "I need the scoped Shopify token — see blocked.md."}},
    {"tool": "finish_task", "args": {"summary": "resumed with the human's answer and finished"}},
]


def main():
    sb = make_sandbox("blocked", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    add_task(sb, "tester", "task that needs the human once")
    assert run_drain(sb) == 0

    t = read_state(sb)["tasks"][0]
    assert t["status"] == "blocked", t["status"]
    with open(os.path.join(sb, "blocked.md"), "r", encoding="utf-8") as f:
        assert "scoped Shopify token" in f.read()
    print("[blocked] question recorded in blocked.md, task blocked, loop moved on")

    r = subprocess.run([PY, LOOP, "answer", t["id"],
                        "--text", "Token created: shpat-XXXX, products scope only.",
                        "--root", sb], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_state(sb)["tasks"][0]["status"] == "queued"

    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done", f"{t['status']}: {t.get('error')}"
    assert t["summary"].startswith("resumed with the human's answer")
    with open(os.path.join(sb, t["context_ref"]), "r", encoding="utf-8") as f:
        ctx = json.load(f)
    assert any("Human answer" in (m.get("content") or "") for m in ctx), \
        "the human's answer must be in the resumed context"
    print("PASS test_blocked: ask_human -> blocked.md -> answer -> resumed -> done")


if __name__ == "__main__":
    main()
