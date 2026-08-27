#!/usr/bin/env python3
"""REPAIR — a blocked goal fixes what blocked it, grounded in evidence.

THE REQUIREMENT THIS SERVES. The project calls for a goal agent that, when
the job is not done, modifies itself and its approach UNTIL it is done —
"not in a dumb way, like an AI hallucinating and thinking it really did the
job". That last clause is the entire design problem, and the research
record is unusually clear about it:

  * Huang et al., ICLR 2024 (arXiv:2310.01798): models asked to correct
    themselves WITHOUT an external signal get WORSE, not better. Intrinsic
    reflection is the hallucination loop the owner is describing.
  * Shinn et al., Reflexion / Wang et al., Voyager (arXiv:2305.16291):
    correction works when it incorporates ENVIRONMENT FEEDBACK and
    EXECUTION ERRORS — the actual stderr, the actual failing check.
  * Darwin Gödel Machine (arXiv:2505.22954): self-modification is safe to
    keep only when EMPIRICALLY VALIDATED afterwards, and variants keep a
    LINEAGE — the parent is never destroyed by the child.
  * Feedback Friction (arXiv:2506.11930): models struggle to absorb even
    good feedback, so the signal handed to a retry must be SMALL and
    EXPLICIT — one failing test and its error, not a wall of logs.

So this module obeys four laws, each of which the tests break on purpose
to prove the enforcement is real:

  LAW 1 — NO REPAIR WITHOUT A SIGNAL. Every planned action carries the
          mechanical evidence that motivated it: the failing acceptance
          test's id and command, the failing milestone's check and its
          recorded stderr, the exit-127 that means a tool is missing.
          There is no "reflect and try again" action.
  LAW 2 — REPAIR NEVER GRADES ITSELF. This module can transition a
          contract blocked -> running and take actions; it cannot make
          anything VERIFIED. Only contract.verify / runbook.reconcile —
          the frozen graders, run by the harness — decide whether the
          repair worked. A verified state with no passing verify event
          behind it is detectable forgery (contract.replay).
  LAW 3 — THE MACHINE NEVER LIFTS ITS OWN CEILING. A budget block and a
          tamper block route to the OWNER, always. An agent that can
          raise its own budget when it runs out has no budget; an agent
          that can forgive tampering with its graders has no graders.
  LAW 4 — REVISION KEEPS LINEAGE. A runbook revision is written beside
          its parent (name-v2, provenance.parent set), starting as a
          CANDIDATE with zero trust. The parent's file and earned trust
          record are untouched — an archive, not an overwrite.

And repair itself is watched for the failure it fixes: attempts are
bounded, and planning the IDENTICAL repair twice stops with "repair is
not converging" — the oscillation rule, one level up.

    python repair.py diagnose <root> <gid>
    python repair.py plan     <root> <gid>
    python repair.py apply    <root> <gid> [--resume] [--max 3]
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

MAX_REPAIRS = 3
# the spellings of "a tool is missing" across shells and OSes — the one
# failure class a machine can sometimes fix by itself (via a known recipe)
_MISSING_TOOL = re.compile(
    r"exit\s*127|command not found|not recognized as|No such file or "
    r"directory.*(?:bin|exe)|ModuleNotFoundError|ImportError", re.I)


class RepairError(Exception):
    pass


# ---------------------------------------------------------------- diagnose

def diagnose(root, gid):
    """What blocked this goal, classified into the platform's own gap
    dimensions, with the mechanical evidence attached. -> dict.

    Reads the contract and its event ledger — never the model's opinion of
    what went wrong, because the ledger records what HAPPENED.
    """
    import contract
    c = contract.load(root, gid)
    ev = contract.events(root, gid)
    why = str(c.get("state_why") or "")
    d = {"gid": gid, "state": c["state"], "why": why,
         "kind": "unknown", "signals": [], "owner_only": False}

    if c["state"] not in ("blocked", "exhausted", "failed"):
        d["kind"] = "not_blocked"
        return d
    low = why.lower()
    if "tamper" in low:
        d["kind"] = "tamper"
        d["owner_only"] = True
        d["signals"].append({"what": "the frozen acceptance tests no longer "
                                     "match their seal", "evidence": why})
        return d
    if "budget" in low:
        d["kind"] = "budget"
        d["owner_only"] = True
        d["signals"].append({"what": "a budget ceiling was reached",
                             "evidence": why})
        return d

    # oscillation / exhaustion: recover the exact failing checks and their
    # recorded errors from the ledger — the signal, verbatim
    fails = [e for e in ev if e.get("kind") == "milestone_failed"]
    seen = set()
    for e in fails[-6:]:
        key = (e.get("n"), e.get("check"))
        if key in seen:
            continue
        seen.add(key)
        d["signals"].append({
            "what": f"milestone M{e.get('n')} failed",
            "milestone": e.get("what", ""),
            "check": e.get("check", ""),
            "evidence": e.get("error", "")})
    # failing acceptance tests, from the last verify event
    last_verify = next((e for e in reversed(ev) if e.get("kind") == "verify"),
                       None)
    if last_verify and last_verify.get("failed"):
        by_id = {a["id"]: a for a in (c.get("acceptance") or [])}
        for aid in last_verify["failed"]:
            a = by_id.get(aid) or {}
            d["signals"].append({"what": f"acceptance {aid} failing",
                                 "check": a.get("check", ""),
                                 "evidence": a.get("what", "")})
    if any(_MISSING_TOOL.search(str(s.get("evidence", "")))
           for s in d["signals"]):
        d["kind"] = "capability"
    elif "no convergence" in low or c["state"] == "exhausted":
        d["kind"] = "procedure_and_knowledge"
    elif "frontier" in low:
        d["kind"] = "frontier"
    else:
        d["kind"] = "execution"
    return d


# -------------------------------------------------------------------- plan

def plan(root, gid):
    """Typed repair actions, EACH carrying the signal that motivated it.

    LAW 1 lives here: an action with no evidence behind it is not planned.
    The machine-executable kinds are `study` (find and ingest real sources
    about the failing subject) and `capability` (a known recipe for a
    missing tool). `revise_runbook` and `retry_with_signal` prepare work
    for the model or the owner; `owner` is the honest terminal for what a
    machine must not fix about itself.
    """
    d = diagnose(root, gid)
    actions = []
    if d["kind"] == "not_blocked":
        return {"diagnosis": d, "actions": []}
    if d["owner_only"]:
        actions.append({
            "kind": "owner", "why": d["why"],
            "note": ("a machine that lifts its own budget has no budget; "
                     "a machine that forgives grader tampering has no "
                     "graders" if d["kind"] in ("budget", "tamper") else
                     d["why"])})
        return {"diagnosis": d, "actions": actions}

    # capability: a missing tool with a known, pinned recipe
    if d["kind"] == "capability":
        try:
            import toolbox
            scan = toolbox.scan(root)
            for cap, meta in scan["capabilities"].items():
                if meta.get("ready"):
                    continue
                rx = toolbox.recipe(cap)
                if not rx:
                    continue
                sig = next((s for s in d["signals"]
                            if _MISSING_TOOL.search(str(s.get("evidence", "")))),
                           d["signals"][0] if d["signals"] else {})
                if "package" in rx:
                    actions.append({
                        "kind": "capability", "capability": cap,
                        "signal": sig,
                        "command": f"python acquire.py request {rx['package']} "
                                   f"--root {root} --source {rx['source']} "
                                   f"--version {rx['version']} "
                                   f"--why \"repair of goal {gid}\""})
                else:
                    actions.append({"kind": "owner", "capability": cap,
                                    "signal": sig, "why": rx.get("owner", "")})
        except Exception:
            pass

    # knowledge: study exactly the failing subject, from real catalogues
    import contract
    c = contract.load(root, gid)
    fail_terms = " ".join(
        f"{s.get('milestone', '')} {s.get('what', '')}" for s in d["signals"])
    query = f"{c['goal']} {fail_terms}"[:200]
    study_cmds = []
    try:
        import discover
        res = discover.search(query, limit=5)
        study_cmds = discover.add_url_commands(res, root=root)
        if study_cmds:
            actions.append({
                "kind": "study", "query": res.get("asked", query),
                "signal": d["signals"][0] if d["signals"] else
                          {"what": d["why"]},
                "sources": [h["url"] for h in res.get("hits", [])],
                "commands": study_cmds})
    except Exception as e:
        actions.append({"kind": "study_unavailable",
                        "why": f"{type(e).__name__}: {e}"[:150]})

    # procedure: a runbook that failed gets a REVISION beside it (LAW 4);
    # a pursuit with no runbook gets a retry carrying the signal
    applied = [e for e in contract.events(root, gid)
               if e.get("kind") == "runbook_applied" and not e.get("ok")]
    if applied:
        actions.append({"kind": "revise_runbook",
                        "runbook": applied[-1]["runbook"],
                        "signal": d["signals"][0] if d["signals"] else {}})
    else:
        actions.append({
            "kind": "retry_with_signal",
            "signal": d["signals"][:3],
            "note": "resume the pursuit with the failing checks and their "
                    "recorded errors in the planner's context — the small, "
                    "explicit signal the feedback-friction result asks for"})
    return {"diagnosis": d, "actions": actions}


def _plan_hash(p):
    canon = json.dumps([{k: v for k, v in a.items() if k != "sources"}
                        for a in p["actions"]], sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------- apply

def revise_runbook(root, name, signal):
    """Write <name>-vN beside the parent. LAW 4: the parent file and its
    earned trust record are untouched; the child starts a CANDIDATE with
    the failing signal embedded and the failing step marked TODO, so
    validation refuses it until a model or an owner supplies a new HOW."""
    import runbook
    parent = runbook.load(root, name)
    n = 2
    while os.path.exists(runbook.path(root, f"{name}-v{n}")):
        n += 1
    child = json.loads(json.dumps(parent))          # deep copy
    child["name"] = f"{name}-v{n}"
    child.pop("status", None)
    child["provenance"] = {"parent": name,
                           "reason": str(signal.get("evidence", ""))[:200],
                           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    # mark the step whose verify matches the failing check, else the last
    target = None
    for st in child["steps"]:
        if signal.get("check") and st.get("verify") == signal["check"]:
            target = st
            break
    target = target or child["steps"][-1]
    target["do"] = (f"TODO: replace — the previous `do` failed with: "
                    f"{str(signal.get('evidence', 'unknown'))[:150]}")
    with open(runbook.path(root, child["name"]), "w", encoding="utf-8") as f:
        json.dump(child, f, indent=1)
    return child["name"]


def apply(root, gid, resume=False, max_repairs=MAX_REPAIRS):
    """Execute the machine-executable half of the plan, record everything
    in the contract's event ledger, and (with resume=True) hand the goal
    back to the graders. Returns what happened; never declares success.
    """
    import contract
    ev = contract.events(root, gid)
    prior = [e for e in ev if e.get("kind") == "repair_applied"]
    if len(prior) >= max_repairs:
        return {"applied": [], "resumed": False,
                "stopped": f"{len(prior)} repair(s) already applied — the "
                           f"bound is {max_repairs}, and a goal still "
                           f"blocked after that many grounded repairs "
                           f"needs an owner, not a fourth attempt"}
    p = plan(root, gid)
    if not p["actions"]:
        return {"applied": [], "resumed": False,
                "stopped": "nothing to repair (not blocked)"}
    h = _plan_hash(p)
    if any(e.get("plan_hash") == h for e in prior):
        contract.event(root, gid, "repair_not_converging", plan_hash=h)
        return {"applied": [], "resumed": False,
                "stopped": "this exact repair was already applied once and "
                           "the goal is blocked again — repair is not "
                           "converging, and repeating it is the oscillation "
                           "defect one level up. An owner is the right tool."}

    applied = []
    for a in p["actions"]:
        if a["kind"] == "study":
            # discovery already ran (read-only); ingestion is emitted as
            # explicit commands — fetching writes to the expert and stays
            # an auditable, deliberate act
            applied.append({"kind": "study", "sources": len(a["sources"]),
                            "commands": a["commands"]})
        elif a["kind"] == "revise_runbook":
            child = revise_runbook(root, a["runbook"], a.get("signal") or {})
            applied.append({"kind": "revise_runbook", "child": child,
                            "note": "candidate with zero trust; its TODO "
                                    "must be filled and three verified wins "
                                    "earned before it runs unsupervised"})
        elif a["kind"] in ("capability", "owner", "retry_with_signal",
                           "study_unavailable"):
            applied.append({k: v for k, v in a.items() if k != "signal"})
    # the small, explicit signal file the resumed planner will read
    sig_path = os.path.join(root, "goals", str(gid), "repair.md")
    with open(sig_path, "w", encoding="utf-8") as f:
        f.write(f"# REPAIR SIGNAL for goal {gid}\n\n"
                f"Blocked: {p['diagnosis']['why']}\n\n"
                f"The mechanical evidence (verbatim from the ledger):\n\n")
        for s in p["diagnosis"]["signals"][:3]:
            f.write(f"- {s.get('what', '')}\n"
                    f"  check: {s.get('check', '')}\n"
                    f"  error: {s.get('evidence', '')}\n")
        f.write("\nAttack exactly these. Do not restate them as done — "
                "the harness re-runs every check itself.\n")
    contract.event(root, gid, "repair_applied", plan_hash=h,
                   kinds=[a["kind"] for a in applied])

    resumed, verified = False, False
    if resume:
        c = contract.load(root, gid)
        if c["state"] == "blocked":
            contract.transition(root, gid, "running",
                                why=f"repair {h} applied; back to the graders")
            resumed = True
        # LAW 2: the graders decide. reconcile runs the frozen acceptance
        # tests; repair itself sets nothing beyond blocked -> running.
        try:
            import runbook
            rr = runbook.reconcile(root, gid)
            verified = bool(rr.get("verified"))
        except Exception:
            verified = False
    return {"applied": applied, "resumed": resumed, "verified": verified,
            "plan_hash": h, "stopped": ""}


# --------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("diagnose", "plan"):
        p = sub.add_parser(name)
        p.add_argument("root"); p.add_argument("gid")
    p = sub.add_parser("apply")
    p.add_argument("root"); p.add_argument("gid")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max", type=int, default=MAX_REPAIRS)
    a = ap.parse_args()

    if a.cmd == "diagnose":
        print(json.dumps(diagnose(a.root, a.gid), indent=1))
    elif a.cmd == "plan":
        print(json.dumps(plan(a.root, a.gid), indent=1))
    elif a.cmd == "apply":
        r = apply(a.root, a.gid, resume=a.resume, max_repairs=a.max)
        print(json.dumps(r, indent=1))
        raise SystemExit(0 if not r["stopped"] else 1)


if __name__ == "__main__":
    main()
