#!/usr/bin/env python3
"""THE GOAL CONTRACT — the graders the worker cannot write.

The external audit of this platform put its finger on the one hole in goal
pursuit: THE PLANNER WRITES ITS OWN GRADERS. Milestone CHECK commands are
authored by the same model family that then works to satisfy them, so a plan
under pressure can grade itself generously — `test -f notes.md` instead of
"the exam scored 90" — and the judge cannot help, because the judge reads
the same plan. That is reward hacking, and no prompt fixes it.

The contract is the structural fix, and every property of it is pinned here:

  1. acceptance tests are frozen BEFORE planning and sealed OUTSIDE the
     expert's working root; verify() runs them harness-side
  2. an empty acceptance set is not vacuously "all passing" — it fails
     loudly, because a goal with no graders can never be VERIFIED
  3. editing the frozen tests afterward produces a TAMPER verdict, and a
     tampered contract cannot pass — nothing is even run
  4. the state machine refuses illegal jumps; terminal states are terminal
  5. the worker's file tools cannot write contract files at all
  6. budgets end a pursuit BLOCKED by name, never by surprise
  7. a pursuit failing the same wall twice in a row ends BLOCKED with the
     wall named, instead of burning the remaining cycles on it
  8. the event ledger replays to the same state the snapshot claims, and a
     forged snapshot is DETECTED as divergence
  9. END TO END: a lying judge plus generous planner-authored checks still
     lose — the pursuit is overruled by the CONTRACT, does the work for
     real in the next cycle, and only then ends VERIFIED
 10. END TO END: the same milestone failing identically in two consecutive
     cycles ends the pursuit BLOCKED after cycle 2, not EXHAUSTED after 4

Run from the agent/ directory:  python tests/test_contract.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import contract                # noqa: E402
import fileauth                # noqa: E402
import fleet                   # noqa: E402
import goal                    # noqa: E402

PY = sys.executable

SETTINGS = """[agent]
poll_interval_seconds = 1
inbox_settle_seconds = 0
max_task_usd = 0
reflect_after = []
max_done_rejects = 3

[providers.work]
type = "mock"
script = "scripts/work.json"

[providers.judge]
type = "mock"
script = "scripts/judge.json"

[roles.default]
provider = "work"
model = "mock"

[roles.practitioner]
provider = "work"
model = "mock"

