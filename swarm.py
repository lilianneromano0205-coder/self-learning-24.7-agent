#!/usr/bin/env python3
"""SWARM — a goal multiplies its workers, only where the evidence says to.

THE REQUIREMENT. The owner asked for an agent "capable of multiplying
itself until achieving the goal". The research record says precisely when
that helps and when it destroys the work, and this module is gated on it:

  * Nature Machine Intelligence 2026 (s42256-026-01268-y), 260 controlled
    experiments: centralized coordination on genuinely DECOMPOSABLE tasks
    improved outcomes by up to ~81%; on SEQUENTIAL tasks every multi-agent
    variant tested DEGRADED performance by 39–70%. More agents are not
    monotonically better — they are better exactly where the work is
    separable, and worse everywhere else.
  * MAST — "Why Do Multi-Agent LLM Systems Fail?" (arXiv:2503.13657,
    NeurIPS 2025): 14 failure modes in 3 clusters — system design,
    INTER-AGENT MISALIGNMENT, and TASK VERIFICATION (workers certifying
    their own success). The cure for a failure taxonomy is a structure in
    which the failures cannot be expressed.

Those two results become four structural rules:

  RULE 1 — SEQUENTIAL BY DEFAULT; INDEPENDENCE IS DECLARED, NOT GUESSED.
    A machine cannot know that two acceptance tests do not share hidden
    state. The CALLER — who wrote the graders — declares separability by
    giving acceptance tests a `group`; tests in different groups may run in
    parallel, tests without a group never do. No declaration, no fan-out:
    the Nature-MI degradation numbers are for exactly the case where
    separability was assumed instead of known.
  RULE 2 — FAN OUT ONLY WHEN IT CAN PAY. Parallelism needs at least two
    groups, each with its OWN distinct proven runbook. Two groups served
    by the same procedure gain nothing from two workers, and a group with
    no proven procedure has nothing to run — the coordination cost is paid
    only where there is separable work to buy with it.
  RULE 3 — WORKERS DO NOT TALK, AND DO NOT GRADE. Each worker gets one
    immutable assignment (one group, one runbook) and runs it to
    completion or failure. There is no inter-worker channel to misalign
    (MAST cluster ii has no syntax here), and a worker's opinion of its
    own success is advisory noise: the only reducer is `runbook.settle`,
    which runs ALL the frozen acceptance tests centrally, once, at the
    end (MAST cluster iii, solved structurally).
  RULE 4 — ONE WORKER PER GROUP, EVER. A per-group lease (O_EXCL, stale-
    broken, ownership-verified release — the platform's own lock
    primitive) makes duplicate execution across concurrent swarms
    impossible rather than unlikely. Kubernetes documents that jobs can
    start twice; this platform assumes the same and leases anyway.

Zero model calls throughout — the swarm multiplies MACHINE work.
The frontier (a group with no proven procedure) is reported by name, and
is the model's job or the owner's, never improvised in parallel.

    python swarm.py plan <root> <gid>
    python swarm.py run  <root> <gid> [--allow-candidates]
"""

import argparse
import json
import os
import sys
import threading
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

MAX_WORKERS = 4          # a ceiling, not a target
WORKER_STALE = 900.0     # a lease older than this belongs to a dead worker
SEQ = "__sequential__"


# -------------------------------------------------------------------- plan

