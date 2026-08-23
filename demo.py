#!/usr/bin/env python3
"""No-keys demo: watch the entire ecosystem run on your machine, right now.

Builds a self-contained demo world with SCRIPTED mock models (zero network,
zero cost), drops one file in its inbox, starts the real loop, and lets the
real machinery do everything: inbox scan -> Ripper -> Watcher (cited notes,
spec, index, a planted gap) -> Practitioner -> Reflector -> Examiner with
mechanical verification -> Librarian resolves the gap -> course COMPLETE ->
spaced re-exam. Then it gives you a tour of every file that appeared.

Only the model responses are scripted. The loop, chaining, locks, ticks,
verify.py, and memcheck.py are the exact production code. With real API keys
in settings.toml, the same machinery runs live on real material.

Usage:  python demo.py [--dir demo-run]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CHILD_ENV = {**os.environ, "PYTHONUTF8": "1"}  # Windows consoles default to cp1252


def run(cmd, capture=False, timeout=300):
    return subprocess.run(cmd, capture_output=capture, text=capture,
                          encoding="utf-8" if capture else None,
                          errors="replace" if capture else None,
                          env=CHILD_ENV, timeout=timeout)
PY = sys.executable
COURSE = "demo-course"
C = f"courses/{COURSE}"

NOTES = """# L01 — Exponential backoff
SOURCE: transcript.txt (lang: en)
## Concepts
- C-0101 Exponential backoff doubles the delay per retry [src: transcript 00:00:01]
## Claims & procedures
- P-0102 Maximum of five attempts before giving up [src: transcript 00:00:01]
## Contradicts
(none)
## Unclear
(none)
"""

SPEC = (f'R-001 [from C-0101,P-0102]: lesson 01 notes exist on disk '
        f'CHECK: "{PY}" -c "import os,sys; '
        f"sys.exit(0 if os.path.exists('{C}/lessons/01/notes.md') else 1)\"\n")

SCRIPTS = {
    "ripper": [
        {"tool": "write_file", "args": {"path": f"{C}/lessons/01/transcript.txt",
         "content": "[00:00:01] Exponential backoff doubles the delay each retry; give up after five attempts."}},
        {"tool": "finish_task", "args": {"summary": "ingested lesson 01 (scripted transcript)"}},
    ],
    "watcher": [
        {"tool": "write_file", "args": {"path": f"{C}/lessons/01/notes.md", "content": NOTES}},
        {"tool": "write_file", "args": {"path": f"{C}/spec.md", "content": SPEC}},
        {"tool": "write_file", "args": {"path": f"{C}/index.md",
         "content": "01 | exponential backoff: base and attempt limit | R-001 |\n"}},
        {"tool": "write_file", "args": {"path": f"{C}/gaps.md",
         "content": "- G-001 (librarian) planted contradiction so you can watch the gap loop work\n"}},
        {"tool": "finish_task", "args": {"summary": "studied lesson 01 into cited notes"}},
    ],
    "practitioner": [
        {"tool": "write_file", "args": {"path": f"{C}/artifacts/ex1/MANIFEST.md",
         "content": "satisfies R-001 — see lessons/01/notes.md\n"}},
        {"tool": "finish_task", "args": {"summary": "executed exercise 1, artifact captured"}},
    ],
    "examiner": [
        {"tool": "write_file", "args": {"path": f"{C}/exam-results.md",
         "content": "R-001: PASS — artifact verified against notes\nSCORE: 95\n"}},
        {"tool": "run_command", "args": {"cmd":
         f'"{PY}" "{os.path.join(HERE, "verify.py")}" {COURSE} --root .'}},
        {"tool": "finish_task", "args": {"summary": "graded against spec, mechanical checks run"}},
    ],
    "librarian": [
        {"tool": "write_file", "args": {"path": f"{C}/retractions.md",
         "content": "- G-001 retracted: planted contradiction resolved against the transcript [src: transcript 00:00:01]\n"}},
        {"tool": "write_file", "args": {"path": f"{C}/gaps.md", "content": ""}},
        {"tool": "finish_task", "args": {"summary": "gap resolved, retraction recorded"}},
    ],
    "reflector": [
        {"tool": "write_file", "args": {"path": "skills/backoff-exercise.md",
         "content": "KEYWORDS: backoff, retry\n# Skill: backoff-exercise\nPitfall from this run: off-by-one on the attempt count.\n"}},
        {"tool": "finish_task", "args": {"summary": "reflection recorded into skills/"}},
    ],
}

SETTINGS = """[agent]
max_steps = 50
command_timeout_seconds = 60
poll_interval_seconds = 1
context_token_threshold = 50000
exam_threshold = 90
reexam_days = [0]
inbox_settle_seconds = 0
reflect_after = ["practitioner"]