[roles.examiner]
provider = "judge"
model = "mock"
"""


def wire(root, work, judge):
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(SETTINGS)
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    for name, s in (("work.json", work), ("judge.json", judge)):
        with open(os.path.join(root, "scripts", name), "w",
                  encoding="utf-8") as f:
            json.dump(s, f)


def _exists(path):
    p = path.replace("\\", "/")
    return f'"{PY}" -c "import os,sys;sys.exit(0 if os.path.exists(r\'{p}\') else 1)"'


def main():
    home = make_sandbox("contract", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Contractor", "works under contract")

    check_freeze_seal_and_verify(root)
    check_empty_acceptance_is_not_vacuous(root)
    check_tamper_is_detected_not_passed(root)
    check_the_state_machine_refuses_illegal_jumps(root)
    check_the_worker_cannot_write_the_contract(root)
    check_budgets_block_by_name(home, root)
    check_oscillation_is_diagnosed(root)
    check_replay_reconstructs_and_detects_forgery(root)
    check_the_contract_outranks_the_judge(home)
    check_no_convergence_ends_blocked(home)
    check_the_state_machine_is_a_critical_section()
    print("PASS test_contract")


def check_freeze_seal_and_verify(root):
    marker = os.path.join(root, "out", "acceptance-artifact.txt")
    os.makedirs(os.path.dirname(marker), exist_ok=True)
    c = contract.create(root, "g-unit", "produce the artifact",
                        accept=[{"id": "A1", "what": "artifact exists",
                                 "check": _exists(marker)}],
                        max_usd=1.0, max_cycles=3)
    assert c["state"] == "draft"
    contract.freeze(root, "g-unit")
    c = contract.load(root, "g-unit")
    assert c["state"] == "ready" and c["accept_hash"], c

    # the seal must live OUTSIDE the expert's root — the worker operates
    # under root, and a reference it can reach is not a reference
    sp, kind = contract.seal_path(root)
    assert kind == "home", (sp, kind)
    assert not sp.replace("\\", "/").startswith(
        root.replace("\\", "/")), (sp, root)
    assert os.path.isfile(sp)

    # not met yet -> failing, with the test named
    r = contract.verify(root, "g-unit")
    assert not r["tamper"] and r["mechanical"] and not r["all"], r
    assert r["failed"] == ["A1"], r
    # met -> passing, run by the harness, not asserted by anyone
    with open(marker, "w", encoding="utf-8") as f:
        f.write("real")
    r = contract.verify(root, "g-unit")
    assert r["all"] and r["passed"] == ["A1"], r
    print("[frozen] acceptance was frozen before any work, sealed outside "
          "the worker's root, and verify() ran the checks itself — failing "
          "while the artifact was missing, passing once it existed")


def check_empty_acceptance_is_not_vacuous(root):
    contract.create(root, "g-empty", "an unmeasurable goal")
    contract.freeze(root, "g-empty")
    r = contract.verify(root, "g-empty")
    assert not r["mechanical"] and not r["all"], (
        f"an EMPTY acceptance set was scored as passing: {r}. All-of-nothing "
        f"is the vacuous assertion this platform keeps hunting; a goal with "
        f"no graders has PARTIAL as its honest ceiling.")
    assert "PARTIAL" in r["why"], r
    print("[no-vacuous] zero acceptance tests means nothing can be VERIFIED "
          "— stated in the verdict, not hidden inside an empty all()")


def check_tamper_is_detected_not_passed(root):
    always = f'"{PY}" -c "raise SystemExit(0)"'
    contract.create(root, "g-tamper", "a goal whose graders get edited",
                    accept=[{"id": "A1", "what": "hard thing",
                             "check": f'"{PY}" -c "raise SystemExit(1)"'}])
    contract.freeze(root, "g-tamper")
    # the worker shells around the file authority and swaps the failing
    # grader for one that always passes — the exact move the seal exists for
    c = contract.load(root, "g-tamper")
    c["acceptance"][0]["check"] = always
    contract._write(root, "g-tamper", c)
    r = contract.verify(root, "g-tamper")
    assert r["tamper"], f"an edited grader set was accepted: {r}"
    assert not r["all"] and not r["results"], (
        f"a tampered contract RAN its forged checks: {r}. Tamper must mean "
        f"nothing runs — a forged grader that executes is a forged grader "
        f"that can pass.")
    # and re-hashing the forgery into the contract does not help, because
    # the reference lives outside the root
    c["accept_hash"] = contract._accept_hash(c["acceptance"])
    contract._write(root, "g-tamper", c)
    r = contract.verify(root, "g-tamper")
    assert r["tamper"], (
        f"re-hashing the forged acceptance into the snapshot beat the "
        f"seal: {r}. The OUTSIDE ledger is the reference, or there is none.")
    print("[tamper] swapping a failing grader for a passing one after the "
          "freeze produced a TAMPER verdict with nothing run — and forging "
          "the snapshot's own hash lost to the seal outside the root")


def check_the_state_machine_refuses_illegal_jumps(root):
    contract.create(root, "g-states", "state machine probe")
    for bad in ("verified", "partial", "running"):
        try:
            contract.transition(root, "g-states", bad)
            raise AssertionError(f"draft -> {bad} was allowed")
        except contract.ContractError:
            pass
    contract.freeze(root, "g-states")
    contract.transition(root, "g-states", "running")
    contract.transition(root, "g-states", "verified")
    for bad in ("running", "failed", "partial"):
        try:
            contract.transition(root, "g-states", bad)
            raise AssertionError(f"verified -> {bad} was allowed — a "
                                 f"terminal state must be terminal")
        except contract.ContractError:
            pass
    # blocked is the one resumable ending: the owner fixes the blocker
    contract.create(root, "g-resume", "blockable")
    contract.freeze(root, "g-resume")
    contract.transition(root, "g-resume", "running")
    contract.transition(root, "g-resume", "blocked", why="budget")
    contract.transition(root, "g-resume", "running", why="owner raised it")
    print("[machine] draft cannot jump to verified, verified is terminal, "
          "and blocked is the one ending an owner may deliberately resume")


def check_the_worker_cannot_write_the_contract(root):
    for rel in ("goals/g-unit/contract.json", "goals/g-unit/events.jsonl",
                "goals/g-unit/goal.json"):
        try:
            fileauth.resolve(root, rel, mode="write", actor="agent")
            raise AssertionError(f"the agent may write {rel} — the worker "
                                 f"can edit its own graders through the "
                                 f"front door")
        except fileauth.Denied:
            pass
    # while the working files beside them stay writable — the worker still
    # writes its plans and evidence where it always did
    for rel in ("goals/g-unit/plan-1.md", "goals/g-unit/m1-1.md",
                "goals/g-unit/assessment-1.md"):
        fileauth.resolve(root, rel, mode="write", actor="agent")
    print("[zones] the agent's file tools are refused on contract.json, "
          "events.jsonl and goal.json inside goals/, while plans and "
          "evidence notes beside them stay writable")


def check_budgets_block_by_name(home, root):
    contract.create(root, "g-budget", "a goal with a spend ceiling",
                    max_usd=0.50)
    contract.freeze(root, "g-budget")
    contract.event(root, "g-budget", "spent", usd=0.30, task="t1")
    b = contract.budget_state(root, "g-budget")
    assert not b["exceeded"], b
    contract.event(root, "g-budget", "spent", usd=0.30, task="t2")
    b = contract.budget_state(root, "g-budget")
    assert b["exceeded"] and "spend" in b["exceeded"][0], b
    assert abs(b["spent_usd"] - 0.60) < 1e-6, b

    # and the PURSUIT actually stops on it: a resumed pursuit whose wall
    # clock is already over budget must block before planning anything
    contract.create(root, "g-clock", "an over-time pursuit", max_minutes=1)
    contract.freeze(root, "g-clock")
    with open(contract.events_path(root, "g-clock"), "r+",
              encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
        for r in rows:
            r["at"] = "2026-08-25T00:00:00"          # hours ago
        f.seek(0)
        f.truncate()
        for r in rows:
            f.write(json.dumps(r) + "\n")
    wire(root, [{"tool": "finish_task", "args": {"summary": "x"}}],
         [{"tool": "finish_task", "args": {"summary": "x"}}])
    rec = goal.pursue(home, "contractor", "an over-time pursuit",
                      cycles=2, drive=True, timeout=60, gid="g-clock")
    assert rec["status"] == "blocked", rec
    assert "budget" in rec.get("blocked", ""), rec
    assert "wall-clock" in rec["blocked"], rec
    assert not rec["cycles"], (
        "a pursuit already over budget still planned a cycle — the ceiling "
        "must hold BEFORE new spend, not after it")
    assert contract.load(root, "g-clock")["state"] == "blocked"
    print(f"[budget] spend accumulated from the ledger tripped the ceiling "
          f"by name ({b['exceeded'][0]}), and a pursuit over its wall-clock "
          f"budget blocked before planning anything")


def check_oscillation_is_diagnosed(root):
    contract.create(root, "g-osc", "oscillation probe")
    contract.freeze(root, "g-osc")
    ev = lambda **kw: contract.event(root, "g-osc", "milestone_failed", **kw)
    # same milestone, same check, cycles 1 and 2 -> diagnosed
    ev(n=3, cycle=1, check="python verify.py x", what="w")
    assert contract.oscillating(root, "g-osc") is None, \
        "one failure is not oscillation"
    ev(n=3, cycle=2, check="python verify.py x", what="w")
    d = contract.oscillating(root, "g-osc")
    assert d and "M3" in d and "cycles 1 and 2" in d, d
    # a DIFFERENT check failing on the same milestone is progress of a kind
    contract.create(root, "g-osc2", "different walls")
    contract.freeze(root, "g-osc2")
    contract.event(root, "g-osc2", "milestone_failed", n=1, cycle=1,
                   check="check-a", what="w")
    contract.event(root, "g-osc2", "milestone_failed", n=1, cycle=2,
                   check="check-b", what="w")
    assert contract.oscillating(root, "g-osc2") is None, (
        "the same milestone failing for a NEW reason was called oscillation "
        "— a plan that finds a different wall is converging, not looping")
    # non-consecutive repeats are not oscillation either
    contract.create(root, "g-osc3", "spaced repeats")
    contract.freeze(root, "g-osc3")
    contract.event(root, "g-osc3", "milestone_failed", n=1, cycle=1,
                   check="c", what="w")
    contract.event(root, "g-osc3", "milestone_failed", n=1, cycle=3,
                   check="c", what="w")
    assert contract.oscillating(root, "g-osc3") is None
    print("[oscillation] the same check failing in consecutive cycles is "
          "diagnosed with the wall named; a new failure reason or a spaced "
          "repeat is not — progress and looping are told apart")


def check_replay_reconstructs_and_detects_forgery(root):
    r = contract.replay(root, "g-unit")
    assert r["frozen"] and not r["diverges"], r
    # forge the snapshot's state without an event saying so
    c = contract.load(root, "g-unit")
    c["state"] = "verified"
    contract._write(root, "g-unit", c)
    r = contract.replay(root, "g-unit")
    assert r["diverges"], (
        f"a snapshot claiming a state no event produced was believed: {r}. "
        f"The ledger is append-only and the snapshot is rewritten, so on "
        f"disagreement the ledger wins — that is what makes a crash "
        f"survivable and a forgery visible.")
    print("[replay] the event ledger rebuilt the same state the snapshot "
          "held, and a snapshot forged to 'verified' with no such event "
          "was reported as divergence")


def check_the_contract_outranks_the_judge(home):
    """The centerpiece: reward hacking loses to the frozen graders."""
    root = fleet.create(home, "Honest Builder", "graded from outside")
    GD = "goals/g-accept"
    artifact = os.path.join(root, "deliverable.txt").replace("\\", "/")
    easy1 = _exists(os.path.join(root, GD, "m1-1.md"))
    easy2 = _exists(os.path.join(root, GD, "m2-1.md"))
    # The mock replays its script per task, stopping at the first
    # finish_task whose gate passes — so steps after a finish only run in
    # later tasks. The artifact write sits AFTER cycle 2's plan finish:
    # cycle 1 completes entirely (plan, work, judge) with the artifact
    # still missing, which is exactly when a generous milestone check and a
    # lying judge would have called it done.
    work = [
        {"tool": "write_file", "args": {"path": f"{GD}/plan-1.md",
         "content": f"- M1: write the evidence note CHECK: {easy1}\n"}},
        {"tool": "write_file", "args": {"path": f"{GD}/m1-1.md",
         "content": "looks done to me (it is not)\n"}},
        {"tool": "finish_task", "args": {"summary": "c1"}},
        {"tool": "write_file", "args": {"path": f"{GD}/plan-2.md",
         "content": f"- M1: actually produce the deliverable CHECK: {easy2}\n"}},
        {"tool": "finish_task", "args": {"summary": "planned c2"}},
        {"tool": "write_file", "args": {"path": "deliverable.txt",
         "content": "the real thing\n"}},
        {"tool": "write_file", "args": {"path": f"{GD}/m2-1.md",
         "content": "deliverable.txt written for real\n"}},
        {"tool": "finish_task", "args": {"summary": "worked c2"}},
    ]
    judge = [
        {"tool": "write_file", "args": {"path": f"{GD}/assessment-1.md",
         "content": "All milestones pass their checks.\nVERDICT: ACHIEVED\n"}},
        {"tool": "finish_task", "args": {"summary": "judged c1"}},
        {"tool": "write_file", "args": {"path": f"{GD}/assessment-2.md",
         "content": "Deliverable verified.\nVERDICT: ACHIEVED\n"}},
        {"tool": "finish_task", "args": {"summary": "judged c2"}},
    ]
    wire(root, work, judge)

    rec = goal.pursue(
        home, "honest-builder", "produce the deliverable",
        criteria="deliverable.txt exists with the real content",
        cycles=3, drive=True, timeout=240, gid="g-accept",
        accept=[{"id": "A1", "what": "the deliverable exists",
                 "check": _exists(artifact)}])

    assert rec["status"] == "achieved" and rec["verified"] is True, rec
    assert len(rec["cycles"]) == 2, (
        f"cycle 1's ACHIEVED — judge lying, milestone check generous — must "
        f"have been overruled by the CONTRACT: {[c['verdict'] for c in rec['cycles']]}")
    c1 = rec["cycles"][0]
    assert c1["verdict"] == "NOT ACHIEVED", c1
    assert c1.get("acceptance_failed") == ["A1"], (
        f"the overrule must name the frozen test that refused: {c1}")
    assert not c1.get("overruled"), (
        "cycle 1's milestone check PASSED (it was generous — that is the "
        "attack); the old judge-vs-checks overrule must not fire, only the "
        "contract's")
    # The overrule is durable in the EVENT LEDGER, deliberately not in the
    # assessment file: cycle 2's judge task replays its script and rewrites
    # assessment-1.md, clobbering anything appended there. A record that a
    # later task can silently erase is not a record.
    over = [e for e in contract.events(root, "g-accept")
            if e["kind"] == "acceptance_overruled"]
    assert len(over) == 1 and over[0]["failed"] == ["A1"], over
    assert over[0]["cycle"] == 1, over
    assert contract.load(root, "g-accept")["state"] == "verified"
    kinds = [e["kind"] for e in contract.events(root, "g-accept")]
    assert "verify" in kinds and kinds.count("cycle_started") == 2, kinds
    final = [e for e in contract.events(root, "g-accept")
             if e["kind"] == "verify"][-1]
    assert final["all"] is True and final["passed"] == ["A1"], final
    print("[outranked] a lying judge AND a generous planner-authored check "
          "both said done while the deliverable did not exist — the frozen "
          "acceptance test refused, the pursuit was overruled into cycle 2, "
          "did the work for real, and only then ended VERIFIED, with the "
          "whole story in the event ledger")


def check_no_convergence_ends_blocked(home):
    root = fleet.create(home, "Wall Hitter", "stopped before cycle three")
    GD = "goals/g-wall"
    impossible = _exists(os.path.join(root, "never-exists"))
    work = [
        {"tool": "write_file", "args": {"path": f"{GD}/plan-1.md",
         "content": f"- M1: pass the impossible gate CHECK: {impossible}\n"}},
        {"tool": "write_file", "args": {"path": f"{GD}/plan-2.md",
         "content": f"- M1: pass the impossible gate CHECK: {impossible}\n"}},
        {"tool": "write_file", "args": {"path": f"{GD}/m1-1.md",
         "content": "tried\n"}},
        {"tool": "finish_task", "args": {"summary": "x"}},
        {"tool": "finish_task", "args": {"summary": "x"}},
        {"tool": "finish_task", "args": {"summary": "x"}},
    ]
    judge = [
        {"tool": "write_file", "args": {"path": f"{GD}/assessment-1.md",
         "content": "M1 failed.\nVERDICT: NOT ACHIEVED\n"}},
        {"tool": "finish_task", "args": {"summary": "j1"}},
        {"tool": "write_file", "args": {"path": f"{GD}/assessment-2.md",
         "content": "M1 failed again, identically.\nVERDICT: NOT ACHIEVED\n"}},
        {"tool": "finish_task", "args": {"summary": "j2"}},
    ]
    wire(root, work, judge)
    rec = goal.pursue(home, "wall-hitter", "get through the wall",
                      cycles=4, drive=True, timeout=240, gid="g-wall")
    assert rec["status"] == "blocked", rec
    assert "no convergence" in rec.get("blocked", ""), rec
    assert "M1" in rec["blocked"], rec
    assert len(rec["cycles"]) == 2, (
        f"the pursuit burned {len(rec['cycles'])} cycles on an identical "
        f"wall; after two identical failures the third attempt is not "
        f"persistence, it is a loop")
    assert contract.load(root, "g-wall")["state"] == "blocked"
    print("[converge] the same milestone failing the same check in cycles "
          "1 and 2 ended the pursuit BLOCKED with the wall named — two of "
          "the four budgeted cycles were spent, not all four")



def check_the_state_machine_is_a_critical_section():
    """"The ONLY way state changes" has to hold when two things ask at once.

    `transition` was read -> check TRANSITIONS -> write with nothing between
    the steps, and `_write` used the shared `p + ".tmp"`. Two callers could
    read the same `running`, each find its own move legal, and both write —
    and TRANSITIONS gives a terminal state no exits, so the ledger could
    record a jump the machine exists to refuse. On Windows the shared temp
    turned the loser into a PermissionError instead, which is its own defect:
    a legitimate transition failing with a rights error rather than a rule.
    """
    import threading
    import tempfile
    import contract as C
    root = tempfile.mkdtemp(prefix="ct-race-")
    C.create(root, "g", "goal",
             accept=[{"id": "A1", "what": "x",
                      "check": f'"{PY}" -c "pass"'}])
    C.freeze(root, "g")
    C.transition(root, "g", "running", why="t")

    accepted, refused = [], []

    def flip(to):
        try:
            C.transition(root, "g", to, why="race")
            accepted.append(to)
        except C.ContractError as e:
            refused.append((to, "rule"))
        except Exception as e:
            refused.append((to, type(e).__name__))

    ts = [threading.Thread(target=flip, args=(s,))
          for s in ("verified", "blocked")]
    for t in ts:
        t.start()
    for t in ts:
        t.join()

    assert len(accepted) == 1, (
        f"both endings were accepted ({accepted}) — a terminal state has no "
        f"exits, so the ledger now records a jump the machine refuses")
    assert refused and refused[0][1] == "rule", (
        f"the losing transition failed with {refused} rather than by the "
        f"contract rule — a shared temp file is not a state machine")
    state = C.load(root, "g")["state"]
    assert state == accepted[0], (state, accepted)
    kinds = [(e.get("kind"), e.get("to")) for e in C.events(root, "g")]
    assert kinds.count(("state", "verified")) + \
        kinds.count(("state", "blocked")) == 1, kinds
    print(f"[machine] two threads raced one contract to two mutually "
          f"exclusive endings: {accepted[0]} was accepted, the other was "
          f"refused BY THE RULE, and the ledger carries exactly one ending")

if __name__ == "__main__":
    main()
