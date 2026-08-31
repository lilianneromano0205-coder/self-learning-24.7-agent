#!/usr/bin/env python3
"""MASTERY — competence proven on sealed unseen work, never self-declared.

Both external audits named the same missing subsystem: the platform learned
INFORMATION (sources → notes → closed-book exam) but never proved
PROCEDURAL COMPETENCE — building something unseen and passing graders it
cannot touch. capability.py + mastery.py are that subsystem, and this file
pins its laws:

  1. a pack that cannot examine every competency on SEALED tasks is
     refused at validation — mastery of an unexamined competency would be
     memorisation wearing a medal
  2. THE ANTI-SELF-EXAM LAW: transfer tasks and validators live outside
     the expert's root, where the worker's file tools cannot resolve, and
     the pack's full content is sealed — editing a validator after the
     freeze is a TAMPER verdict and nothing is graded
  3. the PRE-TEST baseline is recorded before any study, however bad —
     improvement claims need a floor to be measured from
  4. practice and exam tasks are graded by the harness running the pack's
     validators through the contract machinery; a pre-existing correct
     artifact passes with ZERO model calls, a missing one fails
  5. the MASTERY VERDICT is computed only from harness-run grader results
     against the pack's frozen thresholds — with the grader events
     preceding the verdict event in the ledger
  6. diagnosis maps failing transfer tasks to the competencies they
     examine, carrying the failing checks as evidence (no signal, no
     re-study)
  7. a consumed evaluation set is never re-sat: a gap found by the
     exam ends in a demand for a fresh independently sealed pack,
     because a student who has seen the transfer tasks can never be
     examined on them again
  8. RETENTION: retest runs the same sealed tasks under fresh pursuit ids
     with no study artifacts injected, and records the delta
  9. verified practice pursuits distill into runbook drafts

Run from the agent/ directory:  python tests/test_mastery.py
"""

import io
import json
import os
import shutil
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import capability              # noqa: E402
import contract                # noqa: E402
import fileauth                # noqa: E402
import fleet                   # noqa: E402
import mastery                 # noqa: E402

PACK = "responsive-pricing"

GOOD_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>main { display: grid; gap: 1rem; }
@media (min-width: 700px) { main { grid-template-columns: repeat(4, 1fr); } }
</style></head>
<body>
<header><h1>Plans</h1></header>
<main>
  <section><h2>Free</h2><p>$0</p><a href="/s">Start free</a></section>
  <section><h2>Team</h2><p>$12</p><a href="/s">Choose Team</a></section>
  <section><h2>Business</h2><p>$49</p><a href="/s">Choose Business</a></section>
  <section><h2>Enterprise</h2><p>$199</p>
    <button aria-label="Contact sales">Contact sales</button></section>
