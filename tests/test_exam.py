#!/usr/bin/env python3
"""Hidden exams as machinery (Part 8 layer 3).

A question file in exam/pending/ dispatches a closed-book Student whose
context contains the mission, the index, and the questions — and provably NOT
the notes, in ANY message. Closed book is enforced at the TOOL level too: the
scripted Student tries to read the notes mid-exam and is mechanically refused
(the production allowlist has no read access for the role). The sat exam
chains straight into Examiner grading. An exam is dispatched exactly once per
question-file CONTENT: replacing the file with new questions dispatches a
fresh sitting; identical content never re-dispatches.

Run from the agent/ directory:  python tests/test_exam.py
"""

import hashlib
import json
import os

from common import make_sandbox, read_state, run_drain

C = "courses/exam-course"
SECRET = "the hidden constant is 42"

# the scripted student CHEATS first — that attempt must be refused by the
# tool allowlist, and the exam continues from the refusal
STUDENT = [
    {"tool": "read_file", "args": {"path": f"{C}/lessons/01/notes.md"}},
    {"tool": "write_file", "args": {"path": f"{C}/exam/answers/exam-1.md",
                                    "content": "A1: base is 2 [C-0101]\nA2: CANNOT ANSWER\n"}},
    {"tool": "finish_task", "args": {"summary": "exam sat closed-book"}},
]
EXAMINER = [
    {"tool": "write_file", "args": {"path": f"{C}/exam-results.md",
                                    "content": "exam-1: 1/2 correct\nSCORE: 50\n"}},
    {"tool": "finish_task", "args": {"summary": "exam graded"}},
]


