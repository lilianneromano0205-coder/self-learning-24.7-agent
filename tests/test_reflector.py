#!/usr/bin/env python3
"""Reflection chain (Part 9 mechanism 2).

When a role listed in reflect_after finishes a task, a reflector task is
auto-queued on the same course and completes; the reflector itself never
triggers another reflection (no infinite chain).

Run from the agent/ directory:  python tests/test_reflector.py
"""

from common import add_task, make_sandbox, read_state, run_drain

WORK = [
    {"tool": "write_file", "args": {"path": "out/work.txt", "content": "done"}},
    {"tool": "finish_task", "args": {"summary": "work complete"}},
]
REFLECT = [
    {"tool": "write_file", "args": {"path": "lessons-learned.md", "content": "- reflected\n"}},
    {"tool": "finish_task", "args": {"summary": "reflection recorded"}},
]


def main():
    sb = make_sandbox(
        "reflector",
        providers={
            "mockw": {"script": "scripts/work.json"},
            "mockr": {"script": "scripts/reflect.json"},
        },
        roles={"tester": "mockw", "reflector": "mockr"},
        scripts={"scripts/work.json": WORK, "scripts/reflect.json": REFLECT},
        reflect_after='"tester"',
    )
    add_task(sb, "tester", "do some work", course="c1")
    rc = run_drain(sb)
    assert rc == 0

    tasks = read_state(sb)["tasks"]
    roles = [t["role"] for t in tasks]
    assert roles == ["tester", "reflector"], f"expected exactly one reflection, got {roles}"
    assert all(t["status"] == "done" for t in tasks), [(t["role"], t["status"]) for t in tasks]
    assert tasks[1].get("course") == "c1", "reflection must inherit the course"
    print("[reflection] exactly one Reflector task followed the work, it completed, and it did not chain further")
    print("PASS test_reflector: one reflection queued after the work task, completed, no chain")


if __name__ == "__main__":
    main()
