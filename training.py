#!/usr/bin/env python3
"""TRAINING LAB — the governed half of learning from verified experience.

Manual §18. The boundary it opens with is the whole design:

    "Training is a separate subsystem. Production expert state and production
     model checkpoints remain immutable during a run. No silent live weight
     mutation."

WHAT THIS MODULE IS, PLAINLY. It implements the parts of §18 that are real
without a GPU and without a training framework: the trajectory store, the
sanitised export, the environment/dataset manifest with hashes, the eval
contract, the model registry and the promotion gate with rollback. Those are
the parts that decide whether a training run is *trustworthy*.

WHAT IT IS NOT. It does not perform gradient updates. There is no GRPO
implementation here, no LoRA, no reward model — those need torch, a GPU and a
serving stack, none of which belong in a stdlib-only platform. §18 marks the
Training Lab REQUIRED/EXPERIMENTAL, and a module that faked the training step
would be worse than one that does not have it: it would let the platform
claim a level of the proof ladder it has not earned.

So `run()` produces an exportable, hash-pinned training package and stops at
the boundary, telling you exactly what an external trainer must do with it.
`promote()` refuses a checkpoint whose DECLARED held-out score does not clear
its declared bar, and every promotion records a rollback target.

WHERE THE SCORE COMES FROM, SAID PLAINLY

This module does not run the evaluation and cannot. The trainer is external —
that is the whole boundary above — so the score arrives from outside, and the
sentence here used to read "promote() refuses a checkpoint that has not passed
a held-out evaluation", which describes a control this file does not have. An
audit was right to call that out: what is governed is a DECLARED result.

So the declaration is now BOUND to something a third party can re-check:

  * `register` requires an EVIDENCE FILE — the evaluation's own output — and
    stores its sha256 beside the score, the checkpoint, the verifier hash and
    the holdout hash. The four travel together and any of them changing
    invalidates the comparison.
  * the record says `score_origin: "declared"` in as many words, so nobody
    reading the registry later mistakes it for an observation this platform
    made.
  * `register`, `promote` and `rollback` refuse to run from inside an agent
    task. A shell-capable worker could otherwise register itself a candidate
    at 0.99 and promote it, which is the shortest path from "the model is
    graded" to "the model grades itself".

That is as far as a stdlib-only platform can honestly bind a number it did
not compute. It is a chain of custody, not a proof of the evaluation.

The invariants from the validation gate, all enforced here:

  * the verifier/control plane is IMMUTABLE to the trainee — a trajectory is
    exported with the verifier's own hash, and a candidate evaluated with a
    different verifier is rejected rather than compared
  * train and eval sets are SEPARATED, by hash, and overlap is refused
  * no benchmark contamination — held-out task ids never appear in training
  * model version immutable; rollback mandatory
"""

import hashlib
import json
import os
import time
import uuid
import math
from pathlib import Path
import learning_authority as authority

DIR = "training"
RUNS = os.path.join(DIR, "runs")
STORE = os.path.join(DIR, "trajectories.jsonl")
REGISTRY = os.path.join(DIR, "registry.json")

# What may be exported. Anything not on this list never leaves the fleet —
# a trajectory carries the shape of the work, never the credentials or the
# owner's private material.
EXPORT_FIELDS = ("task", "role", "goal", "steps", "outcome", "verified",
                 "criterion", "evidence", "cost_usd", "at")

REDACT_KEYS = ("api_key", "authorization", "token", "secret", "password",
               "cookie", "bearer")


class Refused(Exception):
    pass


def _p(root, rel):
    return os.path.join(root, rel)


# --------------------------------------------------------- trajectory store

def _sanitise(value, depth=0):
    """Strip anything credential-shaped, at any depth. A training corpus is
    the single most-copied artefact a platform produces."""
    if depth > 6:
        return "<deep>"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(r in str(k).lower() for r in REDACT_KEYS):
                out[k] = "<redacted>"
            else:
                out[k] = _sanitise(v, depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitise(v, depth + 1) for v in value[:200]]
    if isinstance(value, str):
        low = value.lower()
        if any(r in low for r in ("sk-", "bearer ", "api_key=", "token=")):
            return "<redacted>"
        return value[:4000]
    return value


