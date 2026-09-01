#!/usr/bin/env python3
"""CONFIDENCE — spend compute in proportion to doubt, not in proportion to habit.

Every serious small-model result in the 2026 literature rests on the same
principle: compute should follow difficulty. A trivial task and a hard one get
the same treatment in most systems, which is simultaneously wasteful and
inadequate. The escalation ladder that fixes it needs a number to climb, and
this module computes that number.

Nothing here asks a model how confident it is — self-reported confidence is
the least reliable signal available. Every input is something the harness
already measured:

    gate          did the task's own definition of done pass? (hard)
    grounding     do the cited atoms exist, and how many?
    evidence      did the research brief establish what the question rests on?
    contested     did it touch a point its own material disagrees about?
    premise       does verified memory contradict the goal?
    competence    what is this expert's MEASURED record in this domain?
    experience    has it done work like this before (skills, gotchas)?
    friction      how many times did the gate refuse along the way?

The band decides what happens next:

    high    ship it
    medium  spend more attempts (candidates.py) before accepting
    low     escalate to the stronger model, or ask the human

That is the whole idea: a task nobody is sure about earns more compute, and
one that sailed through earns none. The band is recorded on the task and
shown in the panel, so "why did this cost more" is answerable.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

WEIGHTS = {"grounding": 0.20, "evidence": 0.15, "contested": 0.15,
           "premise": 0.10, "competence": 0.20, "experience": 0.10,
           "friction": 0.10}
HIGH, LOW = 0.75, 0.45
ACTIONS = {"high": "ship", "medium": "more_compute", "low": "escalate"}


def _competence(root, task):
    """The expert's MEASURED record in this domain, not its opinion."""
    parent = os.path.dirname(root)
    if os.path.basename(parent) != "experts":
        return None
    home, slug = os.path.dirname(parent), os.path.basename(root)
    try:
        import memory
        rows = memory.competence(home, slug).get(slug, {})
    except Exception:
        return None
    domain = task.get("course") or task.get("role") or "general"
    c = rows.get(domain) or rows.get("general")
    if not c:
        return None
    if c["claim"] == "insufficient evidence":
        return 0.5, {"claim": c["claim"], "attempts": c["attempts"],
                     "note": "no record either way in this domain"}
    return c["score"], {"claim": c["claim"], "attempts": c["attempts"],
                        "confidence": c["confidence"]}


def _experience(root, task):
    """Has this expert done work like this before?"""
    goal = task.get("goal") or ""
    hits = 0
    try:
        import skills
        hits += len(skills.select(root, [s["rel"] for s in skills.discover(root)
                                          if set(s["keywords"]) &
                                          set(goal.lower().split())], cap=3))
    except Exception:
        pass
    try:
        import gotchas
        hits += len(gotchas.matching(root, goal, task.get("course")))
    except Exception:
        pass
    if not hits:
        return 0.45, {"prior_work": 0, "note": "nothing similar in memory"}
    return min(1.0, 0.6 + 0.13 * hits), {"prior_work": hits}


def _wants_citations(task, text):
    """Citation grounding only means something where citations are CLAIMED or
    REQUIRED. A practitioner's note that cites nothing is not ungrounded --
    it is not that kind of artifact, and scoring it as a failure made a task
    that passed rank below one that failed."""
    if re.search(r"citecheck", str(task.get("done_check") or ""), re.I):
        return True
    return bool(re.search(r"\b[CPU]-\d{2,}\b", text or ""))


def _grounding(root, task, artifacts):
    try:
        import citecheck
    except ImportError:
        return None
    texts = [p for p in artifacts if p.lower().endswith((".md", ".txt"))]
    if not texts:
        return None
    problems = cited = looked = 0
    for rel in texts:
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError:
            continue
        if not _wants_citations(task, body):
            continue
        looked += 1
        try:
            probs, n_cited, _ = citecheck.check(root, full)
        except Exception:
            continue
        problems += len(probs)
        cited += n_cited
    if not looked:
        return None
    if not cited and not problems:
        return None
    if problems:
        return 0.0, {"unresolved_citations": problems, "cited": cited}
    return min(1.0, 0.6 + 0.08 * cited), {"cited": cited, "unresolved": 0}


