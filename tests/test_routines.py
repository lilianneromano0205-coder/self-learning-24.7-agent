#!/usr/bin/env python3
"""ROUTINES: show the work once, then it is a standing arrangement (M6).

1. a FINISHED task becomes a skill written from the trajectory that actually
   worked, plus an armed intention -- one gesture, two artifacts
2. the routine keeps the original's definition of done (a scheduled task
   with no gate is how a fleet quietly produces garbage every morning)
3. an unfinished or failed task is refused: a routine is a promise that this
   works
4. when the intention fires, the queued task carries the skill, and the
   compiled window activates it
5. the panel saves, lists and cancels routines

Run from the agent/ directory:  python tests/test_routines.py
"""

import json
import os
import sys
import urllib.error

from common import AGENT_DIR, PY, agent_setting, api, make_sandbox, \
    read_state, run_drain, start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import context
import fleet
import loop
import prospective as pm
import routines as RT

SCRIPT = [{"tool": "run_command", "args": {"cmd": "echo margin check"}},
          {"tool": "write_file", "args": {"path": "reports/margin.md",
                                          "content": "# margin\nok\n"}},
          {"tool": "finish_task", "args": {"summary": "margin report written"}}]


def main():
    home = make_sandbox("routines", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": SCRIPT})
    root = fleet.create(home, "Rout", "does the same job every day")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\nsandbox = "host"\nallow_unsafe_host = true\n'
                'poll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\n\n[providers.m]\ntype = "mock"\n'
                'script = "script.json"\n\n[roles.default]\nprovider = "m"\n'
                'model = "mock"\n')
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump(SCRIPT, f)
    gate = f'"{PY}" -c "import os,sys;sys.exit(0 if os.path.exists(\'reports/margin.md\') else 1)"'
    a = loop.Agent(root)
    tid = a.add_task("practitioner", "produce the daily margin report",
                     done_check=gate)
    assert run_drain(root) == 0
    t = read_state(root)["tasks"][0]
    assert t["status"] == "done", t

    # --- 1/2. save it
    r = RT.save(root, tid, name="Daily margin check", every_days=1)
    assert r["name"] == "daily-margin-check"
    skill = open(os.path.join(root, "skills", r["name"], "SKILL.md"),
                 encoding="utf-8").read()
    assert skill.startswith("---\nname: daily-margin-check")
    assert "produce the daily margin report" in skill
    assert "run_command" in skill and "write_file" in skill, \
        "the procedure is reconstructed from what actually happened"
    assert "## Definition of done" in skill and "margin.md" in skill
    assert r["done_check"] == gate, "the routine keeps the gate it passed"
    armed = [x for x in pm.load(root) if x["id"] == r["intention"]]
    assert armed and armed[0]["status"] == "armed"
    assert armed[0]["then"]["done_check"] == gate
    assert armed[0]["then"]["memory_files"] == [f"skills/{r['name']}/SKILL.md"]
    assert json.load(open(os.path.join(root, "routines",
                                       f"{r['name']}.json"), encoding="utf-8"))
    print("[save] one finished task became a skill written from its own "
          "trajectory plus an armed schedule, carrying the same gate")

    # --- 3. refusals
    a.add_task("practitioner", "a task that never ran")
    pending = [x for x in read_state(root)["tasks"] if x["status"] == "queued"]
    try:
        RT.save(root, pending[0]["id"], every_days=1)
        raise AssertionError("an unfinished task must not become a routine")
    except ValueError as e:
        assert "only a task that finished" in str(e), str(e)
    try:
        RT.save(root, tid)
        raise AssertionError("a routine with no schedule must be refused")
    except ValueError as e:
        assert "needs a schedule" in str(e), str(e)
    try:
        RT.save(root, "nope-not-a-task", every_days=1)
        raise AssertionError("an unknown task must be refused")
    except KeyError:
        pass
    print("[refuse] only work that actually finished may become a promise, "
          "and it must say when to run")

    # --- 4. it fires, carrying the skill into the window
    items = pm.load(root)
    for it in items:
        if it["id"] == r["intention"]:
            it["when"]["n"] = 0                  # due immediately
            it["last_fired"] = None
    pm.save(root, items)
    n = pm.check(root, loop.Agent(root))
    assert n >= 1, "the routine's intention must fire when due"
    fired = [x for x in read_state(root)["tasks"]
             if "Routine 'daily-margin-check'" in x["goal"]]
    assert fired, [x["goal"][:40] for x in read_state(root)["tasks"]]
    assert fired[0]["done_check"] == gate
    msgs, man = context.compile(loop.Agent(root), fired[0])
    assert "daily-margin-check" in msgs[1]["content"]
    assert "## Steps that worked" in msgs[1]["content"], \
        "the fired task must carry the procedure that worked"
    print("[fire] when the schedule came due it queued a gated task carrying "
          "the exact procedure that worked")

    # --- 5. the panel
    proc, base = start_panel(home)
    try:
        rows = api(base, "GET", "/api/experts/rout/routines")
        assert any(x["name"] == "daily-margin-check" and x["status"] == "armed"
                   for x in rows), rows
        r2 = api(base, "POST", "/api/experts/rout/routine",
                 {"task_id": tid, "name": "weekly-margin", "every_days": 7})
        assert r2["routine"] == "weekly-margin" and r2["gated"] is True, r2
        try:
            api(base, "POST", "/api/experts/rout/routine",
                {"task_id": tid, "name": "no-when"})
            raise AssertionError("a routine with no schedule must 400")
        except urllib.error.HTTPError as e:
            assert e.code == 400, e.code
        c = api(base, "POST", "/api/experts/rout/routine",
                {"op": "cancel", "name": "weekly-margin"})
        assert c["cancelled"] == "weekly-margin"
        rows2 = api(base, "GET", "/api/experts/rout/routines")
        assert not any(x["name"] == "weekly-margin" for x in rows2)
    finally:
        stop_panel(proc, base)
    print("[panel] routines are saved, listed and cancelled from the panel; "
          "one with no schedule is refused with 400")
    print("PASS test_routines")


if __name__ == "__main__":
    main()
