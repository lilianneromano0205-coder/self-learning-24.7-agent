#!/usr/bin/env python3
"""THE MISSION ENGINE — an objective that survives everything.

Manual §8 (Goal → Learn → Acquire → Execute → Verify) and §11 (anti-drift).

The existing goal engine plans, works, judges and replans. What it cannot do
is answer "why is this action worth doing" for any individual step, because
the objective lives in a prompt and a plan file: compact the transcript,
restart the process, swap the model, and the *words* survive while the
*binding* between an action and the outcome it serves does not.

So a mission is not a longer prompt. It is a CONTRACT held outside the
transcript, and every action must trace to it:

    Goal → Success criterion → Milestone → Task → Expected evidence

Manual §11: *"Before every consequential action, the planner must show the
chain… If the chain is absent, the action is busy work and must be
replanned."* `justify()` is that check, and it refuses rather than warns.

Three invariants, all mechanical:

  OBJECTIVE IS IMMUTABLE   the objective and success criteria are written
                           once. A revision is an explicit, recorded
                           amendment with a reason — never an edit in place,
                           because an objective that can be quietly rewritten
                           is an objective a drifting agent will rewrite.
  EVIDENCE IS MONOTONIC    a criterion that has been met cannot silently
                           become unmet. Invalidating one requires a stated
                           reason and is kept in the record, so "we passed
                           that last week" cannot evaporate.
  EVERY ACTION IS BOUND    a task carries the criterion it serves. Work that
                           serves no criterion is refused as busy work.

Gap analysis (§8) classifies what is actually blocking progress into the four
dimensions the manual names — knowledge, capability, authority, strategy —
because each routes somewhere different: study, acquisition, the human, or a
replan. "It failed" routes nowhere.
"""

import hashlib
import json
import os
import sys
import time
import uuid

# A Windows console defaults to cp1252, which cannot encode the arrows this
# module prints. Same guard chief.py and ui.py already use.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):        # pragma: no cover
    pass

DIR = "missions"

# --- the four gap dimensions (§8) and where each one ROUTES ----------------
GAPS = {
    "knowledge": {
        "means": "the expert does not know something the mission requires",
        "routes_to": "research → sources → curriculum → study → exam",
        "user_sees": "Needs to learn",
    },
    "capability": {
        "means": "a tool, skill, package or computer is missing",
        "routes_to": "capability acquisition in a disposable worker",
        "user_sees": "Needs a tool",
    },
    "authority": {
        "means": "a permission, credential or human decision is missing",
        "routes_to": "the owner — this one cannot be solved by trying harder",
        "user_sees": "Needs you",
    },
    "strategy": {
        "means": "the approach itself is wrong, not the execution",
        "routes_to": "replan with the failure as evidence",
        "user_sees": "Needs a new plan",
    },
    "environment": {
        "means": "the world changed under the plan",
        "routes_to": "re-observe, then replan",
        "user_sees": "Environment changed",
    },
    "execution": {
        "means": "the step was right and the attempt failed",
        "routes_to": "retry with the error in hand",
        "user_sees": "Retrying",
    },
}

CRITERION_STATES = ("pending", "met", "failed", "invalidated")


# ------------------------------------------------------------------- paths

def _dir(root, mid):
    d = os.path.join(root, DIR, mid)
    os.makedirs(d, exist_ok=True)
    return d


def path(root, mid):
    return os.path.join(_dir(root, mid), "mission.json")


