#!/usr/bin/env python3
"""CONTRACT STATE MACHINE — exhaustively model-checked (register #62).

The register's highest-value formal target is the contract state machine.
A full TLA+/SPIN model needs tools this stdlib platform does not carry —
but the machine is small enough to check EXHAUSTIVELY against the real
implementation, which is better than a model of it:

  1. all |STATES|^2 transition attempts probed against transition() —
     accepted exactly when TRANSITIONS lists them, refused with the reason
     otherwise. Not a sample: every edge and every non-edge.
  2. graph properties proven over the declared machine and re-proven by
     probe: `verified` is reachable ONLY through `running`; terminal
     states (verified/partial/exhausted/failed) have no exits; every state
     is reachable from draft (no dead entries in the table).
  3. a seeded random walk of legal transitions replayed: replay() derives
     the same final state from the ledger alone, no divergence.
  4. a hand-edit of the snapshot AFTER the walk is flagged as divergence —
     the ledger wins over the file.

Run from the agent/ directory:  python tests/test_contract_model.py
"""

import json
import os
import random
import sys
from collections import deque

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import contract                # noqa: E402
import fleet                   # noqa: E402

TERMINAL = {"verified", "partial", "exhausted", "failed"}


def _force_state(root, gid, state):
    """Place the machine IN a state directly (harness-side test rig): the
    probe is about which EXITS transition() allows from there."""
    p = contract.path(root, gid)
    c = json.load(open(p, encoding="utf-8"))
    c["state"] = state
    with open(p, "w", encoding="utf-8") as f:
        json.dump(c, f)


def main():
    home = make_sandbox("contractmodel",
                        providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Modelcheck", "is a small exhaustive prover")
    contract.create(root, "g-model", "exhaustively probed goal",
                    accept=[{"id": "A1", "what": "n/a", "check": "true"}])

    # 1. every (from, to) pair — the full square, not a sample
    probed = accepted = refused = 0
    for src in contract.STATES:
        for dst in contract.STATES:
            _force_state(root, "g-model", src)
            legal = dst in contract.TRANSITIONS.get(src, ())
            probed += 1
            try:
                contract.transition(root, "g-model", dst, why="model probe")
                assert legal, (
                    f"transition() ACCEPTED {src} -> {dst}, which the "
                    f"declared machine forbids — the implementation is "
                    f"looser than its own table")
                accepted += 1
            except contract.ContractError as e:
                assert not legal, (
                    f"transition() REFUSED legal {src} -> {dst}: {e}")
                refused += 1
    n = len(contract.STATES)
    assert probed == n * n
    declared = sum(len(v) for v in contract.TRANSITIONS.values())
    assert accepted == declared and refused == n * n - declared

    # 2a. verified is reachable ONLY through running (checked on the graph,
    #     already re-proven edge-by-edge above)
    into_verified = [s for s, outs in contract.TRANSITIONS.items()
                    if "verified" in outs]
    assert into_verified == ["running"], (
        f"states that can reach verified directly: {into_verified} — the "
        f"only door to verified must be running, where the graders sit")
    # 2b. terminal states have no exits
    for t in TERMINAL:
        assert contract.TRANSITIONS.get(t) == (), (
            f"terminal state {t} has exits: {contract.TRANSITIONS.get(t)}")
    # 2c. every state is reachable from draft — no dead entries
    seen, q = {"draft"}, deque(["draft"])
    while q:
        for nxt in contract.TRANSITIONS.get(q.popleft(), ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    assert seen == set(contract.STATES), (
        f"unreachable states in the declared machine: "
        f"{set(contract.STATES) - seen}")

    # 3. seeded legal random walks; replay derives the same state from the
    #    ledger alone (walk on a FRESH contract so its ledger is coherent)
    rng = random.Random(62)
    for walk in range(6):
        gid = f"g-walk-{walk}"
        contract.create(root, gid, "replayed walk",
                        accept=[{"id": "A1", "what": "n/a", "check": "true"}])
        contract.freeze(root, gid)               # draft -> ready, on ledger
        state = "ready"
        for _ in range(rng.randint(1, 8)):
            outs = contract.TRANSITIONS.get(state, ())
            if not outs:
                break
            state = rng.choice(list(outs))
            contract.transition(root, gid, state, why="walk")
        rep = contract.replay(root, gid)
        assert not rep["diverges"], (walk, rep)
        assert rep["state"] == contract.load(root, gid)["state"] == state

    # 4. the ledger wins: a hand-edited snapshot is called out
    _force_state(root, "g-walk-0", "verified")
    rep = contract.replay(root, "g-walk-0")
    ledger_state = rep["state"]
    if ledger_state != "verified":
        assert rep["diverges"], (
            "the snapshot was forged to 'verified' and replay() saw no "
            "divergence — the forgery would have stood")

    print(f"[model] all {n}x{n}={probed} transition attempts probed: "
          f"{accepted} accepted (exactly the {declared} declared), "
          f"{refused} refused with the reason; verified's only door is "
          f"running; all 4 terminal states exitless; every state reachable "
          f"from draft; 6 seeded walks replayed from the ledger with zero "
          f"divergence; a forged snapshot flagged")
    print("PASS test_contract_model")


if __name__ == "__main__":
    main()
