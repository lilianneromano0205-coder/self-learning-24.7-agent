#!/usr/bin/env python3
"""CURRICULUM — study in a considered order, not the order things arrived.

Hand this platform ten hour-long videos and forty 500-page PDFs and, until
now, it studied them in whatever order they landed: a beginner's blog post
before the specification, the same idea learned four times from four sources,
and no notion of which material the mission actually needs. That is the dumb
way to learn, and it is expensive in exactly the resource that matters —
context.

A person who studies well does four things, and all four are computable here:

  AUTHORITY FIRST   read the specification before the tutorial, so everything
                    after it is read against a baseline instead of averaged
                    into one. `sources.py` already rates every source.
  FOUNDATIONS FIRST introductions and overviews before advanced material, and
                    a lesson that DEFINES atoms other lessons cite is a
                    prerequisite by construction.
  DON'T RE-READ     four sources covering the same ground are not four
                    lessons. Near-duplicates are skimmed for their differences,
                    not studied again from scratch.
  KNOW WHY          each lesson earns its depth from how much the mission
                    actually needs it.

Every lesson comes out with a DEPTH and a REASON:

    study   full notes, atoms, spec items -- the expensive path
    skim    indexed, and read only for what it adds to what is known
    skip    a near-duplicate of material already studied

Nothing is deleted and nothing is hidden: a skipped lesson stays on disk with
the reason recorded, and `--plan` shows the whole ordering before a single
task is queued.

    python curriculum.py --root <expert> --course <c>            # the plan
    python curriculum.py --root <expert> --course <c> --apply    # queue it
    python curriculum.py --root <expert> --course <c> --coverage
"""

import argparse
import json
import os
import re

FOUNDATION_MARKERS = (
    "introduction", "introducing", "getting started", "basics", "fundamental",
    "overview", "primer", "beginner", "chapter 1", "lesson 1", "part 1",
    "what is", "first steps", "prerequisite", "foundation",
)
ADVANCED_MARKERS = (
    "advanced", "deep dive", "internals", "optimisation", "optimization",
    "edge case", "pitfall", "expert", "at scale", "performance tuning",
)
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
        "at", "by", "from", "into", "that", "this", "it", "is", "are", "be",
        "was", "were", "do", "does", "did", "as", "if", "then", "than", "you",
        "your", "we", "our", "how", "what", "why", "when", "which", "can"}
# Thresholds measured, not guessed. On real fixtures: a specification and a
# blog post covering the SAME ground in different words score 0.02 on 5-word
# shingles and 0.38 on content-word overlap; unrelated material scores 0.00 on
# both; an identical copy scores 1.00 on both. So shingles detect plagiarism
# and word overlap detects subject — the duplicate check needs the second, and
# keeps the first because a verbatim copy should never be missed either.
DUPLICATE_AT = 0.60        # essentially the same material: do not study twice
OVERLAP_AT = 0.30          # same ground, different words: read for the delta
SKIM_BELOW = 0.10          # mission relevance below which studying is waste
SHINGLE = 5
TIER_WEIGHT = {1: 1.0, 2: 0.8, 3: 0.55, 4: 0.3}
UNKNOWN_TIER_WEIGHT = 0.6  # neutral: an untraceable source is not punished
PLAN_FILE = "curriculum.json"


def words(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOP]


def shingles(text, n=SHINGLE):
    w = words(text)
    if len(w) < n:
        return {" ".join(w)} if w else set()
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a, b):
    """Backwards-compatible set similarity (used for mission relevance)."""
    return jaccard(a, b)


def covers_mission(lesson_words, mission_words):
    """What fraction of the MISSION's vocabulary this lesson touches.

    Not Jaccard: a 4,000-word lesson against a 15-word mission is punished by
    the union no matter how squarely it hits the subject. Containment asks the
    question actually being asked -- how much of what we came here to learn
    does this material speak to?
    """
    if not mission_words:
        return 0.5
    return len(lesson_words & mission_words) / len(mission_words)


def covers_same_ground(a_text, b_text):
    """How much of the same SUBJECT two lessons cover.

    The max of verbatim overlap (5-word shingles) and subject overlap
    (content words): the first catches a copy, the second catches a
    paraphrase, and a lesson only needs to fail one of them to be worth
    skipping.
    """
    return max(jaccard(shingles(a_text), shingles(b_text)),
               jaccard(set(words(a_text)), set(words(b_text))))


