#!/usr/bin/env python3
"""Wake-on-event (M2-L3): an external system delivers an event and the
agent wakes — armed `event` intentions fire at once with the payload fenced
in context; a direct goal can be queued with the event; bad events are
refused; the fired task runs to done.

Run from the agent/ directory:  python tests/test_wake.py
"""

import json
import os
import sys
import urllib.error

from common import AGENT_DIR, api, make_sandbox, read_state, run_drain, \
    start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import fleet
import prospective as pm


def main():
    home = make_sandbox("wake", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Night Watch", "wakes on events")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\n\n[providers.m]\ntype = "mock"\n'
                'script = "script.json"\n\n[roles.default]\nprovider = "m"\n'
                'model = "mock"\n')
    json.dump([{"tool": "finish_task", "args": {"summary": "handled"}}],
              open(os.path.join(root, "script.json"), "w", encoding="utf-8"))

    proc, base = start_panel(home)
    try:
        # arm: one-shot on price.drop, repeating on ping
        r = api(base, "POST", "/api/experts/night-watch/intention",
                {"kind": "event", "name": "price.drop",
                 "goal": "re-run the margin analysis"})
        one_shot = r["armed"]
        api(base, "POST", "/api/experts/night-watch/intention",
            {"kind": "event", "name": "ping", "repeat": True,
             "goal": "acknowledge the ping"})
        # the panel auto-starts the loop on wake; stop it so this test
        # controls execution (drains are deterministic)
        api(base, "POST", "/api/experts/night-watch/stop", {})

        # --- a wake fires the armed intention exactly once
        w = api(base, "POST", "/api/experts/night-watch/wake",
                {"event": "price.drop", "payload": {"sku": "A1", "drop": 0.15}})
        assert w["fired"] == 1 and w["queued"] == [] and w["file"].startswith("events/")
        api(base, "POST", "/api/experts/night-watch/stop", {})
        tasks = read_state(root)["tasks"]
        fired = [t for t in tasks if "event 'price.drop' arrived" in t["goal"]]
        assert len(fired) == 1, [t["goal"][:60] for t in tasks]
        assert fired[0]["memory_files"] == [w["file"]], fired[0]["memory_files"]
        assert "margin analysis" in fired[0]["goal"]
        with open(os.path.join(root, w["file"]), encoding="utf-8") as f:
            ev = json.load(f)
        assert ev["payload"] == {"sku": "A1", "drop": 0.15}
        w2 = api(base, "POST", "/api/experts/night-watch/wake",
                 {"event": "price.drop", "payload": {}})
        api(base, "POST", "/api/experts/night-watch/stop", {})
        assert w2["fired"] == 0, "a one-shot intention fires once"
        rec = next(x for x in pm.load(root) if x["id"] == one_shot)
        assert rec["status"] == "fired" and len(rec["when"]["consumed"]) == 1
        print("[wake] an external event fired the armed intention once; the "
              "payload travels fenced as a memory file, never as instructions")

        # --- repeat intentions fire per arrival
        for _ in range(2):
            r = api(base, "POST", "/api/experts/night-watch/wake",
                    {"event": "ping", "payload": {"n": 1}})
            assert r["fired"] == 1
            api(base, "POST", "/api/experts/night-watch/stop", {})
        pings = [t for t in read_state(root)["tasks"] if "'ping' arrived" in t["goal"]]
        assert len(pings) == 2
        print("[repeat] a repeating intention fires on every arrival")

        # --- direct goal mode + refusals
        r = api(base, "POST", "/api/experts/night-watch/wake",
                {"event": "deploy.done", "payload": {"sha": "abc"},
                 "goal": "verify the deployment", "stop": {"max_steps": 5}})
        api(base, "POST", "/api/experts/night-watch/stop", {})
        assert len(r["queued"]) == 1
        direct = next(t for t in read_state(root)["tasks"] if t["id"] == r["queued"][0])
        assert direct["memory_files"] == [r["file"]] and direct["stop"] == {"max_steps": 5}
        assert "WAKE EVENT 'deploy.done'" in direct["goal"]
        for bad in ("Bad Name!", "", "x" * 70):
            try:
                api(base, "POST", "/api/experts/night-watch/wake",
                    {"event": bad, "payload": {}})
                raise AssertionError(f"bad event name must be refused: {bad!r}")
            except urllib.error.HTTPError as e:
                assert e.code == 400
        print("[direct] a wake can queue its own gated task; bad names are "
              "refused with 400")
    finally:
        stop_panel(proc, base)

    # --- the fired work actually runs
    assert run_drain(root) == 0
    tasks = read_state(root)["tasks"]
    assert tasks and all(t["status"] == "done" for t in tasks), \
        [(t["goal"][:30], t["status"]) for t in tasks]
    with open(os.path.join(root, "contexts", tasks[0]["id"] + ".json"),
              encoding="utf-8") as f:
        first_user = next(m["content"] for m in json.load(f) if m["role"] == "user")
    assert "<<<FILE-CONTENT events/" in first_user, \
        "the event payload must reach the model inside a content fence"
    print("[run] every woken task drained to done with its payload fenced in "
          "context")
    print("PASS test_wake")


if __name__ == "__main__":
    main()