[agent.chain]
ripper = "watcher"
watcher = "practitioner"
practitioner = "examiner"

{providers}

{roles}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default="demo-run")
    ap.add_argument("--force", action="store_true",
                    help="replace --dir even if it is not a previous demo run")
    args = ap.parse_args()
    root = os.path.abspath(args.dir)

    print(f"=== building the demo world in {root} ===")
    # --dir accepts any path, and this used to delete it recursively with no
    # confirmation at all. A demo is not worth destroying a directory somebody
    # pointed at by mistake: a previous demo run is moved aside, anything else
    # needs --force.
    if os.path.exists(root):
        looks_like_demo = os.path.exists(os.path.join(root, "scripts")) or \
            not os.listdir(root)
        if not looks_like_demo and not args.force:
            sys.exit(f"ERROR: {root} exists and is not a previous demo run. "
                     f"Choose another --dir, or pass --force to replace it.")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.move(root, f"{root}.prev-{stamp}")
        print(f"    previous run kept at {os.path.basename(root)}.prev-{stamp}")
    os.makedirs(root)
    shutil.copytree(os.path.join(HERE, "prompts"), os.path.join(root, "prompts"))
    os.makedirs(os.path.join(root, "scripts"))
    provider_blocks, role_blocks = [], []
    for role, script in SCRIPTS.items():
        with open(os.path.join(root, "scripts", f"{role}.json"), "w", encoding="utf-8") as f:
            json.dump(script, f)
        provider_blocks.append(f'[providers.{role}]\ntype = "mock"\n'
                               f'script = "scripts/{role}.json"\ndelay_seconds = 0.2')
        role_blocks.append(f'[roles.{role}]\nprovider = "{role}"\nmodel = "mock"')
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(SETTINGS.format(providers="\n\n".join(provider_blocks),
                                roles="\n\n".join(role_blocks)))

    print("=== dropping one file into the inbox (the only human action) ===")
    os.makedirs(os.path.join(root, "inbox"))
    with open(os.path.join(root, "inbox", "demo course.pdf"), "wb") as f:
        f.write(b"%PDF-1.4 demo placeholder")

    print("=== starting the real loop; watch each step below ===\n")
    r = run([PY, os.path.join(HERE, "loop.py"), "run", "--drain", "--root", root])
    if r.returncode != 0:
        sys.exit("demo loop exited nonzero — see output above")

    print("\n=== the tour: everything the agent produced ===")
    for rel in (f"{C}/lessons/01/transcript.txt", f"{C}/lessons/01/notes.md",
                f"{C}/spec.md", f"{C}/index.md", f"{C}/gaps.md",
                f"{C}/exam-results.md", f"{C}/retractions.md",
                f"{C}/artifacts/ex1/MANIFEST.md", "skills/backoff-exercise.md",
                f"{C}/exam/schedule.json", "state.json", "logs/agent.log"):
        mark = "ok" if os.path.exists(os.path.join(root, rel)) else "MISSING"
        print(f"  [{mark}] {args.dir}/{rel}")

    print("\n=== proofs, run against the demo's own output ===")
    for tool, label in (("memcheck.py", "memory integrity"),
                        ("verify.py", "mechanical spec checks")):
        r = run([PY, os.path.join(HERE, tool), COURSE, "--root", root],
                capture=True, timeout=60)
        print(f"  {label}: {'PASS' if r.returncode == 0 else 'FAIL'}"
              f" ({r.stdout.strip().splitlines()[-1]})")
    r = run([PY, os.path.join(HERE, "loop.py"), "course", COURSE, "--root", root],
            capture=True, timeout=60)
    print("  " + " | ".join(line.strip() for line in r.stdout.strip().splitlines()))

    print(f"""
=== DEMO COMPLETE ===
The model responses were scripted (no keys, no network, no cost); everything
else — inbox scan, chaining, locks, gap loop, verification, exit criterion,
re-exam — was the real production machinery.

Explore the world it built:   {args.dir}/
Read the study notes:         {args.dir}/{C}/lessons/01/notes.md
Read the step-by-step log:    {args.dir}/logs/agent.log

To run it LIVE on real material: put your API keys in agent.env, run
`python loop.py check` until every role says OK, then `python loop.py run`
and drop real files into inbox/.""")


if __name__ == "__main__":
    main()
