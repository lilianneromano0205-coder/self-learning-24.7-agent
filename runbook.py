#!/usr/bin/env python3
"""RUNBOOKS — the goal agent's power that needs no model at all.

THE ARGUMENT. Before AI there were already agents doing regulated,
life-adjacent work reliably: crawlers with persistent frontiers, spacecraft
autonomy with modeled domains, workflow engines, cluster controllers. None
of them were intelligent. They were reliable because the WORK WAS WRITTEN
DOWN as executable procedure and the machine replayed it, verifying as it
went. The model-era mistake is re-deriving the same procedure from scratch
with an LLM every time — paying tokens, latency and hallucination risk for
work that stopped being novel after the first success.

A runbook is that procedure, machine-executable: typed steps, each an action
plus a verification, run through the Execution Authority (policy screened,
sandboxed, approval-tiered) with ZERO model calls. The division of labour:

    the MODEL is for the frontier — goals nobody here has done before.
    It plans, works, fails, recovers, and — when the pursuit ends VERIFIED —
    writes down what actually worked as a runbook.

    the MACHINE is for everything after — the same goal, or one like it,
    is reconciled deterministically: observe which acceptance tests fail,
    apply the matching proven runbook, re-verify, repeat. Cost: pennies of
    compute, no tokens, no drift, no hallucination.

That is where the multiplier lives. A model that spends itself only on the
unknown, in a system that turns each success into deterministic capability,
does less and less model-work per goal as the library grows — and the
library is auditable, versioned, and runs identically at 3am.

TRUST IS EARNED, NEVER SELF-DECLARED — the same discipline as skills:

  * anyone (the worker included) may AUTHOR a runbook: runbooks/*.json is
    workspace. Authoring is where the model's intelligence lands.
  * a new runbook is a CANDIDATE. It runs only inside supervised pursuits
    or when a caller explicitly allows candidates — never in the
    model-free reconcile path.
  * the trust ledger (runbooks/trust.json) is CONTROL: the worker's file
    tools cannot touch it, and only the harness records outcomes. Three
    wins — runs where every step's verification passed AND the caller's
    own acceptance test passed after — promote it to PROVEN. Two
    consecutive losses quarantine it.
  * a QUARANTINED runbook matches nothing until an owner clears it.

WHAT A RUNBOOK IS NOT. It is not a script that runs unexamined: every `do`
goes through policy and the sandbox exactly like a live model command, and
every step must prove itself with its `verify` before the next step runs —
a runbook that stops verifying stops executing. And it is not a claim of
generality: a runbook does the thing it does, on the machine it was proven
on, and the trust ledger records exactly how often that held.

    python runbook.py list     <root>
    python runbook.py validate <root> <name>
    python runbook.py run      <root> <name> [--allow-candidate]
    python runbook.py match    <root> "the goal text"
    python runbook.py reconcile <root> <gid> [--allow-candidates]
    python runbook.py draft    <root> <gid>     # skeleton from a pursuit
"""

import argparse
import json
import os
import re
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

DIR = "runbooks"
TRUST = os.path.join(DIR, "trust.json")
PROMOTE_WINS = 3           # distinct all-verified runs before PROVEN
QUARANTINE_LOSSES = 2      # consecutive failed runs before QUARANTINED
MAX_STEPS = 20             # a procedure longer than this is several procedures
STEP_TIMEOUT = 300
PROBE_TIMEOUT = 30         # when.requires probes are observations, not work
MAX_COMPOSE = 3            # composition depth; deeper is a design smell

_WORD = re.compile(r"[a-z0-9]{3,}")
STOP = {"the", "and", "for", "with", "into", "from", "that", "this", "are",
        "was", "will", "can", "have", "has", "all", "any", "its", "our"}


class RunbookError(Exception):
    pass


# ------------------------------------------------------------------- files

def _dir(root):
    return os.path.join(root, DIR)


def path(root, name):
    return os.path.join(_dir(root), f"{name}.json")


def _slug_ok(name):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", str(name or "")))


def load(root, name):
    with open(path(root, name), encoding="utf-8") as f:
        rb = json.load(f)
    problems = validate(rb)
    if problems:
        raise RunbookError(f"runbook {name!r} is malformed: "
                           + "; ".join(problems))
    return rb


