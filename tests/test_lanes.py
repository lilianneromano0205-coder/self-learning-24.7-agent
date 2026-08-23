#!/usr/bin/env python3
"""The five agent-creation lanes — and every framework behind the panel —
exercised through the panel's own HTTP API, the way the UI does it.

1. TRAINED     POST /api/experts
2. QUICK       POST /api/quick (specialty + kind + prompt + goal)
3. ARCHETYPE   POST /api/quick {template}: the archetype's charter lands in
               identity.md; an operator archetype gets the Examiner chain
4. LEARNER     POST /api/learner {topic}: expert created AND a goal record
               exists for it (the goal engine was launched)
5. TEAM        POST /api/team with two of the above
Also: the Teach tab's 'apply template' action (the one that 500'd), the
intentions API, the skills API, the variants API (spawn + list), the
federation API (publish + read), the consult list shape the Ask tab renders,
and the settings shape the Wiring tab renders (key_present).

Run from the agent/ directory:  python tests/test_lanes.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from common import AGENT_DIR, free_port, make_sandbox

PY = sys.executable
PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    home = make_sandbox("lanes", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m", "practitioner": "m"},
                        scripts={"s.json": [{"tool": "finish_task",
                                             "args": {"summary": "ok"}}]})
    proc = subprocess.Popen([PY, os.path.join(AGENT_DIR, "ui.py"),
                             "--home", home, "--port", str(PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env={**os.environ, "PYTHONUTF8": "1"})
    try:
        for _ in range(60):
            try:
                api("GET", "/api/experts"); break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("panel did not come up")

        # ---- lane 1: trained
        r = api("POST", "/api/experts", {"name": "Deep One", "identity": "depth"})
        assert r["created"] == "deep-one"
        # ---- lane 2: quick, fully personalised
        r = api("POST", "/api/quick", {"name": "Fast One",
                                       "specialty": "python scripts",
                                       "kind": "auto",
                                       "system_prompt": "Prefer stdlib.",
                                       "goal": "build and run a csv checker"})
        assert r["created"] == "fast-one" and r["kind"] == "operator", r
        with open(os.path.join(home, "experts", "fast-one", "identity.md"),
                  encoding="utf-8") as f:
            assert "OWNER CHARTER (verbatim):\nPrefer stdlib." in f.read()
        print("[lanes 1-2] trained expert and personalised quick operator "
              "created through the API")

        # ---- lane 3: archetype
        r = api("POST", "/api/quick", {"name": "Customs Copilot",
                                       "template": "tradeops-landed-cost"})
        assert r["created"] == "customs-copilot"
        assert r["template"] == "tradeops-landed-cost" and r["kind"] == "advisor"
        with open(os.path.join(home, "experts", "customs-copilot", "identity.md"),
                  encoding="utf-8") as f:
            ident = f.read()
        assert "licensed customs broker" in ident, \
            "the archetype's charter (with its boundary) must be the identity"
        # an operator archetype gets the examiner review chain
        r = api("POST", "/api/quick", {"name": "Ops Runner",
                                       "template": "devops-runner"})
        assert r["kind"] == "operator"
        with open(os.path.join(home, "experts", "ops-runner", "settings.toml"),
                  encoding="utf-8") as f:
            assert 'practitioner = "examiner"' in f.read(), \
                "operator archetypes must chain the Examiner"
        try:
            api("POST", "/api/quick", {"name": "Ghost", "template": "nope"})
            raise AssertionError("unknown template must 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
        print("[lane 3] archetype charters applied at creation; operators "
              "chain the Examiner; unknown templates 404")

        # the Teach tab's apply-template action (used to hit `launch` and 500)
        r = api("POST", "/api/experts/deep-one/template", {"template": "scout"})
        assert r["kind"] == "advisor" and r["template"] == "scout"
        with open(os.path.join(home, "experts", "deep-one", "identity.md"),
                  encoding="utf-8") as f:
            assert "Opportunity scout" in f.read()
        print("[teach] 'use as this agent's charter' now applies the template "
              "for real")

        # ---- lane 4: learner
        r = api("POST", "/api/learner", {"name": "ECG Scholar",
                                         "topic": "12-lead ECG interpretation",
                                         "sources": ["https://example.org/ecg"]})
        assert r["created"] == "ecg-scholar" and r["pursuing"].startswith("g-")
        gdir = os.path.join(home, "experts", "ecg-scholar", "goals")
        for _ in range(50):          # the goal engine writes its record quickly
            if os.path.isdir(gdir) and any(
                    os.path.exists(os.path.join(gdir, g, "goal.json"))
                    for g in os.listdir(gdir)):
                break
            time.sleep(0.2)
        recs = [json.load(open(os.path.join(gdir, g, "goal.json"), encoding="utf-8"))
                for g in os.listdir(gdir)
                if os.path.exists(os.path.join(gdir, g, "goal.json"))]
        assert recs and "Learn 12-lead ECG interpretation to mastery" in recs[0]["goal"]
        assert "closed-book self-exam" in recs[0]["goal"]
        goals = api("GET", "/api/goals")
        assert any(g["expert"] == "ecg-scholar" for g in goals)
        try:
            api("POST", "/api/learner", {"name": "Empty", "topic": ""})
            raise AssertionError("a learner without a topic must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 400
        print("[lane 4] a topic became an expert plus a running study goal, "
              "visible in Work -> Goals")

        # ---- lane 5: team (two of the above)
        r = api("POST", "/api/team", {"experts": ["deep-one", "fast-one"],
                                      "lead": "deep-one",
                                      "goal": "ship a checker with docs"})
        assert r["run"].startswith("t-")
        print("[lane 5] a team of two created agents launched")

        # ---- intentions API (Overview card)
        r = api("POST", "/api/experts/fast-one/intention",
                {"kind": "file_contains", "path": "watch/p.md",
                 "needle": "DROP", "goal": "re-run the margin analysis"})
        pid = r["armed"]
        items = api("GET", "/api/experts/fast-one/prospective")
        assert items[0]["id"] == pid and items[0]["status"] == "armed"
        api("POST", "/api/experts/fast-one/intention", {"op": "cancel", "id": pid})
        assert api("GET", "/api/experts/fast-one/prospective")[0]["status"] == "cancelled"
        r = api("POST", "/api/experts/fast-one/intention",
                {"kind": "at", "in_days": "2", "goal": "follow up"})
        assert api("GET", "/api/experts/fast-one/prospective")[-1]["when"]["kind"] == "at"
        print("[intentions] armed, listed, cancelled through the panel API")

        # ---- skills API
        sk = api("GET", "/api/experts/fast-one/skills")
        assert set(sk) >= {"proven", "candidate", "quarantined"}
        # ---- variants API
        r = api("POST", "/api/experts/fast-one/variant",
                {"op": "spawn", "id": "v2", "role": "practitioner",
                 "prompt": "# ROLE: practitioner — terser\n", "note": "terser"})
        assert r["spawned"] == "v2"
        m = api("GET", "/api/experts/fast-one/variants")
        assert m["v2"]["status"] == "spawned" and m["v2"]["roles"] == ["practitioner"]
        print("[skills+variants] both frameworks readable and drivable from "
              "the panel")

        # ---- federation API
        f0 = api("GET", "/api/federation")
        assert f0["fleet_id"] and f0["fingerprint"] and f0["card"] is None
        r = api("POST", "/api/federation", {"expose": ["deep-one"],
                                            "name": "Test Fleet",
                                            "endpoint": "http://127.0.0.1:7900"})
        assert r["published"] == ["deep-one"]
        f1 = api("GET", "/api/federation")
        assert [sk["expert"] for sk in f1["card"]["skills"]] == ["deep-one"]
        assert f1["a2a"]["protocolVersion"] == "1.0"
        # the WORD "secret" legitimately appears in the A2A security-scheme
        # description; what must never appear is the secret's VALUE
        sys.path.insert(0, AGENT_DIR)
        import federation as F
        real_secret = F.identity(home)["secret"]
        assert real_secret and real_secret not in json.dumps(f1), \
            "key material leaked into a panel payload"
        print("[federation] identity, publish, A2A card — all from the panel, "
              "no secret material in any payload")

        # ---- shapes the UI renders
        st = api("GET", "/api/experts/fast-one/settings")
        assert all("key_present" in p for p in st["providers"].values()), \
            "Wiring renders key_present"
        d = api("GET", "/api/experts/fast-one")
        assert "consults" in d
        print("[shapes] settings carry key_present; detail carries consults — "
              "the panel renders what the backend actually returns")
        print("PASS test_lanes")
    finally:
        # graceful: the panel terminates its own child drivers first (a bare
        # terminate() on Windows would orphan them to haunt later tests)
        try:
            urllib.request.urlopen(urllib.request.Request(
                BASE + "/api/shutdown", data=b"{}", method="POST",
                headers={"Content-Type": "application/json"}), timeout=5).read()
        except Exception:
            pass
        try:
            proc.wait(10)
        except Exception:
            proc.terminate()
            proc.wait(10)


if __name__ == "__main__":
    main()
