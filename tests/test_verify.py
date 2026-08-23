#!/usr/bin/env python3
"""Mechanical spec verification (Part 8 layer 1).

An impossible CHECK must come back FAIL with evidence — never a polite PASS —
a satisfiable CHECK must PASS, and an item with no CHECK is left for the
Examiner. Re-running must replace the previous results section, not stack.

Run from the agent/ directory:  python tests/test_verify.py
"""

import os
import re
import subprocess
import sys

from common import AGENT_DIR, make_sandbox

VERIFY = os.path.join(AGENT_DIR, "verify.py")
PY = sys.executable

SPEC = f"""\
R-001 [from C-0001]: a passing mechanical item CHECK: "{PY}" -c "import sys; sys.exit(0)"
R-002: an impossible item CHECK: "{PY}" -c "import sys; print('requirement violated'); sys.exit(1)"
R-003 [from P-0002]: a judgment item with no mechanical check
"""


def run_verify(sb):
    return subprocess.run([PY, VERIFY, "vc", "--root", sb],
                          capture_output=True, text=True, timeout=60)


def main():
    sb = make_sandbox("verify", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    cdir = os.path.join(sb, "courses", "vc")
    os.makedirs(cdir)
    with open(os.path.join(cdir, "spec.md"), "w", encoding="utf-8") as f:
        f.write(SPEC)

    r = run_verify(sb)
    assert r.returncode == 1, f"a failing check must exit 1, got {r.returncode}\n{r.stdout}{r.stderr}"
    with open(os.path.join(cdir, "exam-results.md"), "r", encoding="utf-8") as f:
        results = f.read()
    assert re.search(r"R-001: PASS", results), results
    assert re.search(r"R-002: FAIL — .*requirement violated", results), \
        "FAIL must carry evidence from the command output:\n" + results
    assert re.search(r"R-003: NOT MECHANICAL", results), results
    print("[round 1] PASS/FAIL/NOT MECHANICAL all graded correctly, evidence captured")

    # fix the impossible item; the results section must be replaced, not stacked
    with open(os.path.join(cdir, "spec.md"), "w", encoding="utf-8") as f:
        f.write(SPEC.replace("sys.exit(1)", "sys.exit(0)").replace("an impossible", "a fixed"))
    r = run_verify(sb)
    assert r.returncode == 0, f"all-pass must exit 0\n{r.stdout}{r.stderr}"
    with open(os.path.join(cdir, "exam-results.md"), "r", encoding="utf-8") as f:
        results = f.read()
    assert results.count("## Mechanical checks") == 1, "section must be replaced, not duplicated"
    assert re.search(r"R-002: PASS", results) and not re.search(r"R-002: FAIL", results)
    print("[round 2] re-run replaced the section; fixed item now PASS, exit 0")
    print("[verify] spec CHECK commands ran mechanically: a failing item failed the gate, and a re-run replaced the results section in place")
    print("PASS test_verify")


if __name__ == "__main__":
    main()
