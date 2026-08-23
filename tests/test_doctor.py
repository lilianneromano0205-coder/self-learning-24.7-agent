#!/usr/bin/env python3
"""The platform health check, and creation that never leaves a half-expert.

1. doctor.py inspects a real fleet home: runtime, anatomy, toolbox, every
   expert (settings parse + memcheck over every course), and keys — and its
   exit code is the verdict.
2. It NAMES real damage instead of passing: a broken expert (no settings)
   and a course with corrupted memory both surface as problems.
3. fleet.create rolls back completely if creation fails mid-way — an
   interrupted spin-up never leaves a mind without its settings.

Run from the agent/ directory:  python tests/test_doctor.py
"""

import os
import subprocess
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import fleet

PY = sys.executable
DOCTOR = os.path.join(AGENT_DIR, "doctor.py")


def run_doctor(home):
    r = subprocess.run([PY, DOCTOR, "--home", home], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=300, env={**os.environ, "PYTHONUTF8": "1"})
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    home = make_sandbox("doctor", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})

    # --- a healthy-enough fleet: the doctor reports every section
    root = fleet.create(home, "Sound Mind", "testing")
    os.makedirs(os.path.join(root, "courses", "c1", "lessons", "01"),
                exist_ok=True)
    with open(os.path.join(root, "courses/c1/lessons/01/notes.md"), "w",
              encoding="utf-8") as f:
        f.write("# L01\n- C-0101 a fact [src: transcript 00:01]\n")
    with open(os.path.join(root, "courses/c1/lessons/01/transcript.txt"), "w",
              encoding="utf-8") as f:
        f.write("[00:01] a fact\n")
    with open(os.path.join(root, "courses/c1/index.md"), "w",
              encoding="utf-8") as f:
        f.write("01 | a lesson | R-001 |\n")
    code, out = run_doctor(home)
    for section in ("[1/5] runtime", "[2/5] anatomy", "[3/5] toolbox",
                    "[4/5] fleet", "[5/5] keys"):
        assert section in out, f"missing section {section}\n{out}"
    import doctor
    assert f"all {len(doctor.CORE_MODULES)} core modules import" in out
    assert "[readiness]" in out, "the doctor must say what stands between " \
        "this install and running today"
    assert "sound-mind" in out and "1 course(s) sound" in out, out
    assert "VERDICT" in out
    print("[healthy] all five sections reported; a sound expert reads as sound")

    # --- real damage must be NAMED, not glossed over
    broken = os.path.join(home, "experts", "half-born")
    os.makedirs(os.path.join(broken, "logs"), exist_ok=True)   # no settings.toml
    with open(os.path.join(root, "courses/c1/lessons/01/notes.md"), "a",
              encoding="utf-8") as f:
        f.write("- C-0101 a DUPLICATE id [src: ghost-file 00:09]\n")
    code, out = run_doctor(home)
    assert code == 1, "damage must fail the verdict"
    assert "half-born" in out and "settings broken" in out, out
    assert "memory violations" in out and "c1" in out, out
    print("[damage] half-born expert and corrupted course memory both named, exit 1")

    # --- creation rolls back on failure
    inner = fleet._create_inner
    def boom(home_, dest, *a, **k):
        os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
        raise RuntimeError("simulated failure mid-creation")
    fleet._create_inner = boom
    try:
        try:
            fleet.create(home, "Doomed", "x")
            raise AssertionError("creation must propagate the failure")
        except RuntimeError:
            pass
        assert not os.path.exists(os.path.join(home, "experts", "doomed")), \
            "a failed creation must leave NOTHING behind"
    finally:
        fleet._create_inner = inner
    # and a normal creation still works right after
    ok = fleet.create(home, "After Failure", "x")
    assert os.path.exists(os.path.join(ok, "settings.toml"))
    print("[rollback] interrupted creation leaves nothing; the next one succeeds")

    # --- a fleet home that is NOT the code directory must not raise false
    # alarms about deployment files (found live: it reported agent.service and
    # Dockerfile "missing" for every fleet living elsewhere)
    clean = make_sandbox("doctor_elsewhere", providers={"m": {"script": "s.json"}},
                         roles={"tester": "m"}, scripts={"s.json": []})
    fleet.create(clean, "Only Expert", "x")
    code, out = run_doctor(clean)
    assert "agent.service missing" not in out and "Dockerfile missing" not in out, \
        f"deployment files live with the CODE, not the fleet:\n{out}"
    assert "OK      deploy" in out, out
    problems = [l for l in out.splitlines() if l.strip().startswith("PROBLEM")]
    assert all("keys" in p for p in problems), \
        f"a healthy remote fleet must only lack keys, got: {problems}"
    print("[elsewhere] a fleet home outside the code directory reports cleanly")
    print("PASS test_doctor")


if __name__ == "__main__":
    main()
