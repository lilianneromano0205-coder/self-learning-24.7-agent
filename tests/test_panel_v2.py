#!/usr/bin/env python3
"""The control plane's second half (M7): edit what the agent IS, read what
the team SAID, and never sign a dialog you cannot see behind.

1. identity editor: PUT rewrites identity.md, keeps a timestamped backup and
   an edit history, and the next context window carries the new words
2. owner pins: PUT writes commons/pins.md, and it is injected FIRST into
   every agent's commons digest
3. team runs as threads: brief, plan, each deliverable, the synthesis
4. approval cards carry a brief (done / this step / next) and a takeover note
   for browser tools
5. readiness and fleet-wide tool health are served for the Home banner

Run from the agent/ directory:  python tests/test_panel_v2.py
"""

import json
import os
import sys
import urllib.error

from common import AGENT_DIR, api, make_sandbox, read_state, run_drain, \
    start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import approvals
import commons
import context
import fleet
import loop

SCRIPT = [{"tool": "write_file", "args": {"path": "out/a.md", "content": "x"}},
          {"tool": "finish_task", "args": {"summary": "ok"}}]


def main():
    home = make_sandbox("panel_v2", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": SCRIPT})
    root = fleet.create(home, "Panelist", "the original identity")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\n\n[providers.m]\ntype = "mock"\n'
                'script = "script.json"\n\n[roles.default]\nprovider = "m"\n'
                'model = "mock"\n')
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump(SCRIPT, f)

    proc, base = start_panel(home)
    try:
        # --- 1. identity
        got = api(base, "GET", "/api/experts/panelist/identity")
        assert "the original identity" in got["identity"], got
        r = api(base, "PUT", "/api/experts/panelist/identity",
                {"identity": "You are the NIGHT SHIFT analyst. Terse, exact.\n"})
        assert r["saved"] == "identity.md" and r["backup"].startswith("identity.md.bak-")
        assert os.path.isfile(os.path.join(root, r["backup"])), r
        old = open(os.path.join(root, r["backup"]), encoding="utf-8").read()
        assert "the original identity" in old, "the previous words are kept"
        again = api(base, "GET", "/api/experts/panelist/identity")
        assert "NIGHT SHIFT" in again["identity"] and len(again["history"]) == 1
        try:
            api(base, "PUT", "/api/experts/panelist/identity",
                {"identity": "x" * 200_000})
            raise AssertionError("an absurd identity must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        msgs, man = context.compile(loop.Agent(root), {
            "id": "t-id", "role": "practitioner", "goal": "check the window",
            "memory_files": []})
        assert "NIGHT SHIFT" in msgs[0]["content"], \
            "the edited identity must reach the very next window"
        assert "identity.md" in " ".join(man["system"]["files"])
        print("[identity] the owner rewrote who this agent is; the previous "
              "version was kept and the new words were in the next window")

        # --- 2. pins
        api(base, "PUT", "/api/commons/pins",
            {"pins": "# PINS\n- Never email a customer without my sign-off.\n"})
        got = api(base, "GET", "/api/commons/pins")
        assert "Never email a customer" in got["pins"]
        digest = commons.digest(home)
        assert digest.index("Never email a customer") < 400, \
            "pins must ride at the very top of the commons block"
        rel = os.path.join(root, "commons-digest.md")
        assert "Never email a customer" in open(rel, encoding="utf-8").read(), \
            "every agent's materialised digest is refreshed on save"
        try:
            api(base, "PUT", "/api/commons/pins", {"pins": "y" * 30_000})
            raise AssertionError("absurd pins must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        print("[pins] the owner's binding lines are injected first, for every "
              "agent, and re-materialised the moment they are saved")

        # --- 3. team runs as threads
        ws = os.path.join(home, "teamwork", "t-20260821-000000")
        os.makedirs(ws, exist_ok=True)
        for name, body in (("brief.md", "GOAL: ship the page\nROSTER: a, b"),
                           ("plan.md", "- S1 [panelist]: write the copy"),
                           ("output-S1.md", "COPY: buy our thing"),
                           ("result.md", "SYNTHESIS: shipped")):
            with open(os.path.join(ws, name), "w", encoding="utf-8") as f:
                f.write(body)
        with open(os.path.join(ws, "team.json"), "w", encoding="utf-8") as f:
            json.dump({"id": "t-20260821-000000", "goal": "ship the page",
                       "experts": ["panelist"], "lead": "panelist",
                       "status": "done", "result": "teamwork/t-20260821-000000/result.md",
                       "steps": [{"expert": "panelist", "status": "done",
                                  "file": "teamwork/t-20260821-000000/output-S1.md"}]}, f)
        th = api(base, "GET", "/api/team?run=t-20260821-000000&files=1")
        kinds = [m["kind"] for m in th["messages"]]
        assert kinds == ["brief", "plan", "deliverable", "synthesis"], kinds
        assert th["messages"][2]["from"] == "panelist"
        assert "COPY: buy our thing" in th["messages"][2]["text"]
        assert th["messages"][2]["status"] == "done"
        assert th["run"]["lead"] == "panelist"
        try:
            api(base, "GET", "/api/team?run=nope&files=1")
            raise AssertionError("an unknown run must 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        print("[thread] a team run reads as a conversation: brief, plan, each "
              "specialist's file, the lead's synthesis -- all auditable")

        # --- 4. approval cards
        tid = loop.Agent(root).add_task("practitioner", "do a guarded thing")
        assert run_drain(root) == 0
        approvals.request(root, "k-1", "browserbase", "browse_and_click",
                          {"url": "https://example.com"}, "destructive tool",
                          task_id=tid)
        a = api(base, "GET", "/api/experts/panelist/approvals")
        rec = a["pending"][0]
        assert rec["brief"] and set(rec["brief"]) >= {"done", "this_step", "next"}
        assert isinstance(rec["brief"]["done"], list)
        assert rec["takeover"] and "sign in" in rec["takeover"]
        assert "password" in rec["takeover"], \
            "the takeover note must promise the agent never sees the password"
        approvals.request(root, "k-2", "db", "drop_table", {"t": "x"},
                          "destructive tool", task_id=tid)
        a2 = api(base, "GET", "/api/experts/panelist/approvals")
        plain = [x for x in a2["pending"] if x["tool"] == "drop_table"][0]
        assert not plain.get("takeover"), "only browser tools get a takeover note"
        # a decision on a task that is no longer waiting still REPORTS as the
        # decision it is -- never as an error the owner has to interpret
        done = api(base, "POST", "/api/experts/panelist/approval",
                   {"id": plain["id"], "op": "deny", "task": tid})
        assert done["status"] == "denied", done
        assert str(done.get("resumed", "")).startswith("no task was waiting"), done
        assert approvals.load(root, plain["id"])["status"] == "denied"
        left = api(base, "GET", "/api/experts/panelist/approvals")
        assert not [x for x in left["pending"] if x["id"] == plain["id"]]
        print("[approval] every pending sign-off carries what was done, what "
              "this step is and what comes next; browser tools add takeover")

        # --- 5. Home's readiness banner + fleet tool health
        rd = api(base, "GET", "/api/readiness")
        assert set(rd) >= {"ready", "items"} and isinstance(rd["items"], list)
        for item in rd["items"]:
            assert set(item) >= {"what", "how", "blocking"}, item
            assert "sk-" not in json.dumps(item), "readiness never prints a key"
        sysv = api(base, "GET", "/api/system")
        assert isinstance(sysv.get("tool_stats"), list)
        tools = {t["tool"]: t for t in sysv["tool_stats"]}
        assert "write_file" in tools and tools["write_file"]["calls"] >= 1
        assert 0 <= tools["write_file"]["error_rate"] <= 1
        print("[home] readiness lists what is missing by NAME (never a value) "
              "and the fleet's tool health is one call away")
    finally:
        stop_panel(proc, base)
    print("PASS test_panel_v2")


if __name__ == "__main__":
    main()
