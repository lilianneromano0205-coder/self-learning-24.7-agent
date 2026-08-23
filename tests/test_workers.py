#!/usr/bin/env python3
"""COMPUTERS: the cheapest SAFE one that can actually do the work.

Manual §13 and UI spec §7. Two claims worth testing, because both are easy
to get subtly wrong:

  * "cheapest" must never outrank "safe". A free, instantly-available
    organization machine on the internal network would win every tie-break
    on cost and latency — and would quietly become the default computer for
    arbitrary model-authored work. Isolation outranks speed.
  * the choice must be EXPLAINABLE. UI spec §7: a mission should say
    "Using Office Windows PC because Excel + internal network are required",
    not print a backend name.

Run from the agent/ directory:  python tests/test_workers.py
"""

import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import workers              # noqa: E402


def _fleet(home):
    workers.register(home, "Local Docker", "local-docker",
                     ["docker", "install", "node", "browser"])
    workers.register(home, "Office Windows PC", "fleet-worker",
                     ["excel", "office", "internal-network", "windows",
                      "gui", "browser"], note="the machine in the back office")
    workers.register(home, "GPU Box", "gpu-worker", ["gpu", "install"])
    workers.register(home, "This Computer", "local-host",
                     ["install", "excel", "internal-network", "gui"])


def check_registry(home):
    _fleet(home)
    rows = workers.load(home)
    assert len(rows) == 4
    by_id = {r["id"]: r for r in rows}
    assert by_id["local-docker"]["zone"] == "isolated"
    assert by_id["office-windows-pc"]["zone"] == "org"
    assert by_id["this-computer"]["zone"] == "trusted"
    # a scale-to-zero worker starts stopped: an expert must not imply an
    # always-on machine (manual §13 cost principle)
    assert by_id["gpu-box"]["state"] == "stopped"
    assert by_id["gpu-box"]["scales_to_zero"]
    try:
        workers.register(home, "Local Docker", "local-docker")
        raise AssertionError("duplicate ids must be refused")
    except ValueError:
        pass
    try:
        workers.register(home, "Weird", "quantum-toaster")
        raise AssertionError("an unknown worker kind must be refused")
    except ValueError:
        pass
    print(f"[registry] {len(rows)} computers registered with zone, capability "
          f"and cost; scale-to-zero kinds start stopped, so one expert does "
          f"not imply one always-on machine")


def check_isolation_outranks_speed(home):
    """The bug this test exists for: a free, instant ORG machine beating a
    disposable container on a tie-break, and silently becoming the default."""
    w, why = workers.choose(home, "write a python script that parses a CSV")
    assert w["id"] == "local-docker", (
        f"ordinary work must run in the most isolated computer available, "
        f"got {w['id']} ({w['zone']}). Both are free and the org machine "
        f"starts faster — which is exactly why cost and latency must not be "
        f"the only tie-breaks.")
    assert w["zone"] == "isolated"
    print("[isolation] free work went to the disposable container, not to the "
          "equally-free, faster-starting organization machine — blast radius "
          "outranks speed")


def check_trusted_is_never_automatic(home):
    for task in ("do anything", "install a package", "write a report",
                 "open a file"):
        w, _ = workers.choose(home, task)
        assert w is None or w["zone"] != "trusted", (
            f"the owner's own machine must never be chosen automatically for "
            f"model-authored work; got {w['id']} for {task!r}")
    # it is available when the operator explicitly allows it
    w, _ = workers.choose(home, "use excel on the internal network",
                          allow_trusted=True)
    assert w is not None
    print("[trusted] the owner's own machine is never selected automatically; "
          "it becomes eligible only when explicitly allowed")


def check_capability_matching(home):
    w, why = workers.choose(home, "update the Excel sheet on the internal network")
    assert w["id"] == "office-windows-pc", why
    assert "excel" in why["needed"] and "internal-network" in why["needed"]

    w, why = workers.choose(home, "fine-tune a model on the GPU")
    assert w["id"] == "gpu-box", why

    # something nothing can do is refused with the reason, not silently
    # dropped onto whatever was closest
    w, why = workers.choose(home, "run this on macos")
    assert w is None
    assert "macos" in why["needed"]
    assert "no registered computer" in why["why"]
    assert all(c["why_not"] for c in why["considered"] if not c["eligible"])
    print("[matching] requirements are read from the task text; an impossible "
          "requirement returns no computer AND the reason each one was "
          "ineligible, instead of falling back to whatever was nearest")


def check_explanation_is_human(home):
    w, why = workers.choose(home, "update the Excel sheet on the internal network")
    text = why["why"]
    assert text.startswith("Using Office Windows PC because"), text
    assert "excel" in text and "internal-network" in text
    assert "fleet-worker" not in text, (
        "the sentence must name the computer and the reason, not the backend "
        "kind — UI spec §7")
    print(f"[explain] the choice reads as a sentence: {text!r}")


def check_policy_scoping(home):
    """An organization machine can be restricted to named experts."""
    workers.register(home, "Finance Server", "fleet-worker",
                     ["excel", "internal-network", "finance-db"],
                     experts=["treasurer"])
    w, why = workers.choose(home, "query the finance-db", expert="marketer")
    assert w is None or "finance" not in w["id"], why
    blocked = [c for c in why["considered"] if c["id"] == "finance-server"]
    assert blocked and "policy" in (blocked[0]["why_not"] or ""), blocked
    w, why = workers.choose(home, "query the finance-db", expert="treasurer")
    assert w and w["id"] == "finance-server", why
    print("[policy] a computer restricted to named experts is invisible to "
          "the others, and the refusal says it was policy rather than "
          "capability")


def check_cost_accrues_only_when_used(home):
    before = workers.get(home, "gpu-box")["spend_usd"]
    assert before == 0.0, "a stopped computer costs nothing"
    workers.set_state(home, "gpu-box", "online")
    workers.note_use(home, "gpu-box", seconds=3600)
    after = workers.get(home, "gpu-box")
    assert abs(after["spend_usd"] - 2.50) < 0.01, after["spend_usd"]
    assert after["last_used"]
    workers.set_state(home, "gpu-box", "stopped")
    workers.note_use(home, "gpu-box", seconds=0)
    assert abs(workers.get(home, "gpu-box")["spend_usd"] - 2.50) < 0.01, (
        "a stopped computer must not keep accruing")
    print("[cost] an idle computer accrued nothing, an hour of GPU time "
          "accrued $2.50, and stopping it stopped the meter")


def main():
    sb = make_sandbox("workers", providers={"m": {"script": "s.json"}},
                      roles={"practitioner": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    check_registry(sb)
    check_isolation_outranks_speed(sb)
    check_trusted_is_never_automatic(sb)
    check_capability_matching(sb)
    check_explanation_is_human(sb)
    check_policy_scoping(sb)
    check_cost_accrues_only_when_used(sb)
    print("PASS test_workers")


if __name__ == "__main__":
    main()
