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
`promote()` refuses a checkpoint that has not passed a held-out evaluation,
and every promotion records a rollback target.

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
    tree = tree or os.path.dirname(os.path.abspath(__file__))
    rows = trajectories(root, verified_only=verified_only)
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
    ranked = sorted(rows, key=lambda r: hashlib.sha256(
        str(r.get("task")).encode()).hexdigest())
    n_hold = max(1, min(len(ranked) - 1, round(len(ranked) * holdout_ratio)))
    holdout, train = ranked[:n_hold], ranked[n_hold:]
    train_ids = {r["task"] for r in train}
    hold_ids = {r["task"] for r in holdout}
    overlap = train_ids & hold_ids
    if overlap:
        raise Refused(f"benchmark contamination: {len(overlap)} task(s) are "
                      f"in both sets")
    rid = f"{name}-{time.strftime('%Y%m%d-%H%M%S')}"
    d = _p(root, os.path.join(RUNS, rid))
    os.makedirs(d, exist_ok=True)
    for fn, rows_ in (("train.jsonl", train), ("holdout.jsonl", holdout)):
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            for r in rows_:
                f.write(json.dumps({k: r.get(k) for k in EXPORT_FIELDS},
                                   ensure_ascii=False) + "\n")
    manifest = {
        "id": rid, "name": name,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "train": {"n": len(train), "hash": _hash_rows(train)},
        "holdout": {"n": len(holdout), "hash": _hash_rows(holdout),
                    "task_ids": sorted(hold_ids)},
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
             eval_detail="", seeds=1):
    """A candidate checkpoint, with the evaluation that judged it."""
    d = _p(root, os.path.join(RUNS, run_id))
    try:
        with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
    except OSError:
        raise Refused(f"no training run {run_id!r}")
    if verifier_hash != man["verifier_hash"]:
        raise Refused(
            "this checkpoint was evaluated with a DIFFERENT verifier than the "
            "one that produced the data. Comparing those two numbers would "
            "measure the verifier, not the model.")
    reg = _registry(root)
    reg["candidates"].append({
        "run": run_id, "checkpoint": checkpoint,
        "eval_score": float(eval_score), "eval_detail": str(eval_detail)[:400],
        "seeds": int(seeds), "verifier_hash": verifier_hash,
        "holdout_hash": man["holdout"]["hash"],
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "promoted": False,
    })
    _save_registry(root, reg)
    return reg["candidates"][-1]


def promote(root, checkpoint, baseline_score, threshold=0.02, by="owner"):
    """The gate. §18: promote only if predefined thresholds pass, canary
    first, and preserve rollback."""
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
    delta = cand["eval_score"] - float(baseline_score)
    if delta < threshold:
        raise Refused(
            f"held-out score {cand['eval_score']:.3f} vs baseline "
            f"{baseline_score:.3f} = {delta:+.3f}, below the {threshold:+.3f} "
            f"bar. Not promoted: a change that cannot clear its own declared "
            f"threshold is not an improvement.")
    previous = reg.get("promoted")
    cand["promoted"] = True
    reg["promoted"] = {"checkpoint": checkpoint, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "by": by, "eval_score": cand["eval_score"],
                       "baseline": float(baseline_score),
                       "rollback_to": previous["checkpoint"] if previous else None}
    reg["history"].append(dict(reg["promoted"]))
    _save_registry(root, reg)
    return reg["promoted"]


def rollback(root, by="owner", why=""):
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
    p.add_argument("--seeds", type=int, default=1)
    p.add_argument("--root", default=".")
    p = sub.add_parser("promote"); p.add_argument("checkpoint")
    p.add_argument("--baseline", type=float, required=True)
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
        c = register(root, a.run, a.checkpoint, a.eval_score, a.verifier_hash,
                     seeds=a.seeds)
        print(f"registered {c['checkpoint']} @ {c['eval_score']:.3f}")
        return
    p = promote(root, a.checkpoint, a.baseline)
    print(f"promoted {p['checkpoint']} (rollback target: "
          f"{p['rollback_to'] or 'none'})")


if __name__ == "__main__":
    main()
