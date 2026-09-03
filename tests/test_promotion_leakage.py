#!/usr/bin/env python3
"""PROMOTION LEAKAGE — can any worker-writable path define success or
earned trust? Asked permanently, of every such path, by name.

The platform's central safety rule is

    experience -> CANDIDATE -> fresh independent evaluation -> PROVEN

so every file that records a verdict, a seal, a trust status, a proof
observation, an evaluation suite or an authority grant must be out of the
worker's reach. The 2026-09-02 consolidated audit asked for this to become
a dedicated suite rather than a one-time sweep (docs/DESIGN-P6.1, finding
11). For each path two things are checked:

  static    fileauth.zone_of classifies it CONTROL or RUNTIME — never
            workspace; the module-computed seal paths must resolve outside
            the root or under a CONTROL zone inside it (org/);
  dynamic   fileauth.resolve(root, path, "write", "agent") REFUSES it, while
            the harness actor is still allowed through (the ledgers must be
            writable by the platform, or nothing could ever be recorded).

The path constants the modules actually use are pinned to the enumeration,
so a renamed ledger cannot slip out of it. A new ledger that lands in a
workspace zone fails here with its name and what it decides.

First run found one: proof/observations.jsonl — the ledger proof.evaluate
derives every proof LEVEL from — sat in the agent's proof/ workspace.

Run from the agent/ directory:  python tests/test_promotion_leakage.py
"""
import os
import sys
import tempfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import contract                 # noqa: E402
import effects                  # noqa: E402
import fileauth                 # noqa: E402
import harness                  # noqa: E402
import procedure                # noqa: E402
import proof                    # noqa: E402
import runbook                  # noqa: E402
import skills                   # noqa: E402
import verifier                 # noqa: E402

# (root-relative path, what it decides)
IN_ROOT = [
    ("runbooks/trust.json", "procedure trust: candidate / proven / quarantined"),
    ("skills/graph.json", "skill promotion ledger"),
    ("candidates/task-1/2/score.json", "best-of-N gate score"),
    ("goals/g1/contract.json", "a goal's definition of done"),
    ("goals/g1/events.jsonl", "a goal's event ledger"),
    ("goals/g1/steering.jsonl", "the owner's steering channel"),
    ("missions/m1/mission.json", "the mission contract"),
    ("mastery/pack1/events.jsonl", "mastery verdict evidence"),
    ("courses/source-overrides.json", "source authority re-ratings"),
    ("frontier/frontier.json", "capability frontier ledger"),
    ("frontier/probes/p1.json", "a sealed capability probe"),
    ("acquisitions.json", "acquisition grants"),
    ("training/registry.json", "training promotion registry"),
    ("training/runs/r1/manifest.json", "training verifier pin"),
    ("proof/observations.jsonl", "proof-level evidence ledger"),
    ("memory/cases.jsonl", "the case ledger: did a fix hold, verified by a gate"),
    ("state.json", "task state, including every done_check"),
    ("settings.toml", "authority allowlists and providers"),
    ("identity.md", "a system prompt source"),
    ("identity.history.jsonl", "charter edit history"),
    ("prospective.json", "prospective ledger"),
    ("reconcilers.json", "reconciler declarations: a desired state and its proven restore"),
    ("safe_mode.json", "the fleet's safe-mode switch: fault protection the model cannot clear"),
    ("variants/manifest.json", "variant manifest"),
    ("mcp.json", "MCP server configuration"),
    ("approvals/pending.json", "approval decisions"),
    ("effects/x.json", "effect control"),
    ("org/seal.json", "the org seal"),
    ("commons-digest.md", "the fleet-attributed lessons block"),
    ("prompts/system.md", "prompt sources"),
    ("capabilities/x/__init__.py", "an acquired capability's install"),
    ("logs/effects.jsonl", "the exactly-once effects ledger"),
    ("logs/agent.log", "the event ledger every report reads"),
]


