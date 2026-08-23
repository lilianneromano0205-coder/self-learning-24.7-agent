#!/usr/bin/env python3
"""Model routing is EARNED, not declared (M6).

NVIDIA's SLM thesis says most agent calls should go to a small cheap model.
This platform only believes that about a model it has measured:

1. every terminal task appends one outcome line (provider, model, status,
   gate-verified, cost)
2. profiles aggregate them into pass rate, gated pass rate, avg cost
3. choose() takes the CHEAPEST candidate clearing the bar on this expert's
   own gated work -- and says why
4. raise the bar (or remove the evidence) and it falls back to the static
   configuration, naming what was missing -- never a silent downgrade
5. the loop uses the choice and logs model_routed; the panel serves profiles

Run from the agent/ directory:  python tests/test_modelrouter.py
"""

import json
import os
import sys

from common import AGENT_DIR, agent_setting, api, make_sandbox, read_state, \
    run_drain, start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import loop
import modelrouter

DONE = [{"tool": "finish_task", "args": {"summary": "ok"}}]


def seed(root, provider, model, n, passes, verified=True, cost=0.001):
    for i in range(n):
        modelrouter.record(root, {
            "id": f"seed-{provider}-{i}", "role": "practitioner",
            "status": "done" if i < passes else "failed",
            "done_check": "gate" if verified else None, "steps": [1, 2]},
            provider, model, cost)


def main():
    sb = make_sandbox("modelrouter", providers={"m": {"script": "s.json"}},
                      roles={"practitioner": "m"}, scripts={"s.json": DONE})
    # two candidates: a cheap one and a strong one, both mock-backed
    with open(os.path.join(sb, "settings.toml"), "r", encoding="utf-8") as f:
        cfg = f.read()
    cfg = cfg.replace('[roles.practitioner]',
                      '[providers.cheap]\ntype = "mock"\nscript = "s.json"\n'
                      'prices = {"small-1" = 0.10}\n\n'
                      '[providers.strong]\ntype = "mock"\nscript = "s.json"\n'
                      'prices = {"big-1" = 3.00}\n\n[roles.practitioner]')
    cfg += ('route = "auto"\n'
            'route_candidates = ["cheap:small-1", "strong:big-1"]\n'
            'route_min_pass = 0.8\nroute_min_n = 5\n')
    with open(os.path.join(sb, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(cfg)
    a = loop.Agent(sb)

    # --- 1/2. no evidence yet -> the static configuration stands
    prov, model, d = modelrouter.choose(a, "practitioner")
    assert (prov, model) == ("m", "mock"), (prov, model)
    assert d["routed"] is False and "only 0 run(s)" in d["why"], d["why"]
    print("[unproven] with no measured runs, routing keeps the configured "
          "model and says exactly what evidence is missing")

    # --- 3. the cheap model earns it
    seed(sb, "cheap", "small-1", 6, 6)
    seed(sb, "strong", "big-1", 6, 6)
    prof = modelrouter.profiles(sb, "practitioner")
    assert prof["cheap:small-1"]["n"] == 6
    assert prof["cheap:small-1"]["verified_pass_rate"] == 1.0
    assert prof["strong:big-1"]["verified_pass_rate"] == 1.0
    prov, model, d = modelrouter.choose(a, "practitioner")
    assert (prov, model) == ("cheap", "small-1"), (prov, model, d)
    assert d["routed"] and d["cost"] == 0.10 and "cheapest" in d["why"]
    print("[earned] both models proved themselves, so the cheap one won on "
          "price -- the expensive one is not the default, it is the fallback")

    # --- 4. the cheap model starts failing -> the strong one takes over
    seed(sb, "cheap", "small-1", 6, 0)
    prof = modelrouter.profiles(sb, "practitioner")
    assert prof["cheap:small-1"]["verified_pass_rate"] == 0.5
    prov, model, d = modelrouter.choose(a, "practitioner")
    assert (prov, model) == ("strong", "big-1"), (prov, model, d)
    assert any("cheap:small-1" in r for r in d["rejected"]), d
    print("[demoted] once the cheap model dropped below the bar, routing "
          "moved to the stronger one and recorded why")

    # --- raise the bar past everything -> static fallback, explained
    with open(os.path.join(sb, "settings.toml"), "r", encoding="utf-8") as f:
        raised = f.read().replace("route_min_pass = 0.8", "route_min_pass = 1.0")
    with open(os.path.join(sb, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(raised.replace("route_min_n = 5", "route_min_n = 500"))
    a2 = loop.Agent(sb)
    prov, model, d = modelrouter.choose(a2, "practitioner")
    assert (prov, model) == ("m", "mock") and d["rule"] == "static-fallback"
    assert "500 needed" in d["why"], d["why"]
    print("[fallback] an unreachable bar falls back to the configured model "
          "instead of guessing")

    # --- 5. end to end through the loop
    sb2 = make_sandbox("modelrouter_loop", providers={"m": {"script": "s.json"}},
                       roles={"practitioner": "m"}, scripts={"s.json": DONE})
    with open(os.path.join(sb2, "settings.toml"), "r", encoding="utf-8") as f:
        cfg2 = f.read()
    cfg2 = cfg2.replace('[roles.practitioner]',
                        '[providers.cheap]\ntype = "mock"\nscript = "s.json"\n'
                        'prices = {"small-1" = 0.10}\n\n[roles.practitioner]')
    cfg2 += ('route = "auto"\nroute_candidates = ["cheap:small-1"]\n'
             'route_min_pass = 0.5\nroute_min_n = 2\n')
    with open(os.path.join(sb2, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(cfg2)
    seed(sb2, "cheap", "small-1", 4, 4)
    loop.Agent(sb2).add_task("practitioner", "do the routed work")
    assert run_drain(sb2) == 0
    t = read_state(sb2)["tasks"][0]
    assert t["status"] == "done"
    assert t.get("route", {}).get("chosen") == "cheap:small-1", t.get("route")
    with open(os.path.join(sb2, "logs", "agent.log"), encoding="utf-8") as f:
        log = f.read()
    assert '"model_routed"' in log and "cheap:small-1" in log
    rows = modelrouter.outcomes(sb2)
    mine = [r for r in rows if r["task"] == t["id"]]
    assert mine and mine[0]["provider"] == "cheap" and mine[0]["status"] == "done", mine
    print("[loop] the loop used the routed model, logged the decision, and "
          "filed its own outcome as the next run's evidence")

    # --- panel
    home = make_sandbox("modelrouter_home", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": DONE})
    import fleet
    root = fleet.create(home, "Router", "picks its own model")
    seed(root, "cheap", "small-1", 5, 5)
    proc, base = start_panel(home)
    try:
        r = api(base, "GET", "/api/experts/router/models?profiles=1")
        assert "profiles" in r and "cheap:small-1" in r["profiles"], r
        assert r["profiles"]["cheap:small-1"]["n"] == 5
    finally:
        stop_panel(proc, base)
    print("[panel] the measured profile of every model is served to the owner")
    print("PASS test_modelrouter")


if __name__ == "__main__":
    main()
