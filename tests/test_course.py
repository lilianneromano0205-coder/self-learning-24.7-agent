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

from common import (AGENT_DIR, agent_setting, make_sandbox, read_state,
                    run_drain)

sys.path.insert(0, AGENT_DIR)
import loop

REEXAM = [{"tool": "finish_task", "args": {"summary": "re-exam done"}}]
# an Examiner that cannot finish: every step is a path the File Authority
# refuses, and there are more of them than the step ceiling below, so the task
# never reaches the mock's script-exhausted finish_task and ends `failed`
BAD_EXAMINER = [{"tool": "read_file", "args": {"path": "../escape.txt"}}] * 8


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

    check_a_failed_reexam_is_not_recorded_as_taken()
    print("PASS test_course")


def check_a_failed_reexam_is_not_recorded_as_taken():
    """`done` must mean the re-examination HAPPENED, not that one was ordered.

    The flag used to be set on the same line that created the task, so
    scheduled -> queued -> permanently done was reached whether the
    examination succeeded, failed, or never ran at all. The test above cannot
    see that: its mock always finishes, so schedule.json comes out identical
    in the success case and in the total-failure case — an assertion that
    cannot discriminate.

    Here the Examiner's provider is scripted so every attempt fails. The entry
    must stay open and re-queue, and after REEXAM_MAX_ATTEMPTS it must close
    as outcome='failed' — recorded as UNEXAMINED, which is a different and
    more honest thing than recorded as passed.
    """
    sb = make_sandbox("course_reexam_fail",
                      providers={"m": {"script": "s.json"},
                                 "bad": {"script": "bad.json"}},
                      roles={"tester": "m", "examiner": "bad"},
                      scripts={"s.json": REEXAM, "bad.json": BAD_EXAMINER})
    # a short ceiling so the failing Examiner reaches `failed` quickly, and no
    # harness retries so every Examiner task in state.json is one re-exam
    # ATTEMPT rather than a retry of one
    agent_setting(sb, "max_steps = 2")
    agent_setting(sb, "max_task_retries = 0")
    a = loop.Agent(sb)
    c = "courses/mycourse"
    write(sb, f"{c}/spec.md", "R-001: only item\n")
    write(sb, f"{c}/exam-results.md", "R-001: PASS - evidence\nSCORE: 95\n")
    write(sb, f"{c}/gaps.md", "")
    assert a.course_status("mycourse")["complete"]

    sched_path = os.path.join(sb, c, "exam", "schedule.json")
    trail = []
    for _round in range(loop.REEXAM_MAX_ATTEMPTS + 2):
        run_drain(sb)
        with open(sched_path, "r", encoding="utf-8") as f:
            entry = json.load(f)["entries"][0]
        trail.append((entry["done"], entry.get("attempts"),
                      entry.get("outcome")))
        if entry["done"]:
            break

    exams = [t for t in read_state(sb)["tasks"] if t["role"] == "examiner"]
    assert exams and all(t["status"] == "failed" for t in exams), \
        [t["status"] for t in exams]
    assert len(exams) == loop.REEXAM_MAX_ATTEMPTS, (
        f"a failed re-exam must be RETRIED, not filed as taken: "
        f"{len(exams)} attempt(s) for {loop.REEXAM_MAX_ATTEMPTS} allowed "
        f"- trail {trail}")
    assert entry["done"] and entry.get("outcome") == "failed", entry
    assert entry.get("attempts") == loop.REEXAM_MAX_ATTEMPTS, entry
    print(f"[re-exam failure] {loop.REEXAM_MAX_ATTEMPTS} failed attempts were "
          f"re-queued, never counted as taken, and the entry closed as "
          f"outcome='failed' rather than silently done")


if __name__ == "__main__":
    main()