def names(root):
    try:
        return sorted(fn[:-5] for fn in os.listdir(_dir(root))
                      if fn.endswith(".json") and fn != "trust.json")
    except OSError:
        return []


def validate(rb):
    """-> list of problems, empty when well-formed. A runbook that cannot be
    validated cannot be trusted to run, however plausible it looks."""
    out = []
    if not isinstance(rb, dict):
        return ["not an object"]
    if not _slug_ok(rb.get("name")):
        out.append("name must be a short slug (a-z0-9_-)")
    trig = rb.get("triggers")
    if not isinstance(trig, list) or not trig or \
            not all(isinstance(t, str) and t.strip() for t in trig):
        out.append("triggers must be a non-empty list of words")
    # APPLICABILITY, typed (the audit's P1: keyword triggers alone are
    # shallow). `when.not` are negative triggers — words whose presence in a
    # goal means this procedure is the WRONG tool however well the positive
    # triggers fired. `when.requires` are observe-probes — commands that must
    # exit 0 for the procedure to be applicable HERE AND NOW (the tool is
    # installed, the input file exists, the service answers). Both optional;
    # a runbook without `when` behaves exactly as before.
    if "when" in rb:
        w = rb.get("when")
        if not isinstance(w, dict):
            out.append("`when` must be an object")
        else:
            nt = w.get("not") or []
            if not isinstance(nt, list) or \
                    not all(isinstance(t, str) and t.strip() for t in nt):
                out.append("when.not must be a list of words")
            req = w.get("requires") or []
            if not isinstance(req, list) or \
                    not all(isinstance(c, str) and c.strip() for c in req):
                out.append("when.requires must be a list of probe commands")
            elif any("TODO" in c for c in req):
                out.append("when.requires still carries a TODO — a draft, "
                           "not a runbook")
    steps = rb.get("steps")
    if not isinstance(steps, list) or not steps:
        out.append("steps must be a non-empty list")
    elif len(steps) > MAX_STEPS:
        out.append(f"{len(steps)} steps; more than {MAX_STEPS} means this is "
                   f"several procedures wearing one name")
    else:
        for i, st in enumerate(steps, 1):
            if not isinstance(st, dict):
                out.append(f"step {i} is not an object")
                continue
            # COMPOSITION (the HTN-methods half of the audit's E51): a step
            # may be `{"run": "<sub-runbook>"}` instead of do+verify — the
            # sub-runbook's own per-step verifies are the proof, and its own
            # earned trust still gates it at execution time.
            sub = str(st.get("run") or "").strip()
            if sub:
                if not _slug_ok(sub):
                    out.append(f"step {i}: `run` must name a runbook slug")
                if str(st.get("do") or "").strip() \
                        or str(st.get("verify") or "").strip():
                    out.append(f"step {i}: a step is EITHER do+verify OR "
                               f"run — both is two steps wearing one number")
                continue
            if not str(st.get("do") or "").strip():
                out.append(f"step {i} has no `do` command")
            if not str(st.get("verify") or "").strip():
                out.append(
                    f"step {i} has no `verify`. A step that cannot prove "
                    f"itself is a step the machine must not take blind — "
                    f"the verify IS what separates a runbook from a script.")
            if "TODO" in str(st.get("do", "")):
                out.append(f"step {i} still carries a TODO — a draft, "
                           f"not a runbook")
    return out


# ------------------------------------------------------------------- trust

