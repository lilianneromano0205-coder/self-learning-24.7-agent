#!/usr/bin/env python3
"""CAPABILITY ROUTING — pick the model from measured outcomes, not vibes.

NVIDIA's position paper (*Small Language Models are the Future of Agentic
AI*) makes the economic argument the whole 2026 agent industry then adopted:
most agent calls are narrow, repetitive and format-bound, so a small model is
usually sufficient AND better suited — the frontier model should be reserved
for the steps that actually need it. Their NeMo Switchyard router picks per
call by capability, cost and latency.

The platform already had the crude half of this (a cheap model per role, a
stronger one on escalation). What was missing is EVIDENCE: which model
actually passes this expert's gates, at what cost. Every finished task
appends one line to logs/model-outcomes.jsonl, and this module turns those
lines into per-model profiles:

    n · pass_rate · verified_pass_rate · avg_cost_usd · replay_agreement

A role opts in with:

    [roles.practitioner]
    provider = "openrouter"          # the static fallback, always kept
    model    = "meta-llama/llama-3.3-70b-instruct"
    route    = "auto"
    route_candidates = ["openrouter:qwen/qwen-2.5-7b-instruct",
                        "openrouter:meta-llama/llama-3.3-70b-instruct"]
    route_min_pass = 0.8             # gate-verified pass rate to qualify
    route_min_n    = 5               # evidence required before it may win

`choose()` returns the CHEAPEST candidate that clears both bars, or the
static configuration with a plain-language `why` when none does. Routing is
therefore never a guess and never silent: the decision, its reason and the
evidence behind it are logged (`model_routed`) and shown in the panel.
"""

import json
import os
import time

LEDGER = os.path.join("logs", "model-outcomes.jsonl")
REPLAY_LOG = os.path.join("logs", "replay.jsonl")
DEFAULT_MIN_PASS = 0.8
DEFAULT_MIN_N = 5
# how often an unproven candidate gets a real task, so it can earn evidence
DEFAULT_EXPLORE_EVERY = 7


def _path(root):
    return os.path.join(root, LEDGER)


def record(root, task, provider, model, cost=0.0):
    """One line per terminal task outcome. Append-only, tiny, and the only
    input routing is ever allowed to use."""
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "task": task.get("id"), "role": task.get("role"),
           "provider": provider, "model": model,
           "status": task.get("status"),
           "verified": bool(task.get("done_check")),
           "steps": len(task.get("steps", []) or []),
           "cost_usd": float(cost or task.get("cost_usd") or 0.0)}
    p = _path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def outcomes(root, limit=5000):
    out = []
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            for line in f.readlines()[-limit:]:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue          # a corrupt line is skipped, never fatal
    except OSError:
        pass
    return out