def plan(root, gid, allow_candidates=False):
    """Observe the failing acceptance tests and decide, from declared
    groups and available procedures, whether parallelism can pay.

    -> {"parallel": bool, "why": str, "groups": [...], "failing": [...]}
    Never guesses independence (RULE 1) and never plans a fan-out that
    cannot pay (RULE 2)."""
    import contract
    import runbook
    c = contract.load(root, gid)
    vr = contract.verify(root, gid)
    if vr.get("tamper"):
        return {"parallel": False, "why": vr["why"], "groups": [],
                "failing": []}
    if not vr.get("mechanical"):
        return {"parallel": False, "groups": [], "failing": [],
                "why": "no mechanical acceptance tests — nothing a swarm "
                       "could divide"}
    if vr.get("all"):
        return {"parallel": False, "groups": [], "failing": [],
                "why": "already passing — nothing to do"}

    by_id = {a["id"]: a for a in (c.get("acceptance") or [])}
    failing = [by_id[i] for i in vr["failed"] if i in by_id]
    groups = {}
    for a in failing:
        g = str(a.get("group") or "").strip() or SEQ
        groups.setdefault(g, []).append(a)

    declared = {g: tests for g, tests in groups.items() if g != SEQ}
    if len(declared) < 2:
        return {"parallel": False, "groups": [], "failing": vr["failed"],
                "why": ("independence was not declared for at least two "
                        "groups of failing tests — sequential by default: "
                        "assumed separability is where multi-agent "
                        "degradation lives (Nature MI 2026, -39% to -70% "
                        "on sequential work)")}

    # RULE 2: each group needs its own distinct proven procedure
    assigned, seen_rb = [], set()
    for g, tests in sorted(declared.items()):
        # THE GROUP'S OWN TESTS ARE THE QUERY — not the goal text. Measured:
        # with the goal included, a goal naming both halves ("produce the
        # alpha report and beta index") made EVERY group match the same
        # runbook, because each group's query carried the other group's
        # words. Two groups, one procedure, no fan-out — a matching defect
        # masquerading as a payment-gate refusal.
        q = " ".join(t.get("what", "") for t in tests)
        hits = runbook.match(root, q, allow_candidates=allow_candidates)
        if not hits:
            hits = runbook.match(root, f"{c['goal']} {q}",
                                 allow_candidates=allow_candidates)
        rb = hits[0]["name"] if hits else None
        assigned.append({"group": g, "tests": [t["id"] for t in tests],
                         "runbook": rb})
        if rb:
            seen_rb.add(rb)
    runnable = [a for a in assigned if a["runbook"]]
    distinct = len({a["runbook"] for a in runnable})
    if len(runnable) < 2 or distinct < 2:
        return {"parallel": False, "groups": assigned,
                "failing": vr["failed"],
                "why": (f"{len(runnable)} group(s) have a matching "
                        f"procedure and {distinct} are distinct — "
                        f"parallelism cannot pay here; the groups without "
                        f"a procedure are the frontier, named: "
                        f"{[a['group'] for a in assigned if not a['runbook']]}")}
    return {"parallel": True, "groups": assigned, "failing": vr["failed"],
            "why": f"{len(runnable)} independent group(s), each with its "
                   f"own proven procedure"}


# --------------------------------------------------------------------- run

def _worker(root, gid, assignment, allow_candidates, results, idx):
    """One immutable assignment, one lease, no channel to anyone (RULE 3/4).
    The result it writes is ADVISORY — the reducer is the graders."""
    import contract
    import locks
    import runbook
    g = assignment["group"]
    lease = os.path.join(root, "goals", str(gid), f"swarm-{g}")
    try:
        with locks.holding(lease, timeout=0.5, stale=WORKER_STALE):
            rr = runbook.run(root, assignment["runbook"],
                             allow_candidate=allow_candidates)
            contract.event(root, gid, "swarm_worker", group=g,
                           runbook=assignment["runbook"],
                           ok=bool(rr["ok"]), why=rr["why"][:150])
            results[idx] = {"group": g, "runbook": assignment["runbook"],
                            "ok": bool(rr["ok"]), "why": rr["why"]}
    except TimeoutError:
        contract.event(root, gid, "swarm_worker", group=g,
                       runbook=assignment["runbook"], ok=False,
                       why="lease held elsewhere — another worker owns "
                           "this group")
        results[idx] = {"group": g, "runbook": assignment["runbook"],
                        "ok": False,
                        "why": "lease held by another worker; not run "
                               "twice (RULE 4)"}
    except Exception as e:
        # A WORKER THAT DIES MUST STILL REPORT. The first version caught
        # only the lease timeout; any other exception killed the thread
        # silently, and run() then FILTERED the empty slot away — so a
        # crashed worker looked like one that was never started, while its
        # half-done side effects stayed on disk. Found live: two workers,
        # one ledger row (the unlocked-append defect in contract.event was
        # the trigger; this catch-all is the belt to that buckle). Every
        # exception becomes a result row and an event; nothing about a
        # worker's death is inferred from its silence.
        try:
            contract.event(root, gid, "swarm_worker", group=g,
                           runbook=assignment["runbook"], ok=False,
                           why=f"worker died: {type(e).__name__}: {e}"[:150])
        except Exception:
            pass
        results[idx] = {"group": g, "runbook": assignment["runbook"],
                        "ok": False,
                        "why": f"worker died: {type(e).__name__}: {e}"[:200]}