def capture(root, task, outcome, verified, criterion=None, evidence=""):
    """Record ONE trajectory. Only verified work is worth training on, but
    failures are captured too — a trainer needs both, and §18's Agent-RLVR
    note is precisely about using failure as guidance."""
    rec = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task": task.get("id"), "role": task.get("role"),
        "goal": str(task.get("base_goal") or task.get("goal") or "")[:1000],
        "steps": _sanitise(task.get("steps", [])[:60]),
        "outcome": outcome, "verified": bool(verified),
        "criterion": criterion, "evidence": str(evidence)[:500],
        "cost_usd": float(task.get("cost_usd") or 0.0),
    }
    rec = _sanitise(rec)
    try:
        os.makedirs(os.path.dirname(_p(root, STORE)), exist_ok=True)
        with open(_p(root, STORE), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


def trajectories(root, verified_only=False, limit=100000):
    out = []
    try:
        with open(_p(root, STORE), "r", encoding="utf-8") as f:
            for line in f.readlines()[-limit:]:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if verified_only and not r.get("verified"):
                    continue
                out.append(r)
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ export

def _hash_rows(rows):
    h = hashlib.sha256()
    for r in rows:
        h.update(json.dumps(r, sort_keys=True, ensure_ascii=False).encode())
    return h.hexdigest()[:16]


def _verifier_hash(tree):
    """The control plane the trainee must NOT be able to influence. Exported
    with the dataset so a later evaluation can prove it used the same one."""
    import proof
    return proof.code_hash(["verify.py", "citecheck.py", "memcheck.py",
                            "designcheck.py", "gates.py", "loop.py"], tree)


def export(root, name, holdout_ratio=0.2, verified_only=True, tree=None):
    """Build a training package: train set, held-out eval set, and a manifest
    that pins both by hash along with the verifier that judged them.

    The split is by TASK ID hash, not by shuffling, so re-exporting the same
    corpus produces the same split — an eval set that moves between runs
    cannot tell you whether the model improved.
    """
    _owner_only("export sealed training dataset")
    authority.identifier(name)
    if not math.isfinite(holdout_ratio) or not 0 < holdout_ratio < 1:
        raise Refused("holdout ratio must be strictly between zero and one")
    tree = tree or os.path.dirname(os.path.abspath(__file__))
    rows = [_sanitise({k: r.get(k) for k in EXPORT_FIELDS})
            for r in trajectories(root, verified_only=verified_only)]
    if any(not r.get("task") for r in rows):
        raise Refused("every training trajectory needs a task identity")
    if len(rows) < 4:
        raise Refused(
            f"only {len(rows)} usable trajectory/trajectories. A training run "
            f"on a handful of examples measures noise; gather more verified "
            f"work first.")
    # Rank by a hash of the task id and take an exact proportion, rather than
    # comparing each hash against a threshold. Thresholding is deterministic
    # but not PROPORTIONAL: with a small corpus it can put everything on one
    # side by chance, and a run that sometimes has no held-out set is a run
    # whose eval number sometimes means nothing.
    task_ids = sorted({r["task"] for r in rows}, key=lambda t: hashlib.sha256(str(t).encode()).hexdigest())
    if len(task_ids) < 4:
        raise Refused("at least four independent trajectory task identities required")
    n_hold = max(1, min(len(task_ids) - 1, round(len(task_ids) * holdout_ratio)))
    held_ids = set(task_ids[:n_hold])
    holdout = [r for r in rows if r["task"] in held_ids]
    train = [r for r in rows if r["task"] not in held_ids]
    train_ids = {r["task"] for r in train}
    hold_ids = {r["task"] for r in holdout}
    overlap = train_ids & hold_ids
    if overlap:
        raise Refused(f"benchmark contamination: {len(overlap)} task(s) are "
                      f"in both sets")
    rid = f"{name}-{uuid.uuid4().hex[:16]}"
    d = _p(root, os.path.join(RUNS, rid))
    os.makedirs(d, exist_ok=True)
    for fn, rows_ in (("train.jsonl", train),):
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            for r in rows_:
                f.write(json.dumps({k: r.get(k) for k in EXPORT_FIELDS},
                                   ensure_ascii=False) + "\n")
    manifest = {
        "id": rid, "name": name,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "train": {"n": len(train), "hash": _hash_rows(train)},
        "holdout": {"n": len(holdout), "hash": _hash_rows(holdout),
                    "task_ids": sorted(hold_ids), "storage": "owner_authority"},
        "verified_only": verified_only,
        "verifier_hash": _verifier_hash(tree),
        "boundary": (
            "This package is DATA. Expert Fleet does not perform gradient "
            "updates: no GRPO, no LoRA, no reward model lives here, because "
            "that needs a GPU and a training stack this platform deliberately "
            "does not carry. An external trainer consumes train.jsonl, and "
            "the resulting checkpoint is registered here and evaluated "
            "against holdout.jsonl with the SAME verifier hash before it may "
            "be promoted."),
        "next_step": (
            "run your trainer against train.jsonl, then: "
            "python training.py register <run-id> --checkpoint <name> "
            "--eval-score <0..1>"),
    }
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    authority.store(root, "training-run", rid, {"manifest": manifest, "holdout": holdout,
                    "train_hash": authority.digest(train)})
    return manifest


# ---------------------------------------------------------------- registry

def _registry(root):
    try:
        with open(_p(root, REGISTRY), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"candidates": [], "promoted": None, "history": []}


def _save_registry(root, rec):
    os.makedirs(os.path.dirname(_p(root, REGISTRY)), exist_ok=True)
    tmp = f"{_p(root, REGISTRY)}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, ensure_ascii=False)
    os.replace(tmp, _p(root, REGISTRY))
    return rec


def register(root, run_id, checkpoint, eval_score, verifier_hash,
             eval_detail="", seeds=1, evidence=None):
    """A candidate checkpoint, with the evaluation that DECLARED it.

    `evidence` is the path to the evaluation's own output — the file the
    external trainer produced when it ran the holdout. It is required, it must
    exist and be non-empty, and its sha256 is pinned into the record beside
    the score.

    This does not make the score true. It makes it CHECKABLE: the registry
    now names a specific artifact that a third party can re-read, and a score
    edited later no longer matches the evidence it claimed to come from. The
    field `score_origin` says "declared" so the record cannot be mistaken for
    an observation this platform made.
    """
    _owner_only("register")
    authority.identifier(run_id)
    authority.identifier(checkpoint)
    d = _p(root, os.path.join(RUNS, run_id))
    try:
        with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
    except OSError:
        raise Refused(f"no training run {run_id!r}")
    sealed = authority.load(root, "training-run", run_id)
    if man != sealed["manifest"]:
        raise Refused("TAMPER: changed training manifest")
    if verifier_hash != man["verifier_hash"]:
        raise Refused(
            "this checkpoint was evaluated with a DIFFERENT verifier than the "
            "one that produced the data. Comparing those two numbers would "
            "measure the verifier, not the model.")
    try:
        score = float(eval_score)
    except (TypeError, ValueError):
        raise Refused(f"eval_score {eval_score!r} is not a number")
    if not (0.0 <= score <= 1.0):
        raise Refused(
            f"eval_score {score} is outside 0..1. A score this registry "
            f"cannot interpret is not a result — and the promotion gate "
            f"compares it against a baseline on the same scale.")
    if not evidence:
        raise Refused(
            "a candidate needs the EVALUATION'S OWN OUTPUT (--evidence "
            "<file>). This platform does not run the evaluation, so the score "
            "is a declaration; without an artifact to pin it to there is "
            "nothing anyone can re-check, and the registry would be governing "
            "a number rather than a result.")
    try:
        with open(evidence, "rb") as f:
            blob = f.read()
    except OSError as e:
        raise Refused(f"the evidence file could not be read: {e}")
    if not blob.strip():
        raise Refused(f"the evidence file {evidence!r} is empty")
    reg = _registry(root)
    if any(c["checkpoint"] == checkpoint for c in reg["candidates"]):
        raise Refused("checkpoint identity is immutable; choose a new candidate")
    reg["candidates"].append({
        "run": run_id, "checkpoint": checkpoint,
        "eval_score": score, "eval_detail": str(eval_detail)[:400],
        "score_origin": "declared",
        "evidence": os.path.basename(str(evidence))[:120],
        "evidence_sha256": hashlib.sha256(blob).hexdigest(),
        "evidence_bytes": len(blob),
        "seeds": int(seeds), "verifier_hash": verifier_hash,
        "holdout_hash": man["holdout"]["hash"],
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "promoted": False,
    })
    _save_registry(root, reg)
    return reg["candidates"][-1]


def promote(root, checkpoint, baseline_score, threshold=0.02, by="owner"):
    """The gate. §18: promote only if predefined thresholds pass, canary
    first, and preserve rollback.

    The number compared here was DECLARED by whoever registered the
    candidate — see the module docstring. What this gate enforces is that the
    declaration is complete, pinned to an evidence artifact, and clears a bar
    fixed before the comparison."""
    _owner_only("promote")
    if not all(math.isfinite(float(v)) for v in (baseline_score, threshold)) or not 0 <= float(baseline_score) <= 1 or threshold < 0.02:
        raise Refused("invalid baseline or promotion threshold")
    reg = _registry(root)
    cand = next((c for c in reversed(reg["candidates"])
                 if c["checkpoint"] == checkpoint), None)
    if not cand:
        raise Refused(f"{checkpoint!r} is not a registered candidate")
    if cand["seeds"] < 2:
        raise Refused(
            "§18 requires at least two independent seeds for a training "
            "experiment. One seed cannot distinguish an improvement from a "
            "lucky initialisation.")
    if not cand.get("evidence_sha256"):
        raise Refused(
            f"{checkpoint!r} was registered without pinned evaluation "
            f"evidence, so its score is a bare assertion with nothing behind "
            f"it. Re-register it with --evidence <the evaluation's output>.")
    delta = cand["eval_score"] - float(baseline_score)
    if delta < threshold:
        raise Refused(
            f"held-out score {cand['eval_score']:.3f} vs baseline "
            f"{baseline_score:.3f} = {delta:+.3f}, below the {threshold:+.3f} "
            f"bar. Not promoted: a change that cannot clear its own declared "
            f"threshold is not an improvement.")
    if cand.get("score_origin") != "sealed_paired_evaluation":
        raise Refused("declared evidence is not promotable: sealed evaluation and canary required")
    receipt = authority.load(root, "training-eval", checkpoint)
    canary = authority.load(root, "training-canary", checkpoint)
    policy = authority.load(root, "training-policy", cand["run"])
    if receipt["candidate"] != cand or not canary["passed"] or canary["checkpoint_sha256"] != cand["checkpoint_sha256"]:
        raise Refused("TAMPER or failing canary")
    if float(baseline_score) != receipt["baseline_score"] or threshold != policy["threshold"]:
        raise Refused("promotion criteria differ from sealed policy")
    if _verifier_hash(policy["tree"]) != cand["verifier_hash"]:
        raise Refused("verifier changed after evaluation")
    if hashlib.sha256(Path(cand["checkpoint_path"]).read_bytes()).hexdigest() != cand["checkpoint_sha256"]:
        raise Refused("checkpoint changed after evaluation")
    previous = reg.get("promoted")
    cand["promoted"] = True
    reg["promoted"] = {"checkpoint": checkpoint, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "by": by, "eval_score": cand["eval_score"],
                       "score_origin": cand.get("score_origin", "declared"),
                       "evidence_sha256": cand.get("evidence_sha256"),
                       "verifier_hash": cand.get("verifier_hash"),
                       "holdout_hash": cand.get("holdout_hash"),
                       "baseline": float(baseline_score),
                       "rollback_to": previous["checkpoint"] if previous else None}
    reg["history"].append(dict(reg["promoted"]))
    _save_registry(root, reg)
    return reg["promoted"]


def rollback(root, by="owner", why=""):
    _owner_only("rollback")
    reg = _registry(root)
    cur = reg.get("promoted")
    if not cur:
        raise Refused("nothing is promoted")
    target = cur.get("rollback_to")
    reg["promoted"] = ({"checkpoint": target, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "by": by, "rolled_back_from": cur["checkpoint"],
                        "why": why} if target else None)
    reg["history"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "action": "rollback", "from": cur["checkpoint"],
                           "to": target, "by": by, "why": why})
    _save_registry(root, reg)
    return reg["promoted"]


