#!/usr/bin/env python3
"""RUNBOOKS — the goal agent working with NO MODEL AT ALL.

The design directive, almost verbatim: the pre-AI agents — crawlers,
spacecraft autonomy, workflow engines, cluster controllers — did regulated,
hard work reliably without any intelligence, because the work was WRITTEN
DOWN as executable procedure and the machine replayed it, verifying as it
went. The model belongs at the frontier; everything behind the frontier
should run deterministically, for pennies, with no tokens and no
hallucination surface.

What this file proves, each a way the design could be hollow:

  1. a malformed runbook (no verify, TODO steps, too many steps) is refused
     by validation — plausible-looking is not runnable
  2. execution is step-by-step and each step must PROVE itself: a failing
     verify stops the run at that step, and later steps never execute
  3. every `do` runs under the full model-command containment: a runbook
     carrying a denied command is refused by policy, not executed
  4. trust is EARNED: three all-verified wins promote candidate -> proven,
     recorded only by the harness; two consecutive losses quarantine; the
     worker's file tools cannot touch the trust ledger; and a "status"
     field written inside the runbook file itself is ignored
  5. matching is by trigger terms; quarantined runbooks never volunteer;
     candidates only appear when explicitly allowed
  6. RECONCILE: a goal contract is driven to VERIFIED by observe -> apply
     -> verify rounds with zero model involvement, and the boundary is
     honest — no matching runbook means BLOCKED with the frontier named,
     not an attempt to improvise
  7. THE ECONOMICS, END TO END: goal.pursue on a goal whose procedure is
     proven completes VERIFIED with ZERO tasks created — the model was
     never consulted. The same pursuit without the runbook would have
     planned, worked and judged through model tasks.
  8. a draft from a verified pursuit is a SKELETON that validation refuses
     until its TODOs are filled — an honest draft, not a fake procedure

Run from the agent/ directory:  python tests/test_runbook.py
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


def _write_rb(root, rb):
    os.makedirs(os.path.join(root, "runbooks"), exist_ok=True)
    with open(runbook.path(root, rb["name"]), "w", encoding="utf-8") as f:
        json.dump(rb, f)


def main():
    home = make_sandbox("runbook", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Machinist", "runs procedures, not prose")

    check_validation_refuses_the_hollow(root)
    check_steps_prove_themselves(root)
    check_policy_contains_the_do(root)
    check_trust_is_earned_not_declared(root)
    check_matching_respects_trust(root)
    check_reconcile_without_a_model(home, root)
    check_pursue_prefers_the_machine(home)
    check_draft_is_an_honest_skeleton(root)
    check_applicability_is_probed(root)
    check_composition_keeps_every_gate(root)
    check_recording_earns_nothing(root)
    print("PASS test_runbook")


def check_validation_refuses_the_hollow(root):
    bad = [
        ({"name": "x!", "triggers": ["a"], "steps": [{"do": "d", "verify": "v"}]},
         "name"),
        ({"name": "ok", "triggers": [], "steps": [{"do": "d", "verify": "v"}]},
         "triggers"),
        ({"name": "ok", "triggers": ["a"], "steps": []}, "steps"),
        ({"name": "ok", "triggers": ["a"], "steps": [{"do": "d"}]}, "verify"),
        ({"name": "ok", "triggers": ["a"],
          "steps": [{"do": "TODO: fill me", "verify": "v"}]}, "TODO"),
        ({"name": "ok", "triggers": ["a"],
          "steps": [{"do": "d", "verify": "v"}] * 21}, "several procedures"),
    ]
    for rb, needle in bad:
        problems = runbook.validate(rb)
        assert problems and any(needle in p for p in problems), (rb, problems)
    assert runbook.validate({"name": "ok", "triggers": ["a"],
                             "steps": [{"do": "d", "verify": "v"}]}) == []
    print(f"[valid] {len(bad)} malformed shapes refused with the defect "
          f"named — a step with no verify, a TODO left in, a 21-step "
          f"monolith; a runbook that cannot be validated cannot be trusted "
          f"to run")


def check_steps_prove_themselves(root):
    out1 = os.path.join(root, "out", "step1.txt")
    out2 = os.path.join(root, "out", "step2.txt")
    _write_rb(root, {
        "name": "two-steps", "triggers": ["two", "steps"],
        "steps": [
            {"do": _touch_cmd(out1), "verify": _exists(out1)},
            # step 2's verify checks a file its `do` never creates
            {"do": f'"{PY}" -c "pass"', "verify": _exists(out2)},
        ]})
    r = runbook.run(root, "two-steps", allow_candidate=True)
    assert not r["ok"] and r["stopped_at"] == 2, r
    assert "its own proof failed" in r["why"], r
    assert os.path.exists(out1), "step 1 really ran"
    assert len(r["steps"]) == 2, r
    # and a runbook whose steps all verify succeeds
    _write_rb(root, {
        "name": "one-step", "triggers": ["one", "step"],
        "steps": [{"do": _touch_cmd(out2), "verify": _exists(out2)}]})
    r2 = runbook.run(root, "one-step", allow_candidate=True)
    assert r2["ok"] and r2["stopped_at"] == 0, r2
    print("[prove] each step must pass its own verify before the next runs: "
          "a failing step 2 stopped the run at step 2 with the reason "
          "stated, after step 1 demonstrably executed")


def check_policy_contains_the_do(root):
    _write_rb(root, {
        "name": "hostile", "triggers": ["hostile"],
        "steps": [{"do": "rm -rf /", "verify": f'"{PY}" -c "pass"'}]})
    r = runbook.run(root, "hostile", allow_candidate=True)
    assert not r["ok"] and r["stopped_at"] == 1, r
    assert "refused" in r["why"], r
    assert r["steps"][0].get("refused"), r
    print("[contained] a runbook step is a model-authored command and gets "
          "the model-command stack: `rm -rf /` in a `do` was refused by "
          "policy, not executed")


def check_trust_is_earned_not_declared(root):
    win = os.path.join(root, "out", "win.txt")
    _write_rb(root, {
        "name": "earner", "triggers": ["earner"],
        # the author tries to VOTE on their own trust — must be ignored
        "status": "proven",
        "steps": [{"do": _touch_cmd(win), "verify": _exists(win)}]})
    assert runbook.status(root, "earner") == "candidate", (
        "a status field inside the runbook file was believed — the author "
        "does not get a vote on whether the author is trusted")
    # A RUN THE CALLER NEVER ACCEPTED EARNS NOTHING. This loop used to be
    # the whole proof of "trust is earned": three bare runs, no contract, no
    # grader, and the printout called them "verified wins". But a runbook's
    # own `verify` lines are written by whoever wrote the runbook, so three
    # of them prove that the procedure does what its author said it does —
    # not that it does what was asked. The module docstring already promised
    # the stronger rule ("AND the caller's own acceptance test passed
    # after"); the code did not implement it and this test enshrined the
    # weaker one.
    for i in range(runbook.PROMOTE_WINS + 2):
        r = runbook.run(root, "earner", allow_candidate=True)
        assert r["ok"] and r["accepted"] is False, r
    assert runbook.status(root, "earner") == "candidate", (
        f"{runbook.PROMOTE_WINS + 2} runs whose steps verified promoted a "
        f"runbook that no caller ever accepted — 'proven' then means "
        f"'its own checks passed', which is a claim about the author")

    # ...and an ACCEPTED win does promote. `accept` is the caller's own
    # verdict, supplied from outside the procedure.
    accepted_runs = {"n": 0}

    def caller_accepts():
        accepted_runs["n"] += 1
        return True

    for i in range(runbook.PROMOTE_WINS):
        assert runbook.status(root, "earner") == "candidate", i
        r = runbook.run(root, "earner", allow_candidate=True,
                        accept=caller_accepts)
        assert r["ok"] and r["accepted"], r
    assert runbook.status(root, "earner") == "proven"
    assert accepted_runs["n"] == runbook.PROMOTE_WINS

    # a run whose steps verify but whose CALLER rejects it is not a win
    _write_rb(root, {
        "name": "wrong-thing", "triggers": ["wrong"],
        "steps": [{"do": _touch_cmd(os.path.join(root, "out", "w.txt")),
                   "verify": _exists(os.path.join(root, "out", "w.txt"))}]})
    for _ in range(runbook.PROMOTE_WINS + 1):
        r = runbook.run(root, "wrong-thing", allow_candidate=True,
                        accept=lambda: False)
        assert r["ok"] and not r["accepted"], r
    assert runbook.status(root, "wrong-thing") == "candidate", (
        "a procedure whose every step proves itself while the caller's "
        "graders reject the result reached 'proven' — that is a procedure "
        "that reliably does the WRONG thing, promoted for reliability")
    t = runbook._trust(root)["wrong-thing"]
    assert t["wins"] == runbook.PROMOTE_WINS + 1 and t["accepted_wins"] == 0, t
    # the trust ledger is CONTROL: the worker's file tools are refused
    try:
        fileauth.resolve(root, "runbooks/trust.json", mode="write",
                         actor="agent")
        raise AssertionError("the agent may write runbooks/trust.json — a "
                             "worker that can edit the ledger can promote "
                             "its own procedure without the wins")
    except fileauth.Denied:
        pass
    fileauth.resolve(root, "runbooks/anything.json", mode="write",
                     actor="agent")     # authoring stays open
    # two consecutive losses quarantine
    gone = os.path.join(root, "out", "never.txt")
    _write_rb(root, {
        "name": "loser", "triggers": ["loser"],
        "steps": [{"do": f'"{PY}" -c "pass"', "verify": _exists(gone)}]})
    for _ in range(runbook.QUARANTINE_LOSSES):
        runbook.run(root, "loser", allow_candidate=True)
    assert runbook.status(root, "loser") == "quarantined"
    r = runbook.run(root, "loser", allow_candidate=True)
    assert not r["ok"] and "QUARANTINED" in r["why"], r
    print(f"[earned] {runbook.PROMOTE_WINS} ACCEPTED wins promoted a "
          f"candidate to proven, recorded by the harness in a ledger the "
          f"worker cannot write; {runbook.PROMOTE_WINS + 2} self-verified "
          f"runs with no caller acceptance promoted nothing, and a procedure "
          f"the caller's graders rejected stayed a candidate after "
          f"{runbook.PROMOTE_WINS + 1} of its own clean runs; a "
          f"self-declared 'proven' inside the file was ignored; "
          f"{runbook.QUARANTINE_LOSSES} consecutive losses quarantined, and "
          f"a quarantined runbook refuses to run")


def check_matching_respects_trust(root):
    hits = runbook.match(root, "run the earner procedure please")
    assert [h["name"] for h in hits] == ["earner"], hits
    assert runbook.match(root, "the loser procedure") == [], (
        "a QUARANTINED runbook volunteered for work")
    assert runbook.match(root, "two steps forward") == [], (
        "a CANDIDATE ran unsupervised — candidates need explicit allowance")
    sup = runbook.match(root, "two steps forward", allow_candidates=True)
    assert any(h["name"] == "two-steps" for h in sup), sup
    assert runbook.match(root, "something entirely unrelated") == []
    print("[match] trigger terms select the runbook; quarantined never "
          "volunteers; candidates appear only under explicit allowance; an "
          "unrelated goal matches nothing")


def check_reconcile_without_a_model(home, root):
    art = os.path.join(root, "out", "report.txt")
    if os.path.exists(art):
        os.remove(art)
    contract.create(root, "g-mach", "produce the machinist report",
                    accept=[{"id": "A1", "what": "report exists",
                             "check": _exists(art)}])
    contract.freeze(root, "g-mach")
    # a PROVEN runbook that does the work: earn its wins first
    _write_rb(root, {
        "name": "make-report", "triggers": ["machinist", "report"],
        "steps": [{"do": _touch_cmd(art), "verify": _exists(art)}]})
    # ACCEPTED wins: the caller checks the artifact itself, from outside the
    # procedure. A bare run proves the runbook's own verify lines and earns
    # nothing — see check_trust_is_earned_not_declared.
    for _ in range(runbook.PROMOTE_WINS):
        r = runbook.run(root, "make-report", allow_candidate=True,
                        accept=lambda: os.path.exists(art))
        assert r["ok"] and r["accepted"], r
    assert runbook.status(root, "make-report") == "proven"
    os.remove(art)                       # so reconcile has real work to do

    before = os.path.getmtime(os.path.join(root, "state.json")) \
        if os.path.exists(os.path.join(root, "state.json")) else None
    rr = runbook.reconcile(root, "g-mach")
    assert rr["verified"], rr
    assert rr["rounds"] and rr["rounds"][0]["runbook"] == "make-report", rr
    assert os.path.exists(art)
    assert contract.load(root, "g-mach")["state"] == "verified"
    after = os.path.getmtime(os.path.join(root, "state.json")) \
        if os.path.exists(os.path.join(root, "state.json")) else None
    assert before == after, (
        "reconcile touched the task queue — the model-free path must not "
        "create or mutate tasks at all")
    kinds = [e["kind"] for e in contract.events(root, "g-mach")]
    assert "runbook_applied" in kinds, kinds

    # the honest boundary: no runbook -> BLOCKED naming the frontier
    other = os.path.join(root, "out", "novel.txt")
    contract.create(root, "g-novel", "do something never done before",
                    accept=[{"id": "A1", "what": "novel artifact",
                             "check": _exists(other)}])
    contract.freeze(root, "g-novel")
    rr2 = runbook.reconcile(root, "g-novel")
    assert not rr2["verified"], rr2
    assert "frontier" in rr2["blocked"], rr2
    print("[reconcile] a goal contract was driven to VERIFIED by observe -> "
          "apply -> verify with no model and no task queue involvement; a "
          "goal with no matching procedure ended BLOCKED naming the "
          "frontier instead of improvising")


def check_pursue_prefers_the_machine(home):
    """The economics, end to end through the REAL goal engine."""
    root = fleet.create(home, "Free Rider", "goals for pennies")
    # a mock provider that would FAIL any task instantly — so if the model
    # path runs at all, the pursuit cannot possibly end verified
    with open(os.path.join(root, "settings.toml"), "w",
              encoding="utf-8") as f:
        f.write('[agent]\nsandbox = "host"\nallow_unsafe_host = true\n'
                'poll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\nmax_done_rejects = 1\n\n'
                '[providers.m]\ntype = "mock"\nscript = "scripts/w.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n')
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    with open(os.path.join(root, "scripts", "w.json"), "w",
              encoding="utf-8") as f:
        json.dump([], f)                    # an empty script: every task dies

    art = os.path.join(root, "out", "weekly.txt")
    _write_rb(root, {
        "name": "weekly-artifact", "triggers": ["weekly", "artifact"],
        "steps": [{"do": _touch_cmd(art), "verify": _exists(art)}]})
    for _ in range(runbook.PROMOTE_WINS):
        r = runbook.run(root, "weekly-artifact", allow_candidate=True,
                        accept=lambda: os.path.exists(art))
        assert r["ok"] and r["accepted"], r
    assert runbook.status(root, "weekly-artifact") == "proven"
    os.remove(art)

    # timeout=30, deliberately tight: on the machine path this pursuit never
    # waits on a task at all, so the bound is irrelevant to a pass — while a
    # build where the fast path is broken falls into the model loop and
    # fails HERE in seconds instead of hanging for the default 1800s/task.
    # A mutation a test can only catch after half an hour is a mutation
    # nobody re-runs the suite to check.
    rec = goal.pursue(home, "free-rider", "produce the weekly artifact",
                      cycles=3, drive=False, timeout=30,
                      accept=[{"id": "A1", "what": "the artifact exists",
                               "check": _exists(art)}])
    assert rec["status"] == "achieved" and rec["verified"] is True, rec
    assert rec.get("runbook") == ["weekly-artifact"], rec
    assert not rec["cycles"], (
        f"the pursuit ran {len(rec['cycles'])} model cycle(s) for a goal "
        f"whose procedure was already proven — the machine path must "
        f"preempt the model entirely")
    st = os.path.join(root, "state.json")
    tasks = []
    if os.path.exists(st):
        tasks = json.load(open(st, encoding="utf-8")).get("tasks", [])
    assert tasks == [], (
        f"{len(tasks)} task(s) were created — a model was consulted. The "
        f"provider here fails every task by construction, so the only way "
        f"this pursuit ends VERIFIED is the zero-token path — and it did.")
    print("[pennies] goal.pursue completed a goal VERIFIED with ZERO tasks "
          "created and ZERO model calls — against a provider rigged to fail "
          "any task instantly, so the model path could not have produced "
          "this outcome even by accident. The model is now reserved for "
          "goals the library has never seen.")


def check_draft_is_an_honest_skeleton(root):
    out, rb = runbook.draft(root, "g-mach")
    assert os.path.exists(out)
    assert any("TODO" in s["do"] for s in rb["steps"]), rb
    try:
        runbook.load(root, rb["name"])
        raise AssertionError("a skeleton with TODO steps validated — a "
                             "draft must be refused until a model or an "
                             "owner fills in the HOW")
    except runbook.RunbookError as e:
        assert "TODO" in str(e), e
    # the acceptance tests travelled into the skeleton as verifies
    assert any("report" in s["verify"] for s in rb["steps"]), rb
    print("[draft] a verified pursuit yields a skeleton carrying the proven "
          "VERIFICATIONS with the HOW left as named TODOs — validation "
          "refuses to run it until they are filled, because the machine can "
          "recover what was proven but not how it was done")


def check_applicability_is_probed(root):
    """The audit's P1: matching ("about this goal") was standing in for
    applicability ("can run here and now"). `when.not` vetoes by words;
    `when.requires` probes by command; reconcile takes the best match that
    can ACTUALLY run and names the ones that cannot."""
    marker = os.path.join(root, "out", "precondition.txt")
    if os.path.exists(marker):
        os.remove(marker)
    art = os.path.join(root, "out", "applic.txt")
    if os.path.exists(art):
        os.remove(art)
    # negative trigger: right words, wrong domain -> excluded from match
    _write_rb(root, {
        "name": "gated-maker", "triggers": ["applic", "artifact"],
        "when": {"not": ["manually"], "requires": [_exists(marker)]},
        "steps": [{"do": _touch_cmd(art), "verify": _exists(art)}]})
    for _ in range(runbook.PROMOTE_WINS):
        open(marker, "w").close()
        # accept=: the caller's own check, from outside the procedure. Only
        # an accepted win promotes (check_trust_is_earned_not_declared).
        r = runbook.run(root, "gated-maker", allow_candidate=True,
                        accept=lambda: os.path.exists(art))
        assert r["ok"] and r["accepted"], r
    os.remove(art)
    assert runbook.match(root, "make the applic artifact manually") == [], (
        "a negative trigger fired and the runbook still volunteered")
    hits = runbook.match(root, "make the applic artifact")
    assert any(h["name"] == "gated-maker" for h in hits), hits
    # requires-probe: not applicable until the precondition exists
    os.remove(marker)
    ap = runbook.applicable(root, "gated-maker")
    assert not ap["ok"] and ap["blocked_by"], ap
    # reconcile refuses to run an inapplicable match, NAMING the missing
    # precondition instead of running a procedure into a wall
    contract.create(root, "g-applic", "make the applic artifact",
                    accept=[{"id": "A1", "what": "artifact exists",
                             "check": _exists(art)}])
    contract.freeze(root, "g-applic")
    rr = runbook.reconcile(root, "g-applic")
    assert not rr["verified"] and "applicable" in rr["blocked"], rr
    assert "gated-maker" in rr["blocked"], rr
    # satisfy the precondition -> the same goal reconciles to VERIFIED
    open(marker, "w").close()
    rr2 = runbook.reconcile(root, "g-applic")
    assert rr2["verified"], rr2
    assert contract.load(root, "g-applic")["state"] == "verified"
    print("[applicable] a negative trigger vetoed a matching runbook; an "
          "unmet when.requires probe made a PROVEN match inapplicable and "
          "reconcile blocked NAMING the precondition; satisfying it let the "
          "identical goal reconcile to VERIFIED")


def check_composition_keeps_every_gate(root):
    """HTN half of E51: a step may run another runbook — but the sub keeps
    its own trust gate, a failure stops the parent, and a cycle is refused
    with the chain named."""
    a1 = os.path.join(root, "out", "comp-a.txt")
    a2 = os.path.join(root, "out", "comp-b.txt")
    for p in (a1, a2):
        if os.path.exists(p):
            os.remove(p)
    _write_rb(root, {
        "name": "comp-child", "triggers": ["child"],
        "steps": [{"do": _touch_cmd(a1), "verify": _exists(a1)}]})
    _write_rb(root, {
        "name": "comp-parent", "triggers": ["parent"],
        "steps": [{"run": "comp-child"},
                  {"do": _touch_cmd(a2), "verify": _exists(a2)}]})
    # validation: a step cannot be BOTH run and do+verify
    problems = runbook.validate({
        "name": "twoinone", "triggers": ["x"],
        "steps": [{"run": "comp-child", "do": "d", "verify": "v"}]})
    assert any("EITHER" in p for p in problems), problems
    # the sub's own trust gates it: child is a candidate, so a parent run
    # without allowance stops AT THE CHILD, not after it
    rr = runbook.run(root, "comp-parent", allow_candidate=False)
    assert not rr["ok"], "a candidate child ran inside a parent unsupervised"
    for _ in range(runbook.PROMOTE_WINS):
        r = runbook.run(root, "comp-parent", allow_candidate=True,
                        accept=lambda: os.path.exists(a1) and os.path.exists(a2))
        assert r["ok"] and r["accepted"], r
    assert os.path.exists(a1) and os.path.exists(a2)
    assert runbook.status(root, "comp-child") == "proven", (
        "the child's own outcomes were not recorded through composition")
    # a cycle is refused with the chain named, not walked forever
    _write_rb(root, {
        "name": "loop-a", "triggers": ["la"], "steps": [{"run": "loop-b"}]})
    _write_rb(root, {
        "name": "loop-b", "triggers": ["lb"], "steps": [{"run": "loop-a"}]})
    for n in ("loop-a", "loop-b"):
        for _ in range(runbook.PROMOTE_WINS):
            runbook.record(root, n, True, "seeded for the cycle check",
                           accepted=True)
    rc = runbook.run(root, "loop-a")
    assert not rc["ok"] and "cycle" in rc["why"] and "loop-a" in rc["why"], rc
    print("[compose] a parent runbook ran its child in place with the "
          "child's own trust gate enforced and its own wins recorded "
          "(candidate child stopped an unsupervised parent; the child "
          "earned proven through composition); a mutual cycle was refused "
          "with the chain named")


def check_recording_earns_nothing(root):
    """Teach-by-demonstration, the honest version: a recorded procedure is
    a CANDIDATE (a demo you watched is a claim), a step with no verify is
    refused (recording does not relax the law), and a --rehearse replay
    through the full authority stack proves the recording RUNS — and earns
    no trust, because a rehearsal is the procedure checking itself. Trust
    still needs three ACCEPTED wins, and nobody accepted a rehearsal."""
    art = os.path.join(root, "out", "recorded.txt")
    if os.path.exists(art):
        os.remove(art)
    try:
        runbook.record_demo(root, "half-demo", ["demo"],
                       [{"do": _touch_cmd(art)}])
        raise AssertionError("a demonstrated step with no verify was "
                             "accepted — recording relaxed the law")
    except runbook.RunbookError as e:
        assert "verify" in str(e), e
    r = runbook.record_demo(root, "demoed", ["recorded", "artifact"],
                       [{"do": _touch_cmd(art), "verify": _exists(art)}])
    assert r["status"] == "candidate", (
        f"a fresh recording came out {r['status']} — trust must be earned, "
        f"not conferred by the demo")
    r2 = runbook.record_demo(root, "demoed2", ["recorded", "again"],
                        [{"do": _touch_cmd(art), "verify": _exists(art)}],
                        rehearse=True)
    assert r2["rehearsed"] is True, r2
    t2 = runbook._trust(root).get("demoed2", {})
    assert t2.get("wins") == 1, "a verified rehearsal must be recorded"
    assert t2.get("accepted_wins") == 0, (
        "a rehearsal earned an ACCEPTED win — nobody accepted it. The demo "
        "replayed its own verify lines; that proves the recording runs, not "
        "that it does the job somebody asked for")
    assert r2["status"] == "candidate", r2
    assert runbook.load(root, "demoed")["provenance"]["recorded"] is True
    print("[record] a demonstrated procedure landed as a CANDIDATE with "
          "recorded provenance; a step without verify was refused; the "
          "rehearsal replayed the demo through the authority stack, was "
          "recorded as a run, and earned NO trust — a procedure grading its "
          "own replay is still the procedure grading itself")


if __name__ == "__main__":
    main()
