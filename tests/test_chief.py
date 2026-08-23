#!/usr/bin/env python3
"""The Chief of Staff briefing: "what should I do today?" answered from the
fleet's real instruments, ranked by rules — zero model calls, so it cannot
hallucinate a priority.

Seeds a fleet with one of everything that should demand attention — a
blocked agent, a stalled pulse, an unfunded provider, an open gap, an
intention due within 24h, a fresh quarantined skill — and proves the
briefing finds each one and ranks them in the fixed order. Also: the quiet
fleet gets a calm ADVANCE, and the archetype template pack is present with
its safety boundaries intact.

Run from the agent/ directory:  python tests/test_chief.py
"""

import json
import os
import sys
import time

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import chief
import fleet
import prospective as pm
import skills as sg
import templates


def main():
    home = make_sandbox("chief", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})

    # a quiet fleet first: one calm ADVANCE, nothing invented
    fleet.create(home, "Calm One", "placid specialist")
    b = chief.briefing(home)
    assert [r["verb"] for r in b["recommendations"]] == ["ADVANCE"], \
        b["recommendations"]
    print("[quiet] an untroubled fleet gets one calm ADVANCE — no invented "
          "urgency")

    # --- now seed one of everything that demands attention
    root = os.path.join(home, "experts", "calm-one")

    # 1. blocked on the owner
    with open(os.path.join(root, "blocked.md"), "w", encoding="utf-8") as f:
        f.write("\n## 2026-08-21 10:00 — task ab12 (practitioner)\n"
                "Which supplier quote should I trust?\n")
    with open(os.path.join(root, "state.json"), "w", encoding="utf-8") as f:
        json.dump({"tasks": [
            {"id": "ab12", "role": "practitioner", "status": "blocked",
             "goal": "compare quotes", "steps": [], "cost_usd": 0,
             "created": "2026-08-21T10:00:00"},
            {"id": "cd34", "role": "practitioner", "status": "running",
             "goal": "long build", "steps": [1], "cost_usd": 0,
             "created": "2026-08-21T10:05:00"}]}, f)

    # 2. stalled pulse: claims running, pulse 20 minutes cold
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with open(os.path.join(root, "logs", "heartbeat.json"), "w",
              encoding="utf-8") as f:
        json.dump({"ts": time.time() - 1200, "pid": 1, "task": "cd34",
                   "role": "practitioner", "note": "working"}, f)

    # 3. unfunded provider (real type, key env never set)
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[providers.openrouter]\nbase_url = "https://openrouter.ai/api/v1"\n'
                'api_key_env = "TEST_NEVER_SET_KEY_XYZ"\n\n'
                "[roles.default]\nprovider = \"openrouter\"\nmodel = \"x\"\n")

    # 4. an open gap
    os.makedirs(os.path.join(root, "courses", "imports"), exist_ok=True)
    with open(os.path.join(root, "courses", "imports", "gaps.md"), "w",
              encoding="utf-8") as f:
        f.write("- G-001 duty rate for HS 8501 unverified\n")

    # 5. an intention due within 24h
    pm.add(root, {"kind": "at", "iso": time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 3600))},
        {"role": "practitioner", "goal": "re-check the tariff schedule"})

    # 6. a freshly quarantined skill
    os.makedirs(os.path.join(root, "skills"), exist_ok=True)
    with open(os.path.join(root, "skills", "bad-trick.md"), "w",
              encoding="utf-8") as f:
        f.write("KEYWORDS: trick\nbad advice\n")
    for i in range(3):
        sg.record_use(root, ["skills/bad-trick.md"], f"t{i}", success=False)

    b = chief.briefing(home)
    verbs = [r["verb"] for r in b["recommendations"]]
    for need in ("ANSWER", "RESTART", "FUND", "REPAIR", "PREPARE", "REVIEW"):
        assert need in verbs, f"missing {need}: {verbs}"
    assert verbs == sorted(verbs, key=["ANSWER", "RESTART", "FUND", "REPAIR",
                                       "PREPARE", "REVIEW", "HARVEST",
                                       "ADVANCE"].index), \
        f"the ranking must hold: {verbs}"
    byverb = {r["verb"]: r for r in b["recommendations"]}
    assert "supplier quote" in byverb["ANSWER"]["what"], \
        "the briefing must carry the actual question"
    assert "20m cold" in byverb["RESTART"]["what"].replace("cold_minutes", "") \
        or "cold" in byverb["RESTART"]["what"]
    assert "TEST_NEVER_SET_KEY_XYZ" in byverb["FUND"]["what"]
    assert "imports" in byverb["REPAIR"]["what"]
    assert "tariff schedule" in byverb["PREPARE"]["what"]
    assert "bad-trick" in byverb["REVIEW"]["what"]
    md = chief.render_markdown(b)
    assert md.startswith("# Today") and "**ANSWER**" in md
    print("[ranked] all six situations found from real instruments and "
          "ranked in the fixed order, each with the concrete detail")

    # --- the archetype pack: present, and boundaries written into charters
    ts = {t["slug"]: t for t in templates.TEMPLATES}
    assert len(ts) >= 19, len(ts)
    for slug in ("scout", "critic-sentinel", "market-researcher",
                 "competitive-intel", "trend-forecaster", "treasurer-analyst",
                 "tradeops-landed-cost", "local-radar", "seo-orchestrator"):
        assert slug in ts, slug
    assert "never investment advice" in ts["treasurer-analyst"]["specialty"]
    assert "licensed customs broker" in ts["tradeops-landed-cost"]["specialty"]
    assert "rollback" in ts["seo-orchestrator"]["specialty"].lower()
    assert "never fabricate" in ts["local-radar"]["specialty"] \
        or "never fabricate events" in ts["local-radar"]["specialty"]
    assert all(t["kind"] in ("advisor", "maker", "operator")
               for t in templates.TEMPLATES)
    print("[archetypes] 19 pluggable specialists; authority boundaries are "
          "written INTO the charters (analysis not advice, broker "
          "verification, rollback-gated changes)")
    print("PASS test_chief")


if __name__ == "__main__":
    main()
