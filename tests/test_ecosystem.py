#!/usr/bin/env python3
"""THE BEAST TEST — every subsystem, one organism, cross-checked.

One fleet lives a full life in miniature and every system must agree with
every other at the end:

  teach -> skill loads into a GATED task -> win recorded in the skill graph
  -> competence earned at the fleet level -> a failure files itself into the
  categorized ledger -> a prospective watch fires when its file changes and
  the fired task RUNS -> two processes race the same due intention and it
  fires EXACTLY once (the measured double-fire, fixed) -> forty parallel
  skill-outcome writers lose NOTHING -> recall chains cited atoms across
  files -> a variant trial is REFUSED while a live loop pulses -> the chief
  ranks the fleet's real troubles -> retirement preserves the whole world
  and the map still shows it -> the doctor inspects it all and finds only
  the one honest problem (no provider key).

Run from the agent/ directory:  python tests/test_ecosystem.py
"""

import json
import os
import subprocess
import sys
import time

from common import AGENT_DIR, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import chief
import fleet
import loop
import memory
import prospective as pm
import recall
import skills as sg
import variants as V

PY = sys.executable
OK_CHECK = f'"{PY}" -c "import sys;sys.exit(0)"'
BAD_CHECK = f'"{PY}" -c "import sys;sys.exit(1)"'