def _replay_agreement(root):
    """How often a replayed decision matched the original (replay.py)."""
    agree = {}
    try:
        with open(os.path.join(root, REPLAY_LOG), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = f"{r.get('provider')}:{r.get('model')}"
                a = agree.setdefault(key, [0, 0])
                a[1] += 1
                if r.get("agreed") or r.get("match"):
                    a[0] += 1
    except OSError:
        pass
    return {k: round(v[0] / v[1], 3) for k, v in agree.items() if v[1]}


def profiles(root, role=None):
    """-> {"provider:model": {n, pass_rate, verified_pass_rate, avg_cost...}}"""
    agg = {}
    for r in outcomes(root):
        if role and r.get("role") != role:
            continue
        key = f"{r.get('provider')}:{r.get('model')}"
        a = agg.setdefault(key, {"key": key, "provider": r.get("provider"),
                                 "model": r.get("model"), "n": 0, "passes": 0,
                                 "verified_n": 0, "verified_passes": 0,
                                 "cost": 0.0, "steps": 0})
        a["n"] += 1
        a["cost"] += float(r.get("cost_usd") or 0)
        a["steps"] += int(r.get("steps") or 0)
        ok = r.get("status") == "done"
        a["passes"] += 1 if ok else 0
        if r.get("verified"):
            a["verified_n"] += 1
            a["verified_passes"] += 1 if ok else 0
    agree = _replay_agreement(root)
    for a in agg.values():
        a["pass_rate"] = round(a["passes"] / a["n"], 3) if a["n"] else 0.0
        a["verified_pass_rate"] = (round(a["verified_passes"] / a["verified_n"], 3)
                                   if a["verified_n"] else None)
        a["avg_cost_usd"] = round(a["cost"] / a["n"], 6) if a["n"] else 0.0
        a["avg_steps"] = round(a["steps"] / a["n"], 1) if a["n"] else 0.0
        a["replay_agreement"] = agree.get(a["key"])
    return agg


def _price(cfg, provider, model):
    """Owner-declared price per 1M output tokens, when there is one."""
    prov = ((cfg or {}).get("providers", {}) or {}).get(provider, {}) or {}
    prices = prov.get("prices", {}) or {}
    for k in (model, "default"):
        if k in prices:
            try:
                return float(prices[k])
            except (TypeError, ValueError):
                pass
    return None


def candidates(rc):
    out = []
    for c in (rc.get("route_candidates") or []):
        if ":" in str(c):
            p, _, m = str(c).partition(":")
            out.append((p.strip(), m.strip()))
    return out


def choose(agent, role):
    """-> (provider, model, decision). Never raises: the static setting is
    always a valid answer, and it is what an unproven candidate falls back to."""
    rc = agent.role_cfg(role)
    static = (rc.get("provider"), rc.get("model"))
    if str(rc.get("route", "")).lower() != "auto":
        return static[0], static[1], {"routed": False, "rule": "static",
                                      "why": "this role is not on auto routing"}
    cands = candidates(rc)
    if not cands:
        return static[0], static[1], {
            "routed": False, "rule": "static",
            "why": "route = auto but no route_candidates were listed"}
    min_pass = float(rc.get("route_min_pass", DEFAULT_MIN_PASS))
    min_n = int(rc.get("route_min_n", DEFAULT_MIN_N))
    prof = profiles(agent.root, role)

    # EXPLORATION — without it this whole module was inert.
    #
    # A candidate needs `min_n` recorded outcomes to be eligible, and outcomes
    # are only recorded for the model that actually ran. So a model listed
    # ONLY in route_candidates was never tried, never accrued a run, and was
    # rejected forever with "only 0 run(s), N needed". The router could
    # confirm the configured default and could never replace it — which is
    # the one thing it exists to do.
    #
    # The fix is the cheapest possible: send every Nth task of this role to
    # the least-evidenced candidate. Deterministic (a counter, not a coin, so
    # a run is reproducible), bounded by the same gates and budget as any
    # other task, and it stops as soon as a candidate has enough evidence to
    # be judged on merit.
    unproven = [(f"{p}:{m}", p, m) for p, m in cands
                if (prof.get(f"{p}:{m}") or {}).get("n", 0) < min_n]
    every = int(rc.get("route_explore_every", DEFAULT_EXPLORE_EVERY))
    if unproven and every > 0:
        done = sum(pp.get("n", 0) for pp in prof.values())
        if done % every == every - 1:
            unproven.sort(key=lambda t: (prof.get(t[0]) or {}).get("n", 0))
            key, prov, model = unproven[0]
            have = (prof.get(key) or {}).get("n", 0)
            return prov, model, {
                "routed": True, "rule": "explore", "chosen": key,
                "why": (f"exploring {key}: {have}/{min_n} runs of evidence so "
                        f"far. A candidate that is never tried can never earn "
                        f"the bar, so every {every}th task samples the "
                        f"least-evidenced one."),
                "exploring": True}

    scored, rejected = [], []
    for prov, model in cands:
        key = f"{prov}:{model}"
        p = prof.get(key)
        if not p or p["n"] < min_n:
            rejected.append(f"{key}: only {(p or {}).get('n', 0)} run(s), "
                            f"{min_n} needed")
            continue
        rate = p["verified_pass_rate"]
        if rate is None:
            rate = p["pass_rate"]
        if rate < min_pass:
            rejected.append(f"{key}: {rate:.0%} pass, {min_pass:.0%} required")
            continue
        price = _price(agent.cfg, prov, model)
        cost = price if price is not None else p["avg_cost_usd"]
        scored.append((cost, prov, model, key, rate, p["n"]))
    if not scored:
        return static[0], static[1], {
            "routed": False, "rule": "static-fallback",
            "why": "no candidate has earned the bar yet: " + "; ".join(rejected),
            "rejected": rejected}
    scored.sort()
    cost, prov, model, key, rate, n = scored[0]
    return prov, model, {
        "routed": True, "rule": "auto", "chosen": key, "cost": cost,
        "why": (f"cheapest model clearing {min_pass:.0%} on this expert's own "
                f"gated work: {key} at {rate:.0%} over {n} run(s)"),
        "rejected": rejected}


def explain(agent, role):
    prov, model, d = choose(agent, role)
    return f"{role}: {prov}:{model}\n  {d['why']}"


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="capability routing from evidence")
    ap.add_argument("--root", default=".")
    ap.add_argument("--role")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if a.role:
        import loop
        agent = loop.Agent(root)
        prov, model, d = choose(agent, a.role)
        print(json.dumps({"provider": prov, "model": model, **d}, indent=1)
              if a.json else explain(agent, a.role))
        return
    prof = profiles(root)
    if a.json:
        print(json.dumps(prof, indent=1))
        return
    if not prof:
        print("no model outcomes recorded yet — run some gated work first")
    for p in sorted(prof.values(), key=lambda x: -x["n"]):
        vr = ("n/a" if p["verified_pass_rate"] is None
              else f"{p['verified_pass_rate']:.0%}")
        print(f"{p['key']:<44} n={p['n']:<4} pass={p['pass_rate']:.0%} "
              f"gated={vr:<5} ${p['avg_cost_usd']:.5f}/task "
              f"{p['avg_steps']} steps")


if __name__ == "__main__":
    main()
