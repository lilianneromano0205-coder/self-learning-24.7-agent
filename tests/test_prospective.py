#!/usr/bin/env python3
"""Prospective memory: remembering to ACT later, executed by the scheduler —
never left to a model's recall (the PM-Bench lesson).

1. Conditions are mechanical: a deadline, a recurrence, a file appearing, a
   file gaining a phrase, a task completing. No model evaluates them.
2. Firing queues a NORMAL gated task on the agent's board — no shortcuts.
3. One-shots fire exactly once and keep their record; recurrences re-arm.
4. Watched paths cannot escape the agent's world.
5. The running loop fires due intentions by itself and the fired task is
   then executed like any other work.

Run from the agent/ directory:  python tests/test_prospective.py
"""

import json
import os
import sys
import time

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import loop
import prospective as pm


def main():
    sb = make_sandbox("prospective", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    agent = loop.Agent(sb)

    # --- 1+2. a passed deadline fires once and queues a real task
    it = pm.add(sb, {"kind": "at", "iso": "2020-01-01T00:00:00"},
                {"role": "tester", "goal": "send the quarterly follow-up"},
                note="armed in the past so it is due now")
    assert it["status"] == "armed"
    fired = pm.check(sb, agent)
    assert fired == 1
    tasks = read_state(sb)["tasks"]
    assert len(tasks) == 1 and tasks[0]["role"] == "tester"
    assert "PROSPECTIVE INTENTION FIRED" in tasks[0]["goal"]
    assert "deadline" in tasks[0]["goal"] and \
        "send the quarterly follow-up" in tasks[0]["goal"]
    assert "armed in the past" in tasks[0]["goal"], \
        "the WHY must travel with the fired task"
    # exactly once: the record survives as 'fired', it does not re-fire
    assert pm.check(sb, agent) == 0
    rec = pm.load(sb)[0]
    assert rec["status"] == "fired" and rec["fired_task"] == tasks[0]["id"]
    print("[deadline] fired exactly once, queued a normal task carrying the "
          "trigger and the reason; the record survives as history")

    # --- file_contains: fires only when the phrase actually appears
    it2 = pm.add(sb, {"kind": "file_contains", "path": "watch/prices.md",
                      "needle": "PRICE DROP"},
                 {"role": "tester", "goal": "re-run the margin analysis"})
    os.makedirs(os.path.join(sb, "watch"), exist_ok=True)
    with open(os.path.join(sb, "watch", "prices.md"), "w",
              encoding="utf-8") as f:
        f.write("competitor prices steady today\n")
    assert pm.check(sb, agent) == 0, "no needle yet -> must not fire"
    with open(os.path.join(sb, "watch", "prices.md"), "a",
              encoding="utf-8") as f:
        f.write("ALERT: PRICE DROP on the pro tier\n")
    assert pm.check(sb, agent) == 1
    goals = [t["goal"] for t in read_state(sb)["tasks"]]
    assert any("margin analysis" in g for g in goals)
    print("[watch] file_contains held silent until the phrase appeared, "
          "then fired")

    # --- task_done: 'after X finishes, do Y'
    done_id = read_state(sb)["tasks"][0]["id"]
    pm.add(sb, {"kind": "task_done", "task": done_id},
           {"role": "tester", "goal": "publish the follow-up summary"})
    # that task is still queued -> not due
    assert pm.check(sb, agent) == 0
    st = read_state(sb)
    st["tasks"][0]["status"] = "done"
    with open(os.path.join(sb, "state.json"), "w", encoding="utf-8") as f:
        json.dump(st, f)
    assert pm.check(sb, agent) == 1
    print("[chain] task_done waited for the task, then queued the follow-on")

    # --- every_days re-arms
    it3 = pm.add(sb, {"kind": "every_days", "n": 0.00001},
                 {"role": "tester", "goal": "daily review"})
    time.sleep(1.1)
    assert pm.check(sb, agent) == 1
    rec3 = next(x for x in pm.load(sb) if x["id"] == it3["id"])
    assert rec3["status"] == "armed" and rec3["fire_count"] == 1, \
        "a recurrence stays armed after firing"
    print("[recur] every_days fired and re-armed itself")

    # --- 4. containment: a watched path cannot escape the agent's world
    for bad in ("../outside.md", "..\\..\\secrets"):
        try:
            pm.add(sb, {"kind": "file_exists", "path": bad},
                   {"role": "tester", "goal": "x"})
            raise AssertionError(f"escape must be refused: {bad}")
        except ValueError:
            pass
    # cancel is recorded, not deleted
    it4 = pm.add(sb, {"kind": "at", "iso": "2999-01-01T00:00:00"},
                 {"role": "tester", "goal": "far future"})
    pm.cancel(sb, it4["id"])
    assert next(x for x in pm.load(sb)
                if x["id"] == it4["id"])["status"] == "cancelled"
    print("[safety] path escapes refused; cancellation is a recorded status")

    # --- check: WHEN a probe command exits 0 (the condition no file
    #     pattern can express — "when the price gap exceeds 15%"), with the
    #     probe policy-screened and rate-limited per intention
    marker = os.path.join(sb, "watch", "gap-alert.txt")
    count = os.path.join(sb, "watch", "probe-count.txt")
    py = sys.executable.replace("\\", "/")
    probe = (f'"{py}" -c "import io,os,sys;'
             f"p=r'{count.replace(chr(92), '/')}';"
             f"n=int(io.open(p).read()) if os.path.exists(p) else 0;"
             f"io.open(p,'w').write(str(n+1));"
             f"sys.exit(0 if os.path.exists(r'{marker.replace(chr(92), '/')}') else 1)\"")
    it5 = pm.add(sb, {"kind": "check", "cmd": probe, "every_s": 3600},
                 {"role": "tester", "goal": "re-run the gap analysis"})
    assert pm.check(sb, agent) == 0, "probe exits 1 -> must not fire"
    n1 = int(open(count).read())
    assert n1 == 1, f"the probe should have run exactly once, ran {n1}"
    assert pm.check(sb, agent) == 0
    assert int(open(count).read()) == n1, (
        "a second tick inside every_s re-ran the probe — the rate limit is "
        "decorative and every idle tick pays a subprocess")
    open(marker, "w").close()
    rec5 = next(x for x in pm.load(sb) if x["id"] == it5["id"])
    rec5["when"]["last_probe"] = 0.0          # window elapsed (simulated)
    items = pm.load(sb)
    for i, x in enumerate(items):
        if x["id"] == it5["id"]:
            items[i] = rec5
    pm.save(sb, items)
    assert pm.check(sb, agent) == 1, "condition holds -> must fire"
    goals = [t["goal"] for t in read_state(sb)["tasks"]]
    assert any("gap analysis" in g and "exited 0" in g for g in goals)
    print("[probe] a check-condition held silent while its command exited "
          "1 (probed once, rate-limited across ticks), then fired when the "
          "condition became true — the trigger names the probe")

    # --- 5. the RUNNING LOOP fires intentions and executes the fired work
    sb2 = make_sandbox("prospective_loop",
                       providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"},
                       scripts={"s.json": [{"tool": "finish_task",
                                            "args": {"summary": "did it"}}]})
    pm.add(sb2, {"kind": "at", "iso": "2020-01-01T00:00:00"},
           {"role": "tester", "goal": "the overdue action"})
    assert run_drain(sb2) == 0, \
        "drain must fire the due intention, run the task, then complete"
    tasks = read_state(sb2)["tasks"]
    assert len(tasks) == 1 and tasks[0]["status"] == "done"
    assert "the overdue action" in tasks[0]["goal"]
    rec = pm.load(sb2)[0]
    assert rec["status"] == "fired" and rec["fired_task"] == tasks[0]["id"]
    with open(os.path.join(sb2, "logs", "agent.log"), encoding="utf-8") as f:
        assert '"prospective_fired"' in f.read(), \
            "the firing must land in the log (and thus the Live Pulse)"
    print("[loop] an idle drain noticed the due intention, queued it, "
          "executed it to done, and logged the firing")
    print("PASS test_prospective")


if __name__ == "__main__":
    main()