def write(sb, rel, content):
    p = os.path.join(sb, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


def digest_of(sb, rel):
    """The exact bytes on disk (line endings included), as the loop hashes them."""
    with open(os.path.join(sb, rel), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def main():
    sb = make_sandbox(
        "exam",
        providers={"mocks": {"script": "scripts/student.json"},
                   "mocke": {"script": "scripts/examiner.json"}},
        roles={"student": "mocks", "examiner": "mocke"},
        scripts={"scripts/student.json": STUDENT, "scripts/examiner.json": EXAMINER},
        extra='[agent.chain]\nstudent = "examiner"\n',
        role_tools={"student": ["write_file"]},  # the production allowlist
    )
    write(sb, f"{C}/mission.md", "Learn backoff deeply.")
    write(sb, f"{C}/index.md", "01 | backoff basics: base and attempt limits | R-001 |\n")
    write(sb, f"{C}/lessons/01/notes.md",
          f"# L01\n- C-0101 backoff base is 2, and {SECRET} [src: transcript 00:01]\n")
    write(sb, f"{C}/exam/pending/exam-1.md",
          "Q1: what is the backoff base?\nQ2: what is the hidden constant?\n")

    assert run_drain(sb) == 0

    tasks = read_state(sb)["tasks"]
    roles = [t["role"] for t in tasks]
    assert roles == ["student", "examiner"], roles
    assert all(t["status"] == "done" for t in tasks)
    assert os.path.exists(os.path.join(sb, C, "exam", "answers", "exam-1.md"))

    # the closed-book guarantee, across the WHOLE context: index and questions
    # present, notes absent from every message, and the cheat attempt refused
    with open(os.path.join(sb, tasks[0]["context_ref"]), "r", encoding="utf-8") as f:
        ctx = json.load(f)
    whole = json.dumps(ctx, ensure_ascii=False)
    first_user = next(m["content"] for m in ctx if m["role"] == "user")
    assert "backoff basics" in first_user, "index.md must be in the student context"
    assert "hidden constant?" in first_user, "the questions must be in the student context"
    assert SECRET not in whole, \
        "CLOSED-BOOK VIOLATION: notes content leaked into the student context"
    denials = [m for m in ctx if m.get("role") == "tool"
               and "not permitted" in (m.get("content") or "")]
    assert denials, "the Student's attempt to read the notes must be refused by the tools"
    print("[closed-book] notes absent from every message; the Student's read-the-notes "
          "cheat was mechanically refused; mission+index+questions present")

    # dispatch exactly once per content: a second drain must not re-sit the exam
    assert run_drain(sb) == 0
    assert len(read_state(sb)["tasks"]) == 2, "identical exam content must dispatch once"
    with open(os.path.join(sb, C, "exam", "exam-state.json"), "r", encoding="utf-8") as f:
        est = json.load(f)["dispatched"]
    assert est == {"exam-1.md": digest_of(sb, f"{C}/exam/pending/exam-1.md")}, est
    print("[dispatch] identical question file never re-dispatched (tracked by content hash)")

    # REPLACED questions under the same filename = a new exam: one fresh sitting
    write(sb, f"{C}/exam/pending/exam-1.md",
          "Q1: what is the backoff base?\nQ2: what is the give-up threshold?\n")
    assert run_drain(sb) == 0
    tasks = read_state(sb)["tasks"]
    assert [t["role"] for t in tasks] == ["student", "examiner"] * 2, \
        [t["role"] for t in tasks]
    assert all(t["status"] == "done" for t in tasks)
    digest2 = digest_of(sb, f"{C}/exam/pending/exam-1.md")
    with open(os.path.join(sb, C, "exam", "exam-state.json"), "r", encoding="utf-8") as f:
        assert json.load(f)["dispatched"] == {"exam-1.md": digest2}
    assert run_drain(sb) == 0 and len(read_state(sb)["tasks"]) == 4, \
        "the replaced exam must be sat exactly once too"
    print("[re-dispatch] replaced question file -> exactly one fresh sitting + grading")
    check_a_failed_exam_is_not_recorded_as_sat()
    print("PASS test_exam: closed-book by context AND by tools; dispatch once per content")


def check_a_failed_exam_is_not_recorded_as_sat():
    """DISPATCHED IS NOT SAT — the same defect the spaced re-exam scheduler
    carried, in its sibling function.

    `est["dispatched"][fn] = digest` was written on the same beat as
    add_task, so a Student task that died terminally — provider outage,
    retries exhausted, a loop killed between the two — left the exam recorded
    as dispatched with a matching content hash, and the tick skipped it
    forever. An exam nobody sat is not an exam that was skipped once; it is a
    course that quietly stopped being examined, while the panel and the
    self-model keep reading the last score as current.

    Here the Student's provider fails every attempt. The exam must be
    re-dispatched, bounded, and then recorded as failed rather than as sat.
    """
    import sys
    from common import AGENT_DIR, agent_setting
    sys.path.insert(0, AGENT_DIR)
    import loop

    BAD = [{"tool": "read_file", "args": {"path": "../escape.txt"}}] * 8
    sb = make_sandbox("exam_failure",
                      providers={"m": {"script": "s.json"},
                                 "bad": {"script": "bad.json"}},
                      roles={"student": "bad", "examiner": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}],
                               "bad.json": BAD})
    agent_setting(sb, "max_steps = 2")
    agent_setting(sb, "max_task_retries = 0")
    c = "courses/hydro"
    pend = os.path.join(sb, c, "exam", "pending")
    os.makedirs(pend, exist_ok=True)
    with open(os.path.join(pend, "q1.md"), "w", encoding="utf-8") as f:
        f.write("1. What is the exit criterion?\n")

    state_path = os.path.join(sb, c, "exam", "exam-state.json")
    trail = []
    for _ in range(loop.REEXAM_MAX_ATTEMPTS + 2):
        run_drain(sb)
        with open(state_path, encoding="utf-8") as f:
            est = json.load(f)
        rec = (est.get("tasks") or {}).get("q1.md") or {}
        trail.append((bool(est.get("dispatched", {}).get("q1.md")),
                      rec.get("attempts"), rec.get("outcome")))
        if rec.get("outcome"):
            break

    students = [t for t in read_state(sb)["tasks"] if t["role"] == "student"]
    assert students and all(t["status"] == "failed" for t in students), \
        [t["status"] for t in students]
    assert len(students) == loop.REEXAM_MAX_ATTEMPTS, (
        f"a Student task that died left the exam recorded as sat: "
        f"{len(students)} attempt(s) for {loop.REEXAM_MAX_ATTEMPTS} allowed "
        f"— trail {trail}")
    assert rec.get("outcome") == "failed", rec
    print(f"[exam failure] {loop.REEXAM_MAX_ATTEMPTS} Student tasks died and "
          f"the exam was re-dispatched each time, then closed as "
          f"outcome='failed' — recorded as UNEXAMINED rather than sat")


if __name__ == "__main__":
    main()
