#!/usr/bin/env python3
"""REPAIR — self-modification until the job is done, without the hallucination.

The owner's requirement: when the goal is not achieved, the agent modifies
itself and its approach until it IS — "not in a dumb way, like an AI
hallucinating and thinking it really did the job". The research record says
exactly how that goes wrong and repair.py is built on it: intrinsic
self-correction degrades performance (Huang et al., ICLR 2024,
arXiv:2310.01798); correction works from ENVIRONMENT FEEDBACK and execution
errors (Voyager, arXiv:2305.16291); self-modifications are kept only when
empirically validated afterwards, with lineage (Darwin Gödel Machine,
arXiv:2505.22954); and the feedback handed to a retry must be small and
explicit (arXiv:2506.11930).

Four laws, each broken here to prove the enforcement is real:

  LAW 1 — no repair without a signal: every planned action carries the
          failing check and its recorded error, verbatim from the ledger
  LAW 2 — repair never grades itself: it can move blocked -> running and
          act, but VERIFIED can only come from the frozen graders; the
          event ledger shows a passing verify before any verified state
  LAW 3 — the machine never lifts its own ceiling: budget and tamper
          blocks route to the OWNER, and the budget in the contract is
          bit-for-bit unchanged after a repair pass
  LAW 4 — revision keeps lineage: a failing runbook's revision is written
          BESIDE it as a zero-trust candidate with the failure embedded
          and a TODO that validation refuses; the parent file and its
          earned trust are untouched

Plus repair's own honesty about itself: attempts are bounded, and planning
the identical repair twice stops with "not converging" — the oscillation
rule applied one level up.

Run from the agent/ directory:  python tests/test_repair.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import contract                # noqa: E402
import fleet                   # noqa: E402
import repair                  # noqa: E402
import runbook                 # noqa: E402

PY = sys.executable


def _exists(path):
    p = path.replace("\\", "/")
    return f'"{PY}" -c "import os,sys;sys.exit(0 if os.path.exists(r\'{p}\') else 1)"'


def _touch_cmd(path):
    p = path.replace("\\", "/")
    return (f'"{PY}" -c "import io,os;'
            f"os.makedirs(os.path.dirname(r'{p}'),exist_ok=True);"
            f"io.open(r'{p}','w',encoding='utf-8').write('made')\"")


def _blocked_by_oscillation(root, gid, goal, check, err):
    contract.create(root, gid, goal,
                    accept=[{"id": "A1", "what": "the artifact",
                             "check": check}])
    contract.freeze(root, gid)
    contract.transition(root, gid, "running")
    for cyc in (1, 2):
        contract.event(root, gid, "cycle_started", cycle=cyc)
        contract.event(root, gid, "milestone_failed", n=1, cycle=cyc,
                       check=check, what="produce the artifact", error=err)
    contract.transition(root, gid, "blocked",
                        why="no convergence: milestone M1 failed the same "
                            "check in cycles 1 and 2")


def main():
    home = make_sandbox("repair", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Mender", "fixes what blocked it")

    check_law1_no_repair_without_a_signal(root)
    check_law3_owner_only_ceilings(root)
    check_law4_revision_keeps_lineage(root)
    check_law2_only_the_graders_verify(home, root)
    check_repair_watches_itself(root)
    check_the_signal_reaches_the_resumed_planner(root)
    print("PASS test_repair")


def check_law1_no_repair_without_a_signal(root):
    art = os.path.join(root, "out", "law1.txt")
    ERR = "TypeError: cannot join tuple to str at build_report line 40"
    _blocked_by_oscillation(root, "g-sig", "build the quarterly report",
                            _exists(art), ERR)
    d = repair.diagnose(root, "g-sig")
    assert d["kind"] == "procedure_and_knowledge", d
    assert any(ERR in str(s.get("evidence", "")) for s in d["signals"]), (
        f"the diagnosis lost the recorded error — a repair not anchored to "
        f"the mechanical evidence is reflection, and reflection makes "
        f"models worse (arXiv:2310.01798): {d['signals']}")
    p = repair.plan(root, "g-sig")
    assert p["actions"], p
    grounded = [a for a in p["actions"]
                if a["kind"] in ("study", "revise_runbook",
                                 "retry_with_signal")]
    assert grounded, p["actions"]
    for a in grounded:
        sig = a.get("signal")
        sigs = sig if isinstance(sig, list) else [sig] if sig else []
        assert sigs and any(s for s in sigs), (
            f"action {a['kind']!r} carries no signal — LAW 1: no repair "
            f"without the evidence that motivated it")
    retry = next(a for a in p["actions"] if a["kind"] == "retry_with_signal")
    assert any(ERR in str(s.get("evidence", "")) for s in retry["signal"]), (
        "the retry action dropped the verbatim error — the retry context "
        "must carry the exact failing signal, small and explicit")
    print("[law1] a blocked goal's diagnosis and every grounded repair "
          "action carry the failing check and its recorded error VERBATIM "
          "from the ledger — there is no 'reflect and try again' action "
          "anywhere in the plan")


def check_law3_owner_only_ceilings(root):
    # budget block
    contract.create(root, "g-ceil", "an over-budget pursuit", max_usd=1.0)
    contract.freeze(root, "g-ceil")
    contract.transition(root, "g-ceil", "running")
    contract.event(root, "g-ceil", "spent", usd=2.0, task="t")
    contract.transition(root, "g-ceil", "blocked",
                        why="budget: spend $2.00 > $1.00")
    before = contract.load(root, "g-ceil")["budget"]
    p = repair.plan(root, "g-ceil")
    assert [a["kind"] for a in p["actions"]] == ["owner"], (
        f"a budget block planned machine actions: {p['actions']} — a "
        f"machine that lifts its own budget has no budget")
    r = repair.apply(root, "g-ceil", resume=False)
    after = contract.load(root, "g-ceil")["budget"]
    assert before == after, (
        f"repair CHANGED the budget {before} -> {after} — LAW 3 exists "
        f"precisely so this cannot happen")
    assert contract.load(root, "g-ceil")["state"] == "blocked"
    # tamper block
    contract.create(root, "g-tmp", "a tampered goal",
                    accept=[{"id": "A1", "what": "x",
                             "check": f'"{PY}" -c "raise SystemExit(1)"'}])
    contract.freeze(root, "g-tmp")
    contract.transition(root, "g-tmp", "running")
    contract.transition(root, "g-tmp", "blocked",
                        why="contract tamper: the acceptance tests no "
                            "longer match the sealed hash")
    p2 = repair.plan(root, "g-tmp")
    assert [a["kind"] for a in p2["actions"]] == ["owner"], p2["actions"]
    print("[law3] a budget block and a tamper block both plan exactly one "
          "action — OWNER — and a repair pass left the contract's budget "
          "bit-for-bit unchanged: the machine cannot lift its own ceiling "
          "or forgive edits to its own graders")


def check_law4_revision_keeps_lineage(root):
    gone = os.path.join(root, "out", "law4-missing.txt")
    made = os.path.join(root, "out", "law4-made.txt")
    os.makedirs(os.path.join(root, "runbooks"), exist_ok=True)
    parent = {"name": "publisher", "triggers": ["publish", "bulletin"],
              "steps": [{"do": _touch_cmd(made), "verify": _exists(made)},
                        {"do": f'"{PY}" -c "pass"', "verify": _exists(gone)}]}
    with open(runbook.path(root, "publisher"), "w", encoding="utf-8") as f:
        json.dump(parent, f)
    # the parent earned real history before failing
    runbook.record(root, "publisher", True, "earlier win", accepted=True)
    parent_trust = dict(runbook._trust(root)["publisher"])

    ERR = "the CDN rejected the upload: 403 on PUT /bulletin"
    child = repair.revise_runbook(root, "publisher",
                                  {"check": _exists(gone), "evidence": ERR})
    assert child == "publisher-v2", child
    # parent untouched — file AND trust
    with open(runbook.path(root, "publisher"), encoding="utf-8") as f:
        assert json.load(f) == parent, (
            "the parent runbook file was modified — a revision is a child "
            "in an archive, never an overwrite (arXiv:2505.22954)")
    assert runbook._trust(root)["publisher"] == parent_trust, (
        "the parent's earned trust record changed during revision")
    # child: candidate, lineage, signal embedded, TODO refused
    assert runbook.status(root, child) == "candidate"
    raw = json.load(open(runbook.path(root, child), encoding="utf-8"))
    assert raw["provenance"]["parent"] == "publisher", raw["provenance"]
    assert ERR in raw["provenance"]["reason"], raw["provenance"]
    marked = [s for s in raw["steps"] if "TODO" in s["do"]]
    assert len(marked) == 1 and ERR[:60] in marked[0]["do"], (
        f"the failing step must carry the failure it has to answer: {marked}")
    assert raw["steps"][0]["do"] == parent["steps"][0]["do"], (
        "a step that was NOT failing was rewritten — the revision touches "
        "the failing step only")
    try:
        runbook.load(root, child)
        raise AssertionError("a revision with a TODO validated as runnable")
    except runbook.RunbookError:
        pass
    print("[law4] revising a failing runbook wrote publisher-v2 BESIDE its "
          "parent — parent file and earned trust untouched, child a "
          "zero-trust candidate carrying the exact failure it must answer, "
          "refused by validation until the TODO is filled")


def check_law2_only_the_graders_verify(home, root):
    art = os.path.join(root, "out", "law2.txt")
    if os.path.exists(art):
        os.remove(art)
    ERR = "exporter crashed: UnicodeDecodeError in bulletin.csv"
    _blocked_by_oscillation(root, "g-grade", "publish the weekly bulletin",
                            _exists(art), ERR)
    # a PROVEN runbook now exists that genuinely fixes it — the repair
    # "worked"; the question is WHO gets to say so
    os.makedirs(os.path.join(root, "runbooks"), exist_ok=True)
    with open(runbook.path(root, "bulletin-fix"), "w", encoding="utf-8") as f:
        json.dump({"name": "bulletin-fix",
                   "triggers": ["weekly", "bulletin"],
                   "steps": [{"do": _touch_cmd(art),
                              "verify": _exists(art)}]}, f)
    for _ in range(runbook.PROMOTE_WINS):
        r = runbook.run(root, "bulletin-fix", allow_candidate=True,
                        accept=lambda: os.path.exists(art))
        assert r["ok"] and r["accepted"], r
    assert runbook.status(root, "bulletin-fix") == "proven"
    os.remove(art)

    r = repair.apply(root, "g-grade", resume=True)
    assert not r["stopped"], r
    assert r["resumed"] is True, r
    assert r["verified"] is True, r
    c = contract.load(root, "g-grade")
    assert c["state"] == "verified", c["state"]
    # LAW 2, mechanically: in the ledger, a PASSING verify event precedes
    # the verified state — the graders spoke first, then the state moved.
    ev = contract.events(root, "g-grade")
    kinds = [(e.get("kind"), e.get("all"), e.get("to")) for e in ev]
    vi = next(i for i, e in enumerate(ev)
              if e.get("kind") == "verify" and e.get("all") is True)
    si = next(i for i, e in enumerate(ev)
              if e.get("kind") == "state" and e.get("to") == "verified")
    assert vi < si, (
        f"the contract reached 'verified' BEFORE any passing verify event — "
        f"repair graded itself, which is the hallucination loop wearing a "
        f"repair's clothes: {kinds}")
    assert any(e.get("kind") == "repair_applied" for e in ev), kinds
    assert any(e.get("kind") == "runbook_applied" for e in ev), kinds
    # and a repair that fixes NOTHING does not verify
    gone = os.path.join(root, "out", "never-law2.txt")
    _blocked_by_oscillation(root, "g-nofix", "reach the unreachable",
                            _exists(gone), "no tool can make this file")
    r2 = repair.apply(root, "g-nofix", resume=True)
    assert r2["verified"] is False, r2
    assert contract.load(root, "g-nofix")["state"] != "verified"
    print("[law2] a repair whose fix was real ended VERIFIED — but the "
          "ledger shows the passing verify event BEFORE the state change: "
          "the frozen graders spoke first. A repair that fixed nothing "
          "resumed and did NOT verify. Repair moves blocked->running; it "
          "never grades.")


def check_repair_watches_itself(root):
    gone = os.path.join(root, "out", "never-conv.txt")
    _blocked_by_oscillation(root, "g-loop", "an unfixable goal",
                            _exists(gone), "identical failure forever")
    r1 = repair.apply(root, "g-loop", resume=False)
    assert not r1["stopped"], r1
    contract.transition(root, "g-loop", "running")
    contract.transition(root, "g-loop", "blocked",
                        why="no convergence: milestone M1 failed the same "
                            "check in cycles 1 and 2")
    r2 = repair.apply(root, "g-loop", resume=False)
    assert r2["stopped"] and "not converging" in r2["stopped"], (
        f"the IDENTICAL repair plan was applied twice: {r2} — repeating a "
        f"repair that did not work is the oscillation defect one level up")
    # and the hard bound holds even when plans differ
    ev_kinds = [e["kind"] for e in contract.events(root, "g-loop")]
    assert ev_kinds.count("repair_applied") == 1, ev_kinds
    r3 = repair.apply(root, "g-loop", max_repairs=1)
    assert r3["stopped"] and "bound is 1" in r3["stopped"], r3
    print("[bounded] the identical repair plan was refused a second run "
          "('not converging'), and the attempt bound turned away a repair "
          "past its limit — a goal still blocked after grounded repairs "
          "gets an owner, not a fourth attempt")


def check_the_signal_reaches_the_resumed_planner(root):
    # apply() wrote repair.md for g-sig earlier? ensure one exists for a gid
    r = repair.apply(root, "g-sig", resume=False)
    sig = os.path.join(root, "goals", "g-sig", "repair.md")
    assert os.path.exists(sig), "apply() did not write the signal file"
    body = open(sig, encoding="utf-8").read()
    assert "TypeError: cannot join tuple to str" in body, body
    assert "re-runs every check itself" in body, (
        "the signal file must tell the planner the harness re-checks — "
        "restating a fix as done changes nothing")
    assert len(body) < 2000, (
        f"the signal file is {len(body)} chars — small and explicit is the "
        f"requirement (arXiv:2506.11930), not a wall of logs")
    # goal.pursue includes it in the planner's context when present
    import io as _io
    src = _io.open(os.path.join(AGENT_DIR, "goal.py"),
                   encoding="utf-8").read()
    assert 'repair.md' in src and 'base_mem.append' in src, (
        "goal.pursue no longer injects repair.md into the resumed "
        "planner's context")
    print("[signal] apply() wrote a repair.md under 2000 chars carrying the "
          "verbatim error and the warning that the harness re-checks; a "
          "resumed pursuit injects it into the planner's context")


if __name__ == "__main__":
    main()
