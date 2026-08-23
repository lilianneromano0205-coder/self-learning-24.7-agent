#!/usr/bin/env python3
"""Memory integrity (memcheck.py).

A course seeded with every violation type — duplicate atom ID, citation to a
nonexistent file, spec item citing an undefined atom, lesson missing from the
index — must fail with each violation named. The repaired course must pass.

Run from the agent/ directory:  python tests/test_memcheck.py
"""

import os
import subprocess
import sys

from common import AGENT_DIR, make_sandbox

MEMCHECK = os.path.join(AGENT_DIR, "memcheck.py")
PY = sys.executable


def write(sb, rel, content):
    p = os.path.join(sb, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


def run_memcheck(sb):
    return subprocess.run([PY, MEMCHECK, "mc", "--root", sb],
                          capture_output=True, text=True, timeout=60)


def main():
    sb = make_sandbox("memcheck", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    c = "courses/mc"

    # a broken course: 4 distinct violation types
    write(sb, f"{c}/lessons/01/transcript.txt", "[00:01] backoff doubles the wait")
    write(sb, f"{c}/lessons/01/notes.md",
          "# L01\n## Concepts\n- C-0101 backoff doubles wait [src: transcript 00:01]\n"
          "- P-0102 ghost claim [src: whiteboard 00:05]\n")     # broken citation
    write(sb, f"{c}/lessons/02/notes.md",
          "# L02\n## Concepts\n- C-0101 duplicate atom [src: transcript 00:01]\n")  # dup + lesson 02 has no transcript of its own but cites lesson-relative...
    write(sb, f"{c}/spec.md",
          "R-001 [from C-0101]: fine\nR-002 [from C-9999]: cites a ghost atom\n")
    write(sb, f"{c}/index.md", "01 | backoff | R-001 |\n")       # lesson 02 missing

    r = run_memcheck(sb)
    assert r.returncode == 1, f"broken memory must fail\n{r.stdout}"
    for expected in ("DUPLICATE ID: C-0101", "BROKEN CITATION", "whiteboard",
                     "UNGROUNDED SPEC: R-002", "C-9999", "INDEX GAP: lesson 02"):
        assert expected in r.stdout, f"missing violation '{expected}' in:\n{r.stdout}"
    print("[broken] all 4 violation types detected and named")

    # repair everything
    write(sb, f"{c}/lessons/01/notes.md",
          "# L01\n## Concepts\n- C-0101 backoff doubles wait [src: transcript 00:01]\n"
          "- P-0102 real claim [src: transcript 00:01]\n")
    write(sb, f"{c}/lessons/02/notes.md",
          "# L02\n## Concepts\n- C-0201 own atom [src: ../01/transcript.txt 00:01]\n")
    write(sb, f"{c}/spec.md",
          "R-001 [from C-0101]: fine\nR-002 [from C-0201,P-0102]: also fine\n")
    write(sb, f"{c}/index.md", "01 | backoff | R-001 |\n02 | more | R-002 |\n")

    r = run_memcheck(sb)
    assert r.returncode == 0, f"repaired memory must pass\n{r.stdout}"
    assert "internally sound" in r.stdout
    print("[repaired] memory passes: IDs unique, citations resolve, spec grounded, index complete")
    print("PASS test_memcheck")


if __name__ == "__main__":
    main()