def set_evaluation_policy(root, run_id, *, baseline_checkpoint, canary_tasks,
                          seeds=(0, 1, 2), threshold=0.02, tree=None):
    """Freeze criteria BEFORE importing a trained candidate; owner callbacks judge.

    baseline_checkpoint is an immutable model revision/reference chosen by the
    owner. A score supplied by the external trainer is never the evaluator.
    """
    _owner_only("set evaluation policy")
    sealed = authority.load(root, "training-run", run_id)
    tree = os.path.abspath(tree or os.path.dirname(__file__))
    if _verifier_hash(tree) != sealed["manifest"]["verifier_hash"]:
        raise Refused("verifier changed since export")
    if len(set(seeds)) < 3 or any(type(s) is not int or s < 0 for s in seeds):
        raise Refused("three distinct nonnegative seeds required")
    if not math.isfinite(threshold) or threshold < 0.02 or threshold > 1:
        raise Refused("invalid promotion threshold")
    if not baseline_checkpoint:
        raise Refused("immutable baseline reference required")
    ids = [str(r.get("task", "")) for r in canary_tasks]
    held = {str(r["task"]) for r in sealed["holdout"]}
    training_ids = {str(r["task"]) for r in _training_rows(root, run_id)}
    if len(ids) < 20 or len(set(ids)) != len(ids) or "" in ids or set(ids) & (held | training_ids):
        raise Refused("canary requires 20 distinct fresh tasks outside train and holdout")
    if len(held) < 20:
        raise Refused("sealed evaluation requires at least 20 distinct holdout tasks")
    return authority.store(root, "training-policy", run_id,
        {"baseline_checkpoint": baseline_checkpoint, "canary_tasks": canary_tasks,
         "seeds": list(seeds), "threshold": threshold, "tree": tree,
         "verifier_hash": sealed["manifest"]["verifier_hash"]})


