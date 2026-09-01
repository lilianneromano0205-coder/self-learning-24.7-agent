#!/usr/bin/env python3
"""THE TRAINING LAB'S BOUNDARY IS THE FEATURE.

Manual §18 invariants: *"Verifier/control plane is immutable to trainee;
train/eval data separated; no benchmark contamination; model version
immutable; rollback mandatory."* And the opening boundary: *"Production
expert state and production model checkpoints remain immutable during a run.
No silent live weight mutation."*

This module deliberately does NOT train weights — that needs a GPU and a
trainer this platform does not carry. What it must get right is everything
that decides whether a training run can be TRUSTED, and each of those is
testable without a single gradient:

  * a trajectory export is sanitised — a training corpus is the most-copied
    artefact a platform produces, so a credential in one is a credential
    everywhere
  * the train/held-out split is deterministic and non-overlapping, or the
    eval number measures the split rather than the model
  * a candidate evaluated with a DIFFERENT verifier is refused, because that
    comparison measures the verifier
  * promotion requires clearing a declared threshold and more than one seed
  * every promotion records a rollback target

Run from the agent/ directory:  python tests/test_training.py
"""

import hashlib
import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import training             # noqa: E402


# The sealed evaluation contract needs >= 20 held-out tasks, and export()
# holds out 20% — so 100 VERIFIED trajectories, which `verified=(i % 4 != 0)`
# turns into at exactly n=134. The default holdout ratio stays exercised
# rather than being widened to make the fixture cheap.
BASELINE = "base-rev-0000000000000000"
CANARY = [{"task": f"canary-{i}", "goal": f"fresh task {i}"} for i in range(20)]


def _frozen_judge(model_reference, row, seed):
    """The MECHANICAL grader, owner-supplied and blind to which side it is
    scoring beyond the reference it was handed: the baseline reference fails
    every row, a real checkpoint file passes. It returns an exact bool, which
    is the only thing evaluate_checkpoint will accept."""
    return model_reference != BASELINE


def _seed(root, n=134):
    for i in range(n):
        training.capture(
            root,
            {"id": f"t{i}", "role": "practitioner",
             "goal": f"do useful thing {i}",
             "steps": [{"tool": "write_file",
                        "args": {"path": "out/x.md",
                                 "api_key": "sk-live-must-not-travel"},
                        "result": "ok"}],
             "cost_usd": 0.01},
            outcome="done", verified=(i % 4 != 0),
            criterion="C1", evidence=f"gate passed for {i}")


def check_export_is_sanitised(root):
    _seed(root)
    rows = training.trajectories(root)
    blob = json.dumps(rows)
    assert "sk-live-must-not-travel" not in blob, (
        "a credential reached the trajectory store; a training corpus is the "
        "most-copied artefact a platform produces")
    assert "<redacted>" in blob
    print("[sanitised] a credential inside a captured step was redacted "
          "before it ever reached the trajectory store")


def check_split_is_deterministic_and_clean(root):
    a = training.export(root, "runA")
    b = training.export(root, "runB")
    assert a["train"]["hash"] == b["train"]["hash"], (
        "the split must be deterministic: an eval set that moves between runs "
        "cannot tell you whether the model improved")
    assert a["holdout"]["hash"] == b["holdout"]["hash"]
    assert set(a["holdout"]["task_ids"]).isdisjoint(
        {r["task"] for r in training.trajectories(root)
         if r["task"] not in a["holdout"]["task_ids"]} & set()), "sanity"
    # the real contamination check: no task in both files
    d = os.path.join(root, "training", "runs", a["id"])
    train_ids = {json.loads(l)["task"]
                 for l in open(os.path.join(d, "train.jsonl"), encoding="utf-8")}
    # holdout rows no longer land on disk beside the trainer's input — export
    # seals them into owner authority (test_advanced_learning asserts the
    # file's ABSENCE); the manifest still names every held-out task id
    hold_ids = set(a["holdout"]["task_ids"])
    assert train_ids and hold_ids
    assert not (train_ids & hold_ids), "benchmark contamination"
    print(f"[split] {len(train_ids)} train / {len(hold_ids)} held-out, "
          f"deterministic across re-exports and provably non-overlapping")
    return a


