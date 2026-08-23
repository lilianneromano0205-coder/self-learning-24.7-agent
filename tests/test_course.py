#!/usr/bin/env python3
"""Exit criterion + spaced re-exams (Part 8).

course_status must say COMPLETE only when all spec items PASS, gaps.md is
empty, and the exam score meets the threshold. On completion the idle loop
schedules re-exams; a due entry queues exactly one Examiner task and never
re-queues.

Run from the agent/ directory:  python tests/test_course.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import loop

REEXAM = [{"tool": "finish_task", "args": {"summary": "re-exam done"}}]


def write(sb, rel, content):
    p = os.path.join(sb, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    sb = make_sandbox("course", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m", "examiner": "m"},
                      scripts={"s.json": REEXAM})
    a = loop.Agent(sb)
    c = "courses/mycourse"

    # incomplete in every dimension, then fixed one dimension at a time
    write(sb, f"{c}/spec.md", "R-001: first item\nR-002: second item\n")
    st = a.course_status("mycourse")
    assert not st["complete"] and st["spec_total"] == 2 and st["spec_pass"] == 0

    write(sb, f"{c}/exam-results.md",
          "R-001: PASS — evidence\nR-002: FAIL — missing\nSCORE: 95\n")
    assert not a.course_status("mycourse")["complete"], "a FAIL item must block completion"

    write(sb, f"{c}/exam-results.md",
          "R-001: PASS — evidence\nR-002: FAIL\nR-002: PASS — fixed on retry\nSCORE: 85\n")
    st = a.course_status("mycourse")
    assert st["spec_pass"] == 2, "the LAST verdict per item must win"
    assert not st["complete"], "score below threshold must block completion"

    write(sb, f"{c}/gaps.md", "- G-001 lesson 2 contradiction unresolved\n")
    write(sb, f"{c}/exam-results.md",
          "R-001: PASS — evidence\nR-002: PASS — fixed\nSCORE: 95\n")
    assert not a.course_status("mycourse")["complete"], "open gaps must block completion"

    write(sb, f"{c}/gaps.md", "")
    st = a.course_status("mycourse")
    assert st["complete"], st
    print("[exit criterion] every dimension blocks alone; all satisfied -> COMPLETE")

    # idle loop: schedules re-exams (due day 0 in test config), queues exactly one
    assert run_drain(sb) == 0
    sched_path = os.path.join(sb, c, "exam", "schedule.json")
    with open(sched_path, "r", encoding="utf-8") as f:
        sched = json.load(f)
    assert len(sched["entries"]) == 1 and sched["entries"][0]["done"]
    tasks = read_state(sb)["tasks"]
    reexams = [t for t in tasks if t["role"] == "examiner"]
    assert len(reexams) == 1 and reexams[0]["status"] == "done", reexams
    assert sched["entries"][0]["task"] == reexams[0]["id"]

    # a second drain must not re-queue anything
    assert run_drain(sb) == 0
    assert len([t for t in read_state(sb)["tasks"] if t["role"] == "examiner"]) == 1, \
        "a done schedule entry must never re-queue"
    print("[re-exam] scheduled on completion, queued once, ran, never re-queued")
    print("PASS test_course")


if __name__ == "__main__":
    main()