def _trust(root):
    try:
        with open(os.path.join(root, TRUST), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_trust(root, t):
    p = os.path.join(root, TRUST)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(t, f, indent=1)
    os.replace(tmp, p)


def status(root, name):
    """candidate | proven | quarantined — from the CONTROL ledger only.
    A field inside the runbook file itself is ignored: the author does not
    get a vote on whether the author is trusted."""
    rec = _trust(root).get(name) or {}
    return rec.get("status", "candidate")


def record(root, name, won, why=""):
    """The HARNESS records an outcome. Nothing else may — trust.json is
    CONTROL-zoned against the worker's file tools, and this function is the
    single writer the platform uses.

    UNDER THE LOCK, because this is a read-modify-write on a shared ledger
    and locks.py's own docstring names that the platform's standing race.
    Found live, not theorised: two swarm workers finishing at once called
    record() concurrently, one thread's os.replace hit the other's open
    read handle, and the worker died with WinError 32 (sharing violation)
    — its outcome unrecorded. A trust ledger that can lose outcomes under
    exactly the concurrency the swarm creates is a trust ledger only when
    nobody is working."""
    import locks
    with locks.holding(os.path.join(root, TRUST), timeout=10.0, stale=8.0):
        return _record_locked(root, name, won, why)


def _record_locked(root, name, won, why=""):
    t = _trust(root)
    rec = t.setdefault(name, {"status": "candidate", "wins": 0, "losses": 0,
                              "streak_losses": 0, "history": []})
    if won:
        rec["wins"] += 1
        rec["streak_losses"] = 0
        if rec["status"] == "candidate" and rec["wins"] >= PROMOTE_WINS:
            rec["status"] = "proven"
    else:
        rec["losses"] += 1
        rec["streak_losses"] += 1
        if rec["streak_losses"] >= QUARANTINE_LOSSES:
            # a procedure that keeps failing is not tried a third time on
            # its own authority — same shape as goal oscillation
            rec["status"] = "quarantined"
    rec["history"] = (rec.get("history") or [])[-19:] + [{
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "won": bool(won), "why": str(why)[:200]}]
    _write_trust(root, t)
    return rec["status"]


def clear_quarantine(root, name):
    """Owner-only in spirit: exposed on the CLI, never called by the loop.
    Locked for the same reason record() is: one ledger, many possible
    writers, one critical section."""
    import locks
    with locks.holding(os.path.join(root, TRUST), timeout=10.0, stale=8.0):
        return _clear_locked(root, name)


def _clear_locked(root, name):
    t = _trust(root)
    if name in t and t[name].get("status") == "quarantined":
        t[name]["status"] = "candidate"
        t[name]["streak_losses"] = 0
        _write_trust(root, t)
        return True
    return False


# ---------------------------------------------------------------- matching

def _terms(text):
    return {w for w in _WORD.findall(str(text or "").lower()) if w not in STOP}


def match(root, goal_text, allow_candidates=False):
    """Runbooks whose triggers this goal satisfies, best first.

    The rule is the platform's standard one (skills, gotchas): every
    substantive word of a trigger must appear in the goal. PROVEN runbooks
    rank first; candidates appear only when explicitly allowed; quarantined
    runbooks never appear — a procedure that kept failing does not get to
    volunteer.
    """
    gw = _terms(goal_text)
    hits = []
    for name in names(root):
        st = status(root, name)
        if st == "quarantined":
            continue
        if st == "candidate" and not allow_candidates:
            continue
        try:
            rb = load(root, name)
        except (RunbookError, OSError, ValueError):
            continue
        # negative triggers veto: a goal that names what this procedure is
        # WRONG for does not get it, however well the positive words fired
        neg = [t for t in ((rb.get("when") or {}).get("not") or [])
               if _terms(t) and _terms(t) <= gw]
        if neg:
            continue
        fired = [t for t in rb["triggers"] if _terms(t) and _terms(t) <= gw]
        if fired:
            hits.append({"name": name, "status": st, "fired": fired,
                         "steps": len(rb["steps"]),
                         "requires": len((rb.get("when") or {})
                                         .get("requires") or [])})
    hits.sort(key=lambda h: (0 if h["status"] == "proven" else 1,
                             -len(h["fired"])))
    return hits


def applicable(root, name, cfg=None):
    """-> {"ok", "blocked_by": [...]}. Runs the runbook's `when.requires`
    observe-probes through the Execution Authority (as gates, like every
    verify). Matching says "this procedure is ABOUT this goal"; applicable
    says "this procedure can run HERE AND NOW" — the audit's point was that
    the first was standing in for the second. No `requires` means
    unconditionally applicable, which is what every existing runbook says."""
    import execution
    try:
        rb = load(root, name)
    except (RunbookError, OSError, ValueError) as e:
        return {"ok": False, "blocked_by": [f"unloadable: {e}"[:160]]}
    req = (rb.get("when") or {}).get("requires") or []
    cfg = cfg or _cfg(root)
    blocked = []
    for cmd in req:
        try:
            rc, _o, err = execution.run(
                "gate", cmd, root, cfg=cfg, role="practitioner",
                timeout=PROBE_TIMEOUT,
                reason=f"runbook {name} applicability probe")
            if rc != 0:
                blocked.append(f"`{cmd[:80]}` exited {rc}"
                               + (f": {err[:80]}" if err else ""))
        except execution.Refused as e:
            blocked.append(f"`{cmd[:80]}` refused: {str(e)[:80]}")
    return {"ok": not blocked, "blocked_by": blocked}


# --------------------------------------------------------------- execution

def _cfg(root):
    try:
        import tomllib
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError, ImportError):
        return {}