def _evidence(root, task):
    """Did the research brief actually establish what the question rests on?"""
    goal = task.get("goal") or ""
    try:
        import hashlib
        key = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:10]
        with open(os.path.join(root, "research", f"{key}.json"),
                  encoding="utf-8") as f:
            rep = json.load(f)
    except (OSError, ValueError):
        return None
    cov = float(rep.get("coverage") or 0)
    return cov, {"coverage": cov,
                 "unestablished": len(rep.get("unestablished") or [])}


def _contested(root, task, artifacts):
    course = task.get("course")
    if not course:
        return None
    try:
        import conflicts
    except ImportError:
        return None
    touched = problems = 0
    for rel in artifacts:
        if not rel.lower().endswith((".md", ".txt")):
            continue
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        try:
            probs, n = conflicts.check(root, full, course)
        except Exception:
            continue
        problems += len(probs)
        touched += n
    if not touched:
        return None
    if problems:
        return 0.0, {"contested_touched": touched, "asserted_as_settled": problems}
    return 0.7, {"contested_touched": touched, "handled_honestly": True}


def _premise(root, task):
    try:
        import premise
        warns = premise.check(root, task.get("goal") or "", task.get("course"))
    except Exception:
        return None
    if not warns:
        return None
    return 0.2, {"premise_warnings": len(warns),
                 "kinds": sorted({w["kind"] for w in warns})}


def _friction(task):
    """How hard was this to land? Refusals and retries are doubt made visible."""
    rejects = int(task.get("done_rejects") or 0)
    attempt = int(task.get("attempt") or 1)
    if not rejects and attempt <= 1:
        return None
    penalty = min(1.0, 0.25 * rejects + 0.2 * (attempt - 1))
    return max(0.0, 1.0 - penalty), {"gate_refusals": rejects,
                                     "attempt": attempt}


def score(agent, task, artifacts=None):
    """-> {confidence, band, action, signals, why}. Never raises."""
    root = agent.root
    if artifacts is None:
        try:
            import candidates
            artifacts = candidates.written_paths(task)
        except Exception:
            artifacts = []
    signals, parts = {}, {}
    probes = (("grounding", lambda: _grounding(root, task, artifacts)),
              ("evidence", lambda: _evidence(root, task)),
              ("contested", lambda: _contested(root, task, artifacts)),
              ("premise", lambda: _premise(root, task)),
              ("competence", lambda: _competence(root, task)),
              ("experience", lambda: _experience(root, task)),
              ("friction", lambda: _friction(task)))
    for name, fn in probes:
        try:
            got = fn()
        except Exception as e:
            signals[name] = {"error": str(e)[:120]}
            continue
        if got is None:
            continue
        value, info = got
        parts[name] = max(0.0, min(1.0, float(value)))
        signals[name] = dict(info, score=round(parts[name], 3))

    gate_passed = None
    if task.get("done_check"):
        gate_passed = task.get("status") == "done"
        signals["gate"] = {"declared": True, "passed": bool(gate_passed)}
    if parts:
        total = sum(WEIGHTS[k] * v for k, v in parts.items())
        norm = sum(WEIGHTS[k] for k in parts)
        conf = total / norm if norm else 0.5
    else:
        conf = 0.6 if gate_passed else 0.5
        signals["note"] = {"only_signal": "the gate" if gate_passed is not None
                           else "nothing measurable yet"}
    if gate_passed is False:
        conf = min(conf, 0.3)             # a refused gate caps confidence
    band = "high" if conf >= HIGH else "low" if conf < LOW else "medium"
    weakest = sorted(parts.items(), key=lambda kv: kv[1])[:2]
    why = "; ".join(f"{k} {v:.2f}" for k, v in weakest) or "no measured signals"
    return {"confidence": round(conf, 4), "band": band,
            "kind": "heuristic_score", "calibrated": False,
            "calibration_evidence": "NOT_MEASURED: held-out class-specific validation required",
            "action": ACTIONS[band], "signals": signals,
            "weakest": [k for k, _ in weakest], "why": why}


def render(rep):
    return (f"HEURISTIC CONFIDENCE SCORE {rep['confidence']:.0%} ({rep['band']}) -> "
            f"{rep['action']}; weakest: {rep['why']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--task", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    import loop
    agent = loop.Agent(os.path.abspath(a.root))
    task = agent.find_task(a.task)
    if not task:
        raise SystemExit(f"no task {a.task}")
    rep = score(agent, task)
    print(json.dumps(rep, indent=1) if a.json else
          render(rep) + "\n" + json.dumps(rep["signals"], indent=1))


if __name__ == "__main__":
    main()