def _training_rows(root, run_id):
    sealed = authority.load(root, "training-run", run_id)
    path = Path(root) / RUNS / authority.identifier(run_id) / "train.jsonl"
    if path.is_symlink():
        raise Refused("redirected training dataset")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if authority.digest(rows) != sealed["train_hash"]:
        raise Refused("TAMPER: training dataset changed")
    return rows


def evaluate_checkpoint(root, run_id, checkpoint, checkpoint_path, evaluator):
    """Trusted owner evaluator(model_reference, heldout_row, seed) -> exact bool.

    External training is never run here. The evaluator adapter must itself
    keep graders out of the trainee's input and maintain execution isolation.
    Passing a callable is owner code execution, never a worker tool.
    """
    _owner_only("evaluate checkpoint")
    authority.identifier(checkpoint)
    sealed = authority.load(root, "training-run", run_id)
    policy = authority.load(root, "training-policy", run_id)
    if _verifier_hash(policy["tree"]) != policy["verifier_hash"]:
        raise Refused("verifier changed")
    path = Path(checkpoint_path).resolve(strict=True)
    if not path.is_file() or Path(checkpoint_path).is_symlink():
        raise Refused("checkpoint must be a regular immutable file")
    ck_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    records = []
    for seed in policy["seeds"]:
        for row in sealed["holdout"]:
            base = evaluator(policy["baseline_checkpoint"], dict(row), seed)
            result = evaluator(str(path), dict(row), seed)
            if type(base) is not bool or type(result) is not bool:
                raise Refused("evaluator must return a mechanical boolean")
            records.append({"task": row["task"], "seed": seed, "base": base, "candidate": result})
    if hashlib.sha256(path.read_bytes()).hexdigest() != ck_hash or _verifier_hash(policy["tree"]) != policy["verifier_hash"]:
        raise Refused("checkpoint/verifier mutated during evaluation")
    n = len(records)
    score = sum(r["candidate"] for r in records) / n
    baseline = sum(r["base"] for r in records) / n
    candidate = {"run": run_id, "checkpoint": checkpoint, "checkpoint_path": str(path),
        "checkpoint_sha256": ck_hash, "eval_score": score, "score_origin": "sealed_paired_evaluation",
        "seeds": len(policy["seeds"]), "verifier_hash": policy["verifier_hash"],
        "holdout_hash": sealed["manifest"]["holdout"]["hash"],
        "evidence_sha256": authority.digest(records), "promoted": False}
    reg = _registry(root)
    if any(c["checkpoint"] == checkpoint for c in reg["candidates"]):
        raise Refused("checkpoint identity already registered")
    authority.store(root, "training-eval", checkpoint,
                    {"candidate": candidate, "baseline_score": baseline, "records": records})
    reg["candidates"].append(candidate)
    _save_registry(root, reg)
    return {"candidate": candidate, "baseline_score": baseline}


