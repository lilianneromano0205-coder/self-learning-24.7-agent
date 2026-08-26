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
    check_failover_attribution_is_per_attempt(  )
    print("PASS test_modelrouter")


def check_failover_attribution_is_per_attempt(home=None):
    """The audit's confirmed defect: the terminal outcome was credited to
    the LAST provider that served, so failover polluted the router's
    evidence in both directions — the cheap model escaped blame for
    failures it mostly caused, and the fallback was blamed for finishing
    them. The router then learned exactly wrong economics.

    Per-attempt rows fix it: each provider:model pair that served carries
    its own steps, its own cost, and its SHARE of the task, and profiles()
    weights by share. Old single rows (no share) keep weight 1, so the
    append-only history keeps its old meaning.
    """
    import tempfile
    root = tempfile.mkdtemp(prefix="router-attr-")
    # a failover failure: cheap served 9 of 10 steps, big finished it
    rows = modelrouter.record_served(
        root, {"id": "t1", "role": "practitioner", "status": "failed",
               "done_check": "gate"},
        {"cheap:small": {"provider": "cheap", "model": "small",
                         "steps": 9, "cost_usd": 0.009},
         "big:large": {"provider": "big", "model": "large",
                       "steps": 1, "cost_usd": 0.020}})
    assert len(rows) == 2, rows
    by = {r["provider"]: r for r in rows}
    assert abs(by["cheap"]["share"] - 0.9) < 1e-6, by
    assert abs(by["big"]["share"] - 0.1) < 1e-6, by
    assert not by["cheap"]["sole"] and not by["big"]["sole"], by
    assert abs(by["cheap"]["cost_usd"] - 0.009) < 1e-9, (
        "each pair must carry only the cost IT incurred")
    # a clean sole-provider success for the cheap pair
    modelrouter.record_served(
        root, {"id": "t2", "role": "practitioner", "status": "done",
               "done_check": "gate"},
        {"cheap:small": {"provider": "cheap", "model": "small",
                         "steps": 5, "cost_usd": 0.005}})
    st = modelrouter.profiles(root)
    c, b = st["cheap:small"], st["big:large"]
    assert abs(c["n"] - 1.9) < 1e-6, (
        f"cheap should weigh 0.9 (its share of the failure) + 1.0 (its "
        f"sole success) = 1.9, got {c['n']} — under the old scheme it "
        f"weighed 1.0 and its record was untouched by the failure it "
        f"mostly caused")
    assert abs(c["pass_rate"] - round(1.0 / 1.9, 3)) < 1e-3, c
    assert abs(b["n"] - 0.1) < 1e-6 and b["pass_rate"] == 0.0, (
        f"big should carry only its 0.1 share of the failure, got {b}")
    print("[attribution] a failover failure was split 0.9/0.1 by served "
          "share: the cheap model that did nine steps carries nine tenths "
          "of the failure, the fallback that finished it carries one tenth "
          "— the router's economics are no longer polluted by whoever "
          "happened to serve last")


if __name__ == "__main__":
    main()
