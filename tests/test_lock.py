#!/usr/bin/env python3
"""Single-writer course lock (Part 5 B7) and the shared lock primitive.

1. Unit: a queued task is skipped while another live task holds the course
   lock; leftover locks from a dead/finished owner, an unknown owner, or an
   owner whose lock file is simply OLD are each broken and logged.
2. Integration: two tasks on the same course serialize, both complete, and
   no .lock file remains.
3. Hammer: threads contending on locks.holding lose NOTHING — on Windows,
   creating the lockfile while a releasing holder's delete is still pending
   reports EACCES (PermissionError), and before that was treated as
   contention it killed a whole writer thread: CI's swarm ledger hammer
   lost 25 of 100 rows to one such window.

Run from the agent/ directory:  python tests/test_lock.py
"""

import os
import sys
import threading
import time

from common import AGENT_DIR, add_task, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import locks
import loop

SCRIPT = [
    {"tool": "write_file", "args": {"path": "out/{id}.txt", "content": "x"}},
    {"tool": "finish_task", "args": {"summary": "ok"}},
]


def main():
    sb = make_sandbox(
        "lock",
        providers={"mockq": {"script": "scripts/quick.json"}},
        roles={"tester": "mockq"},
        scripts={"scripts/quick.json": [
            {"tool": "write_file", "args": {"path": "out/mark.txt", "content": "x"}},
            {"tool": "finish_task", "args": {"summary": "ok"}},
        ]},
    )
    a = loop.Agent(sb)

    # --- unit: lock held by a live running task blocks; dead owner is broken
    t_running = {"id": "owner001", "role": "tester", "status": "running", "course": "c1"}
    t_queued = {"id": "waiter001", "role": "tester", "status": "queued", "course": "c1"}
    state = {"tasks": [t_running, t_queued]}
    a.acquire_lock(t_running)
    assert not a.can_lock(state, t_queued), "queued task must be blocked by a live lock"
    assert a.next_task(state) is t_running, "running task is always resumed first"

    # owner finished but crashed before releasing -> lock must be broken
    t_running["status"] = "done"
    assert a.can_lock(state, t_queued), "leftover lock from finished owner must break"
    assert not os.path.exists(a.lock_path("c1")), "broken lock must be deleted"

    # unknown owner (state lost the task) -> also broken
    with open(a.lock_path("c1"), "w", encoding="utf-8") as f:
        f.write("ghost0000000")
    assert a.can_lock(state, t_queued), "lock from unknown owner must break"

    # owner still 'running' but the lock FILE is old (crashed machine, clock
    # moved on) -> the age branch breaks it
    with open(a.lock_path("c1"), "w", encoding="utf-8") as f:
        f.write("owner001")
    t_running["status"] = "running"
    stale = time.time() - (a.lock_stale_minutes + 5) * 60
    os.utime(a.lock_path("c1"), (stale, stale))
    assert a.can_lock(state, t_queued), "an old lock must break even mid-'running'"
    assert not os.path.exists(a.lock_path("c1")), "stale lock must be deleted"
    print("[unit] live lock blocks; dead/unknown/stale owner locks are broken")

    # --- integration: two tasks, same course, both complete, lock cleaned up
    add_task(sb, "tester", "first writer", course="c1")
    add_task(sb, "tester", "second writer", course="c1")
    rc = run_drain(sb)
    assert rc == 0
    tasks = [t for t in read_state(sb)["tasks"] if t.get("course") == "c1"]
    assert len(tasks) == 2 and all(t["status"] == "done" for t in tasks), \
        [t["status"] for t in tasks]
    assert not os.path.exists(a.lock_path("c1")), ".lock must be released after finish"
    print("[integration] two same-course tasks serialized, both done, lock released")

    # --- hammer: rapid acquire/release across threads loses no writer.
    # Short critical sections maximise the create-vs-delete window that
    # produces delete-pending EACCES on Windows; before PermissionError was
    # retried as contention, this reproduced a dead thread 2 runs in 3.
    target = os.path.join(sb, "hammer.jsonl")
    open(target, "w").close()
    n_threads, n_each, failures = 12, 40, []

    def hammer(i):
        try:
            for k in range(n_each):
                with locks.holding(target, timeout=20.0, stale=8.0):
                    with open(target, "a", encoding="utf-8") as f:
                        f.write(f"{i}:{k}\n")
        except Exception as e:              # noqa: BLE001 — any death counts
            failures.append(f"thread {i}: {type(e).__name__}: {e}")

    threads = [threading.Thread(target=hammer, args=(i,))
               for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not failures, (
        "a writer died inside the lock primitive — on Windows this is the "
        "delete-pending EACCES race, and a dead writer is silently lost "
        f"ledger rows: {failures}")
    rows = sum(1 for _ in open(target, encoding="utf-8"))
    assert rows == n_threads * n_each, (
        f"{n_threads * n_each} writes were made and the file holds {rows}")
    print(f"[hammer] {n_threads} threads x {n_each} acquisitions: every "
          f"writer survived and all {rows} rows landed — EACCES during "
          f"lockfile creation is retried as the contention it is")
    print("PASS test_lock")


if __name__ == "__main__":
    main()
