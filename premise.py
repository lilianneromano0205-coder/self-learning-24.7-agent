#!/usr/bin/env python3
"""PREMISE AWARENESS — refuse to build on something already known false.

The fifth ability LongMemEval-V2 measures is the one agents fail most
politely: a task arrives whose premise the agent's own memory already
contradicts ("summarize what we learned from the Redis migration" — which
was cancelled), and the agent cheerfully invents an answer. Being helpful
about a false premise is a hallucination with better manners.

So before the first token of work, the compiler checks the goal against what
this expert has actually verified:

  * an atom ID cited in the goal that NO note defines        -> unknown atom
  * an atom ID this expert RETRACTED (courses/*/retractions) -> retracted atom
  * a goal whose subject matches a retraction line           -> retracted topic
  * a claim the fleet QUARANTINED (commons/quarantine.md)    -> withdrawn claim

Matches are conservative: a warning fires only when the overlap is specific
(an exact atom ID, or every content word of the retracted subject present in
the goal), because a premise check that cries wolf gets ignored, and an
ignored check is worse than none.

The warnings are rendered into the context window as a short PREMISE CHECK
block — not as a refusal. The agent is told to say so and stop rather than
build on a dead premise; the human keeps the decision.
"""

import os
import re
import time

ATOM_CITE_RE = re.compile(r"\b([CPU]-\d{2,}[\w.]*)\b")
RETRACT_RE = re.compile(r"^\s*-\s*(?P<id>\S+)\s+retracted:\s*(?P<why>.*)$", re.M)
QUARANTINE_RE = re.compile(r"~~(?P<fact>.+?)~~\s*(?:—|--)?\s*"
                           r"(?:withdrawn:\s*(?P<why>.*))?$", re.M)
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
        "at", "by", "from", "into", "that", "this", "it", "is", "are", "be",
        "was", "were", "do", "does", "did", "as", "if", "then", "than", "we",
        "our", "us", "what", "which", "who", "how", "why", "write", "summarize",
        "explain", "report", "make", "using", "use", "about", "learned",
        "learn", "task", "goal", "please"}
MIN_TOPIC_WORDS = 2


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOP}


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _home(root):
    """experts/<slug> -> the fleet home two levels up (None when standalone)."""
    parent = os.path.dirname(root)
    if os.path.basename(parent) == "experts":
        return os.path.dirname(parent)
    return None


def retractions(root, course=None):
    """Every retraction this expert has recorded: [(id, why, rel)]."""
    out = []
    courses = os.path.join(root, "courses")
    names = [course] if course else None
    try:
        names = names or sorted(os.listdir(courses))
    except OSError:
        return out
    for c in names:
        rel = os.path.join("courses", str(c), "retractions.md")
        for m in RETRACT_RE.finditer(_read(os.path.join(root, rel))):
            out.append((m.group("id"), m.group("why").strip(),
                        rel.replace(os.sep, "/")))
    return out


def quarantined(root):
    """Claims the fleet withdrew (commons/quarantine.md, local or shared)."""
    out = []
    seen = set()
    paths = [os.path.join(root, "commons", "quarantine.md")]
    home = _home(root)
    if home:
        paths.append(os.path.join(home, "commons", "quarantine.md"))
    for p in paths:
        for m in QUARANTINE_RE.finditer(_read(p)):
            fact = " ".join(m.group("fact").split())
            if fact and fact not in seen:
                seen.add(fact)
                out.append((fact, (m.group("why") or "").strip()))
    return out


def check(root, goal, course=None):
    """Return the premise warnings for this goal (possibly empty)."""
    warnings = []
    goal = goal or ""
    gw = words(goal)
    cited = set(ATOM_CITE_RE.findall(goal))

    try:
        import citecheck
        known = citecheck.known_atoms(root)
    except Exception:
        known = set()

    retracted = retractions(root, course)
    retracted_ids = {r[0] for r in retracted}

    for atom in sorted(cited):
        if atom in retracted_ids:
            why = next(r[1] for r in retracted if r[0] == atom)
            warnings.append({
                "kind": "retracted_atom", "subject": atom,
                "warning": f"the goal cites {atom}, which this expert RETRACTED "
                           f"({why[:120]})",
                "evidence": next(r[2] for r in retracted if r[0] == atom)})
        elif known and atom not in known:
            warnings.append({
                "kind": "unknown_atom", "subject": atom,
                "warning": f"the goal cites {atom}, which no note here defines "
                           f"-- do not invent what it says",
                "evidence": "courses/*/notes.md"})

    for rid, why, rel in retracted:
        subj = words(why)
        if len(subj) >= MIN_TOPIC_WORDS and subj <= gw:
            warnings.append({
                "kind": "retracted_topic", "subject": rid,
                "warning": f"this expert retracted {rid} on exactly this "
                           f"subject: {why[:120]}",
                "evidence": rel})

    for fact, why in quarantined(root):
        subj = words(fact)
        if len(subj) >= 3 and subj <= gw:
            warnings.append({
                "kind": "quarantined_claim", "subject": fact[:80],
                "warning": f"the fleet withdrew this claim: \"{fact[:100]}\""
                           + (f" ({why[:80]})" if why else ""),
                "evidence": "commons/quarantine.md"})

    # never warn about the same subject twice
    out, seen = [], set()
    for w in warnings:
        k = (w["kind"], w["subject"])
        if k not in seen:
            seen.add(k)
            out.append(w)
    return out


def render(warnings):
    if not warnings:
        return ""
    lines = ["PREMISE CHECK — before you start: your own verified memory "
             "contradicts part of this task. If the premise is dead, SAY SO "
             "and stop; do not build on it, and never invent the missing part."]
    for w in warnings:
        lines.append(f"- [{w['kind']}] {w['warning']} (see {w['evidence']})")
    return "\n".join(lines)


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="premise check for a task goal")
    ap.add_argument("goal")
    ap.add_argument("--root", default=".")
    ap.add_argument("--course")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    w = check(os.path.abspath(a.root), a.goal, a.course)
    if a.json:
        print(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "warnings": w}, indent=1))
        return
    print(render(w) or "premise clean: nothing in memory contradicts this goal")
    raise SystemExit(1 if w else 0)


if __name__ == "__main__":
    main()
