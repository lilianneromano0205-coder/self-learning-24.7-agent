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
    # §11's policy decides the TIE-BREAK among models that already cleared the
    # bar. "Cheapest that works" and "the one that works best" are different
    # answers to the same evidence, and the owner is entitled to say which.
    prefer = str(rc.get("route_prefer", "cost")).lower()
    if prefer == "quality":
        scored.sort(key=lambda t: (-t[4], t[0]))
    else:
        scored.sort()
    cost, prov, model, key, rate, n = scored[0]
    return prov, model, {
        "routed": True, "rule": "auto", "chosen": key, "cost": cost,
        "prefer": prefer,
        "why": ((f"best verified pass rate clearing {min_pass:.0%} on this "
                 f"expert's own gated work: {key} at {rate:.0%} over "
                 f"{n} run(s)") if prefer == "quality" else
                (f"cheapest model clearing {min_pass:.0%} on this expert's own "
                 f"gated work: {key} at {rate:.0%} over {n} run(s)")),
        "rejected": rejected}


# ---------------------------------------------------------------- policies
# UI spec §11: "Move Models out of the primary navigation. Normal user chooses
# policy: Cheapest, Balanced, Highest Quality, or Custom budget/risk profile."
#
# A policy is not a new mechanism. It is a NAME for the two numbers this
# router already reads — the bar a model must clear, and what breaks the tie
# among the models that clear it. Inventing a parallel decision path would
# mean two things that pick models, and eventually they would disagree.
POLICIES = {
    "cheapest": {
        "min_pass": 0.50, "prefer": "cost",
        "label": "Cheapest",
        "means": "the least expensive model that still passes half its gates",
        "costs_you": "more retries, so the saving is smaller than it looks",
    },
    "balanced": {
        "min_pass": 0.80, "prefer": "cost",
        "label": "Balanced",
        "means": "the cheapest model that clears a high bar on this expert's "
                 "own gated work",
        "costs_you": "nothing obvious — this is the default for a reason",
    },
    "quality": {
        "min_pass": 0.90, "prefer": "quality",
        "label": "Highest quality",
        "means": "the model with the best verified pass rate, cost second",
        "costs_you": "money; use it where being wrong is expensive",
    },
}


def policy_of(root):
    """Which named policy this expert's settings currently correspond to.

    Derived by comparing the settings to the presets rather than stored, for
    the same reason proof levels are derived: a stored label and the settings
    it claims to describe drift apart, and then the label is a lie.
    """
    cfg = _load_cfg(root)
    roles = cfg.get("roles", {})
    on_auto = [r for r in roles.values()
               if str(r.get("route", "")).lower() == "auto"]
    if not on_auto:
        return {"policy": "manual", "label": "Pinned models",
                "means": "each role uses exactly the model you set; nothing "
                         "is chosen automatically",
                "roles_on_auto": 0, "roles_total": len(roles)}
    bars = {float(r.get("route_min_pass", DEFAULT_MIN_PASS)) for r in on_auto}
    prefs = {str(r.get("route_prefer", "cost")).lower() for r in on_auto}
    for name, p in POLICIES.items():
        if bars == {p["min_pass"]} and prefs == {p["prefer"]}:
            return {"policy": name, **p, "roles_on_auto": len(on_auto),
                    "roles_total": len(roles)}
    say_bar = " or ".join(f"{b:.0%}" for b in sorted(bars))
    say_pref = " and ".join("cheapest that clears it" if x == "cost"
                            else "best that clears it" for x in sorted(prefs))
    return {"policy": "custom", "label": "Custom",
            "means": (f"a {say_bar} verified bar, then {say_pref} — your own "
                      f"setting, not one of the presets"),
            "min_pass": min(bars), "prefer": sorted(prefs)[0],
            "roles_on_auto": len(on_auto), "roles_total": len(roles)}


def set_policy(root, name, min_pass=None, prefer=None, roles=None):
    """Apply a policy to every auto-routable role, or to the named ones.

    Returns what changed, per role, because a settings write nobody can see
    the effect of is a settings write nobody trusts.
    """
    import providers as P
    if name in POLICIES:
        bar = POLICIES[name]["min_pass"]
        pref = POLICIES[name]["prefer"]
    elif name == "manual":
        # pin every role to exactly the model it is set to. The branch below
        # is what does the work; these values are only what gets reported.
        bar, pref = DEFAULT_MIN_PASS, "cost"
    elif name == "custom":
        if min_pass is None:
            raise ValueError("a custom policy needs its own bar (min_pass)")
        bar, pref = float(min_pass), str(prefer or "cost").lower()
        if not 0.0 <= bar <= 1.0:
            raise ValueError("the bar is a pass RATE between 0 and 1")
        if pref not in ("cost", "quality"):
            raise ValueError("prefer must be 'cost' or 'quality'")
    else:
        raise ValueError(f"unknown policy {name!r}; the presets are: "
                         + ", ".join(sorted(POLICIES)) + ", custom, manual")
    cfg = _load_cfg(root)
    changed = {}
    for role, rc in cfg.get("roles", {}).items():
        if roles and role not in roles:
            continue
        if name == "manual":
            was, rc["route"] = rc.get("route"), "static"
        else:
            was = (rc.get("route"), rc.get("route_min_pass"),
                   rc.get("route_prefer"))
            rc["route"] = "auto"
            rc["route_min_pass"] = bar
            rc["route_prefer"] = pref
        changed[role] = {"was": was, "now": (rc.get("route"), bar, pref)}
    P.save(root, cfg)
    return {"policy": name, "min_pass": bar, "prefer": pref,
            "roles": changed}


def _load_cfg(root):
    import providers as P
    return P.load(root)


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
