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
  7. relearning is bounded and oscillation-aware: identical failure
     signatures across rounds stop the loop with the wall named
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
    and swarm tests use to make 'zero model calls' a proof, not a claim."""
    with open(os.path.join(root, "settings.toml"), "w",
              encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
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
    check_pretest_baseline_is_recorded(home, root)
    check_grading_is_mechanical_and_model_free(home, root)
    check_verdict_only_from_the_graders(home, root)
    check_diagnosis_carries_evidence(home, root)
    check_relearning_is_bounded(home, root)
    check_retention_retest(home, root)
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
    # 2 of 3 transfer artifacts correct -> 0.667 < bar 0.7 -> NOT mastered
    _place(root, "out/t1/pricing.html")
    _place(root, "out/t2/pricing.html")
    ex = mastery.exam(home, "student", PACK, timeout=12)
    assert ex["score"] == round(2 / 3, 3), ex   # stage scores are round(,3)
    v = mastery.verdict(home, "student", PACK,
                        practice_score=1.0, exam_score=ex["score"])
    assert v["mastered"] is False, (
        f"2/3 on the sealed exam with a 0.7 bar was called MASTERED: {v}")
    assert "FLOOR" in v["ceiling"], v
    # third artifact -> 3/3 -> mastered, and the ledger order holds:
    # grader events precede the verdict event
    _place(root, "out/t3/pricing.html")
    ex2 = mastery.exam(home, "student", PACK, timeout=12)
    assert ex2["score"] == 1.0, ex2
    v2 = mastery.verdict(home, "student", PACK, 1.0, ex2["score"])
    assert v2["mastered"] is True
    ev = mastery.events(root, PACK)
    vi = max(i for i, e in enumerate(ev) if e["kind"] == "verdict")
    gi = max(i for i, e in enumerate(ev) if e["kind"] == "task_graded")
    assert gi < vi, "a verdict landed before the graders that justify it"
    print("[verdict] 2/3 on the sealed exam against a 0.7 bar is NOT "
          "mastered; 3/3 is — computed from harness-run grader results "
          "against the pack's frozen thresholds, grader events before the "
          "verdict in the ledger, and the verdict names its own ceiling "
          "(a mechanical floor, not taste)")


def check_diagnosis_carries_evidence(home, root):
    # break t2's artifact so its responsive check fails
    p = os.path.join(root, "out", "t2", "pricing.html")
    io.open(p, "w", encoding="utf-8").write(
        GOOD_HTML.replace("@media (min-width: 700px)", "/* gone */"))
    ex = mastery.exam(home, "student", PACK, timeout=12)
    plan = mastery.diagnose(ex)
    comps = {p_["competency"] for p_ in plan}
    assert "responsive-layout" in comps, (
        f"t2 failed its responsive check and diagnosis named {comps}")
    hit = next(p_ for p_ in plan if p_["competency"] == "responsive-layout")
    assert "t2" in hit["failed_tasks"] and hit["failed_checks"], (
        f"the diagnosis must carry the failing task and checks as its "
        f"evidence — no signal, no re-study: {hit}")
    _place(root, "out/t2/pricing.html")     # repair for later checks
    print("[diagnose] a transfer failure mapped to exactly the competency "
          "its task examines, carrying the failing checks as evidence")


def check_relearning_is_bounded(home, root):
    # make t1 fail permanently, monkeypatch study to count invocations,
    # and let run() loop: identical failure signatures must stop it
    os.remove(os.path.join(root, "out", "t1", "pricing.html"))
    calls = []
    orig_study = mastery.study
    mastery.study = lambda *a, **kw: calls.append(kw.get("competencies")) or []
    try:
        r = mastery.run(home, "student", PACK, drive=False,
                        skip_study=True, timeout=12)
    finally:
        mastery.study = orig_study
    assert r["relearn_rounds"] <= mastery.MAX_RELEARN_ROUNDS, r
    ev = mastery.events(root, PACK)
    assert any(e["kind"] == "not_converging" for e in ev), (
        "the same failure signature repeated across rounds and the loop "
        "did not stop — a third identical attempt is a loop wearing "
        "persistence's clothes")
    assert r["verdict"]["mastered"] is False
    # targeted: re-study was called with SPECIFIC competencies, not None
    targeted = [c for c in calls if c is not None]
    assert targeted and all(c for c in targeted), (
        f"re-study ran untargeted (whole curriculum) instead of attacking "
        f"the failing competencies: {calls}")
    _place(root, "out/t1/pricing.html")
    print(f"[bounded] the mastery loop stopped after "
          f"{r['relearn_rounds']} relearn round(s) on an identical failure "
          f"signature ('not_converging' recorded), verdict NOT mastered, "
          f"and every re-study was targeted at named competencies")


def check_retention_retest(home, root):
    ex_gids = {e["gid"] for e in mastery.events(root, PACK)
               if e.get("kind") == "task_graded" and e.get("phase") == "exam"}
    r = mastery.retest(home, "student", PACK, timeout=12)
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