def run(root, gid, allow_candidates=False):
    """Fan out where the plan says it pays, then let the graders reduce.

    Returns {"verified", "parallel", "rounds", "blocked"} — the same shape
    reconcile returns, because the caller should not care which path won.
    """
    import contract
    import runbook
    p = plan(root, gid, allow_candidates=allow_candidates)
    if not p["parallel"]:
        return {"verified": False, "parallel": False, "rounds": [],
                "blocked": p["why"]}
    work = [a for a in p["groups"] if a["runbook"]][:MAX_WORKERS]
    dropped = [a["group"] for a in p["groups"] if a["runbook"]][MAX_WORKERS:]
    contract.event(root, gid, "swarm_started",
                   workers=len(work), groups=[a["group"] for a in work],
                   capped_out=dropped)
    results = [None] * len(work)
    threads = []
    for i, a in enumerate(work):
        t = threading.Thread(target=_worker,
                             args=(root, gid, a, allow_candidates,
                                   results, i), daemon=True)
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    # a None here means a worker died without even its catch-all firing —
    # report it as what it is; filtering it away made a crashed worker
    # indistinguishable from one that was never started
    rounds = [r if r else {"group": work[i]["group"],
                           "runbook": work[i]["runbook"], "ok": False,
                           "why": "worker vanished without reporting"}
              for i, r in enumerate(results)]

    # RULE 3: the ONLY reducer. Worker ok-flags are advisory; the graders
    # run every acceptance test centrally and alone decide the state.
    st = runbook.settle(root, gid)
    verified = bool(st["verified"])
    if not verified:
        failed = st["vr"].get("failed") or []
        blocked = (f"workers finished ({sum(1 for r in rounds if r['ok'])}"
                   f"/{len(rounds)} reported ok) but the graders still "
                   f"refuse {len(failed)} acceptance test(s): "
                   f"{', '.join(failed)} — a worker's opinion of its own "
                   f"work counts for nothing here")
    else:
        blocked = ""
    return {"verified": verified, "parallel": True, "rounds": rounds,
            "blocked": blocked}


def auto(root, gid, allow_candidates=False):
    """The one entry point goal.pursue uses: parallel where declared and
    payable, sequential reconcile everywhere else — the caller gets one
    shape back either way."""
    import runbook
    p = plan(root, gid, allow_candidates=allow_candidates)
    if p["parallel"]:
        r = run(root, gid, allow_candidates=allow_candidates)
        if r["verified"]:
            return r
        # the swarm did what it could; whatever remains is sequential work
        # or frontier — the ordinary reconcile states it honestly
    return runbook.reconcile(root, gid, allow_candidates=allow_candidates)


# --------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        pp = sub.add_parser(name)
        pp.add_argument("root"); pp.add_argument("gid")
        pp.add_argument("--allow-candidates", action="store_true")
    a = ap.parse_args()
    if a.cmd == "plan":
        print(json.dumps(plan(a.root, a.gid,
                              allow_candidates=a.allow_candidates), indent=1))
    else:
        r = run(a.root, a.gid, allow_candidates=a.allow_candidates)
        print(json.dumps(r, indent=1))
        raise SystemExit(0 if r["verified"] else 1)


if __name__ == "__main__":
    main()
