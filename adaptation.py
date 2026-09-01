"""Experimental, opt-in memory advantages. No weights, provider, or authority edits.

Inspired by https://arxiv.org/abs/2601.18510; this implements a bounded
action-logit adjustment, NOT a reproduction of the JitRL paper. Closed APIs
can use separately labelled candidate verification; no invented API logits.
"""
import math
import re


class Refused(ValueError):
    pass


def _number(value):
    value = float(value)
    if not math.isfinite(value):
        raise Refused("non-finite adaptation value")
    return value


def retrieve(state, trajectories, limit=20):
    """Plain lexical retrieval baseline with provenance and both outcomes.

    Callers must supply independently verified reward receipts, not model
    ratings. Retrieval never grants authority or changes mechanical gates.
    """
    tokens = set(re.findall(r"\w+", state.lower()))
    found, seen = [], set()
    for row in trajectories:
        if row.get("verified") is not True or not row.get("id") or row["id"] in seen:
            continue
        if row.get("split", "experience") != "experience":
            continue  # evaluation material is never adaptation memory
        seen.add(row["id"])
        other = set(re.findall(r"\w+", str(row.get("state", "")).lower()))
        score = len(tokens & other) / max(1, len(tokens | other))
        reward = _number(row.get("reward", 0))
        if not 0 <= reward <= 1:
            raise Refused("reward must be in 0..1")
        if score:
            found.append({"id": row["id"], "action": str(row["action"]),
                          "reward": reward, "similarity": score})
    return sorted(found, key=lambda r: (-r["similarity"], str(r["id"])))[:max(0, min(100, limit))]


def advantages(state, trajectories):
    rows = retrieve(state, trajectories)
    weight = sum(r["similarity"] for r in rows)
    baseline = sum(r["reward"] * r["similarity"] for r in rows) / weight if weight else 0
    grouped = {}
    for row in rows:
        grouped.setdefault(row["action"], []).append(row)
    return {action: sum(r["similarity"] * (r["reward"] - baseline) for r in group)
            / sum(r["similarity"] for r in group) for action, group in grouped.items()}, rows


def local_logits(state, logits, trajectories, *, enabled=False,
                 logits_accessible=False, strength=1.0, max_bias=1.0):
    if not enabled or not logits_accessible:
        raise Refused("experimental local adaptation requires opt-in and accessible logits")
    strength, max_bias = _number(strength), _number(max_bias)
    if not 0 <= strength <= 5 or not 0 <= max_bias <= 2 or not logits:
        raise Refused("invalid bounded logit adjustment")
    adv, rows = advantages(state, trajectories)
    adjusted = {action: _number(logit) + max(-max_bias, min(max_bias, strength * adv.get(action, 0)))
                for action, logit in logits.items()}
    return {"mode": "local_action_logits", "experimental": True, "exact_jitrl": False,
            "logits": adjusted, "advantages": adv,
            "retrieved_ids": [r["id"] for r in rows], "lift": "NOT_EVALUATED"}


def closed_api_rerank(state, candidates, trajectories, verifier, *, enabled=False):
    if not enabled:
        raise Refused("closed API approximation requires explicit opt-in")
    if not candidates or len(candidates) > 32 or len(set(candidates)) != len(candidates):
        raise Refused("supply 1..32 unique candidate actions")
    adv, rows = advantages(state, trajectories)
    accepted = []
    for action in candidates:
        try:
            if verifier(action) is True:
                accepted.append(action)
        except Exception:
            continue  # verifier failure never grants acceptance
    chosen = max(accepted, key=lambda a: adv.get(a, 0)) if accepted else None
    return {"mode": "closed_api_approximation", "experimental": True, "exact_jitrl": False,
            "action": chosen, "verified_candidates": len(accepted),
            "retrieved_ids": [r["id"] for r in rows], "lift": "NOT_EVALUATED"}