def _evidence(root, name, body="holdout run: 24/24 checks, score 0.95\n"):
    """A stand-in for the external trainer's evaluation OUTPUT.

    register() requires one because this platform does not run the
    evaluation: the score is a DECLARATION, and an artifact is what makes a
    declaration re-checkable later. See training.py's "WHERE THE SCORE COMES
    FROM, SAID PLAINLY"."""
    p = os.path.join(root, f"eval-{name}.txt")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


def check_verifier_is_immutable_to_the_trainee(root, man):
    """The comparison that would otherwise measure the verifier."""
    try:
        training.register(root, man["id"], "ckpt-1", 0.91,
                          verifier_hash="a-different-verifier", seeds=2,
                          evidence=_evidence(root, "ckpt-1"))
        raise AssertionError("a checkpoint judged by a different verifier "
                             "must not enter the registry")
    except training.Refused as e:
        assert "DIFFERENT verifier" in str(e)
    ev = _evidence(root, "ckpt-1")
    c = training.register(root, man["id"], "ckpt-1", 0.91,
                          verifier_hash=man["verifier_hash"], seeds=2,
                          evidence=ev)
    assert c["holdout_hash"] == man["holdout"]["hash"]
    # THE SCORE IS DECLARED, AND THE RECORD SAYS SO. This platform cannot run
    # the evaluation (no GPU, no trainer), so what the registry governs is a
    # declaration — pinned to the evaluation's own output by sha256 so a
    # score edited later no longer matches the artifact it claimed to be
    # from. An audit was right that binding the number is the most a
    # stdlib-only platform can honestly do; a registry with NOTHING behind
    # the number was the gap.
    assert c["score_origin"] == "declared", c
    assert c["evidence_sha256"] == hashlib.sha256(
        open(ev, "rb").read()).hexdigest(), c
    for bad, needle in ((None, "EVALUATION'S OWN OUTPUT"),
                        (os.path.join(root, "nope.txt"), "could not be read")):
        try:
            training.register(root, man["id"], "ckpt-bare", 0.99,
                              verifier_hash=man["verifier_hash"], seeds=2,
                              evidence=bad)
            raise AssertionError(f"a candidate with evidence={bad!r} was "
                                 f"accepted — its score has nothing behind it")
        except training.Refused as e:
            assert needle in str(e), str(e)
    empty = os.path.join(root, "eval-empty.txt")
    open(empty, "w").close()
    try:
        training.register(root, man["id"], "ckpt-bare", 0.99,
                          verifier_hash=man["verifier_hash"], seeds=2,
                          evidence=empty)
        raise AssertionError("an empty evidence file was accepted")
    except training.Refused as e:
        assert "empty" in str(e), str(e)
    for bad_score in (1.4, -0.2, float("nan")):
        try:
            training.register(root, man["id"], "ckpt-bad-score", bad_score,
                              verifier_hash=man["verifier_hash"], seeds=2,
                              evidence=ev)
            raise AssertionError(f"score {bad_score} was accepted — the "
                                 f"promotion gate compares it to a baseline "
                                 f"on the 0..1 scale")
        except training.Refused as e:
            assert "0..1" in str(e), str(e)
    print("[verifier] a candidate evaluated with a different verifier was "
          "refused — comparing those numbers would measure the verifier, not "
          "the model")


