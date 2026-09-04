#!/usr/bin/env python3
"""THE CASE LEDGER — did the fix actually work?

The failure record answers "what went wrong". It does not answer the question
that compounds: **what fixed it, and did the fix hold?** That second half is
what turns a log into experience, and it is the difference between a system
that has failed 184 times and one that knows "I have seen this 184 times, and
the thing that works is X".

A case is opened when something fails, and it stays OPEN until a later piece
of work resolves it:

    open      something failed; the cause is recorded
    fixed     a later task with the same signature succeeded -- what it did
              differently is recorded as the fix
    recurred  it came back after being marked fixed, which is the most
              valuable state of all, because it says the fix was wrong

Nothing is inferred from a model's opinion. A case closes because a task with
the same failure signature later PASSED ITS GATE — the same mechanical
evidence the rest of the platform runs on. A case reopens because the same
signature failed again after that.

The payoff is at the point of work: a task whose goal matches an open or
solved case carries the history into its context. "This failed here before,
and this is what fixed it" is the single most useful sentence a working agent
can be handed.

    python cases.py --root <expert>                  # the ledger
    python cases.py --root <expert> --goal "..."     # what bears on this work
    python cases.py --root <expert> --stats
"""

import argparse
import json
import os
import re
import time

import locks

LEDGER = os.path.join("memory", "cases.jsonl")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
        "at", "by", "from", "into", "that", "this", "it", "is", "are", "be",
        "task", "run", "goal", "please", "make", "get", "use", "using"}
MATCH_TERMS = 2
MAX_INJECT = 4


def _path(root):
    return os.path.join(root, LEDGER)


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOP}


def _read(root):
    out = []
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue          # a torn line is skipped, never fatal
    except OSError:
        pass
    return out


def _append(root, rec, locked=False):
    """Under the ledger lock unless the caller already holds it: the case
    ledger is read (load) and then appended by the harness of every task
    that ends, and an unlocked append beside that read loses rows
    (docs/DESIGN-P11, memory G4)."""
    p = _path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if locked:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
    with locks.holding(p):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def load(root):
    """The ledger, folded: later events update the case they belong to."""
    cases = {}
    for rec in _read(root):
        cid = rec.get("case")
        if not cid:
            continue
        cur = cases.setdefault(cid, {"case": cid, "events": 0})
        cur["events"] += 1
        for k, v in rec.items():
            if k in ("case", "event"):
                continue
            if v not in (None, "", []):
                cur[k] = v
        ev = rec.get("event")
        if ev == "opened":
            cur["status"] = "open"
            cur.setdefault("opened_at", rec.get("at"))
        elif ev == "fixed":
            cur["status"] = "fixed"
            cur["fixed_at"] = rec.get("at")
            cur["times_fixed"] = cur.get("times_fixed", 0) + 1
        elif ev == "recurred":
            cur["status"] = "recurred"
            cur["recurrences"] = cur.get("recurrences", 0) + 1
    return sorted(cases.values(), key=lambda c: c.get("opened_at") or "")


def case_id(signature):
    import hashlib
    return "K-" + hashlib.sha256(str(signature).encode("utf-8")).hexdigest()[:8]


def open_case(root, task, failure):
    """A failure opens (or reopens) a case. Returns the case record."""
    sig = failure.get("signature") or f"{failure.get('category')}|{task.get('goal')}"
    cid = case_id(sig)
    p = _path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # load-then-append under one lock: two tasks failing on the same
    # signature at once must open ONE case, not two
    with locks.holding(p):
        existing = {c["case"]: c for c in load(root)}.get(cid)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if existing and existing.get("status") == "fixed":
            # the most valuable event in the ledger: the fix did not hold
            return _append(root, {
                "case": cid, "event": "recurred", "at": now,
                "task": task.get("id"), "problem": (task.get("goal") or "")[:200],
                "cause": (failure.get("cause") or "")[:300],
                "note": "came back after being marked fixed -- the fix was wrong "
                        "or incomplete"}, locked=True)
        if existing:
            return existing
        return _append(root, {
            "case": cid, "event": "opened", "at": now,
            "signature": sig[:200], "category": failure.get("category"),
            "problem": (task.get("base_goal") or task.get("goal") or "")[:200],
            "cause": (failure.get("cause") or failure.get("actual") or "")[:300],
            "failure_id": failure.get("failure_id"), "task": task.get("id"),
            "course": task.get("course"), "role": task.get("role"),
            "terms": sorted(words(task.get("goal")))[:12]}, locked=True)