def load(root, mid):
    try:
        with open(path(root, mid), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(root, mid, rec):
    import fileauth
    rec["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    fileauth.write_json(root, f"{DIR}/{mid}/mission.json", rec, actor="harness")
    return rec


def _fingerprint(objective, criteria):
    """Identity of the CONTRACT. If this changes without an amendment, the
    mission has drifted and the change is visible instead of silent."""
    body = objective + "|" + "|".join(c["text"] for c in criteria)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


# ------------------------------------------------------------------ create

def create(root, objective, criteria, constraints=None, non_goals=None,
           evidence_required=None, expert=None, owner="owner", mid=None):
    """Define success BEFORE planning (§8). A mission with no criteria is
    refused: without them "done" is whatever the model decides it is."""
    objective = " ".join(str(objective or "").split())
    if not objective:
        raise ValueError("a mission needs an objective")
    crits = []
    for i, c in enumerate(criteria or [], 1):
        text = c["text"] if isinstance(c, dict) else str(c)
        text = " ".join(str(text).split())
        if not text:
            continue
        crits.append({
            "id": f"C{i}", "text": text, "state": "pending",
            "evidence": [], "verifier": (c.get("verifier")
                                         if isinstance(c, dict) else None),
            "met_at": None, "notes": "",
        })
    if not crits:
        raise ValueError(
            "a mission needs at least one success criterion. Without one, "
            "'done' is whatever the model says it is — which is the failure "
            "this whole engine exists to prevent.")
    mid = mid or ("m-" + time.strftime("%Y%m%d-%H%M%S") + "-"
                  + uuid.uuid4().hex[:4])
    rec = {
        "id": mid, "objective": objective, "criteria": crits,
        "constraints": [str(x) for x in (constraints or [])],
        "non_goals": [str(x) for x in (non_goals or [])],
        "evidence_required": [str(x) for x in (evidence_required or [])],
        "expert": expert, "owner": owner,
        "status": "open", "milestones": [], "actions": [], "blockers": [],
        "amendments": [], "cost_usd": 0.0,
        "fingerprint": _fingerprint(objective, crits),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "updated": None,
        "closed": None, "closed_why": None,
    }
    return _save(root, mid, rec)


def amend(root, mid, objective=None, add_criteria=None, why="", by="owner"):
    """The ONLY way the contract changes. Recorded, attributed, reasoned.

    An objective that can be edited in place is one a drifting agent will
    edit; an amendment that must state a reason is one a human will notice.
    """
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    if not why.strip():
        raise ValueError("an amendment must say WHY the contract changed")
    before = rec["fingerprint"]
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by, "why": why,
             "from_fingerprint": before, "changed": []}
    if objective and objective.strip() != rec["objective"]:
        entry["changed"].append({"field": "objective",
                                 "from": rec["objective"], "to": objective})
        rec["objective"] = " ".join(objective.split())
    for c in (add_criteria or []):
        text = c["text"] if isinstance(c, dict) else str(c)
        nid = f"C{len(rec['criteria']) + 1}"
        rec["criteria"].append({"id": nid, "text": " ".join(text.split()),
                                "state": "pending", "evidence": [],
                                "verifier": None, "met_at": None, "notes": ""})
        entry["changed"].append({"field": "criterion", "added": nid})
    if not entry["changed"]:
        return rec
    rec["fingerprint"] = _fingerprint(rec["objective"], rec["criteria"])
    entry["to_fingerprint"] = rec["fingerprint"]
    rec["amendments"].append(entry)
    return _save(root, mid, rec)


# ------------------------------------------------------- the justification

def justify(root, mid, criterion_id, milestone=None, task_goal="",
            expected_evidence=""):
    """Manual §11: an action must show Goal → Criterion → Milestone → Task →
    Expected evidence. Returns the chain, or raises: an action that cannot
    name the criterion it serves is busy work, and busy work is how a long
    mission burns a budget while going nowhere."""
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    crit = next((c for c in rec["criteria"] if c["id"] == criterion_id), None)
    if crit is None:
        raise ValueError(
            f"no success criterion {criterion_id!r} in this mission. Every "
            f"action must serve one of: "
            + ", ".join(f"{c['id']} ({c['text'][:40]})"
                        for c in rec["criteria"]))
    if crit["state"] == "met":
        raise ValueError(
            f"{criterion_id} is already met. Work that re-does a satisfied "
            f"criterion is not progress — pick an unresolved one, or amend "
            f"the mission if the criterion is genuinely wrong.")
    if not str(expected_evidence).strip():
        raise ValueError(
            "state the EXPECTED EVIDENCE: what will exist afterwards that "
            "shows this worked. An action whose result cannot be recognised "
            "cannot be verified either.")
    return {
        "mission": mid, "objective": rec["objective"],
        "criterion": {"id": crit["id"], "text": crit["text"]},
        "milestone": milestone, "task": task_goal,
        "expected_evidence": expected_evidence,
        "fingerprint": rec["fingerprint"],
    }


def record_action(root, mid, chain, task_id=None, status="queued"):
    """Bind a task to the criterion it serves, durably and outside the
    transcript — so a context reset cannot break the link."""
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    rec["actions"].append({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "criterion": chain["criterion"]["id"], "task": task_id,
        "milestone": chain.get("milestone"), "goal": chain.get("task", "")[:300],
        "expected_evidence": chain["expected_evidence"][:300],
        "status": status,
    })
    return _save(root, mid, rec)


# ----------------------------------------------------------------- evidence

def meet(root, mid, criterion_id, evidence, verified_by="", task=None):
    """Mark a criterion met, WITH the evidence. Evidence is monotonic: this
    appends, it never replaces, so the record of how something came to be
    accepted survives."""
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    crit = next((c for c in rec["criteria"] if c["id"] == criterion_id), None)
    if crit is None:
        raise ValueError(f"no criterion {criterion_id}")
    if not str(evidence).strip():
        raise ValueError("a criterion is met by EVIDENCE, not by assertion")
    crit["evidence"].append({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evidence": str(evidence)[:500], "verified_by": verified_by[:120],
        "task": task})
    crit["state"] = "met"
    crit["met_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return _save(root, mid, rec)


def invalidate(root, mid, criterion_id, why, by="examiner"):
    """Un-meet a criterion — only explicitly, only with a reason, and the
    prior evidence is KEPT. Manual §11: 'completed evidence is monotonic
    unless explicitly invalidated'."""
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    crit = next((c for c in rec["criteria"] if c["id"] == criterion_id), None)
    if crit is None:
        raise ValueError(f"no criterion {criterion_id}")
    if not why.strip():
        raise ValueError("invalidating met evidence requires a reason")
    crit["evidence"].append({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evidence": f"INVALIDATED by {by}: {why}", "verified_by": by,
        "invalidation": True})
    crit["state"] = "invalidated"
    crit["met_at"] = None
    return _save(root, mid, rec)


# -------------------------------------------------------------- gap router

def blocked(root, mid, dimension, detail, criterion=None, needs_human=None):
    """Record a blocker AND classify it, because the classification is what
    decides where it goes next. '(§8) Failure is diagnosed into knowledge
    gap, capability gap, execution error, environment change, strategy error
    or irreducible human decision.'"""
    if dimension not in GAPS:
        raise ValueError(f"unknown gap dimension {dimension!r}; "
                         f"the four are: {', '.join(sorted(GAPS))}")
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    g = GAPS[dimension]
    rec["blockers"].append({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "dimension": dimension, "detail": str(detail)[:400],
        "criterion": criterion, "routes_to": g["routes_to"],
        "user_sees": g["user_sees"], "resolved": False,
        "needs_human": bool(g["routes_to"].startswith("the owner")
                            if needs_human is None else needs_human),
    })
    return _save(root, mid, rec)


def resolve_blocker(root, mid, index, how=""):
    rec = load(root, mid)
    if not rec or index >= len(rec["blockers"]):
        raise KeyError(f"{mid}#{index}")
    rec["blockers"][index]["resolved"] = True
    rec["blockers"][index]["how"] = str(how)[:300]
    return _save(root, mid, rec)


# ---------------------------------------------------------------- the view

def compile_state(root, mid):
    """THE MISSION CONTRACT, recompiled from disk on every iteration.

    Manual §11: *"The mission state is recompiled on every iteration so
    context reset cannot silently erase the objective."* This is the block
    that goes into the window — short, factual, and derived, so it cannot
    drift from what is actually recorded.
    """
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    met = [c for c in rec["criteria"] if c["state"] == "met"]
    open_ = [c for c in rec["criteria"] if c["state"] in ("pending", "failed",
                                                          "invalidated")]
    live_blockers = [b for b in rec["blockers"] if not b["resolved"]]
    return {
        "id": mid, "objective": rec["objective"],
        "fingerprint": rec["fingerprint"],
        "criteria_total": len(rec["criteria"]),
        "criteria_met": len(met), "criteria_open": len(open_),
        "open": [{"id": c["id"], "text": c["text"], "state": c["state"]}
                 for c in open_],
        "met": [{"id": c["id"], "text": c["text"],
                 "evidence": c["evidence"][-1]["evidence"] if c["evidence"] else ""}
                for c in met],
        "constraints": rec["constraints"], "non_goals": rec["non_goals"],
        "blockers": live_blockers,
        "needs_human": [b for b in live_blockers if b["needs_human"]],
        "amendments": len(rec["amendments"]),
        "actions": len(rec["actions"]),
        "status": rec["status"],
        "complete": bool(rec["criteria"]) and not open_,
    }


def render(state):
    """The context block. Facts only — this is what stops drift."""
    lines = [
        "MISSION CONTRACT — this is what you are for. Every action you take "
        "must serve one of the OPEN criteria below; if it serves none, stop "
        "and say so rather than doing adjacent work.",
        f"- objective: {state['objective']}",
    ]
    if state["constraints"]:
        lines.append("- constraints (binding): "
                     + "; ".join(state["constraints"][:6]))
    if state["non_goals"]:
        lines.append("- explicitly NOT in scope: "
                     + "; ".join(state["non_goals"][:6]))
    lines.append(f"- progress: {state['criteria_met']}/{state['criteria_total']} "
                 f"criteria met")
    for c in state["met"][:8]:
        lines.append(f"    [MET] {c['id']} {c['text'][:90]}"
                     + (f" — evidence: {c['evidence'][:70]}" if c["evidence"] else ""))
    for c in state["open"][:8]:
        mark = "OPEN" if c["state"] == "pending" else c["state"].upper()
        lines.append(f"    [{mark}] {c['id']} {c['text'][:90]}")
    for b in state["blockers"][:5]:
        lines.append(f"- BLOCKED ({b['dimension']}): {b['detail'][:100]} "
                     f"-> {b['routes_to']}")
    if state["amendments"]:
        lines.append(f"- the contract has been amended {state['amendments']} "
                     f"time(s); the objective above is the current one")
    return "\n".join(lines)


def close(root, mid, why="", by="examiner"):
    """A mission closes when its criteria are met — not when someone says so."""
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    st = compile_state(root, mid)
    if not st["complete"]:
        raise ValueError(
            f"{st['criteria_open']} criterion/criteria are still open: "
            + ", ".join(c["id"] for c in st["open"])
            + ". A mission closes on evidence, not on a decision to stop.")
    rec["status"] = "complete"
    rec["closed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec["closed_why"] = why or "every success criterion met with evidence"
    return _save(root, mid, rec)


def abandon(root, mid, why, by="owner"):
    """The honest alternative to a fake completion."""
    rec = load(root, mid)
    if not rec:
        raise KeyError(mid)
    if not why.strip():
        raise ValueError("abandoning a mission requires a reason")
    rec["status"] = "abandoned"
    rec["closed"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec["closed_why"] = f"abandoned by {by}: {why}"
    return _save(root, mid, rec)


def list_missions(root):
    base = os.path.join(root, DIR)
    out = []
    try:
        names = sorted(os.listdir(base), reverse=True)
    except OSError:
        return out
    for mid in names:
        rec = load(root, mid)
        if rec:
            try:
                out.append(compile_state(root, mid))
            except Exception:
                continue
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("objective")
    p.add_argument("--criterion", action="append", default=[], required=True)
    p.add_argument("--constraint", action="append", default=[])
    p.add_argument("--non-goal", action="append", default=[])
    p.add_argument("--expert")
    p.add_argument("--root", default=".")
    p = sub.add_parser("show"); p.add_argument("id"); p.add_argument("--root", default=".")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("list"); p.add_argument("--root", default=".")
    p = sub.add_parser("gaps")
    a = ap.parse_args()
    if a.cmd == "gaps":
        for k, v in GAPS.items():
            print(f"{k:<12} {v['user_sees']:<20} {v['routes_to']}")
        return
    root = os.path.abspath(a.root)
    if a.cmd == "new":
        rec = create(root, a.objective, a.criterion, a.constraint, a.non_goal,
                     expert=a.expert)
        print(f"mission {rec['id']}: {len(rec['criteria'])} success "
              f"criterion/criteria, fingerprint {rec['fingerprint']}")
        return
    if a.cmd == "show":
        st = compile_state(root, a.id)
        print(json.dumps(st, indent=1) if a.json else render(st))
        return
    for st in list_missions(root):
        print(f"{st['id']:<28} {st['status']:<10} "
              f"{st['criteria_met']}/{st['criteria_total']} criteria  "
              f"{st['objective'][:50]}")


if __name__ == "__main__":
    main()