def canary(root, checkpoint, evaluator):
    _owner_only("canary evaluation")
    receipt = authority.load(root, "training-eval", checkpoint)
    cand = receipt["candidate"]
    policy = authority.load(root, "training-policy", cand["run"])
    if _verifier_hash(policy["tree"]) != cand["verifier_hash"]:
        raise Refused("verifier changed")
    path = Path(cand["checkpoint_path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != cand["checkpoint_sha256"]:
        raise Refused("checkpoint changed")
    records = []
    for row in policy["canary_tasks"]:
        base = evaluator(policy["baseline_checkpoint"], dict(row), policy["seeds"][0])
        result = evaluator(str(path), dict(row), policy["seeds"][0])
        if type(base) is not bool or type(result) is not bool:
            raise Refused("canary evaluator must return mechanical booleans")
        records.append({"task": row["task"], "base": base, "candidate": result})
    if hashlib.sha256(path.read_bytes()).hexdigest() != cand["checkpoint_sha256"] or _verifier_hash(policy["tree"]) != cand["verifier_hash"]:
        raise Refused("checkpoint/verifier mutated during canary")
    passed = all(r["candidate"] for r in records)
    return authority.store(root, "training-canary", checkpoint,
        {"passed": passed, "records": records, "checkpoint_sha256": cand["checkpoint_sha256"]})


def _owner_only(cmd):
    """register/promote/rollback are OWNER actions.

    Without this, a shell-capable worker could run `python training.py
    register ... --eval-score 0.99 --seeds 2` followed by `promote ...
    --baseline 0.0` and hand itself a promoted checkpoint — the shortest path
    from "the model is graded" to "the model grades itself". The registry also
    lives in training/, which the File Authority now zones CONTROL, so the
    write would be reverted by the seal around any model-authored command;
    this refuses first and says why. Two controls, neither depending on the
    other."""
    import controlplane
    controlplane.owner_only(f"training {cmd}")


def status(root):
    reg = _registry(root)
    rows = trajectories(root)
    return {
        "trajectories": len(rows),
        "verified": sum(1 for r in rows if r.get("verified")),
        "candidates": len(reg["candidates"]),
        "promoted": reg.get("promoted"),
        "boundary": ("Expert Fleet exports training DATA and governs "
                     "promotion. It does not update weights: that needs a GPU "
                     "and a trainer, and pretending otherwise would let the "
                     "platform claim a proof level it has not earned."),
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("status"); p.add_argument("--root", default=".")
    p = sub.add_parser("export"); p.add_argument("name")
    p.add_argument("--root", default="."); p.add_argument("--holdout", type=float,
                                                          default=0.2)
    p = sub.add_parser("register"); p.add_argument("run")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--eval-score", type=float, required=True)
    p.add_argument("--verifier-hash", required=True)
    p.add_argument("--evidence", required=True,
                   help="the evaluation's OWN OUTPUT file. This platform does "
                        "not run the evaluation, so the score is a "
                        "declaration; the evidence is what makes it "
                        "re-checkable, and its sha256 is pinned beside it")
    p.add_argument("--seeds", type=int, default=1)
    p.add_argument("--root", default=".")
    p = sub.add_parser("promote"); p.add_argument("checkpoint")
    p.add_argument("--baseline", type=float, required=True)
    p.add_argument("--root", default=".")
    p = sub.add_parser("rollback")
    p.add_argument("--why", required=True,
                   help="a rollback with no stated reason teaches nobody "
                        "anything the next time this decision comes up")
    p.add_argument("--by", default="owner")
    p.add_argument("--root", default=".")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.cmd == "status":
        s = status(root)
        print(f"{s['trajectories']} trajectory/trajectories "
              f"({s['verified']} verified), {s['candidates']} candidate(s)")
        print(f"promoted: {s['promoted']['checkpoint'] if s['promoted'] else 'none'}")
        print(f"\n{s['boundary']}")
        return
    if a.cmd == "export":
        man = export(root, a.name, a.holdout)
        print(f"{man['id']}: train {man['train']['n']} / holdout "
              f"{man['holdout']['n']}, verifier {man['verifier_hash']}")
        print(f"\n{man['boundary']}\n\nNEXT: {man['next_step']}")
        return
    if a.cmd == "register":
        _owner_only(a.cmd)
        c = register(root, a.run, a.checkpoint, a.eval_score, a.verifier_hash,
                     seeds=a.seeds, evidence=a.evidence)
        print(f"registered {c['checkpoint']} @ {c['eval_score']:.3f} "
              f"(DECLARED, evidence {c['evidence']} "
              f"sha256:{c['evidence_sha256'][:16]})")
        return
    if a.cmd == "rollback":
        _owner_only(a.cmd)
        try:
            back = rollback(root, a.by, a.why)
        except (Refused, ValueError) as e:
            print(f"REFUSED: {e}")
            raise SystemExit(1)
        print(f"rolled back to {back['checkpoint']} "
              f"(from {back['rolled_back_from']})")
        print("  a promotion without a way back is a one-way door; this is "
              "the way back")
        return
    _owner_only("promote")
    p = promote(root, a.checkpoint, a.baseline)
    print(f"promoted {p['checkpoint']} (rollback target: "
          f"{p['rollback_to'] or 'none'})")


if __name__ == "__main__":
    main()
