#!/usr/bin/env python3
"""ONE COMMAND, AND IT RUNS (M8).

1. an offline bootstrap on an empty folder creates agent.env, the first
   expert and a machine-readable report, and exits 0
2. running it a second time changes nothing and still exits 0 (idempotent)
3. a home whose roles need a real provider, with no key, exits 2 and prints
   the numbered TODO naming the ENV VAR
4. --key NAME=VALUE is written into agent.env and the VALUE IS NEVER PRINTED
   (not on stdout, not in the report)
5. --teach hands the first expert its first material

Run from the agent/ directory:  python tests/test_bootstrap.py
"""

import json
import os
import subprocess
import sys
import tempfile

from common import AGENT_DIR, PY, make_sandbox

BOOT = os.path.join(AGENT_DIR, "bootstrap.py")
SECRET = "sk-do-not-print-me-0123456789"


def run(home, *args, timeout=300):
    r = subprocess.run([PY, BOOT, "--home", home, "--no-panel", *args],
                       capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "PYTHONUTF8": "1"})
    return r


def main():
    # --- 1. offline bootstrap of an empty home
    home = os.path.join(tempfile.gettempdir(), "agent-suite", "bootstrap")
    if os.path.isdir(home):
        import shutil
        shutil.rmtree(home, ignore_errors=True)
    os.makedirs(home, exist_ok=True)
    r = run(home, "--offline", "--expert", "Night Analyst",
            "--identity", "Terse. Cites everything.")
    assert r.returncode == 0, r.stdout + r.stderr
    assert os.path.isfile(os.path.join(home, "agent.env"))
    assert os.path.isdir(os.path.join(home, "experts", "night-analyst"))
    rep = json.load(open(os.path.join(home, "bootstrap.json"), encoding="utf-8"))
    assert rep["ready"] is True and rep["expert"] == "night-analyst"
    steps = [s["step"] for s in rep["steps"]]
    assert steps[0] == "env" and "seed" in steps, steps
    assert steps.index("readiness") < steps.index("expert"), steps
    assert "READY" in r.stdout
    ident = open(os.path.join(home, "experts", "night-analyst", "identity.md"),
                 encoding="utf-8").read()
    assert "Cites everything" in ident
    print("[first-run] one command created the env file, the first expert and "
          "a machine-readable report, and said READY")

    # --- 2. idempotent
    r2 = run(home, "--offline")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    rep2 = json.load(open(os.path.join(home, "bootstrap.json"), encoding="utf-8"))
    assert rep2["expert"] == "night-analyst"
    assert next(s for s in rep2["steps"] if s["step"] == "expert")["created"] is False
    assert next(s for s in rep2["steps"] if s["step"] == "env")["created"] is False
    names = sorted(os.listdir(os.path.join(home, "experts")))
    assert names == ["night-analyst"], names
    print("[idempotent] a second run created nothing, changed nothing, and "
          "still exited 0")

    # --- 4. a key is written but never shown
    r3 = run(home, "--offline", "--key", f"OPENROUTER_API_KEY={SECRET}")
    assert r3.returncode == 0, r3.stdout + r3.stderr
    env_body = open(os.path.join(home, "agent.env"), encoding="utf-8").read()
    assert f"OPENROUTER_API_KEY={SECRET}" in env_body, "the key must be saved"
    assert env_body.count("OPENROUTER_API_KEY=") == 1, "and not duplicated"
    assert SECRET not in r3.stdout and SECRET not in r3.stderr, \
        "THE KEY VALUE MUST NEVER BE PRINTED"
    rep3 = open(os.path.join(home, "bootstrap.json"), encoding="utf-8").read()
    assert SECRET not in rep3, "nor written into the report"
    assert "OPENROUTER_API_KEY" in r3.stdout, "the NAME is fine to show"
    print("[secrets] the key was written into agent.env and never appeared in "
          "the output or the report -- only its name did")

    # --- 3. a real provider with no key blocks, with the fix spelled out
    home2 = os.path.join(tempfile.gettempdir(), "agent-suite", "bootstrap_block")
    if os.path.isdir(home2):
        import shutil
        shutil.rmtree(home2, ignore_errors=True)
    os.makedirs(home2, exist_ok=True)
    r4 = run(home2, "--expert", "Needs Keys")
    root = os.path.join(home2, "experts", "needs-keys")
    if r4.returncode == 0 and os.path.isdir(root):
        # the fresh expert ships with a live provider; drop the key and re-run
        for var in ("DEEPSEEK_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
            os.environ.pop(var, None)
        with open(os.path.join(home2, "agent.env"), "w", encoding="utf-8") as f:
            f.write("# no keys yet\n")
        r4 = run(home2)
    assert r4.returncode == 2, (r4.returncode, r4.stdout[-500:])
    assert "Before this platform can run" in r4.stdout, r4.stdout[-500:]
    assert "_API_KEY" in r4.stdout, "the missing ENV VAR must be named"
    assert "  1." in r4.stdout, "as a numbered TODO"
    rep4 = json.load(open(os.path.join(home2, "bootstrap.json"), encoding="utf-8"))
    assert rep4["ready"] is False and rep4["blocked_on"]
    assert all(len(i["how"]) > 5 for i in rep4["blocked_on"]), "each says HOW"
    print("[blocked] with no provider key the bootstrap refused to claim "
          "readiness, named the variable, and said exactly how to fix it")

    # --- 5. teaching in the same breath
    material = os.path.join(home, "material")
    os.makedirs(material, exist_ok=True)
    with open(os.path.join(material, "lesson1.md"), "w", encoding="utf-8") as f:
        f.write("# Lesson 1\nthe first thing to learn\n")
    r5 = run(home, "--offline", "--teach", material)
    assert r5.returncode == 0, r5.stdout + r5.stderr
    rep5 = json.load(open(os.path.join(home, "bootstrap.json"), encoding="utf-8"))
    assert rep5.get("teach", {}).get("kind") == "folder", rep5.get("teach")
    assert rep5["teach"]["queued"] >= 1
    state = json.load(open(os.path.join(home, "experts", "night-analyst",
                                        "state.json"), encoding="utf-8"))
    assert state["tasks"], "the material became real queued work"
    print("[teach] the same command handed the new expert its first material "
          "and queued the work")
    print("PASS test_bootstrap")


if __name__ == "__main__":
    main()