def check_promotion_gate(root, man):
    # below the declared threshold
    try:
        training.promote(root, "ckpt-1", baseline_score=0.90, threshold=0.02)
        raise AssertionError("a +0.01 change must not clear a +0.02 bar")
    except training.Refused as e:
        assert "below the" in str(e), str(e)
    # single seed
    training.register(root, man["id"], "ckpt-lucky", 0.99,
                      verifier_hash=man["verifier_hash"], seeds=1,
                      evidence=_evidence(root, "ckpt-lucky"))
    try:
        training.promote(root, "ckpt-lucky", baseline_score=0.50)
        raise AssertionError("one seed cannot distinguish an improvement from "
                             "a lucky initialisation")
    except training.Refused as e:
        assert "seed" in str(e)
    # A DECLARED number can no longer promote anything. The trainer's own
    # score is a claim; promotion now needs a policy sealed BEFORE the
    # candidate existed, a paired multi-seed run of the owner's frozen
    # evaluator over the sealed holdout, and a canary on fresh tasks.
    training.register(root, man["id"], "ckpt-declared", 0.95,
                      verifier_hash=man["verifier_hash"], seeds=3,
                      evidence=_evidence(root, "ckpt-declared"))
    try:
        training.promote(root, "ckpt-declared", baseline_score=0.90)
        raise AssertionError("a self-declared score promoted a checkpoint")
    except training.Refused as e:
        assert "sealed evaluation and canary required" in str(e), str(e)

    training.set_evaluation_policy(
        root, man["id"], baseline_checkpoint=BASELINE, canary_tasks=CANARY,
        seeds=(0, 1, 2), threshold=0.02)
    ck = os.path.join(root, "ckpt-good.bin")
    with open(ck, "wb") as f:
        f.write(b"weights")
    ev = training.evaluate_checkpoint(root, man["id"], "ckpt-good", ck,
                                      _frozen_judge)
    assert ev["candidate"]["score_origin"] == "sealed_paired_evaluation", ev
    assert ev["candidate"]["eval_score"] == 1.0 and ev["baseline_score"] == 0.0, ev
    cy = training.canary(root, "ckpt-good", _frozen_judge)
    assert cy["passed"] is True, cy
    p = training.promote(root, "ckpt-good", baseline_score=ev["baseline_score"])
    assert p["checkpoint"] == "ckpt-good"
    assert p["score_origin"] == "sealed_paired_evaluation", p
    assert p["evidence_sha256"], p
    assert p["verifier_hash"] == man["verifier_hash"], p
    assert p["holdout_hash"] == man["holdout"]["hash"], p
    print("[gate] a change below its declared threshold, a single-seed "
          "result and a self-declared score were all refused; promotion "
          "required a policy sealed before the candidate existed, a paired "
          "three-seed run of the owner's frozen evaluator over 20 sealed "
          "held-out tasks, and an all-must-pass canary on 20 fresh ones — "
          "and the record carries checkpoint, verifier hash, holdout hash "
          "and evidence sha256, with the score marked SEALED, not DECLARED")


def check_rollback_is_mandatory(root, man):
    # the second promotion goes through the same sealed path; the policy
    # sealed for this run is reused (authority refuses a duplicate key)
    ck = os.path.join(root, "ckpt-next.bin")
    with open(ck, "wb") as f:
        f.write(b"newer weights")
    ev = training.evaluate_checkpoint(root, man["id"], "ckpt-next", ck,
                                      _frozen_judge)
    assert training.canary(root, "ckpt-next", _frozen_judge)["passed"] is True
    p = training.promote(root, "ckpt-next", baseline_score=ev["baseline_score"])
    assert p["rollback_to"] == "ckpt-good", (
        "every promotion must record what it replaced")
    back = training.rollback(root, why="regression in production")
    assert back["checkpoint"] == "ckpt-good"
    assert back["rolled_back_from"] == "ckpt-next"
    print("[rollback] the promotion recorded what it replaced and the "
          "rollback returned to it — a promotion without a way back is a "
          "one-way door")


def check_boundary_is_stated(root):
    s = training.status(root)
    assert "does not update weights" in s["boundary"]
    man_dir = os.path.join(root, "training", "runs")
    one = sorted(os.listdir(man_dir))[0]
    man = json.load(open(os.path.join(man_dir, one, "manifest.json"),
                         encoding="utf-8"))
    assert "does not perform gradient updates" in man["boundary"]
    assert man["next_step"], "the package must say what a trainer does next"
    # and a corpus too small to mean anything is refused outright
    empty = os.path.join(root, "empty-fleet")
    os.makedirs(empty, exist_ok=True)
    try:
        training.export(empty, "nothing")
        raise AssertionError("a run on a handful of examples measures noise")
    except training.Refused as e:
        assert "trajector" in str(e)
    print("[boundary] the export states plainly that this platform does not "
          "perform gradient updates, names what an external trainer must do, "
          "and refuses a corpus too small to mean anything")


def main():
    root = make_sandbox("training", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"},
                        scripts={"s.json": [{"tool": "finish_task",
                                             "args": {"summary": "ok"}}]})
    check_export_is_sanitised(root)
    man = check_split_is_deterministic_and_clean(root)
    check_verifier_is_immutable_to_the_trainee(root, man)
    check_promotion_gate(root, man)
    check_rollback_is_mandatory(root, man)
    check_boundary_is_stated(root)
    print("PASS test_training")


if __name__ == "__main__":
    main()