</main>
<footer><p>USD.</p></footer>
</body></html>
"""


def _rig(root):
    """A provider that fails every task instantly, so any PASS in these
    tests can only be the machine path — the same construction the runbook
    and swarm tests use to make 'zero model calls' a proof, not a claim.

    The host backend is declared deliberately: a pack's validators live
    OUTSIDE the expert root (the anti-self-exam law puts them there), and the
    docker backend binds only the root, so a container cannot reach the very
    graders this fixture exists to run."""
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
        json.dump([], f)


def _place(root, rel):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(GOOD_HTML)


# --- expressing what the student CAN DO, for the phases that are sealed
#
# Pretest, exam and retention run inside a disposable arena (mastery._run_task)
# which deliberately carries no prior artifacts — "no artifacts, prompts,
# answers or graders return". That is the anti-contamination law working, and
# it means an exam can no longer be staged by dropping a finished file in the
# expert root: the arena never sees it, and it must not.
#
# So competence is expressed the way the platform actually holds it — as a
# PROVEN procedure. `runbooks/` is carried into the arena, goal.pursue tries
# the deterministic path before any model cycle, and a procedure that writes
# the artifact makes the task pass with zero model calls. Teaching the student
# is now `_teach`; forgetting is `_forget`. That is a stronger fixture than
# the old one: it exercises the machine path the exam is supposed to reward,
# instead of pre-loading the answer where the arena cannot see it anyway.

# One word that appears in exactly ONE sealed task's goal, so a procedure
# summons itself for that task and no other. The ids themselves cannot be
# triggers: runbook._WORD keeps tokens of three characters or more, so "t1"
# yields no terms at all and such a trigger can never fire.
TRIGGER = {"t1": "developer", "t2": "fitness", "t3": "accounting",
           "r1": "gardening", "r2": "bicycle", "r3": "theatre"}


def _procedure(tid, html):
    path = f"out/{tid}/pricing.html"
    effect = {"predicate": "file_equals", "path": path, "value": html}
    return {"name": f"write-{tid}", "triggers": [TRIGGER[tid]],
            "procedure_version": 1,
            "steps": [{"id": "step-1", "depends_on": [], "kind": "deterministic",
                       "action": {"tool": "write_file",
                                  "args": {"path": path, "content": html}},
                       "preconditions": [], "effects": [effect]}],
            "operator": {"inputs": {}, "preconditions": [], "effects": [effect],
                         "invariants": [], "cost_usd": 0.0,
                         "cost_basis": "deterministic local file adapter",
                         "latency_seconds": 0.0, "reversibility": "conditional",
                         "authority": ["workspace-write"],
                         "reliability": {"source": "sealed test fixture"}},
            "provenance": {"compiled": True, "trajectory_ids": [],
                           "input_hashes": [], "family": "pricing",
                           "alignment": "test fixture"}}


def _teach(root, tid, html=None):
    """Give the student a PROVEN procedure for one task — competence that
    travels into the sealed arena, unlike an artifact."""
    import procedure
    import runbook
    rb = _procedure(tid, GOOD_HTML if html is None else html)
    os.makedirs(os.path.join(root, "runbooks"), exist_ok=True)
    with open(runbook.path(root, rb["name"]), "w", encoding="utf-8") as f:
        json.dump(rb, f)
    tp = os.path.join(root, runbook.TRUST)
    try:
        with open(tp, encoding="utf-8") as f:
            trust = json.load(f)
    except (OSError, ValueError):
        trust = {}
    trust[rb["name"]] = {"status": "proven", "wins": 3, "accepted_wins": 3,
                         "losses": 0, "streak_losses": 0, "history": [],
                         "evidence_ids": [], "observations": [],
                         "content_hash": procedure.digest(rb)}
    with open(tp, "w", encoding="utf-8") as f:
        json.dump(trust, f)


def _forget(root, tid):
    import runbook
    try:
        os.remove(runbook.path(root, f"write-{tid}"))
    except OSError:
        pass


def _student(home, name, teach=(), broken=()):
    """A FRESH student per examined scenario.

    The sealed evaluation set is one-shot per (expert, pack hash):
    mastery._reserve_exposure consumes it before dispatch and refuses a
    second sitting, which is the anti-peeking law the mastery-leakage fix
    added. So a file that wants to examine four different competence
    profiles cannot re-sit one student four times — it needs four students.
    That is also the more honest fixture: each scenario is a different
    learner, and no sitting can be contaminated by the one before it."""
    root = fleet.create(home, name, "earns competence")
    _rig(root)
    for tid in teach:
        _teach(root, tid)
    for tid in broken:
        _teach(root, tid,
               GOOD_HTML.replace("@media (min-width: 700px)", "/* gone */"))
    return root


def main():
    home = make_sandbox("mastery", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    # install the shipped pack into this home and seal it
    shutil.copytree(os.path.join(AGENT_DIR, "packs", PACK),
                    os.path.join(home, "packs", PACK))
    root = fleet.create(home, "Student", "earns competence")
    _rig(root)

    check_validation_demands_sealed_coverage(home)
    capability.freeze(home, PACK)
    check_the_anti_self_exam_law(home, root)
    check_the_author_law_and_drafts(home)
    check_pretest_baseline_is_recorded(home, root)
    check_grading_is_mechanical_and_model_free(home, root)
    whole = check_verdict_only_from_the_graders(home, root)
    check_diagnosis_carries_evidence(home, root)
    check_a_consumed_exam_demands_a_fresh_pack(home, root)
    check_retention_retest(home, whole)
    check_distillation(home, root)
    print("PASS test_mastery")


def check_validation_demands_sealed_coverage(home):
    problems = capability.validate(home, PACK)
    assert problems == [], problems
    # a competency with no transfer task must be refused
    bad = os.path.join(home, "packs", "bad-pack")
    shutil.copytree(os.path.join(home, "packs", PACK), bad)
    pk = json.load(open(os.path.join(bad, "pack.json"), encoding="utf-8"))
    pk["competencies"]["untested-magic"] = {"study": "magic"}
    pk["name"] = "bad-pack"
    with open(os.path.join(bad, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(pk, f)
    problems = capability.validate(home, "bad-pack")
    assert any("untested-magic" in p and "transfer" in p for p in problems), (
        f"a competency examined by no sealed task passed validation: "
        f"{problems} — mastery of it would be memorisation wearing a medal")
    # and a task with no acceptance is refused
    t = json.load(open(os.path.join(bad, "transfer", "t1.json"),
                       encoding="utf-8"))
    t["accept"] = []
    with open(os.path.join(bad, "transfer", "t1.json"), "w",
              encoding="utf-8") as f:
        json.dump(t, f)
    problems = capability.validate(home, "bad-pack")
    assert any("no acceptance" in p for p in problems), problems
    print("[coverage] a well-formed pack validates; a competency with no "
          "sealed transfer task is refused by name, and an ungraded task "
          "cannot be in a pack at all")


def check_the_anti_self_exam_law(home, root):
    # 2a. the worker's file tools cannot reach the pack
    for rel in (f"../../packs/{PACK}/transfer/t1.json",
                f"../../packs/{PACK}/validators/check_a11y.py"):
        try:
            fileauth.resolve(root, rel, mode="write", actor="agent")
            raise AssertionError(f"the worker can write {rel} — the student "
                                 f"can edit its own exam")
        except fileauth.Denied:
            pass
        try:
            fileauth.resolve(root, rel, mode="read", actor="agent")
            raise AssertionError(f"the worker can read {rel} — the exam is "
                                 f"not unseen")
        except fileauth.Denied:
            pass
    # 2b. sealing covers the validators: edit one after freeze -> TAMPER
    vp = os.path.join(home, "packs", PACK, "validators", "check_a11y.py")
    # BYTES, not text: universal-newline reads plus platform-translated
    # writes change CRLF/LF even when the text looks identical, and the
    # seal hashes bytes — a byte-for-byte restore must be byte-level
    with open(vp, "rb") as f:
        orig = f.read()
    with open(vp, "wb") as f:
        f.write(b"import sys\nsys.exit(0)  # everything passes now\n")
    try:
        v = capability.verify_pack(home, PACK)
        assert v["tamper"] and not v["ok"], v
        try:
            mastery.pretest(home, "student", PACK)
            raise AssertionError("mastery RAN against a tampered pack — a "
                                 "forged grader that executes is a forged "
                                 "grader that can pass")
        except mastery.MasteryError as e:
            assert "seal" in str(e) or "edited" in str(e), e
    finally:
        with open(vp, "wb") as f:
            f.write(orig)
    assert capability.verify_pack(home, PACK)["ok"], (
        "restoring the validator byte-for-byte should restore the seal")
    print("[sealed] the worker's file tools can neither read nor write the "
          "transfer tasks or validators (they live outside its root), and "
          "swapping a validator for `exit 0` after the freeze is a TAMPER "
          "verdict that refuses to grade anything")


def check_the_author_law_and_drafts(home):
    """A drafted pack is a SHAPE that refuses to freeze until the exam is
    written; a sealed pack records its author, and mastery refuses to
    examine the author on their own pack — the student never sits an exam
    it wrote, enforced by provenance and not just file zones."""
    r = capability.draft(home, "novel-domain", "some new craft",
                         {"first-steps": "how this craft begins"},
                         author="drafter")
    assert r["problems"] and any("TODO" in p for p in r["problems"]), r
    try:
        capability.freeze(home, "novel-domain")
        raise AssertionError("a pack of TODOs froze — an exam nobody wrote "
                             "became a diploma mill")
    except capability.PackError:
        pass
    # a sealed pack authored by the student refuses to examine the student
    authored = "authored-by-student"
    shutil.copytree(os.path.join(home, "packs", PACK),
                    os.path.join(home, "packs", authored))
    pj = os.path.join(home, "packs", authored, "pack.json")
    pk = json.load(open(pj, encoding="utf-8"))
    pk["name"] = authored
    pk["author"] = "student"
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(pk, f)
    row = capability.freeze(home, authored)
    assert row.get("author") == "student", row
    try:
        mastery.pretest(home, "student", authored, timeout=12)
        raise AssertionError("the student sat an exam the student wrote")
    except mastery.MasteryError as e:
        assert "authored" in str(e), e
    # a DIFFERENT author's pack passes the same gate
    mastery._refuse_unless_sealed(home, PACK, expert="student")
    print("[author] a drafted pack (all TODOs) cannot freeze; a sealed "
          "pack records its author; the author is refused as its own "
          "student by name, and a different expert passes the same gate")


def check_pretest_baseline_is_recorded(home, root):
    r = mastery.pretest(home, "student", PACK, timeout=12)
    assert r["score"] == 0.0, (
        f"a fresh student with a provider rigged to fail scored "
        f"{r['score']} before any study — the baseline must be honest")
    ev = [e for e in mastery.events(root, PACK) if e["kind"] == "pretest"]
    assert ev and ev[-1]["score"] == 0.0, ev
    assert len(ev[-1]["failed"]) == 3, ev[-1]
    print("[baseline] the sealed transfer set ran BEFORE any study and the "
          "0.0 baseline was recorded with every failing task named — "
          "improvement claims now have a floor to be measured from")


def check_grading_is_mechanical_and_model_free(home, root):
    # place a correct artifact for e1 only -> e1 passes via the machine
    # path (the contract verifies before any planning), others fail
    _place(root, "out/e1/pricing.html")
    st = os.path.join(root, "state.json")
    before = os.path.getmtime(st) if os.path.exists(st) else None
    res = mastery._run_task(home, "student", PACK,
                            capability.exercises(home, PACK)[0],
                            "practice", drive=False, timeout=30)
    assert res["passed"] is True, res
    after = os.path.getmtime(st) if os.path.exists(st) else None
    assert before == after, (
        "grading a pre-satisfied task touched the task queue — a model was "
        "consulted where the machine path should have settled it")
    # and a task whose artifact is missing fails, with the checks named
    res2 = mastery._run_task(home, "student", PACK,
                             capability.exercises(home, PACK)[1],
                             "practice", drive=False, timeout=15)
    assert res2["passed"] is False and res2["failed_checks"], res2
    print("[graded] a correct artifact passed its pack validators with "
          "ZERO model involvement (task queue untouched, against a rigged "
          "provider); a missing artifact failed with its checks named")


def check_verdict_only_from_the_graders(home, root):
    # TWO STUDENTS, ONE SITTING EACH — the sealed set is one-shot per expert.
    #
    # The partial student can do t1 and t2 and not t3, and ALSO has all three
    # finished artifacts lying in its own root. If the arena leaked prior
    # work, t3 would pass too and this score would be 1.0 — so the single
    # number below is simultaneously the scoring assertion and the proof that
    # an exam cannot be staged from work done outside it.
    partial = _student(home, "Partial Student", teach=("t1", "t2"))
    _place(partial, "out/t1/pricing.html")
    _place(partial, "out/t2/pricing.html")
    _place(partial, "out/t3/pricing.html")
    ex = mastery.exam(home, "partial-student", PACK, timeout=12)
    assert ex["score"] == round(2 / 3, 3), (
        f"expected 2 of 3 from competence alone; a 1.0 here would mean the "
        f"three finished artifacts in the expert root reached the sealed "
        f"arena: {ex}")
    v = mastery.verdict(home, "partial-student", PACK,
                        practice_score=1.0, exam_score=ex["score"])
    assert v["mastered"] is False, (
        f"2/3 on the sealed exam with a 0.7 bar was called MASTERED: {v}")
    assert "FLOOR" in v["ceiling"], v
    print("[sealed] a student holding three finished artifacts still scored "
          "only what it could rebuild — prior work does not reach the arena")

    # a student competent at all three -> 3/3 -> mastered, and the ledger
    # order holds: grader events precede the verdict event
    whole = _student(home, "Whole Student", teach=("t1", "t2", "t3"))
    ex2 = mastery.exam(home, "whole-student", PACK, timeout=12)
    assert ex2["score"] == 1.0, ex2
    v2 = mastery.verdict(home, "whole-student", PACK, 1.0, ex2["score"])
    assert v2["mastered"] is True
    ev = mastery.events(whole, PACK)
    vi = max(i for i, e in enumerate(ev) if e["kind"] == "verdict")
    gi = max(i for i, e in enumerate(ev) if e["kind"] == "task_graded")
    assert gi < vi, "a verdict landed before the graders that justify it"
    print("[verdict] 2/3 on the sealed exam against a 0.7 bar is NOT "
          "mastered; 3/3 is — computed from harness-run grader results "
          "against the pack's frozen thresholds, grader events before the "
          "verdict in the ledger, and the verdict names its own ceiling "
          "(a mechanical floor, not taste)")
    return whole


def check_diagnosis_carries_evidence(home, root):
    # a student whose t2 procedure emits markup with NO breakpoint: the
    # responsive check fails for a real gap in competence, not a damaged
    # file. Its own sitting, because the sealed set is one-shot.
    root = _student(home, "Gapped Student", teach=("t1", "t3"), broken=("t2",))
    ex = mastery.exam(home, "gapped-student", PACK, timeout=12)
    plan = mastery.diagnose(ex)
    comps = {p_["competency"] for p_ in plan}
    assert "responsive-layout" in comps, (
        f"t2 failed its responsive check and diagnosis named {comps}")
    hit = next(p_ for p_ in plan if p_["competency"] == "responsive-layout")
    assert "t2" in hit["failed_tasks"] and hit["failed_checks"], (
        f"the diagnosis must carry the failing task and checks as its "
        f"evidence — no signal, no re-study: {hit}")
    print("[diagnose] a transfer failure mapped to exactly the competency "
          "its task examines, carrying the failing checks as evidence")


def check_a_consumed_exam_demands_a_fresh_pack(home, root):
    """The old law said the relearn loop was BOUNDED — it stopped after two
    identical failures. The exposure law replaces it with something stricter:
    the sealed set is consumed by the sitting that used it, so there is no
    second attempt at the same exam to bound. A diagnosis therefore ends in a
    demand for a fresh, independently sealed pack rather than a re-sit, and
    the number of relearn rounds is structurally zero.

    This is the honest reading of "unseen": a student who has now seen t1-t3
    cannot be re-examined on t1-t3 at any distance, however much re-study
    happens in between."""
    root = _student(home, "Stuck Student", teach=("t2", "t3"))
    _forget(root, "t1")
    r = mastery.run(home, "stuck-student", PACK, drive=False,
                    skip_study=True, timeout=12)
    ev = mastery.events(root, PACK)
    assert r["relearn_rounds"] == 0, (
        f"a relearn round re-sat a consumed evaluation set: {r}")
    assert any(e["kind"] == "fresh_pack_required" for e in ev), (
        "the exam found a gap and the loop neither re-sat it nor said why — "
        "a diagnosis that leads nowhere is not a diagnosis")
    assert r["verdict"]["mastered"] is False
    assert r["exam"] == round(2 / 3, 3), r
    sittings = [e for e in ev
                if e.get("kind") == "task_graded" and e.get("phase") == "exam"]
    assert len(sittings) == 3, (
        f"the sealed transfer set was graded {len(sittings)} times for three "
        f"tasks — an exam was re-sat: {sittings}")
    print("[consumed] a gap found by the exam ends in 'fresh pack required', "
          "not a re-sit: each sealed task was graded exactly once, no "
          "relearn round re-used it, and the verdict stayed NOT mastered")


def check_retention_retest(home, root):
    # RETENTION IS A THIRD, SEPARATE SET (r1-r3): never seen in the
    # baseline, in practice or in the exam. Competence for it has to be
    # held independently, which is the whole point of the split.
    for tid in ("r1", "r2", "r3"):
        _teach(root, tid)
    ex_gids = {e["gid"] for e in mastery.events(root, PACK)
               if e.get("kind") == "task_graded" and e.get("phase") == "exam"}
    r = mastery.retest(home, "whole-student", PACK, timeout=12)
    assert r["score"] == 1.0, r
    re_gids = {e["gid"] for e in mastery.events(root, PACK)
               if e.get("kind") == "task_graded"
               and e.get("phase") == "retest"}
    assert re_gids and not (re_gids & ex_gids), (
        "retest reused exam pursuit ids — retention must be measured in "
        "FRESH contexts, or it measures leftover state")
    ret = [e for e in mastery.events(root, PACK)
           if e["kind"] == "retention"]
    assert ret and ret[-1].get("delta_vs_exam") is not None
    print("[retention] the sealed tasks re-ran under fresh pursuit ids and "
          "the delta against the exam was recorded — what survives a fresh "
          "context is the only honest meaning of 'it learned'")


def check_distillation(home, root):
    drafted = mastery.distill(home, "student", PACK)
    assert drafted, "no runbook drafts from verified practice pursuits"
    import runbook
    for name in drafted:
        assert os.path.exists(runbook.path(root, name)), name
        try:
            runbook.load(root, name)
            raise AssertionError(f"draft {name} validated as runnable — "
                                 f"drafts carry TODOs the model or owner "
                                 f"must fill; competence is distilled, "
                                 f"trust is still earned")
        except runbook.RunbookError:
            pass
    print(f"[distill] {len(drafted)} verified practice pursuit(s) became "
          f"runbook draft(s) — proven verifications kept, the HOW left as "
          f"TODOs, zero trust until three verified wins")


if __name__ == "__main__":
    main()
