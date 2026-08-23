#!/usr/bin/env python3
"""ONE TRACE PER TASK, and tool errors counted apart from model errors (M6).

1. build(): every model turn, tool call, gate refusal and compaction becomes
   a span, with per-span duration and per-task totals (cost, tokens, errors)
2. tool_stats(): per-tool call/error counts and error rate -- the number
   that says WHICH tool is unreliable
3. brief(): what was done / what this step is / what comes next, which is
   what an approval card must carry before a human signs anything
4. the panel serves both, and the fleet view aggregates tool health
5. garbage in the log never breaks a trace

Run from the agent/ directory:  python tests/test_trace.py
"""

import json
import os
import sys

from common import AGENT_DIR, PY, api, make_sandbox, read_state, run_drain, \
    start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import fleet
import loop
import trace as TR

BAD = f'"{PY}" -c "import sys;sys.exit(3)"'
SCRIPT = [
    {"tool": "run_command", "args": {"cmd": BAD}},
    {"tool": "write_file", "args": {"path": "out/a.md", "content": "hello"}},
    {"tool": "finish_task", "args": {"summary": "done despite the failure"}},
]


def main():
    home = make_sandbox("trace", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": SCRIPT})
    root = fleet.create(home, "Tracer", "shows its work")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\n\n[providers.m]\ntype = "mock"\n'
                'script = "script.json"\n\n[roles.default]\nprovider = "m"\n'
                'model = "mock"\n')
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump(SCRIPT, f)
    a = loop.Agent(root)
    tid = a.add_task("practitioner", "run a command and write a file")
    assert run_drain(root) == 0
    assert read_state(root)["tasks"][0]["status"] == "done"

    # --- 1. spans and totals
    tr = TR.build(root, tid)
    kinds = [s["kind"] for s in tr["spans"]]
    names = [s.get("name") for s in tr["spans"] if s["kind"] == "tool"]
    assert kinds[0] == "start" and kinds[-1] == "end", kinds
    assert names == ["run_command", "write_file", "finish_task"], names
    assert tr["totals"]["steps"] == 3, tr["totals"]
    assert tr["totals"]["errors"] == 1, "the failing command is one tool error"
    assert tr["status"] == "done" and tr["role"] == "practitioner"
    assert all(s["ms"] >= 0 for s in tr["spans"])
    assert TR.build(root, "no-such-task")["spans"] == []
    print("[spans] the whole life of the task -- start, three tool calls with "
          "durations, end -- rebuilt from the log the harness already writes")

    # --- 2. tool stats
    stats = {s["tool"]: s for s in TR.tool_stats(root)}
    assert stats["run_command"]["calls"] == 1 and stats["run_command"]["errors"] == 1
    assert stats["run_command"]["error_rate"] == 1.0
    assert stats["write_file"]["errors"] == 0 and stats["write_file"]["error_rate"] == 0
    assert TR.tool_stats(root)[0]["tool"] == "run_command", "worst first"
    print("[tools] per-tool error rates separate the one failing tool from "
          "the two that worked")

    # --- 3. the brief an approval card needs
    b = TR.brief(root, tid)
    assert b["done"] and any("run_command" in d for d in b["done"])
    assert any("(failed)" in d for d in b["done"]), b["done"]
    assert b["this_step"] == "the task finished"
    assert b["next"] == "nothing — the gate accepted the work"
    assert b["totals"]["steps"] == 3
    print("[brief] what was done, what is happening now, what comes next -- "
          "the three sentences a human needs before signing anything")

    # --- 5. a corrupt log line is skipped, not fatal
    with open(os.path.join(root, "logs", "agent.log"), "a", encoding="utf-8") as f:
        f.write("this is not json at all\n")
        f.write('2026-08-21 10:00:00 {"event": "task_start", "task": "%s"\n' % tid)
    tr2 = TR.build(root, tid)
    assert len(tr2["spans"]) == len(tr["spans"]), "garbage lines are ignored"
    print("[robust] unparseable log lines are skipped; the trace still builds")

    # --- 4. the panel
    proc, base = start_panel(home)
    try:
        r = api(base, "GET", f"/api/experts/tracer/trace?task={tid}")
        assert r["trace"]["totals"]["steps"] == 3
        assert r["brief"]["this_step"] == "the task finished"
        t = api(base, "GET", "/api/experts/tracer/trace")
        assert any(x["tool"] == "run_command" for x in t["tools"]), t
        sysv = api(base, "GET", "/api/system")
        fleet_tools = {x["tool"]: x for x in sysv.get("tool_stats", [])}
        assert fleet_tools["run_command"]["errors"] == 1, fleet_tools
        assert fleet_tools["run_command"]["error_rate"] == 1.0
    finally:
        stop_panel(proc, base)
    print("[panel] the panel serves the per-task trace, its brief, and the "
          "fleet-wide tool error rates")
    print("PASS test_trace")


if __name__ == "__main__":
    main()