def record_fix(root, task):
    """A task that PASSED ITS GATE closes any open case it matches.

    Mechanical, not editorial: the same evidence that lets a task finish is
    the evidence that the problem is solved. What the successful run did
    differently is recorded as the fix.
    """
    if task.get("status") != "done":
        return None
    goal_terms = words(task.get("goal"))
    if not goal_terms:
        return None
    closed = []
    for c in load(root):
        if c.get("status") not in ("open", "recurred"):
            continue
        shared = goal_terms & set(c.get("terms") or [])
        if len(shared) < MATCH_TERMS:
            continue
        steps = [s.get("tool") for s in (task.get("steps") or [])]
        fix = (task.get("summary") or "")[:300] or \
            f"a {task.get('role')} task using {', '.join(dict.fromkeys(steps))}"
        closed.append(_append(root, {
            "case": c["case"], "event": "fixed",
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "task": task.get("id"), "fix": fix,
            "verified_by": task.get("done_check") or "no gate declared",
            "matched_on": sorted(shared)[:6]}))
    return closed or None


def matching(root, goal, cap=MAX_INJECT):
    """Cases that bear on this work, solved ones first (they carry a fix)."""
    gw = words(goal)
    if not gw:
        return []
    hits = []
    for c in load(root):
        shared = gw & set(c.get("terms") or [])
        if len(shared) >= MATCH_TERMS:
            c = dict(c, matched_on=sorted(shared)[:6])
            hits.append(c)
    order = {"fixed": 0, "recurred": 1, "open": 2}
    hits.sort(key=lambda c: (order.get(c.get("status"), 3),
                             -len(c.get("matched_on") or [])))
    return hits[:cap]


def render(hits):
    if not hits:
        return ""
    lines = ["PRIOR CASES — this expert has been here before. A fix recorded "
             "below was verified by a gate, not by opinion; a RECURRED case "
             "means the obvious fix already failed once."]
    for c in hits:
        st = (c.get("status") or "open").upper()
        line = f"- [{st}] {c.get('problem', '')[:110]}"
        if c.get("cause"):
            line += f"\n    cause: {c['cause'][:130]}"
        if c.get("fix"):
            line += f"\n    what fixed it: {c['fix'][:150]}"
        if c.get("recurrences"):
            line += f"\n    came back {c['recurrences']}x after being 'fixed'"
        lines.append(line)
    return "\n".join(lines)


def stats(root):
    rows = load(root)
    by = {}
    for c in rows:
        by[c.get("status", "open")] = by.get(c.get("status", "open"), 0) + 1
    solved = [c for c in rows if c.get("status") == "fixed"]
    return {"total": len(rows), "by_status": by,
            "solved": len(solved),
            "recurred": sum(1 for c in rows if c.get("status") == "recurred"),
            "solve_rate": round(len(solved) / len(rows), 2) if rows else 0.0}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--goal", help="what prior cases bear on this work?")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.goal:
        hits = matching(root, a.goal)
        print(json.dumps(hits, indent=1) if a.json else
              (render(hits) or "no prior case bears on that work"))
        return
    if a.stats:
        s = stats(root)
        print(json.dumps(s, indent=1) if a.json else
              f"{s['total']} case(s): {s['solved']} solved "
              f"({s['solve_rate']:.0%}), {s['recurred']} recurred after a fix")
        return
    rows = load(root)
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print("no cases yet — they open when something fails")
    for c in rows:
        print(f"{c['case']}  {(c.get('status') or 'open'):<9} "
              f"{(c.get('category') or '?'):<16} {c.get('problem', '')[:60]}")
        if c.get("fix"):
            print(f"           fixed by: {c['fix'][:70]}")


if __name__ == "__main__":
    main()
