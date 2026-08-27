#!/usr/bin/env python3
"""SWARM — multiplication only where the evidence says it pays.

The project calls for an agent "capable of multiplying itself until achieving
the goal". The controlled evidence says exactly when that helps and when it
destroys work: centralized coordination on genuinely decomposable tasks
gained up to ~81%, while on sequential tasks EVERY multi-agent variant
degraded performance 39-70% (Nature Machine Intelligence 2026,
s42256-026-01268-y). And the MAST taxonomy (arXiv:2503.13657, NeurIPS 2025)
clusters multi-agent failures into system design, inter-agent misalignment,
and workers certifying their own success.

swarm.py answers with four structural rules, each broken here:

  RULE 1 — sequential by default: independence is DECLARED by the caller
           (acceptance-test groups), never guessed. No declaration, no
           fan-out — however many tests are failing.
  RULE 2 — fan out only when it can pay: at least two declared groups,
           each with its OWN DISTINCT proven procedure. Groups without a
           procedure are the frontier, reported by name.
  RULE 3 — workers do not talk and do not grade: one immutable assignment
           each, no inter-worker channel exists, and the ONLY reducer is
           the frozen graders run centrally — a swarm whose workers all
           report success still fails when the graders refuse.
  RULE 4 — one worker per group, ever: a per-group lease makes duplicate
           execution across concurrent swarms impossible, not unlikely.

Plus: the worker cap holds with the overflow named, and the whole thing
runs with ZERO model calls — through goal.pursue end to end.

Run from the agent/ directory:  python tests/test_swarm.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import contract                # noqa: E402
import fleet                   # noqa: E402
import goal                    # noqa: E402
import runbook                 # noqa: E402
import swarm                   # noqa: E402

PY = sys.executable


def _exists(path):
    p = path.replace("\\", "/")
    return f'"{PY}" -c "import os,sys;sys.exit(0 if os.path.exists(r\'{p}\') else 1)"'


def _touch_cmd(path):
    p = path.replace("\\", "/")
    return (f'"{PY}" -c "import io,os;'
            f"os.makedirs(os.path.dirname(r'{p}'),exist_ok=True);"
            f"io.open(r'{p}','w',encoding='utf-8').write('made')\"")


def _proven(root, name, triggers, art):
    os.makedirs(os.path.join(root, "runbooks"), exist_ok=True)
    with open(runbook.path(root, name), "w", encoding="utf-8") as f:
        json.dump({"name": name, "triggers": triggers,
                   "steps": [{"do": _touch_cmd(art),
                              "verify": _exists(art)}]}, f)
    for _ in range(runbook.PROMOTE_WINS):
        assert runbook.run(root, name, allow_candidate=True)["ok"]
    if os.path.exists(art):
        os.remove(art)


def main():
    home = make_sandbox("swarm", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Multiplier", "many hands, one set of graders")

    check_rule1_sequential_by_default(root)
    check_rule2_fanout_must_pay(root)
    check_real_fanout_reduced_by_the_graders(root)
    check_rule4_leases_prevent_duplicates(root)
    check_rule3_workers_do_not_grade(root)
    check_the_cap_holds_with_overflow_named(root)
    check_pursue_end_to_end_zero_model(home)
    check_the_ledger_survives_concurrency(root)
    print("PASS test_swarm")


def check_the_ledger_survives_concurrency(root):
    """The event ledger under exactly the load a swarm creates.

    Found live before this existed: two workers emitted two events and the
    ledger held ONE. Windows append mode seeks to end-of-file when the
    handle OPENS, not per write, so concurrent appenders can land on the
    same offset and one row silently clobbers the other — in the file whose
    entire job is to be the source of truth. contract.event now takes the
    platform lock; this hammers it the way the swarm does and counts.
    """
    import threading
    contract.create(root, "g-hammer", "ledger under concurrency")
    contract.freeze(root, "g-hammer")
    base = len(contract.events(root, "g-hammer"))
    N_THREADS, N_EACH = 4, 25

    def hammer(tid):
        for i in range(N_EACH):
            contract.event(root, "g-hammer", "hammer", thread=tid, n=i)

    ts = [threading.Thread(target=hammer, args=(t,)) for t in range(N_THREADS)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    ev = contract.events(root, "g-hammer")
    rows = [e for e in ev if e.get("kind") == "hammer"]
    corrupt = [e for e in ev if e.get("kind") == "corrupt_line"]
    assert not corrupt, (
        f"{len(corrupt)} corrupt line(s) — concurrent appends interleaved "
        f"mid-row in the source-of-truth ledger")
    assert len(rows) == N_THREADS * N_EACH, (
        f"{N_THREADS * N_EACH} events were emitted and the ledger holds "
        f"{len(rows)} — rows were silently lost, which is how a worker's "
        f"death became invisible before the lock existed")
    assert len(ev) == base + N_THREADS * N_EACH
    print(f"[ledger] {N_THREADS} threads appended {N_THREADS * N_EACH} "
          f"events concurrently and the ledger holds exactly "
          f"{N_THREADS * N_EACH}, none corrupt — the append is a critical "
          f"section now, because it measurably was not one before")


def check_rule1_sequential_by_default(root):
    a1 = os.path.join(root, "out", "r1-a.txt")
    a2 = os.path.join(root, "out", "r1-b.txt")
    contract.create(root, "g-nogroup", "two failing tests, nothing declared",
                    accept=[{"id": "A1", "what": "alpha", "check": _exists(a1)},
                            {"id": "A2", "what": "beta", "check": _exists(a2)}])
    contract.freeze(root, "g-nogroup")
    p = swarm.plan(root, "g-nogroup")
    assert p["parallel"] is False, p
    assert "sequential by default" in p["why"], p["why"]
    assert len(p["failing"]) == 2, p
    print("[rule1] two failing acceptance tests with NO declared groups "
          "planned NO fan-out — independence is declared by the caller who "
          "wrote the graders, never guessed by the machine, because assumed "
          "separability is where the measured -39% to -70% lives")


def check_rule2_fanout_must_pay(root):
    a1 = os.path.join(root, "out", "r2-a.txt")
    a2 = os.path.join(root, "out", "r2-b.txt")
    contract.create(root, "g-samerb", "grouped but one procedure",
                    accept=[{"id": "A1", "what": "same thing left",
                             "check": _exists(a1), "group": "left"},
                            {"id": "A2", "what": "same thing right",
                             "check": _exists(a2), "group": "right"}])
    contract.freeze(root, "g-samerb")
    _proven(root, "same-thing", ["same", "thing"],
            os.path.join(root, "out", "r2-shared.txt"))
    p = swarm.plan(root, "g-samerb")
    assert p["parallel"] is False, p
    assert "cannot pay" in p["why"], p["why"]
    # one group with a procedure, one at the frontier -> named, no fan-out
    contract.create(root, "g-frontier", "one known one novel",
                    accept=[{"id": "A1", "what": "same thing again",
                             "check": _exists(a1), "group": "known"},
                            {"id": "A2", "what": "xylophone quantization",
                             "check": _exists(a2), "group": "novel"}])
    contract.freeze(root, "g-frontier")
    p2 = swarm.plan(root, "g-frontier")
    assert p2["parallel"] is False, p2
    assert "novel" in str(p2["why"]), (
        f"the group with no procedure must be NAMED as the frontier: "
        f"{p2['why']}")
    print("[rule2] two groups served by one shared procedure did not fan "
          "out (two workers, one procedure buys nothing), and a group with "
          "no proven procedure was named as the frontier instead of being "
          "improvised in parallel")


def check_real_fanout_reduced_by_the_graders(root):
    alpha = os.path.join(root, "out", "swarm-alpha.txt")
    beta = os.path.join(root, "out", "swarm-beta.txt")
    _proven(root, "make-alpha", ["alpha", "report"], alpha)
    _proven(root, "make-beta", ["beta", "index"], beta)
    contract.create(root, "g-fan", "produce the alpha report and beta index",
                    accept=[{"id": "A1", "what": "alpha report",
                             "check": _exists(alpha), "group": "ga"},
                            {"id": "A2", "what": "beta index",
                             "check": _exists(beta), "group": "gb"}])
    contract.freeze(root, "g-fan")
    st_path = os.path.join(root, "state.json")
    before = os.path.getmtime(st_path) if os.path.exists(st_path) else None

    p = swarm.plan(root, "g-fan")
    assert p["parallel"] is True, p
    r = swarm.run(root, "g-fan")
    assert r["verified"] is True and r["parallel"] is True, r
    assert {x["runbook"] for x in r["rounds"]} == {"make-alpha",
                                                  "make-beta"}, r
    assert os.path.exists(alpha) and os.path.exists(beta)
    assert contract.load(root, "g-fan")["state"] == "verified"

    ev = contract.events(root, "g-fan")
    kinds = [e["kind"] for e in ev]
    assert "swarm_started" in kinds, kinds
    assert kinds.count("swarm_worker") == 2, kinds
    started = next(e for e in ev if e["kind"] == "swarm_started")
    assert started["workers"] == 2 and set(started["groups"]) == {"ga", "gb"}
    # the graders spoke before the state moved — same law as everywhere
    vi = next(i for i, e in enumerate(ev)
              if e.get("kind") == "verify" and e.get("all") is True)
    si = next(i for i, e in enumerate(ev)
              if e.get("kind") == "state" and e.get("to") == "verified")
    assert vi < si, kinds
    after = os.path.getmtime(st_path) if os.path.exists(st_path) else None
    assert before == after, "the swarm touched the task queue — a model got involved"
    print("[fanout] two declared groups with two distinct proven procedures "
          "ran as two workers, both artifacts produced, and the state moved "
          "only after the central graders passed — with the task queue "
          "untouched: multiplication of MACHINE work, zero model calls")


def check_rule4_leases_prevent_duplicates(root):
    g1 = os.path.join(root, "out", "lease-a.txt")
    g2 = os.path.join(root, "out", "lease-b.txt")
    _proven(root, "lease-alpha", ["lease", "left"], g1)
    _proven(root, "lease-beta", ["lease", "right"], g2)
    contract.create(root, "g-lease", "the lease left and lease right work",
                    accept=[{"id": "A1", "what": "lease left",
                             "check": _exists(g1), "group": "L"},
                            {"id": "A2", "what": "lease right",
                             "check": _exists(g2), "group": "R"}])
    contract.freeze(root, "g-lease")
    # another swarm already owns group L: a FRESH lease file
    lease = os.path.join(root, "goals", "g-lease", "swarm-L") + ".lock"
    os.makedirs(os.path.dirname(lease), exist_ok=True)
    with open(lease, "w", encoding="utf-8") as f:
        f.write("9999:someothertoken")
    r = swarm.run(root, "g-lease")
    assert r["verified"] is False, r
    lrow = next(x for x in r["rounds"] if x["group"] == "L")
    assert not lrow["ok"] and "lease" in lrow["why"].lower(), lrow
    assert not os.path.exists(g1), (
        "the leased group's work RAN anyway — duplicate execution is "
        "exactly what the lease exists to make impossible")
    assert os.path.exists(g2), "the un-leased group must still have run"
    os.remove(lease)
    # only ONE group still fails now, so a raw run() correctly refuses to
    # fan out (RULE 1: one group is sequential work) — auto() is the entry
    # point, and it hands the remainder to the sequential reconcile path
    r2 = swarm.run(root, "g-lease")
    assert r2["parallel"] is False, (
        f"a single remaining group was fanned out: {r2} — one group IS "
        f"sequential work, and the rules must hold on the second pass too")
    r3 = swarm.auto(root, "g-lease")
    assert r3["verified"] is True, r3
    print("[rule4] a group whose lease was held by another swarm was NOT "
          "run twice — the worker reported the held lease, the other group "
          "proceeded; with the lease released, the single remaining group "
          "was correctly refused fan-out and finished on the sequential "
          "path instead")


def check_rule3_workers_do_not_grade(root):
    right = os.path.join(root, "out", "grade-right.txt")
    wrong = os.path.join(root, "out", "grade-wrong.txt")
    good = os.path.join(root, "out", "grade-good.txt")
    # a procedure that verifies ITS OWN step but produces the WRONG artifact
    # for the acceptance test — the worker will honestly report ok=True
    _proven(root, "wrong-artifact", ["grade", "widget"], wrong)
    _proven(root, "good-artifact", ["grade", "gadget"], good)
    contract.create(root, "g-grade2", "the grade widget and grade gadget",
                    accept=[{"id": "A1", "what": "grade widget",
                             "check": _exists(right), "group": "w"},
                            {"id": "A2", "what": "grade gadget",
                             "check": _exists(good), "group": "x"}])
    contract.freeze(root, "g-grade2")
    r = swarm.run(root, "g-grade2")
    assert all(x["ok"] for x in r["rounds"]), (
        f"precondition broken — both workers should report ok: {r['rounds']}")
    assert r["verified"] is False, (
        f"every worker said ok and the swarm called it VERIFIED anyway — "
        f"workers certifying their own success is MAST failure cluster "
        f"iii, and the reducer must be the graders alone: {r}")
    assert "counts for nothing" in r["blocked"], r["blocked"]
    assert "A1" in r["blocked"], r["blocked"]
    assert contract.load(root, "g-grade2")["state"] != "verified"
    print("[rule3] both workers reported success; the central graders "
          "refused A1 and the swarm result was NOT verified, with the "
          "refusing test named — a worker's opinion of its own work "
          "counts for nothing")


def check_the_cap_holds_with_overflow_named(root):
    arts = [os.path.join(root, "out", f"cap-{i}.txt") for i in range(3)]
    names = []
    for i, art in enumerate(arts):
        nm = f"cap-proc-{i}"
        _proven(root, nm, [f"capword{i}"], art)
        names.append(nm)
    contract.create(root, "g-cap",
                    "capword0 capword1 capword2 all at once",
                    accept=[{"id": f"A{i+1}", "what": f"capword{i}",
                             "check": _exists(a), "group": f"c{i}"}
                            for i, a in enumerate(arts)])
    contract.freeze(root, "g-cap")
    old = swarm.MAX_WORKERS
    swarm.MAX_WORKERS = 2
    try:
        r = swarm.run(root, "g-cap")
    finally:
        swarm.MAX_WORKERS = old
    assert len(r["rounds"]) == 2, (
        f"{len(r['rounds'])} workers ran under a cap of 2 — a ceiling that "
        f"does not hold is a target")
    ev = contract.events(root, "g-cap")
    started = [e for e in ev if e["kind"] == "swarm_started"][-1]
    assert started["capped_out"], (
        "the overflow group was dropped SILENTLY — a bound that hides what "
        "it dropped reads as 'covered everything' when it did not")
    print(f"[cap] a cap of 2 ran exactly 2 workers and NAMED the group it "
          f"could not take ({started['capped_out']}) instead of silently "
          f"dropping it")


def check_pursue_end_to_end_zero_model(home):
    root = fleet.create(home, "Parallel Rider", "grouped goals for pennies")
    with open(os.path.join(root, "settings.toml"), "w",
              encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\nmax_done_rejects = 1\n\n'
                '[providers.m]\ntype = "mock"\nscript = "scripts/w.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n')
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    with open(os.path.join(root, "scripts", "w.json"), "w",
              encoding="utf-8") as f:
        json.dump([], f)                    # a provider that fails every task
    left = os.path.join(root, "out", "e2e-left.txt")
    right = os.path.join(root, "out", "e2e-right.txt")
    _proven(root, "left-maker", ["left", "ledger"], left)
    _proven(root, "right-maker", ["right", "rollup"], right)

    rec = goal.pursue(
        home, "parallel-rider", "produce the left ledger and right rollup",
        cycles=3, drive=False, timeout=30,
        accept=[{"id": "A1", "what": "left ledger",
                 "check": _exists(left), "group": "gl"},
                {"id": "A2", "what": "right rollup",
                 "check": _exists(right), "group": "gr"}])
    assert rec["status"] == "achieved" and rec["verified"] is True, rec
    assert set(rec.get("runbook") or []) == {"left-maker", "right-maker"}, rec
    assert not rec["cycles"], rec
    st = os.path.join(root, "state.json")
    tasks = json.load(open(st, encoding="utf-8")).get("tasks", []) \
        if os.path.exists(st) else []
    assert tasks == [], (
        f"{len(tasks)} task(s) created — the model was consulted on a goal "
        f"two proven procedures could finish")
    print("[e2e] goal.pursue on a grouped goal fanned out to two workers "
          "and ended VERIFIED with zero tasks and zero model calls — "
          "against a provider rigged to fail any task, so only the machine "
          "path can explain the outcome")


if __name__ == "__main__":
    main()