def _read(path, limit=200_000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def lessons(root, course):
    """Every lesson directory, in numeric order, with its text."""
    base = os.path.join(root, "courses", str(course), "lessons")
    out = []
    try:
        names = sorted(n for n in os.listdir(base)
                       if os.path.isdir(os.path.join(base, n)))
    except OSError:
        return out
    for nn in names:
        d = os.path.join(base, nn)
        text, which = "", None
        for fn in ("transcript.txt", "lesson.md", "notes.md"):
            t = _read(os.path.join(d, fn))
            if t.strip():
                text, which = t, fn
                break
        if not text.strip():
            continue
        out.append({"nn": nn, "dir": f"courses/{course}/lessons/{nn}",
                    "file": f"courses/{course}/lessons/{nn}/{which}",
                    "text": text, "studied": os.path.isfile(
                        os.path.join(d, "notes.md"))})
    return out


def _title(lesson):
    for line in lesson["text"].splitlines():
        s = line.strip().lstrip("# ").strip()
        if len(s) > 3:
            return s[:160]
    return lesson["nn"]


def _source_of(root, course, lesson):
    """Best-effort: tie a lesson to the source it came from."""
    try:
        import sources
        rows = sources.load(root, course)
    except Exception:
        return None
    head = lesson["text"][:2000]
    m = re.search(r"SOURCE-FILE:\s*(\S+)", head) or \
        re.search(r"https?://\S+", head)
    marker = m.group(1) if m else None
    for r in rows:
        ref = str(r.get("ref") or "")
        if marker and (ref in marker or marker in ref):
            return r
        if lesson["nn"] in (r.get("lessons") or []):
            return r
    return None


def _mission(root, course):
    parts = [_read(os.path.join(root, "identity.md"), 4000),
             _read(os.path.join(root, "courses", str(course), "mission.md"), 8000)]
    return set(words(" ".join(parts)))


def _defines_cited_atoms(root, course, all_lessons):
    """A lesson that DEFINES atoms other lessons cite is a prerequisite."""
    defines, cites = {}, {}
    for les in all_lessons:
        notes = _read(os.path.join(root, les["dir"].replace("/", os.sep),
                                   "notes.md"))
        defines[les["nn"]] = set(re.findall(r"^\s*-\s*([CPU]-\d{2,})", notes, re.M))
        cites[les["nn"]] = set(re.findall(r"\[src:[^\]]*\]|\b([CPU]-\d{2,})\b",
                                          notes))
    score = {}
    for nn, defined in defines.items():
        used_elsewhere = 0
        for other, used in cites.items():
            if other == nn:
                continue
            used_elsewhere += len(defined & {u for u in used if u})
        score[nn] = used_elsewhere
    return score


def plan(root, course):
    """-> ordered lessons, each with a depth and the reason for it."""
    items = lessons(root, course)
    if not items:
        return {"course": course, "lessons": [], "note": "no lessons yet"}
    mission = _mission(root, course)
    prereq = _defines_cited_atoms(root, course, items)
    ranked = []
    for les in items:
        src = _source_of(root, course, les)
        tier = int(src["tier"]) if src else None
        authority = TIER_WEIGHT.get(tier, UNKNOWN_TIER_WEIGHT)
        title = _title(les)
        low = (title + " " + les["text"][:400]).lower()
        foundational = 1.0 if any(m in low for m in FOUNDATION_MARKERS) else \
            0.25 if any(m in low for m in ADVANCED_MARKERS) else 0.5
        lw = set(words(les["text"][:20_000]))
        relevance = covers_mission(lw, mission)
        ranked.append({
            "nn": les["nn"], "file": les["file"], "title": title,
            "source": (src or {}).get("ref"), "tier": tier,
            "authority": round(authority, 3),
            "foundational": foundational,
            "relevance": round(relevance, 4),
            "prereq_pull": prereq.get(les["nn"], 0),
            "studied": les["studied"],
            "_text": les["text"][:40_000],
        })
    # order: authority, then prerequisite pull, then foundations, then need
    ranked.sort(key=lambda r: (-r["authority"], -r["prereq_pull"],
                               -r["foundational"], -r["relevance"], r["nn"]))
    seen = []
    for r in ranked:
        dup_of, best = None, 0.0
        for prev in seen:
            s = covers_same_ground(r["_text"], prev["_text"])
            if s > best:
                best, dup_of = s, prev["nn"]
        r["novelty"] = round(1.0 - best, 3)
        if best >= DUPLICATE_AT:
            r["depth"] = "skip"
            r["reason"] = (f"{int(best * 100)}% the same ground as lesson "
                           f"{dup_of}, which is already ahead of it")
        elif best >= OVERLAP_AT:
            r["depth"] = "skim"
            r["reason"] = (f"{int(best * 100)}% overlap with lesson {dup_of}: "
                           f"read it only for what it adds")
        elif r["relevance"] < SKIM_BELOW and r["authority"] < 0.8:
            r["depth"] = "skim"
            r["reason"] = (f"little overlap with the mission "
                           f"({r['relevance']:.2f}) from a tier-"
                           f"{r['tier'] or '?'} source: index it, do not "
                           f"study it")
        else:
            r["depth"] = "study"
            bits = []
            if r["tier"] in (1, 2):
                bits.append(f"tier-{r['tier']} source")
            if r["prereq_pull"]:
                bits.append(f"defines {r['prereq_pull']} atom(s) other "
                            f"lessons cite")
            if r["foundational"] >= 1.0:
                bits.append("foundational")
            bits.append(f"mission relevance {r['relevance']:.2f}")
            r["reason"] = ", ".join(bits)
        seen.append(r)
    for r in ranked:
        r.pop("_text", None)
    counts = {}
    for r in ranked:
        counts[r["depth"]] = counts.get(r["depth"], 0) + 1
    return {"course": course, "lessons": ranked, "counts": counts,
            "saved": save(root, course, ranked)}


def save(root, course, ranked):
    p = os.path.join(root, "courses", str(course), PLAN_FILE)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"lessons": ranked}, f, indent=1, ensure_ascii=False)
        return p.replace(os.sep, "/")
    except OSError:
        return None


