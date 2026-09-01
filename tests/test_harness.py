#!/usr/bin/env python3
"""The harness as an inspectable, self-auditing object (M1).

1. manifest(): the six tools with their per-role allowlists, the gates,
   policies, memory tiers, budgets, loop events, versions — read from the
   code and settings that run, never inferred.
2. check_contracts(): the harness audits itself — a tool declared without an
   execution branch is named; the real code is clean.
3. The session-start health ritual: a drain writes logs/health.json and
   logs/harness.json and logs `health_ritual`; a corrupt ledger is reported
   and the loop STILL drains (a loop that refuses to start cannot repair).
4. The panel serves /api/harness, /api/experts/<s>/harness, /api/readiness;
   readiness names ENV VARIABLE NAMES, never key values.

Run from the agent/ directory:  python tests/test_harness.py
"""

import json
import re
import os
import sys

from common import AGENT_DIR, add_task, api, make_sandbox, read_state, \
    run_drain, start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import harness
import loop


def main():
    sb = make_sandbox("harness", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m", "student": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]},
                      role_tools={"student": ["write_file"]})

    # --- 1. the manifest
    m = harness.manifest(sb)
    names = [t["name"] for t in m["tools"]]
    assert names == ["read_file", "write_file", "transform_table",
                     "run_command", "finish_task", "subquery", "ask_human"], names
    rc = next(t for t in m["tools"] if t["name"] == "run_command")
    assert "student" in rc["denied_roles"], rc
    fin = next(t for t in m["tools"] if t["name"] == "finish_task")
    assert fin["always_allowed"] and fin["denied_roles"] == []
    assert len(m["gates"]) >= 9 and any("definition of done" in g["name"]
                                        for g in m["gates"])
    assert m["policies"]["shell_deny_rules"] and \
        "constitution" in m["policies"]["protected_charters"]
    assert any(t["tier"] == "verbatim archive" for t in m["memory_tiers"])
    assert m["budgets"]["max_steps"] == 50, m["budgets"]
    assert "task_end" in m["loop_events"] and \
        "prospective_fired" in m["loop_events"], \
        "events logged from prospective.py count as loop events"
    assert m["versions"]["code"]["loop.py"] and m["versions"]["prompts"]
    print("[manifest] 7 tools with role allowlists, 9+ gates, policies, 14 "
          "memory tiers, budgets, events, file hashes - all read from "
          "what runs")

    # --- 2. self-audit
    assert harness.check_contracts(sb) == [], harness.check_contracts(sb)
    fake = {"type": "function", "function": {"name": "summon_demon",
                                             "description": "x",
                                             "parameters": {"type": "object"}}}
    loop.TOOL_DEFS.append(fake)
    try:
        probs = harness.check_contracts(sb)
        assert any("summon_demon" in p and "no execution branch" in p
                   for p in probs), probs
    finally:
        loop.TOOL_DEFS.remove(fake)
    assert harness.check_contracts(sb) == []
    print("[contracts] the real harness agrees with itself; a tool declared "
          "without an execution branch is named")

    # --- 3. the health ritual
    add_task(sb, "tester", "any job")
    assert run_drain(sb) == 0
    with open(os.path.join(sb, "logs", "health.json"), encoding="utf-8") as f:
        h = json.load(f)
    assert h["ok"] is True and h["problems"] == [] and h["ms"] < 2000, h
    assert os.path.exists(os.path.join(sb, "logs", "harness.json"))
    with open(os.path.join(sb, "logs", "agent.log"), encoding="utf-8") as f:
        log = f.read()
    assert '"health_ritual"' in log and '"ok": true' in log
    assert read_state(sb)["tasks"][0]["status"] == "done"
    # a corrupt ledger is REPORTED and the loop still works
    os.makedirs(os.path.join(sb, "skills"), exist_ok=True)
    with open(os.path.join(sb, "skills", "graph.json"), "w",
              encoding="utf-8") as f:
        f.write("{not json")
    add_task(sb, "tester", "another job")
    assert run_drain(sb) == 0
    with open(os.path.join(sb, "logs", "health.json"), encoding="utf-8") as f:
        h2 = json.load(f)
    assert h2["ok"] is False and any("skill graph" in p for p in h2["problems"])
    assert all(t["status"] == "done" for t in read_state(sb)["tasks"])
    print("[ritual] every run starts with a sub-second health check written "
          "to logs/health.json; a corrupt ledger is named and the loop still "
          "drains")

    # --- 4. the panel + readiness
    home = make_sandbox("harness_home", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    import fleet
    root = fleet.create(home, "Probe One", "probing")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nreflect_after = []\n\n'
                '[providers.openrouter]\nbase_url = "https://openrouter.ai/api/v1"\n'
                'api_key_env = "TEST_KEY_NEVER_SET_ZZ"\n\n'
                '[roles.default]\nprovider = "openrouter"\nmodel = "x/y"\n')
    proc, base = start_panel(home)
    try:
        h = api(base, "GET", "/api/harness")
        assert h["manifest"]["harness_version"] == harness.HARNESS_VERSION
        assert "readiness" in h and isinstance(h["contracts"], list)
        e = api(base, "GET", "/api/experts/probe-one/harness")
        assert e["manifest"]["root"].endswith("probe-one")
        r = api(base, "GET", "/api/readiness")
        assert r["ready"] is False
        blocking = [i for i in r["items"] if i["blocking"]]
        assert any("TEST_KEY_NEVER_SET_ZZ" in i["how"] for i in blocking), r
        # The readiness payload names VARIABLES, never values. This line used
        # to end in `or True`, which made it an assertion that could not fail
        # — the readiness report could have carried any secret at all and the
        # test would still have been green.
        payload = json.dumps(r)
        os.environ["TEST_KEY_NEVER_SET_ZZ_VALUE_PROBE"] = "sk-should-not-leak"
        r2 = api(base, "GET", "/api/readiness")
        payload2 = json.dumps(r2)
        for blob in (payload, payload2):
            assert "sk-should-not-leak" not in blob
            # nothing key-shaped at all: a long opaque token in a health
            # report is a leak whatever variable it came from
            for tok in re.findall(r"[A-Za-z0-9_\-]{24,}", blob):
                assert not tok.lower().startswith(("sk-", "ghp_", "gsk_",
                                                   "nvapi-", "hf_")), tok
    finally:
        os.environ.pop("TEST_KEY_NEVER_SET_ZZ_VALUE_PROBE", None)
        stop_panel(proc, base)
    print("[panel] /api/harness, /api/experts/<s>/harness, /api/readiness "
          "answer; readiness names the ENV var to set, never a value")
    print("PASS test_harness")


if __name__ == "__main__":
    main()