def run(root, name, allow_candidate=False, cfg=None, record_outcome=True,
        _stack=None):
    """Execute one runbook, step by step, verifying each. ZERO model calls.

    Returns {"ok", "steps": [...], "stopped_at", "why"}. Every `do` runs as
    a model_command (policy + sandbox + approval tier) and every `verify` as
    a gate — the runbook was authored under the worker's influence, so it
    gets exactly the containment a live model command gets. A step whose
    verify fails STOPS the run: a procedure that cannot prove its last step
    must not take its next one.

    A `{"run": "<sub>"}` step executes another runbook in place (the HTN
    half): the sub keeps its OWN trust gate (a proven parent cannot smuggle
    a quarantined child), records its own outcome, and a cycle or a depth
    past MAX_COMPOSE stops the run with the chain named.
    """
    import execution
    stack = list(_stack or [])
    if name in stack:
        return {"ok": False, "steps": [], "stopped_at": 0,
                "why": f"composition cycle: {' -> '.join(stack + [name])} — "
                       f"a procedure that contains itself never finishes"}
    if len(stack) >= MAX_COMPOSE:
        return {"ok": False, "steps": [], "stopped_at": 0,
                "why": f"composition deeper than {MAX_COMPOSE} "
                       f"({' -> '.join(stack + [name])}) — flatten it"}
    stack.append(name)
    rb = load(root, name)
    st = status(root, name)
    if st == "quarantined":
        return {"ok": False, "steps": [], "stopped_at": 0,
                "why": f"runbook {name!r} is QUARANTINED after repeated "
                       f"failures; an owner can clear it "
                       f"(python runbook.py clear {root} {name})"}
    if st == "candidate" and not allow_candidate:
        return {"ok": False, "steps": [], "stopped_at": 0,
                "why": f"runbook {name!r} is a CANDIDATE ({PROMOTE_WINS} "
                       f"verified wins promote it); pass allow_candidate "
                       f"to run it supervised"}
    cfg = cfg or _cfg(root)
    done, why, stopped = [], "", 0
    ok = True
    for i, step in enumerate(rb["steps"], 1):
        sub = str(step.get("run") or "").strip()
        if sub:
            rr = run(root, sub, allow_candidate=allow_candidate, cfg=cfg,
                     record_outcome=record_outcome, _stack=stack)
            done.append({"n": i, "ran": sub, "ok": rr["ok"],
                         "why": (rr["why"] or "")[:200]})
            if not rr["ok"]:
                ok, stopped = False, i
                why = (f"step {i} ran runbook {sub!r} and it stopped: "
                       f"{(rr['why'] or '')[:160]}")
                break
            continue
        t = int(step.get("timeout") or STEP_TIMEOUT)
        try:
            rc, _o, err = execution.run(
                "model_command", step["do"], root, cfg=cfg,
                role="practitioner", timeout=t,
                reason=f"runbook {name} step {i} do")
        except execution.Refused as e:
            ok, stopped = False, i
            why = f"step {i} `do` was refused: {e}"
            done.append({"n": i, "do_rc": None, "verify_rc": None,
                         "refused": str(e)[:200]})
            break
        vrc, _vo, verr = 1, "", ""
        try:
            vrc, _vo, verr = execution.run(
                "gate", step["verify"], root, cfg=cfg,
                role="practitioner", timeout=t,
                reason=f"runbook {name} step {i} verify")
        except execution.Refused as e:
            verr = str(e)
        done.append({"n": i, "do_rc": int(rc), "verify_rc": int(vrc),
                     "err": (err or verr or "")[:200]})
        if vrc != 0:
            ok, stopped = False, i
            why = (f"step {i} did not verify (exit {vrc}): the action ran "
                   f"but its own proof failed — the run stops here rather "
                   f"than building on an unproved step")
            break
    result = {"ok": ok, "steps": done, "stopped_at": stopped, "why": why}
    if record_outcome:
        record(root, name, ok, why or "all steps verified")
    return result


