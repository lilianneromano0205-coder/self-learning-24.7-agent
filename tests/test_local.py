#!/usr/bin/env python3
"""Local-testing ecosystem: agent.env auto-loading, the daemon scanning its
own inbox with no timer and no human command, and the no-keys demo.

Run from the agent/ directory:  python tests/test_local.py
"""

import os
import subprocess
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import loop

PY = sys.executable
FINISH = [{"tool": "finish_task", "args": {"summary": "studied"}}]


def main():
    # --- agent.env auto-load (existing environment wins)
    sb = make_sandbox("local", providers={"m": {"script": "s.json"}},
                      roles={"watcher": "m"}, scripts={"s.json": FINISH})
    var = "LEARNING_AGENT_ENV_TEST_98765"
    os.environ.pop(var, None)
    with open(os.path.join(sb, "agent.env"), "w", encoding="utf-8") as f:
        f.write(f'# comment line\n{var} = "hello-from-env-file"\n')
    loop.Agent(sb)
    assert os.environ.get(var) == "hello-from-env-file", "agent.env must load"
    os.environ.pop(var, None)
    print("[env] agent.env loaded automatically, comments and quotes handled")

    # --- the daemon ingests its own inbox: drop a file, run, no scan command
    os.makedirs(os.path.join(sb, "inbox"))
    with open(os.path.join(sb, "inbox", "solo lesson.md"), "w", encoding="utf-8") as f:
        f.write("# Lesson\nBackoff doubles the wait.\n")
    assert run_drain(sb) == 0
    tasks = read_state(sb)["tasks"]
    assert len(tasks) == 1 and tasks[0]["role"] == "watcher" \
        and tasks[0]["status"] == "done", tasks
    assert os.path.exists(os.path.join(sb, "courses", "solo-lesson",
                                       "lessons", "01", "lesson.md"))
    print("[inbox] daemon scanned its own inbox on idle: file -> lesson -> watcher -> done")

    # --- the no-keys demo runs the full ecosystem and reports COMPLETE
    demo_dir = os.path.join(AGENT_DIR, "tests", "tmp", "demo_run")
    r = subprocess.run([PY, os.path.join(AGENT_DIR, "demo.py"), "--dir", demo_dir],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300,
                       env={**os.environ, "PYTHONUTF8": "1"})
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "DEMO COMPLETE" in r.stdout, r.stdout[-2000:]
    assert "MISSING" not in r.stdout, "demo tour reported missing artifacts:\n" + r.stdout
    assert "status:   COMPLETE" in r.stdout, "demo course must reach COMPLETE"
    assert "memory integrity: PASS" in r.stdout
    assert "mechanical spec checks: PASS" in r.stdout
    print("[demo] python demo.py: full lifecycle, COMPLETE course, both proofs PASS, no keys")
    print("PASS test_local")


if __name__ == "__main__":
    main()
