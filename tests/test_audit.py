#!/usr/bin/env python3
"""Adversarial audit findings, kept as permanent regression tests.

1. Two loops on ONE expert (daemon + team drive): every task claimed exactly
   once, none lost, none double-run.
2. The lost-update race: a second process hammers add_task while a loop is
   saving steps — before the state mutex this LOST tasks outright (probe
   caught 6 lost + 12 regressed); now nothing is lost and nothing regresses.
3. Unicode names: accented course/expert names transliterate instead of
   being mangled (Économie -> economie).

Run from the agent/ directory:  python tests/test_audit.py
"""

import json
import os
import subprocess
import sys
import time

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import fleet
import ingest
import loop

PY = sys.executable
LOOP = os.path.join(AGENT_DIR, "loop.py")
SCRIPT = [
    {"tool": "write_file", "args": {"path": "out/w.txt", "content": "x"}},
    {"tool": "finish_task", "args": {"summary": "ok"}},
]


def spawn(root):
    return subprocess.Popen([PY, LOOP, "run", "--drain", "--root", root],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                            env={**os.environ, "PYTHONUTF8": "1"})


def read_tasks(root):
    with open(os.path.join(root, "state.json"), encoding="utf-8") as f:
        return json.load(f)["tasks"]


def main():
    # --- 1. two concurrent loops, one queue: exactly-once execution
    sb = make_sandbox("audit_two", providers={"m": {"script": "s.json",
                                                    "delay_seconds": 0.15}},
                      roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    a = loop.Agent(sb)
    ids = [a.add_task("tester", f"job {i}") for i in range(6)]
    p1, p2 = spawn(sb), spawn(sb)
    assert p1.wait(180) == 0 and p2.wait(180) == 0
    tasks = read_tasks(sb)
    with open(os.path.join(sb, "logs", "agent.log"), encoding="utf-8") as f:
        log = f.read()
    assert len(tasks) == len(ids), f"lost tasks: {len(ids) - len(tasks)}"
    for t in tasks:
        assert t["status"] == "done" and len(t["steps"]) == 2, t["id"]
        claims = log.count(f'"task_start", "task": "{t["id"]}"')
        assert claims == 1, f"{t['id']} claimed {claims}x — must be exactly once"
    print("[two-loops] 6 tasks, 2 concurrent loops: each claimed exactly once, all done")

    # --- 2. the lost-update race (the audit's worst finding, now closed)
    sb = make_sandbox("audit_race", providers={"m": {"script": "s.json",
                                                     "delay_seconds": 0.05}},
                      roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    a = loop.Agent(sb)
    for i in range(4):
        a.add_task("tester", f"seed {i}")
    proc = spawn(sb)
    added, t0 = 0, time.time()
    while proc.poll() is None and time.time() - t0 < 30 and added < 20:
        a.add_task("tester", f"racer {added}")  # the panel hammering the daemon
        added += 1
        time.sleep(0.02)
    assert proc.wait(400) == 0
    tasks = read_tasks(sb)
    expected = 4 + added
    assert len(tasks) == expected, \
        f"LOST {expected - len(tasks)} task(s) to the write race"
    bad = [t["id"] for t in tasks
           if t["status"] != "done" or len(t["steps"]) != 2]
    assert not bad, f"state regressions on {bad}"
    print(f"[lost-update] {expected} tasks queued under concurrent writes: "
          f"0 lost, 0 regressed (was 6 lost / 12 regressed before the mutex)")

    # --- 3. unicode names survive
    assert fleet.slugify("Économie Avancée") == "economie-avancee"
    assert ingest.slugify("Résumé Financier") == "resume-financier"
    assert fleet.slugify("Städtebau & Design") == "stadtebau-design"
    sb = make_sandbox("audit_uni", providers={"m": {"script": "s.json"}},
                      roles={"watcher": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    os.makedirs(os.path.join(sb, "inbox"), exist_ok=True)
    with open(os.path.join(sb, "inbox", "Économie Avancée.md"), "w",
              encoding="utf-8") as f:
        f.write("# Leçon\nLe taux d'actualisation double.\n")
    assert ingest.scan_inbox(sb) == 1
    assert os.path.isdir(os.path.join(sb, "courses", "economie-avancee")), \
        "accented course names must transliterate cleanly"
    body = open(os.path.join(sb, "courses", "economie-avancee", "lessons",
                             "01", "lesson.md"), encoding="utf-8").read()
    assert "Leçon" in body and "d'actualisation" in body, \
        "the CONTENT must keep its accents — only the slug transliterates"
    print("[unicode] accented names slug cleanly; accented content preserved verbatim")
    print("PASS test_audit")


if __name__ == "__main__":
    main()
