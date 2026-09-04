#!/usr/bin/env python3
"""The fleet's memory institution — the categories that outlive every model,
every session, and every agent.

Context windows are not memory. A window is what one model can see for one
call; memory is what the institution keeps forever, with provenance, and can
retrieve on purpose. This module owns the categories that were missing:

  FAILURES     every material failure as a STRUCTURED record — category,
               expected vs actual, cause, evidence, cost, recurrence count.
               Kept after the bug is fixed, because a fleet without failure
               memory rediscovers the same mistakes forever.
  COMPETENCE   what each agent is DEMONSTRABLY good at, computed from
               verified outcomes — never from self-description. Gated
               (done_check-verified) work counts double; a small sample is
               reported as a small sample.
  RETIRED      retirement stops compute, not existence. A retired agent's
               entire world is preserved and can be queried, compared, or
               restored years later.
  MAP          one index across the whole fleet — active and retired — of who
               knows what, who is good at what, and what everyone got wrong.

Retrieval here is hybrid: structured filters first (kind, agent, category,
domain, recency), then ranked text matching — not one similarity blob.

Usage:
  python memory.py failures [--expert X] [--category C] [--limit N]
  python memory.py competence [--expert X]
  python memory.py retire <expert> --reason "..."
  python memory.py restore <expert>
  python memory.py map
  python memory.py search "terms" [--kind failures|knowledge] [--expert X]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

import locks

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

# The taxonomy is fixed on purpose: free-text categories cannot be counted,
# and a failure you cannot count is a failure you cannot learn from.
CATEGORIES = [
    "false_success",       # claimed done without meeting the definition of done
    "hallucination",       # asserted what no source supports
    "bad_retrieval",       # had the evidence, failed to find or use it
    "context_loss",        # dropped a constraint across steps or handoffs
    "planning",            # loops, thrash, no progress toward the goal
    "tool_misuse",         # wrong tool, wrong arguments, ignored errors
    "missing_evidence",    # proceeded without the proof the task required
    "wrong_assumption",    # built on something untrue
    "coordination",        # handoff, teamwork, or delegation broke down
    "budget",              # ran out of money or steps
    "security",            # tried to exceed its permissions
    "infrastructure",      # provider, network, or environment failed
    "model_limitation",    # the model could not produce a usable call
    "premature_stop",      # gave up while the goal was still reachable
    "eval_gaming",         # optimized the check instead of the work
    "unknown",
]

# Deterministic classification from the harness's own error strings — the
# system knows exactly why it failed, so no model is asked to guess.
_RULES = [
    (r"stop condition", "budget"),
    (r"done_check never passed", "false_success"),
    (r"repetition loop", "planning"),
    (r"max steps ceiling", "planning"),
    (r"cost ceiling|budget", "budget"),
    (r"escapes the agent root|not permitted", "security"),
    (r"malformed tool call|no valid tool call", "model_limitation"),
    (r"All providers failed|HTTP \d|timed out|timeout", "infrastructure"),
    (r"HALLUCINATED CITATIONS", "hallucination"),
    (r"UNGROUNDED ANSWER", "missing_evidence"),
    (r"memory violations|BROKEN CITATION", "bad_retrieval"),
    (r"constraint digest", "context_loss"),
    (r"internal error", "infrastructure"),
]


def classify(error_text):
    t = (error_text or "").lower()
    for pattern, cat in _RULES:
        if re.search(pattern.lower(), t):
            return cat
    return "unknown"


# ------------------------------------------------------------------ paths

def mem_dir(home):
    d = os.path.join(home, "commons")
    for sub in ("failures", "competence"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def retired_dir(home):
    d = os.path.join(home, "retired")
    os.makedirs(d, exist_ok=True)
    return d


def _append_jsonl(path, rec, locked=False):
    """One row, UNDER THE LEDGER LOCK. The commons ledgers are fleet-wide:
    every expert loop and the panel append to the same files, and an
    unlocked append beside a read-modify-append (record_failure counts
    recurrences from what it just read) is a lost update by construction.
    Every reader tolerates a torn line, so the loss was silent. `locked`
    is for a caller that already holds the lock — locks.holding is not
    reentrant (docs/DESIGN-P11, memory G4)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if locked:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return
    with locks.holding(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _read_jsonl(path, limit=None):
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return out[-limit:] if limit else out


# ------------------------------------------------------------------ failures

def record_failure(home, expert, task=None, category=None, expected="",
                   actual="", cause="", evidence="", cost=0.0):
    """One structured failure record. Identical failures are not duplicated —
    they increment a recurrence count, so a recurring problem becomes visibly
    recurring instead of drowning in noise."""
    task = task or {}
    cause = cause or (task.get("error") or "")
    cat = category or classify(cause)
    if cat not in CATEGORIES:
        cat = "unknown"
    path = os.path.join(mem_dir(home), "failures", f"{cat}.jsonl")
    sig_src = f"{expert}|{cat}|{' '.join((cause or '')[:200].split())}"
    rec = {
        # sha256, not hash(): str hashing is randomised per process, so the
        # same failure got a different id in every run and the id written
        # into each gotcha line could never be looked up again
        "failure_id": "F-" + hashlib.sha256(
            sig_src.encode("utf-8")).hexdigest()[:10],
        "signature": sig_src,
        "expert": expert,
        "category": cat,
        "task_id": task.get("id"),
        "role": task.get("role"),
        "course": task.get("course"),
        "goal": (task.get("base_goal") or task.get("goal") or "")[:300],
        "expected": expected or "the task's definition of done",
        "actual": actual or (cause or "")[:300],
        "cause": (cause or "")[:600],
        "evidence": evidence or task.get("context_ref") or "",
        "cost_usd": cost or task.get("cost_usd", 0),
        "attempt": task.get("attempt", 1),
        "recurrence": 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    # read-then-append under ONE lock: the recurrence count is derived from
    # the last row with this signature, and two writers reading the same
    # last row filed the same count twice — a recurring failure that looked
    # less recurrent than it was
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with locks.holding(path):
        existing = _read_jsonl(path)
        for prior in reversed(existing):
            if prior.get("signature") == sig_src:
                rec["failure_id"] = prior["failure_id"]
                rec["recurrence"] = prior.get("recurrence", 1) + 1
                rec["first_seen"] = prior.get("first_seen", prior.get("at"))
                break
        _append_jsonl(path, rec, locked=True)
    return rec


def failures(home, expert=None, category=None, limit=100, since=None):
    d = os.path.join(mem_dir(home), "failures")
    cats = [category] if category else CATEGORIES
    out = []
    for c in cats:
        for rec in _read_jsonl(os.path.join(d, f"{c}.jsonl")):
            if expert and rec.get("expert") != expert:
                continue
            if since and (rec.get("at") or "") < since:
                continue
            out.append(rec)
    # newest first, and a recurring failure outranks a one-off
    out.sort(key=lambda r: (r.get("at", ""), r.get("recurrence", 1)), reverse=True)
    return out[:limit]


def failure_summary(home, expert=None):
    counts, worst = {}, []
    for rec in failures(home, expert=expert, limit=10_000):
        counts[rec["category"]] = counts.get(rec["category"], 0) + 1
    seen = {}
    for rec in failures(home, expert=expert, limit=10_000):
        k = rec["signature"]
        if k not in seen or rec.get("recurrence", 1) > seen[k].get("recurrence", 1):
            seen[k] = rec
    worst = sorted(seen.values(), key=lambda r: -r.get("recurrence", 1))[:5]
    return {"by_category": counts, "total": sum(counts.values()),
            "most_recurrent": worst}


# ------------------------------------------------------------------ competence

def record_outcome(home, expert, domain, success, verified=False, task_id=None,
                   note=""):
    """Competence is EARNED, never declared. Every finished task files an
    outcome; verified (gate-checked) work counts double because it was proven
    rather than claimed."""
    _append_jsonl(os.path.join(mem_dir(home), "competence", f"{expert}.jsonl"), {
        "expert": expert, "domain": domain or "general",
        "success": bool(success), "verified": bool(verified),
        "task_id": task_id, "note": note[:200],
        "at": time.strftime("%Y-%m-%dT%H:%M:%S")})


def competence(home, expert=None):
    """Scores per (expert, domain), computed from evidence. Small samples are
    reported as small — a 1-for-1 record is not mastery."""
    d = os.path.join(mem_dir(home), "competence")
    experts = ([expert] if expert else
               [f[:-6] for f in os.listdir(d)] if os.path.isdir(d) else [])
    out = {}
    for ex in experts:
        rows = _read_jsonl(os.path.join(d, f"{ex}.jsonl"))
        by_domain = {}
        for r in rows:
            dom = r.get("domain") or "general"
            b = by_domain.setdefault(dom, {"n": 0, "ok": 0, "verified_n": 0,
                                           "verified_ok": 0})
            b["n"] += 1
            b["ok"] += 1 if r["success"] else 0
            if r.get("verified"):
                b["verified_n"] += 1
                b["verified_ok"] += 1 if r["success"] else 0
        scored = {}
        for dom, b in by_domain.items():
            weight_n = b["n"] + b["verified_n"]          # verified counts twice
            weight_ok = b["ok"] + b["verified_ok"]
            rate = (weight_ok / weight_n) if weight_n else 0.0
            scored[dom] = {
                "attempts": b["n"], "successes": b["ok"],
                "verified_attempts": b["verified_n"],
                "score": round(rate, 3),
                "confidence": ("none" if b["n"] < 3 else
                               "low" if b["n"] < 10 else
                               "moderate" if b["n"] < 30 else "high"),
                "claim": ("insufficient evidence" if b["n"] < 3 else
                          "demonstrated" if rate >= 0.8 and b["verified_n"] else
                          "adequate" if rate >= 0.6 else "weak"),
            }
        if scored:
            out[ex] = scored
    return out


def best_for(home, domain, minimum_attempts=3):
    """Who should get this work? Answered from verified record, not vibes."""
    ranked = []
    for ex, doms in competence(home).items():
        b = doms.get(domain)
        if b and b["attempts"] >= minimum_attempts:
            ranked.append((b["score"], b["attempts"], ex))
    ranked.sort(reverse=True)
    return [{"expert": e, "score": s, "attempts": n} for s, n, e in ranked]


# ------------------------------------------------------------------ retirement

def retire(home, slug, reason="", by="owner"):
    """Stop an agent's compute WITHOUT destroying it. Everything it was —
    identity, memory, courses, skills, logs, failures — is preserved and
    remains queryable and restorable."""
    src = os.path.join(home, "experts", slug)
    if not os.path.isdir(src):
        raise KeyError(slug)
    # if THIS process ever ran the expert's loop (the panel does), a logging
    # handler still holds logs/agent.log open — on Windows that makes the
    # move fail halfway. Detach every handler rooted in the expert first.
    import logging
    src_real = os.path.realpath(src)
    loggers = [logging.getLogger()] + [
        logging.getLogger(n) for n in logging.Logger.manager.loggerDict]
    for lg in loggers:
        for h in list(getattr(lg, "handlers", [])):
            base = getattr(h, "baseFilename", None)
            if base and os.path.realpath(base).startswith(src_real):
                try:
                    h.close()
                    lg.removeHandler(h)
                except Exception:
                    pass
    dest = os.path.join(retired_dir(home), slug)
    if os.path.exists(dest):
        dest = f"{dest}-{time.strftime('%Y%m%d%H%M%S')}"
    shutil.move(src, dest)
    manifest = {
        "expert": slug, "retired_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "retired_by": by, "reason": reason or "not stated",
        "note": ("Retirement stops compute, not existence. This world is "
                 "complete and can be queried, compared, forked, or restored."),
    }
    try:
        with open(os.path.join(dest, "identity.md"), "r", encoding="utf-8") as f:
            manifest["identity"] = f.read()[:2000]
    except OSError:
        pass
    cdir = os.path.join(dest, "courses")
    manifest["courses"] = sorted(c for c in os.listdir(cdir)
                                 if os.path.isdir(os.path.join(cdir, c))) \
        if os.path.isdir(cdir) else []
    manifest["competence"] = competence(home, slug).get(slug, {})
    manifest["failures"] = failure_summary(home, slug)
    with open(os.path.join(dest, "RETIRED.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest


def restore(home, slug):
    src = os.path.join(retired_dir(home), slug)
    if not os.path.isdir(src):
        raise KeyError(slug)
    dest = os.path.join(home, "experts", slug)
    if os.path.exists(dest):
        raise SystemExit(f"ERROR: an active expert '{slug}' already exists")
    shutil.move(src, dest)
    try:
        os.remove(os.path.join(dest, "RETIRED.json"))
    except OSError:
        pass
    return dest


def retired(home):
    base = retired_dir(home)
    out = []
    for slug in sorted(os.listdir(base)):
        p = os.path.join(base, slug, "RETIRED.json")
        try:
            with open(p, "r", encoding="utf-8") as f:
                out.append(json.load(f))
        except OSError:
            out.append({"expert": slug, "reason": "manifest missing"})
    return out


# ------------------------------------------------------------------ the map

def fleet_map(home):
    """One index over the whole fleet — living and retired: who knows what,
    who is proven good at what, what everyone got wrong. This is the memory
    that survives any individual agent."""
    import fleet
    comp = competence(home)
    active = []
    for e in fleet.list_experts(home):
        active.append({
            "expert": e["name"], "status": "active",
            "identity": e["identity"], "courses": e["courses"],
            "competence": comp.get(e["name"], {}),
            "failures": failure_summary(home, e["name"]),
            "tasks": e["tasks"],
        })
    gone = []
    for m in retired(home):
        gone.append({
            "expert": m["expert"], "status": "retired",
            "identity": (m.get("identity") or "")[:200],
            "courses": m.get("courses", []),
            "competence": m.get("competence", {}),
            "failures": m.get("failures", {}),
            "retired_at": m.get("retired_at"), "reason": m.get("reason"),
        })
    return {"active": active, "retired": gone,
            "totals": {"active": len(active), "retired": len(gone),
                       "failures": failure_summary(home)["total"]}}


# ------------------------------------------------------------------ search

def search(home, query, kind=None, expert=None, category=None, limit=25):
    """Hybrid retrieval: structured filters FIRST (kind, agent, category),
    then ranked text matching over what survives. Filtering before ranking is
    what keeps an answer about one agent's failures from being polluted by
    another's notes."""
    terms = [t for t in re.findall(r"[\w'-]{2,}", (query or "").lower())]
    hits = []

    def score(text):
        low = (text or "").lower()
        n = sum(1 for t in terms if t in low)
        if not n:
            return 0
        return n * 100 + (50 if n == len(terms) else 0)

    if kind in (None, "failures"):
        for rec in failures(home, expert=expert, category=category, limit=5000):
            s = score(f"{rec.get('goal','')} {rec.get('cause','')} "
                      f"{rec.get('category','')} {rec.get('actual','')}")
            if s:
                hits.append({"kind": "failure", "score": s + rec.get("recurrence", 1),
                             "expert": rec["expert"], "category": rec["category"],
                             "recurrence": rec.get("recurrence", 1),
                             "text": f"[{rec['category']}] {rec.get('cause','')[:160]}",
                             "ref": rec.get("evidence") or rec.get("task_id", "")})
    if kind in (None, "knowledge"):
        import recall
        for s, loc, snippet in recall.search(home, query, limit=limit * 2):
            # `continue`, not `pass`. The filter was written and then defeated
            # by the wrong statement, so an expert-scoped query returned the
            # fleet home's own courses/ and skills/ — and, worse, STAMPED them
            # with the requested expert's name two lines below, so the leak
            # was invisible to the obvious assertion ("every hit is expert X").
            # This branch searches the HOME root, whose paths carry no expert
            # segment at all; the per-expert branch below is what answers a
            # scoped query, and it always filtered correctly.
            if expert and f"/{expert}/" not in loc.replace(os.sep, "/"):
                continue
            hits.append({"kind": "knowledge", "score": s, "expert": expert or "",
                         "text": snippet, "ref": loc})
        # also search each expert's own mind unless one was named
        import fleet
        for e in fleet.list_experts(home):
            if expert and e["name"] != expert:
                continue
            for s, loc, snippet in recall.search(e["root"], query, limit=8):
                hits.append({"kind": "knowledge", "score": s,
                             "expert": e["name"], "text": snippet,
                             "ref": f"{e['name']}:{loc}"})
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("failures")
    p.add_argument("--expert"); p.add_argument("--category")
    p.add_argument("--limit", type=int, default=30); p.add_argument("--home", default=HOME)
    p = sub.add_parser("competence")
    p.add_argument("--expert"); p.add_argument("--home", default=HOME)
    p = sub.add_parser("retire")
    p.add_argument("expert"); p.add_argument("--reason", default="")
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("restore")
    p.add_argument("expert"); p.add_argument("--home", default=HOME)
    p = sub.add_parser("map"); p.add_argument("--home", default=HOME)
    p = sub.add_parser("search")
    p.add_argument("query"); p.add_argument("--kind")
    p.add_argument("--expert"); p.add_argument("--category")
    p.add_argument("--home", default=HOME)
    args = ap.parse_args()

    if args.cmd == "failures":
        s = failure_summary(args.home, args.expert)
        print(f"total failures: {s['total']}")
        for c, n in sorted(s["by_category"].items(), key=lambda x: -x[1]):
            print(f"  {c:<18} {n}")
        print("\nmost recurrent:")
        for r in s["most_recurrent"]:
            print(f"  x{r['recurrence']:<3} [{r['category']}] {r['expert']}: "
                  f"{r['cause'][:80]}")
    elif args.cmd == "competence":
        for ex, doms in competence(args.home, args.expert).items():
            print(ex)
            for dom, b in sorted(doms.items()):
                print(f"  {dom:<22} score {b['score']:<6} "
                      f"{b['successes']}/{b['attempts']} "
                      f"({b['verified_attempts']} verified) — {b['claim']}, "
                      f"confidence {b['confidence']}")
    elif args.cmd == "retire":
        m = retire(args.home, args.expert, args.reason)
        print(f"retired {m['expert']} — world preserved at retired/{m['expert']}")
    elif args.cmd == "restore":
        print("restored to", restore(args.home, args.expert))
    elif args.cmd == "map":
        m = fleet_map(args.home)
        print(json.dumps(m["totals"], indent=2))
        for a in m["active"] + m["retired"]:
            best = sorted(a["competence"].items(),
                          key=lambda x: -x[1]["score"])[:2]
            print(f"{a['status']:<8} {a['expert']:<20} "
                  f"courses={len(a['courses'])} "
                  f"failures={a['failures'].get('total',0)} "
                  f"best={[f'{d}:{b[chr(115)+chr(99)+chr(111)+chr(114)+chr(101)]}' for d,b in best]}")
    elif args.cmd == "search":
        for h in search(args.home, args.query, args.kind, args.expert,
                        args.category):
            print(f"[{h['kind']:<9}] {h.get('expert',''):<16} {h['text'][:110]}")


if __name__ == "__main__":
    main()