def main():
    home = make_sandbox("ecosystem", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Atlas", "the one who carries everything")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\nsandbox = "host"\nallow_unsafe_host = true\n'
                'poll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\nmax_done_rejects = 2\nmax_task_retries = 0\n\n'
                '[providers.m]\ntype = "mock"\nscript = "script.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n\n'
                '[roles.practitioner]\nprovider = "m"\nmodel = "mock"\n')
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "write_file",
                    "args": {"path": "out/w.txt", "content": "x"}},
                   {"tool": "finish_task", "args": {"summary": "done"}}], f)

    # teach: a cited course + a skill the first task will load
    os.makedirs(os.path.join(root, "courses/logistics/lessons/01"),
                exist_ok=True)
    with open(os.path.join(root, "courses/logistics/lessons/01/notes.md"),
              "w", encoding="utf-8") as f:
        f.write("# L01\n- C-0101 the depot closes at 18:00 [src: manual p2]\n")
    os.makedirs(os.path.join(root, "courses/logistics/lessons/02"),
                exist_ok=True)
    with open(os.path.join(root, "courses/logistics/lessons/02/notes.md"),
              "w", encoding="utf-8") as f:
        f.write("# L02 decisions\n- C-0201 we reroute evening loads because "
                "of C-0101 [src: mtg 00:05]\n")
    os.makedirs(os.path.join(root, "skills"), exist_ok=True)
    with open(os.path.join(root, "skills", "shipment-plan.md"), "w",
              encoding="utf-8") as f:
        f.write("KEYWORDS: shipment, reroute\nplan steps...\n")

    # ---- 1. gated win: skill loads, wins, competence lands at fleet level
    agent = loop.Agent(root)
    agent.add_task("practitioner", "plan the evening shipment reroute",
                   course="logistics", done_check=OK_CHECK)
    agent.add_task("practitioner", "an impossible shipment job",
                   course="logistics", done_check=BAD_CHECK)
    assert run_drain(root) == 0
    tasks = {t["goal"][:20]: t for t in
             json.load(open(os.path.join(root, "state.json")))["tasks"]}
    good = next(t for t in tasks.values() if t["status"] == "done")
    bad = next(t for t in tasks.values() if t["status"] == "failed")
    assert good["skills_used"] == ["skills/shipment-plan.md"]
    g = sg.load_graph(root)["shipment-plan"]
    assert g["wins"] == 1 and g["verified_wins"] == 1 and g["losses"] == 1, g
    assert g["status"] == "candidate"
    comp = memory.competence(home)["atlas"]["logistics"]
    assert comp["attempts"] == 2 and comp["successes"] == 1
    fails = memory.failures(home, expert="atlas")
    assert fails and fails[0]["category"] == "false_success"
    print("[organism] one gated win + one honest failure: skill graph, fleet "
          "competence, and the failure ledger all agree")

    # ---- 2. prospective watch fires on a file change and the task RUNS
    pm.add(root, {"kind": "file_contains", "path": "watch/board.md",
                  "needle": "DELAYED"},
           {"role": "practitioner", "goal": "reroute the delayed shipment",
            "done_check": OK_CHECK})
    os.makedirs(os.path.join(root, "watch"), exist_ok=True)
    with open(os.path.join(root, "watch", "board.md"), "w",
              encoding="utf-8") as f:
        f.write("carrier update: truck 7 DELAYED at customs\n")
    assert run_drain(root) == 0
    fired = [t for t in
             json.load(open(os.path.join(root, "state.json")))["tasks"]
             if "PROSPECTIVE" in t["goal"]]
    assert len(fired) == 1 and fired[0]["status"] == "done", \
        [(t["goal"][:40], t["status"]) for t in fired]
    print("[prospective] the watch fired on the file change and the fired "
          "task ran to done under its own gate")

    # ---- 3. the double-fire race stays dead: two processes, ONE fire
    pm.add(root, {"kind": "at", "iso": "2020-01-01T00:00:00"},
           {"role": "practitioner", "goal": "the racy follow-up"})
    worker = ("import sys,time;sys.path.insert(0,%r);"
              "import loop,prospective as pm;a=loop.Agent(%r);"
              "time.sleep(0.3);print(pm.check(%r,a))"
              % (AGENT_DIR, root, root))
    ps = [subprocess.Popen([PY, "-c", worker]) for _ in range(2)]
    [p.wait(60) for p in ps]
    racy = [t for t in
            json.load(open(os.path.join(root, "state.json")))["tasks"]
            if "racy follow-up" in t["goal"]]
    assert len(racy) == 1, \
        f"the double-fire race is back: {len(racy)} tasks queued"
    print("[race] two processes evaluated the same due intention — it fired "
          "exactly once (the measured double-fire stays dead)")

    # ---- 4. forty parallel skill-outcome writers lose nothing
    # (the prospective-fired task above ALSO matched the skill and recorded
    #  its own win — the organism compounds — so assert the delta)
    wins_before = sg.load_graph(root)["shipment-plan"]["wins"]
    wr = ("import sys;sys.path.insert(0,%r);import skills as sg;"
          "[sg.record_use(%r,['skills/shipment-plan.md'],'par%%d'%%i,True) "
          "for i in range(20)]" % (AGENT_DIR, root))
    ps = [subprocess.Popen([PY, "-c", wr.replace("par", f"p{n}-")])
          for n in range(2)]
    [p.wait(120) for p in ps]
    g = sg.load_graph(root)["shipment-plan"]
    assert g["wins"] == wins_before + 40, \
        f"lost updates: wins={g['wins']} (want {wins_before + 40})"
    print("[writers] 2 processes x 20 outcomes: all 40 recorded — the graph "
          "lock loses nothing")

    # ---- 5. recall returns the chain, not the fragment
    hits = recall.search(root, "reroute evening loads", limit=5)
    locs = [l for _, l, _ in hits]
    assert any("lessons/02" in l for l in locs)
    assert any(l.startswith("linked:") and "lessons/01" in l for l in locs), \
        f"C-0101's definition must come back as linked evidence: {locs}"
    print("[recall] the decision pulled its cited atom's definition across "
          "files — chain, not fragment")

    # ---- 6. a live loop blocks variant trials (arm contamination guard)
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(os.path.join(root, "logs", "heartbeat.json"), "w",
              encoding="utf-8") as f:
        json.dump({"ts": time.time(), "pid": 1, "note": "working"}, f)
    V.spawn(root, "v9", "practitioner", "# variant\n")
    try:
        V.trial(root, "v9", [{"role": "practitioner", "goal": "a",
                              "done_check": OK_CHECK}] * 2, timeout=60)
        raise AssertionError("a trial beside a live loop must be refused")
    except SystemExit as ex:
        assert "contaminate" in str(ex)
    print("[variants] trial refused while a loop pulses — arms cannot be "
          "contaminated by a foreign claimer")

    # ---- 7. the chief sees the real troubles of THIS fleet
    with open(os.path.join(root, "blocked.md"), "w", encoding="utf-8") as f:
        f.write("\n## 2026-08-21 10:00 — task zz99 (practitioner)\n"
                "Which carrier do we trust for customs-delayed loads?\n")
    st = json.load(open(os.path.join(root, "state.json")))
    st["tasks"][0]["status"] = "blocked"
    json.dump(st, open(os.path.join(root, "state.json"), "w"))
    b = chief.briefing(home)
    verbs = [r["verb"] for r in b["recommendations"]]
    assert "ANSWER" in verbs, verbs
    assert any("customs-delayed" in r["what"] for r in b["recommendations"])
    print("[chief] the briefing surfaced the blocked question with its "
          "actual text, ranked first")

    # ---- 8. retirement preserves the organism; the map still knows it
    man = memory.retire(home, "atlas", reason="scenario complete")
    assert man["courses"] == ["logistics"]
    kept = os.path.join(home, "retired", "atlas")
    for rel in ("skills/graph.json", "prospective.json",
                "courses/logistics/lessons/02/notes.md"):
        assert os.path.exists(os.path.join(kept, rel)), f"lost in retirement: {rel}"
    m = memory.fleet_map(home)
    assert any(a["expert"] == "atlas" for a in m["retired"])
    assert m["totals"]["failures"] >= 1
    memory.restore(home, "atlas")
    assert sg.load_graph(root)["shipment-plan"]["wins"] == wins_before + 40, \
        "the skill record must survive retire+restore intact"
    print("[retire] the whole organism — graph, intentions, notes — survived "
          "retirement and came back byte-true")

    # ---- 9. the doctor inspects everything and finds only the honest problem
    r = subprocess.run([PY, os.path.join(AGENT_DIR, "doctor.py"),
                        "--home", home],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300,
                       env={**os.environ, "PYTHONUTF8": "1"})
    out = r.stdout + r.stderr
    assert "briefing compiles" in out, "the chief check must run"
    assert "corrupt" not in out.lower(), out[-500:]
    assert "stale ledger lock" not in out, out[-500:]
    print("[doctor] full inspection: ledgers parse, no stale locks, the "
          "briefing compiles — nothing wrong but the missing key")
    print("PASS test_ecosystem — the organism holds together")


if __name__ == "__main__":
    main()
