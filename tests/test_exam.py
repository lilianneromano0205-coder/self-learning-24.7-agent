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
    print("PASS test_exam: closed-book by context AND by tools; dispatch once per content")


if __name__ == "__main__":
    main()