def load(root, course):
    try:
        with open(os.path.join(root, "courses", str(course), PLAN_FILE),
                  encoding="utf-8") as f:
            return json.load(f).get("lessons", [])
    except (OSError, ValueError):
        return []


def apply(root, course, agent=None, force=False):
    """Queue the study work in curriculum order. Returns what was queued."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import loop
    agent = agent or loop.Agent(root)
    rows = plan(root, course)["lessons"]
    queued = []
    for r in rows:
        if r["depth"] == "skip" and not force:
            continue
        if r["studied"] and not force:
            continue
        if r["depth"] == "study":
            goal = (f"Study lesson {r['nn']} of course {course} in full "
                    f"(curriculum order: {r['reason']}). The text is in "
                    f"{r['file']}. Write {r['file'].rsplit('/', 1)[0]}/notes.md "
                    f"in the house format, append R-items to spec.md, append "
                    f"the lesson line to index.md.")
        else:
            goal = (f"SKIM lesson {r['nn']} of course {course} "
                    f"({r['reason']}). Do NOT re-derive what the course "
                    f"already knows: read {r['file']} and record ONLY what it "
                    f"adds or contradicts, as atoms in "
                    f"{r['file'].rsplit('/', 1)[0]}/notes.md. If it adds "
                    f"nothing, say so in one line and finish.")
        tid = agent.add_task("watcher", goal, memory_files=[r["file"]],
                             course=course)
        queued.append({"task": tid, "nn": r["nn"], "depth": r["depth"]})
    return queued


def coverage(root, course):
    """What the mission asks for, and whether anything supports it."""
    mission_text = _read(os.path.join(root, "courses", str(course),
                                      "mission.md"), 8000)
    topics = [ln.strip("-* ").strip() for ln in mission_text.splitlines()
              if len(ln.strip("-* ").strip()) > 12]
    notes = ""
    for les in lessons(root, course):
        notes += _read(os.path.join(root, les["dir"].replace("/", os.sep),
                                    "notes.md"))
    known = set(words(notes))
    out = []
    for t in topics[:40]:
        tw = set(words(t))
        hit = len(tw & known) / len(tw) if tw else 0.0
        out.append({"topic": t[:120], "support": round(hit, 2),
                    "covered": hit >= 0.5})
    return {"course": course, "topics": out,
            "uncovered": [t["topic"] for t in out if not t["covered"]]}


def render(rep):
    rows = rep.get("lessons") or []
    if not rows:
        return f"{rep['course']}: {rep.get('note', 'nothing to plan')}"
    c = rep.get("counts", {})
    out = [f"curriculum for {rep['course']}: {c.get('study', 0)} to study, "
           f"{c.get('skim', 0)} to skim, {c.get('skip', 0)} redundant", ""]
    for i, r in enumerate(rows, 1):
        mark = {"study": "STUDY", "skim": "skim ", "skip": "SKIP "}[r["depth"]]
        tier = f"t{r['tier']}" if r["tier"] else "t?"
        out.append(f"{i:>3}. {mark} [{tier}] lesson {r['nn']}  "
                   f"{r['title'][:52]}")
        out.append(f"      {r['reason']}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--course", required=True)
    ap.add_argument("--apply", action="store_true", help="queue the work")
    ap.add_argument("--force", action="store_true",
                    help="queue even already-studied and skipped lessons")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.coverage:
        rep = coverage(root, a.course)
        print(json.dumps(rep, indent=1) if a.json else
              f"{a.course}: {len(rep['topics']) - len(rep['uncovered'])}/"
              f"{len(rep['topics'])} mission topics supported\n" +
              "\n".join(f"  UNCOVERED  {t}" for t in rep["uncovered"]))
        return
    if a.apply:
        q = apply(root, a.course, force=a.force)
        print(json.dumps(q, indent=1) if a.json else
              f"queued {len(q)} lesson(s) in curriculum order:\n" +
              "\n".join(f"  {x['depth']:<5} lesson {x['nn']}  {x['task']}"
                        for x in q))
        return
    rep = plan(root, a.course)
    print(json.dumps(rep, indent=1) if a.json else render(rep))


if __name__ == "__main__":
    main()
