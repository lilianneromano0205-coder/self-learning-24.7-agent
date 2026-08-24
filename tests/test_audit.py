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
    # No task may appear that nobody queued. A phantom task here is not a
    # counting quirk: it is the RETRY of a task that two loops ran at once,
    # one of which crashed into the other and marked the shared work failed.
    assert [t["id"] for t in tasks if t["id"] not in ids] == [], \
        [t["goal"][:70] for t in tasks if t["id"] not in ids]
    assert len(tasks) == len(ids), f"lost tasks: {len(ids) - len(tasks)}"
    # Counting task_start proved the QUEUED path claims once, and was blind
    # to the path that actually broke exactly-once: a second loop resuming a
    # running task logs no start at all. Count what the work DID instead --
    # every step ends in a task_end, so two executions leave two of them.
    for t in tasks:
        assert t["status"] == "done" and len(t["steps"]) == 2, t["id"]
        claims = log.count(f'"task_start", "task": "{t["id"]}"')
        assert claims == 1, f"{t['id']} claimed {claims}x — must be exactly once"
        ends = log.count(f'"task_end", "task": "{t["id"]}"')
        assert ends == 1, f"{t['id']} ended {ends}x — it was executed twice"
    assert log.count('"event": "task_end"') == len(ids), \
        f"{log.count(chr(34) + 'event' + chr(34) + ': ' + chr(34) + 'task_end' + chr(34))} endings for {len(ids)} tasks"
    assert '"event": "step_crash"' not in log, "a loop crashed inside a step"
    print("[two-loops] 6 tasks, 2 concurrent loops: each claimed exactly once, "
          "executed exactly once (6 endings for 6 tasks), and all done")

    # --- 1b. the ownership rule itself, deterministically
    # The race above only opens on a loaded machine: it failed 3 times in 12
    # on one contended CPU and never once on an idle laptop. A guarantee that
    # only fails 25% of the time is not a guarantee, so the rule the race
    # depends on is checked directly and every branch of it is enumerated.
    sb = make_sandbox("audit_own", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    live, other = loop.Agent(sb), loop.Agent(sb)
    assert live.runner_id != other.runner_id, "two loops share one identity"
    tid = live.add_task("tester", "owned work")
    held = live.claim_task(tid)
    assert held and held["runner"]["id"] == live.runner_id, held
    # (a) a live sibling's task is untouchable, by the predicate AND by the
    #     atomic adopt, AND it is invisible to the scheduler
    assert other._may_resume(held) is False, "a live owner's task was adoptable"
    assert other.adopt_task(tid) is None, "adopt_task stole from a live owner"
    assert other.next_task(other.load_state()) is None, \
        "next_task handed out a task a live sibling is running"
    assert live._may_resume(held) is True, "a loop cannot resume its own task"

    def stamp(**kw):
        s = other.load_state()
        t = next(x for x in s["tasks"] if x["id"] == tid)
        t["runner"] = {**held["runner"], **kw}
        other.save_state(s)
        return t

    # (b) the owner died on this machine -> resume at once, no waiting.
    #     This is the crash recovery the unconditional resume was written
    #     for, and it must survive the fix that made resuming conditional.
    dead = 0x7FFFFFFF          # a pid no live process can hold
    assert other._may_resume(stamp(pid=dead)) is True, \
        "a task whose owner is dead was not recoverable"
    assert other.adopt_task(tid) is not None, "could not adopt a dead owner's task"
    stamp(pid=os.getpid(), id=held["runner"]["id"])   # hand it back
    # (c) a task from a version that never stamped an owner stays recoverable
    s = other.load_state()
    t = next(x for x in s["tasks"] if x["id"] == tid)
    t.pop("runner", None)
    other.save_state(s)
    assert other._may_resume(t) is True, "a legacy running task became stranded"
    # (d) another HOST's pid means nothing here, so only the lease can free it
    fresh = stamp(host="somewhere-else", ts=time.time())
    assert other._may_resume(fresh) is False, "adopted a live foreign host's task"
    stale = stamp(host="somewhere-else",
                  ts=time.time() - other.runner_lease_seconds - 1)
    assert other._may_resume(stale) is True, "the lease backstop never expires"
    # (e) a loop parked in a long provider call has a stale timestamp and is
    #     perfectly healthy. On this host liveness decides and the clock gets
    #     no vote, or a slow task would be executed twice for being slow.
    here = other._runner_stamp()["host"]
    ancient = stamp(host=here, pid=os.getpid(),
                    ts=time.time() - other.runner_lease_seconds * 10)
    assert other._may_resume(ancient) is False, \
        "a live owner was overtaken because its lease looked old"
    assert other.adopt_task(tid) is None, "adopt_task overtook a live owner"
    # (f) and every commit refreshes that lease, so the backstop stays true
    #     for the foreign-host case that does depend on it
    mine = live.claim_task(live.add_task("tester", "refresh"))
    was = mine["runner"]["ts"]
    time.sleep(0.01)
    live.commit_task(mine)
    assert mine["runner"]["ts"] > was, "a commit did not refresh the lease"
    print("[ownership] a running task records its owner: a live sibling's work "
          "is refused by the predicate, by adopt_task and by the scheduler, "
          "while a dead owner, an unstamped task and an expired foreign lease "
          "are all still recoverable -- crash recovery survived the fix")

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