def check_constants_are_enumerated():
    listed = {rel for rel, _ in IN_ROOT}
    pins = {runbook.TRUST.replace("\\", "/"): "runbook.TRUST",
            "skills/" + skills.GRAPH: "skills.GRAPH",
            proof.LEDGER.replace("\\", "/"): "proof.LEDGER",
            effects.LEDGER.replace("\\", "/"): "effects.LEDGER"}
    for rel, what in pins.items():
        assert rel in listed, f"{what} = {rel!r} is not in the enumeration"
    for rel, _what in harness.LEDGERS:
        assert rel in listed, f"harness.LEDGERS entry {rel!r} is not enumerated"
    print(f"[constants] the {len(pins)} module path constants and every "
          f"harness ledger are pinned to the enumeration — a renamed ledger "
          f"cannot slip out of it")


def check_static_zones():
    workspace = []
    for rel, what in IN_ROOT:
        zone = fileauth.zone_of(rel)
        if zone not in (fileauth.ZONE_CONTROL, fileauth.ZONE_RUNTIME):
            workspace.append(f"{rel} ({what}) is {zone}")
    assert not workspace, (
        "paths that DEFINE success or trust sit in a worker-writable zone:\n  "
        + "\n  ".join(workspace))
    print(f"[static] all {len(IN_ROOT)} trust-defining paths classify CONTROL "
          f"or RUNTIME — none is workspace")


def check_dynamic_refusals(root):
    leaked = []
    for rel, what in IN_ROOT:
        try:
            fileauth.resolve(root, rel, "write", "agent")
            leaked.append(f"{rel} ({what})")
        except fileauth.Denied:
            pass
    assert not leaked, ("the file authority let an AGENT write:\n  "
                        + "\n  ".join(leaked))
    # the platform itself must still be able to record: the harness actor
    # goes through, or no ledger could ever be written
    for rel in ("runbooks/trust.json", "proof/observations.jsonl",
                "logs/effects.jsonl"):
        fileauth.resolve(root, rel, "write", "harness")
    print(f"[dynamic] the file authority refused an agent write to every one "
          f"of the {len(IN_ROOT)} paths and still admits the harness")


def check_seals_are_control_zoned(root):
    """The seals — procedure authority, the verifier registry, the goal
    contract seal — are computed by their modules, not enumerated by hand
    above. Wherever they resolve, they must be out of the worker's reach:
    outside the expert root, or inside it under a CONTROL zone that the
    file authority refuses to the agent actor."""
    real = os.path.realpath(root)
    seals = {
        "procedure authority (judges, suites, trajectories, receipts)":
            procedure.authority_path(root),
        "verifier registry (candidate / calibrated / trusted)":
            verifier.state_path(root),
        "goal contract seal": contract.seal_path(root)[0],
    }
    problems = []
    for what, path in seals.items():
        full = os.path.realpath(path)
        if not full.startswith(real + os.sep):
            continue                # outside the root: unreachable by construction
        rel = os.path.relpath(full, real).replace("\\", "/")
        zone = fileauth.zone_of(rel)
        if zone != fileauth.ZONE_CONTROL:
            problems.append(f"{what}: {rel} is {zone}")
            continue
        try:
            fileauth.resolve(root, rel, "write", "agent")
            problems.append(f"{what}: {rel} is agent-writable")
        except fileauth.Denied:
            pass
    assert not problems, ("a seal is within the worker's reach:\n  "
                          + "\n  ".join(problems))
    print("[seals] procedure authority, the verifier registry and the goal "
          "contract seal resolve under org/ — CONTROL, refused to the agent "
          "actor — where the worker cannot reach them")


def main():
    root = tempfile.mkdtemp(prefix="leakage-")
    check_constants_are_enumerated()
    check_static_zones()
    check_dynamic_refusals(root)
    check_seals_are_control_zoned(root)
    print("PASS test_promotion_leakage")


if __name__ == "__main__":
    main()
