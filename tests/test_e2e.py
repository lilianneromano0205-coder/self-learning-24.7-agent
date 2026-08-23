#!/usr/bin/env python3
"""End-to-end lifecycle: the whole choreography, no human in the middle.

inbox drop -> scan-inbox queues Ripper -> chain queues Watcher (cited notes,
spec with a real CHECK, index line, one tagged gap) -> chain queues
Practitioner (artifact) -> reflection queues Reflector (skill playbook) ->
chain queues Examiner (writes grades + SCORE, runs verify.py for ground
truth) -> the gap tick queues the Librarian (resolves the gap, records the
retraction) -> exit criterion turns COMPLETE -> the re-exam scheduler queues
one spaced re-exam -> queue drains. Then memcheck must certify the memory.

Models are scripted mocks; everything else — the loop, chaining, locks,
verify.py, memcheck.py, state — is the real code.

Run from the agent/ directory:  python tests/test_e2e.py
"""

import json
import os
import subprocess
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import loop

PY = sys.executable
VERIFY = os.path.join(AGENT_DIR, "verify.py")
MEMCHECK = os.path.join(AGENT_DIR, "memcheck.py")
COURSE = "backoff-course"
C = f"courses/{COURSE}"

NOTES = """# L01 — Backoff
SOURCE: transcript.txt (lang: en)
## Concepts
- C-0101 Exponential backoff doubles the delay per retry [src: transcript 00:00:01]
## Claims & procedures
- P-0102 Maximum of five attempts [src: transcript 00:00:01]
## Contradicts
(none)
## Unclear
(none)
"""

SPEC = (f'R-001 [from C-0101,P-0102]: notes for lesson 01 exist on disk '
        f'CHECK: "{PY}" -c "import os,sys; '
        f"sys.exit(0 if os.path.exists('{C}/lessons/01/notes.md') else 1)\"\n")

RIPPER = [
    {"tool": "write_file", "args": {"path": f"{C}/lessons/01/transcript.txt",
                                    "content": "[00:00:01] Backoff base is 2, max five attempts."}},
    {"tool": "finish_task", "args": {"summary": "ingested lesson 01"}},
]
WATCHER = [
    {"tool": "write_file", "args": {"path": f"{C}/lessons/01/notes.md", "content": NOTES}},
    {"tool": "write_file", "args": {"path": f"{C}/spec.md", "content": SPEC}},
    {"tool": "write_file", "args": {"path": f"{C}/index.md",
                                    "content": "01 | backoff basics | R-001 |\n"}},
    {"tool": "write_file", "args": {"path": f"{C}/gaps.md",
                                    "content": "- G-001 (librarian) planted contradiction to exercise the gap loop\n"}},
    {"tool": "finish_task", "args": {"summary": "studied lesson 01"}},
]
PRACTITIONER = [
    {"tool": "write_file", "args": {"path": f"{C}/artifacts/ex1/MANIFEST.md",
                                    "content": "satisfies R-001\n"}},
    {"tool": "finish_task", "args": {"summary": "executed exercise 1"}},
]
EXAMINER = [
    {"tool": "write_file", "args": {"path": f"{C}/exam-results.md",
                                    "content": "R-001: PASS — artifact verified\nSCORE: 95\n"}},
    {"tool": "run_command", "args": {"cmd": f'"{PY}" "{VERIFY}" {COURSE} --root .'}},
    {"tool": "finish_task", "args": {"summary": "graded against spec"}},
]
LIBRARIAN = [
    {"tool": "write_file", "args": {"path": f"{C}/retractions.md",
                                    "content": "- G-001 retracted: planted contradiction resolved against transcript [src: transcript 00:00:01]\n"}},
    {"tool": "write_file", "args": {"path": f"{C}/gaps.md", "content": ""}},
    {"tool": "finish_task", "args": {"summary": "gap resolved, retraction recorded"}},
]
REFLECTOR = [
    {"tool": "write_file", "args": {"path": "skills/backoff-exercise.md",
                                    "content": "KEYWORDS: backoff, retry\npitfall: off-by-one on attempt count\n"}},
    {"tool": "write_file", "args": {"path": f"{C}/lessons-learned.md",
                                    "content": "- exercise 1 needed one retry\n"}},
    {"tool": "finish_task", "args": {"summary": "reflection recorded"}},
]

CHAIN = """[agent.chain]
ripper = "watcher"
watcher = "practitioner"
practitioner = "examiner"
"""


def main():
    sb = make_sandbox(
        "e2e",
        providers={r: {"script": f"scripts/{r}.json"}
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
    # the only human action in the whole lifecycle: drop a file in the inbox
    os.makedirs(os.path.join(sb, "inbox"))
    with open(os.path.join(sb, "inbox", "backoff course.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 dummy")
    r = subprocess.run([PY, os.path.join(AGENT_DIR, "ingest.py"),
                        "scan-inbox", "--root", sb, "--course", COURSE],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "queued ripper task" in r.stdout, r.stdout + r.stderr

    assert run_drain(sb, timeout=120) == 0

    tasks = read_state(sb)["tasks"]
    roles = [t["role"] for t in tasks]
    assert all(t["status"] == "done" for t in tasks), \
        [(t["role"], t["status"], t.get("error")) for t in tasks]
    for role, count in (("ripper", 1), ("watcher", 1), ("practitioner", 1),
                        ("reflector", 1), ("librarian", 1), ("examiner", 2)):
        assert roles.count(role) == count, f"{role}: expected {count}, got {roles.count(role)} in {roles}"
    print(f"[pipeline] 7 tasks, all done, zero human interventions: {roles}")

    # every artifact of the lifecycle exists
    for rel in (f"{C}/lessons/01/transcript.txt", f"{C}/lessons/01/notes.md",
                f"{C}/spec.md", f"{C}/index.md", f"{C}/exam-results.md",
                f"{C}/retractions.md", f"{C}/artifacts/ex1/MANIFEST.md",
                f"{C}/lessons-learned.md", "skills/backoff-exercise.md",
                f"{C}/exam/schedule.json"):
        assert os.path.exists(os.path.join(sb, rel)), f"missing {rel}"

    # ground truth ran: verify.py's mechanical section is in the results
    with open(os.path.join(sb, C, "exam-results.md"), "r", encoding="utf-8") as f:
        results = f.read()
    assert "## Mechanical checks" in results and "R-001: PASS" in results

    # exit criterion reached, exactly one spaced re-exam queued and done
    a = loop.Agent(sb)
    st = a.course_status(COURSE)
    assert st["complete"], st
    with open(os.path.join(sb, C, "exam", "schedule.json"), "r", encoding="utf-8") as f:
        sched = json.load(f)
    assert [e["done"] for e in sched["entries"]] == [True]
    print("[verification] mechanical PASS from verify.py, course COMPLETE, re-exam ran")

    # the memory the run produced must survive its own integrity checker
    r = subprocess.run([PY, MEMCHECK, COURSE, "--root", sb],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"memcheck must certify the produced memory:\n{r.stdout}"
    print("[memory] memcheck certifies: IDs unique, citations resolve, spec grounded, index complete")
    print("PASS test_e2e: inbox drop -> COMPLETE course, end to end, unattended")


if __name__ == "__main__":
    main()