# --------------------------------------------------------------- reconcile

def settle(root, gid):
    """Run the frozen graders and, ONLY if every one passes, move the
    contract to verified. The single definition of "the graders decide" —
    reconcile and swarm both call this, because two copies of the
    verify-then-transition step is two chances for one of them to trust
    something other than the graders."""
    import contract
    vr = contract.verify(root, gid)
    if vr.get("tamper") or not vr.get("mechanical"):
        return {"verified": False, "vr": vr}
    if not vr.get("all"):
        return {"verified": False, "vr": vr}
    try:
        c = contract.load(root, gid)
        if c["state"] in ("ready", "blocked"):
            contract.transition(root, gid, "running", why="settling")
        if contract.load(root, gid)["state"] == "running":
            contract.transition(root, gid, "verified",
                                why="all acceptance tests passed, run by "
                                    "the harness")
    except Exception:
        pass
    return {"verified": True, "vr": vr}


def reconcile(root, gid, allow_candidates=False, max_rounds=3):
    """THE MODEL-FREE GOAL LOOP — observe, apply, verify, repeat.

    The Kubernetes-controller shape, applied to a goal contract: run the
    frozen acceptance tests (observe), find a proven runbook matching the
    goal (plan, from the library instead of a model), execute it (act),
    re-run the acceptance tests (verify), until they all pass or nothing
    matches. No model is called at any point; a goal whose procedure is
    known costs compute, not tokens.

    Honest limits, stated: candidates are excluded unless explicitly
    allowed (an unproven procedure does not run unsupervised), and when no
    runbook matches the failing tests the result is BLOCKED with the tests
    named — that boundary is exactly where the model (or the owner) is the
    right tool, and pretending otherwise is how deterministic systems
    became brittle the first time around.
    """
    import contract
    rounds = []
    for rnd in range(1, max_rounds + 1):
        vr = contract.verify(root, gid)
        if vr["tamper"]:
            return {"verified": False, "rounds": rounds,
                    "blocked": vr["why"]}
        if not vr["mechanical"]:
            return {"verified": False, "rounds": rounds,
                    "blocked": "no mechanical acceptance tests — nothing "
                               "a machine can reconcile toward"}
        if vr["all"]:
            settle(root, gid)
            return {"verified": True, "rounds": rounds, "blocked": ""}
        c = contract.load(root, gid)
        cands = match(root, c["goal"], allow_candidates=allow_candidates)
        if not cands:
            return {"verified": False, "rounds": rounds,
                    "blocked": f"no {'runbook' if allow_candidates else 'PROVEN runbook'} "
                               f"matches this goal while "
                               f"{len(vr['failed'])} acceptance test(s) "
                               f"fail ({', '.join(vr['failed'])}) — this "
                               f"is the frontier, where the model or the "
                               f"owner is the right tool"}
        # matching says "about this goal"; APPLICABLE says "can run here
        # and now" — probe each match's when.requires and take the best
        # match that can actually run, naming the ones that cannot
        chosen, skipped = None, []
        for cand in cands:
            ap = applicable(root, cand["name"])
            if ap["ok"]:
                chosen = cand["name"]
                break
            skipped.append(f"{cand['name']} needs "
                           f"{'; '.join(ap['blocked_by'])[:120]}")
        if chosen is None:
            return {"verified": False, "rounds": rounds,
                    "blocked": f"{len(cands)} runbook(s) match this goal "
                               f"but none is applicable here: "
                               f"{' | '.join(skipped)[:400]} — satisfy a "
                               f"precondition or take the frontier path"}
        rr = run(root, chosen, allow_candidate=allow_candidates)
        contract.event(root, gid, "runbook_applied", runbook=chosen,
                       ok=rr["ok"], round=rnd,
                       failing_before=vr["failed"])
        rounds.append({"round": rnd, "runbook": chosen, "ok": rr["ok"],
                       "why": rr["why"]})
        if not rr["ok"]:
            return {"verified": False, "rounds": rounds,
                    "blocked": f"runbook {chosen!r} stopped: {rr['why']}"}
    if settle(root, gid)["verified"]:
        return {"verified": True, "rounds": rounds, "blocked": ""}
    vr = contract.verify(root, gid)
    return {"verified": False, "rounds": rounds,
            "blocked": f"{max_rounds} reconcile round(s) spent and "
                       f"{len(vr.get('failed') or [])} acceptance test(s) "
                       f"still fail — not converging, stopping rather than "
                       f"looping"}


