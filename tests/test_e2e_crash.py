#!/usr/bin/env python3
"""The hardest reliability claim: kill -9 in the MIDDLE of the full lifecycle,
restart, and the course must still reach the exact same COMPLETE end state —
same task roles, same artifacts, memory still certified.

Same scripted roles as test_e2e, with per-step delays so the kill reliably
lands mid-pipeline.

Run from the agent/ directory:  python tests/test_e2e_crash.py
"""

import json
import os
import subprocess
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain, start, wait_for
from test_e2e import (C, CHAIN, COURSE, EXAMINER, LIBRARIAN, MEMCHECK,
                      PRACTITIONER, REFLECTOR, RIPPER, WATCHER)

PY = sys.executable


def main():
    sb = make_sandbox(
        "e2e_crash",
        providers={r: {"script": f"scripts/{r}.json", "delay_seconds": 0.3}
                   for r in ("ripper", "watcher", "practitioner",
                             "examiner", "librarian", "reflector")},
        roles={r: r for r in ("ripper", "watcher", "practitioner",
                              "examiner", "librarian", "reflector")},
        scripts={"scripts/ripper.json": RIPPER, "scripts/watcher.json": WATCHER,
                 "scripts/practitioner.json": PRACTITIONER,
                 "scripts/examiner.json": EXAMINER,
                 "scripts/librarian.json": LIBRARIAN,
                 "scripts/reflector.json": REFLECTOR},
        reflect_after='"practitioner"',
        extra=CHAIN,
    )
    os.makedirs(os.path.join(sb, "inbox"))
    with open(os.path.join(sb, "inbox", "backoff course.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 dummy")
    r = subprocess.run([PY, os.path.join(AGENT_DIR, "ingest.py"),
                        "scan-inbox", "--root", sb, "--course", COURSE],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr

    # phase 1: run until the Watcher is mid-study, then kill -9
    proc = start(sb)
    try:
        wait_for(lambda: os.path.exists(os.path.join(sb, C, "lessons", "01", "notes.md")),
                 60, "watcher to be mid-study (notes.md)")
    finally:
        proc.kill()
        proc.wait()
    tasks = read_state(sb)["tasks"]
    assert len(tasks) < 7 or any(t["status"] != "done" for t in tasks), \
        "the kill must land mid-pipeline — raise the mock delay"
    print(f"[phase 1] killed mid-pipeline at {len(tasks)} task(s), "
          f"statuses={[t['status'] for t in tasks]}")

    # phase 2: restart; the pipeline must finish identically to test_e2e
    assert run_drain(sb, timeout=180) == 0
    tasks = read_state(sb)["tasks"]
    roles = [t["role"] for t in tasks]
    assert all(t["status"] == "done" for t in tasks), \
        [(t["role"], t["status"], t.get("error")) for t in tasks]
    for role, count in (("ripper", 1), ("watcher", 1), ("practitioner", 1),
                        ("reflector", 1), ("librarian", 1), ("examiner", 2)):
        assert roles.count(role) == count, f"{role}: {roles.count(role)} != {count} in {roles}"

    sys.path.insert(0, AGENT_DIR)
    import loop
    assert loop.Agent(sb).course_status(COURSE)["complete"]
    with open(os.path.join(sb, C, "exam", "schedule.json"), "r", encoding="utf-8") as f:
        assert [e["done"] for e in json.load(f)["entries"]] == [True]
    r = subprocess.run([PY, MEMCHECK, COURSE, "--root", sb],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"memory must still be certified after the crash:\n{r.stdout}"
    print("[phase 2] restarted: same 7 tasks, course COMPLETE, re-exam ran, memcheck certified")
    print("[crash] kill -9 in the MIDDLE of the lifecycle changed nothing about the end state: same tasks, course complete, memcheck certified")
    print("PASS test_e2e_crash: kill -9 mid-lifecycle changed nothing about the end state")


if __name__ == "__main__":
    main()
