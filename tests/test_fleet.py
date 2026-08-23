#!/usr/bin/env python3
"""The expert fleet: one-command duplication, private identity, isolated memory.

Run from the agent/ directory:  python tests/test_fleet.py
"""

import os
import shutil
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import fleet
import loop

FINISH = [{"tool": "finish_task", "args": {"summary": "ok"}}]


def main():
    home = make_sandbox("fleet", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": FINISH})

    # create two experts from the same template
    alpha = fleet.create(home, "Backoff Master", "exponential backoff and retries")
    beta = fleet.create(home, "Shopify Pro", "the Shopify admin API")
    # the sandbox settings reference a mock script; give each expert its copy
    shutil.copy(os.path.join(home, "s.json"), os.path.join(alpha, "s.json"))
    shutil.copy(os.path.join(home, "s.json"), os.path.join(beta, "s.json"))
    assert os.path.basename(alpha) == "backoff-master"
    for root in (alpha, beta):
        for rel in ("identity.md", "settings.toml", "prompts/constitution.md",
                    "inbox", "skills"):
            assert os.path.exists(os.path.join(root, rel)), f"missing {rel} in {root}"

    # duplicate names are refused, memory is never silently overwritten
    try:
        fleet.create(home, "Backoff Master", "x")
        raise AssertionError("duplicate create must be refused")
    except SystemExit:
        pass

    # identity enters the system prompt, after the constitution
    sp = loop.Agent(alpha).system_prompt("tester")
    assert "Backoff Master" in sp and "exponential backoff" in sp
    assert sp.index("CONSTITUTION") < sp.index("Backoff Master"), \
        "the constitution must outrank the identity"
    assert "Shopify" not in sp, "identities must not bleed between experts"
    print("[identity] each expert carries its own identity, under the constitution")

    # isolated state: a task run in alpha leaves no trace in beta
    a = loop.Agent(alpha)
    a.add_task("tester", "alpha private work")
    a.run(drain=True)
    assert a.load_state()["tasks"][0]["status"] == "done"
    assert not os.path.exists(os.path.join(beta, "state.json")), \
        "beta must have no state from alpha's work"
    print("[isolation] alpha worked; beta's memory untouched")

    # the fleet reports both, with live counts
    listing = {e["name"]: e for e in fleet.list_experts(home)}
    assert set(listing) == {"backoff-master", "shopify-pro"}
    assert listing["backoff-master"]["tasks"]["done"] == 1
    assert listing["shopify-pro"]["tasks"]["done"] == 0
    assert "Shopify" in listing["shopify-pro"]["identity"]
    print("[fleet] list shows both experts with independent task counts")
    print("PASS test_fleet")


if __name__ == "__main__":
    main()