# ------------------------------------------------------------------ drafts

def draft(root, gid):
    """A SKELETON runbook from a verified pursuit's event ledger.

    The machine can recover WHAT was proven (the milestone checks, the
    acceptance tests) but not HOW it was done — the how lived in the
    model's tool calls. So the skeleton carries every verification with
    `do` fields marked TODO, and validate() refuses to run it until a
    model or an owner fills them in. An honest draft, not a fake runbook.
    """
    import contract
    c = contract.load(root, gid)
    ev = contract.events(root, gid)
    steps = []
    seen = set()
    for e in ev:
        if e.get("kind") == "milestone_done" and e.get("check"):
            key = e["check"]
            if key in seen:
                continue
            seen.add(key)
            steps.append({
                "do": f"TODO: the command that accomplishes: "
                      f"{e.get('what', '')[:100]}",
                "verify": e["check"]})
    for a in c.get("acceptance") or []:
        steps.append({"do": "TODO: whatever makes this acceptance test pass",
                      "verify": a["check"]})
    name = re.sub(r"[^a-z0-9]+", "-", c["goal"].lower()).strip("-")[:40] \
        or f"goal-{gid}"
    rb = {"name": name, "version": 1,
          "triggers": sorted(_terms(c["goal"]))[:8],
          "steps": steps or [{"do": "TODO", "verify": "TODO"}],
          "provenance": {"from": f"goal {gid}", "expert_root": os.path.basename(root),
                         "at": time.strftime("%Y-%m-%dT%H:%M:%S")}}
    os.makedirs(_dir(root), exist_ok=True)
    out = path(root, name)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rb, f, indent=1)
    return out, rb


# --------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("root")
    p = sub.add_parser("validate"); p.add_argument("root"); p.add_argument("name")
    p = sub.add_parser("run"); p.add_argument("root"); p.add_argument("name")
    p.add_argument("--allow-candidate", action="store_true")
    p = sub.add_parser("match"); p.add_argument("root"); p.add_argument("goal")
    p.add_argument("--allow-candidates", action="store_true")
    p = sub.add_parser("reconcile"); p.add_argument("root"); p.add_argument("gid")
    p.add_argument("--allow-candidates", action="store_true")
    p = sub.add_parser("draft"); p.add_argument("root"); p.add_argument("gid")
    p = sub.add_parser("clear"); p.add_argument("root"); p.add_argument("name")
    a = ap.parse_args()

    if a.cmd == "list":
        for n in names(a.root):
            t = _trust(a.root).get(n) or {}
            print(f"{n:32} {status(a.root, n):12} "
                  f"wins={t.get('wins', 0)} losses={t.get('losses', 0)}")
    elif a.cmd == "validate":
        try:
            load(a.root, a.name)
            print(f"{a.name}: well-formed")
        except (RunbookError, OSError, ValueError) as e:
            print(f"{a.name}: {e}")
            raise SystemExit(1)
    elif a.cmd == "run":
        r = run(a.root, a.name, allow_candidate=a.allow_candidate)
        print(json.dumps(r, indent=1))
        raise SystemExit(0 if r["ok"] else 1)
    elif a.cmd == "match":
        for h in match(a.root, a.goal, allow_candidates=a.allow_candidates):
            print(f"{h['name']:32} {h['status']:10} fired={h['fired']}")
    elif a.cmd == "reconcile":
        r = reconcile(a.root, a.gid, allow_candidates=a.allow_candidates)
        print(json.dumps(r, indent=1))
        raise SystemExit(0 if r["verified"] else 1)
    elif a.cmd == "draft":
        out, rb = draft(a.root, a.gid)
        print(f"skeleton written to {out} — {len(rb['steps'])} step(s), "
              f"every `do` is a TODO the model or the owner must fill; "
              f"validate refuses it until then")
    elif a.cmd == "clear":
        print("cleared" if clear_quarantine(a.root, a.name)
              else "nothing to clear")


if __name__ == "__main__":
    main()
