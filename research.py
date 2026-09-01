#!/usr/bin/env python3
"""AGENTIC RETRIEVAL — establish the facts before answering the question.

One search and one answer is the weakest possible use of a knowledge base.
The stronger pattern, and the one the agentic-retrieval literature keeps
arriving at, is to treat a question as an INVESTIGATION:

    what must be established before this can be answered?
        -> retrieve for each of those, separately
        -> collect the evidence, with its citation
        -> note explicitly what could NOT be established
        -> only then answer

The last step is the one that matters. A consultant handed "here are the 4
atoms that bear on part one, the 2 that bear on part two, and NOTHING for
part three" writes a different answer from one handed the raw question — and
in particular writes "NOT IN MY TRAINING" for part three instead of
improvising, because the gap is in front of it as a fact.

Decomposition here is DETERMINISTIC: no model is asked what the
sub-questions are. It splits on the grammar of the question (clauses,
conjunctions, enumerations) and on the terms that carry meaning. That is
weaker than a model at nuance and far stronger at being predictable,
inspectable and free — and the retrieval, not the decomposition, is where
the value is.

    python research.py "the question" --root <expert>
    python research.py "the question" --root <expert> --json
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ATOM_RE = re.compile(r"\b([CPU]-\d{2,}[\w.]*)\b")
SPLIT_RE = re.compile(r"[?;]|(?:\band\b|\balso\b|\bplus\b|\bas well as\b)",
                      re.I)
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
        "at", "by", "from", "into", "that", "this", "it", "is", "are", "be",
        "was", "were", "do", "does", "did", "as", "if", "then", "than", "we",
        "our", "you", "your", "what", "which", "who", "how", "why", "when",
        "should", "would", "could", "can", "may", "might", "must", "will",
        "about", "tell", "me", "give", "explain", "describe", "please"}
MIN_TERMS = 2
MAX_SUBS = 6
HITS_PER_SUB = 6


def terms(text):
    return [w for w in re.findall(r"[a-z0-9']+", (text or "").lower())
            if len(w) > 2 and w not in STOP]


def facts_needed(question):
    """-> the sub-questions this question rests on, in asking order."""
    question = " ".join(str(question or "").split())
    parts = [p.strip(" ,.") for p in SPLIT_RE.split(question) if p and p.strip()]
    subs, seen = [], set()
    for p in parts:
        t = terms(p)
        if len(t) < MIN_TERMS:
            continue
        key = " ".join(sorted(set(t))[:6])
        if key in seen:
            continue
        seen.add(key)
        subs.append({"ask": p[:200], "terms": t[:12]})
        if len(subs) >= MAX_SUBS:
            break
    if not subs:                       # a short question is its own investigation
        t = terms(question)
        if t:
            subs = [{"ask": question[:200], "terms": t[:12]}]
    # any atom the question names is a fact to establish in its own right
    for atom in dict.fromkeys(ATOM_RE.findall(question)):
        subs.append({"ask": f"what does {atom} actually say?", "terms": [atom],
                     "atom": atom})
    return subs[:MAX_SUBS + 3]


def investigate(root, question, per_sub=HITS_PER_SUB, *, plan=None, as_of=None, cfg=None):
    """Retrieve and assess claims before any answer.

    Explicit plans carry propositions, counterclaims, dependencies and date
    requirements. Grammar-only decomposition remains available but never
    upgrades retrieved text to established facts. Invalid plans fail closed.
    """
    import recall
    import research_plan
    if cfg is None:
        import sources
        cfg = sources._root_cfg(root)
    return research_plan.collect(root, question, plan, as_of, per_sub, cfg, recall.search)


def answer(report):
    """Complete source-relative answers require a current gap assessment."""
    import research_plan
    return research_plan.answer(report)


def discover_gaps(root, report, cfg=None, rails=None, general_web=False,
                  as_of=None, limit=8):
    """Find candidates for unresolved claims without changing claim states.

    Discovery snippets remain fenced candidates. Only a later guarded fetch,
    source record and fresh investigation can support a proposition.
    """
    import copy
    import discover
    before = copy.deepcopy(report.get("gap_assessment"))
    searches = []
    for sub in report.get("subs", []):
        if sub.get("established"):
            continue
        query = sub.get("ask") or sub.get("proposition") or report.get("question", "")
        found = discover.search(query, rails=rails, limit=limit, cfg=cfg,
                                general_web=general_web, as_of=as_of)
        searches.append({"claim_id": sub.get("id"), "query": query,
                         "discovery": found})
    if report.get("gap_assessment") != before:
        raise RuntimeError("discovery altered the frozen gap assessment")
    return {"searches": searches, "claim_states_changed": False,
            "instruction": "fetch candidates through ingest, then investigate again"}


def render(report):
    """The briefing block a consultant is handed before it writes anything."""
    if not report.get("subs"):
        return ""
    import sources
    assessment = report.get("gap_assessment", {})
    L = ["RESEARCH BRIEF — retrieved evidence is not established truth. "
         "For unresolved claims declare NOT IN MY TRAINING; do not fill gaps.",
         f"GAP ASSESSMENT: {'performed' if assessment.get('performed') else 'MISSING'}; "
         f"complete answer ready: {assessment.get('answer_ready', False)}."]
    for s in report["subs"]:
        if not s["hits"]:
            L.append(f"- {s['ask']}  -> NOTHING FOUND in this expert's memory")
            continue
        L.append(f"- {s['ask']} -> {s.get('state', 'unresolved').upper()}"
                 + (f"  (atoms: {', '.join(s['atoms'][:8])})" if s["atoms"] else ""))
        for h in s["hits"][:3]:
            L.append(sources.fence_content(h['where'], h['text'][:500]))
        if s.get("missing_evidence"):
            L.append("GAPS: " + "; ".join(s["missing_evidence"]))
        if s.get("counterevidence"):
            L.append("COUNTEREVIDENCE: " + ", ".join(s["counterevidence"]))
    if report.get("unestablished"):
        L.append(f"UNESTABLISHED ({len(report['unestablished'])}): "
                 + "; ".join(report["unestablished"][:4]))
    return "\n".join(L)


def save(root, question, report):
    """Persist the brief so the consultant can be handed it as a fenced file."""
    import hashlib
    d = os.path.join(root, "research")
    os.makedirs(d, exist_ok=True)
    key = hashlib.sha256(question.encode("utf-8")).hexdigest()[:10]
    rel = f"research/{key}.md"
    with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
        f.write(f"# Research brief\n\n> {question}\n\n" + render(report) + "\n")
    with open(os.path.join(root, f"research/{key}.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    return rel


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("question")
    ap.add_argument("--root", default=".")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--plan", help="JSON list of factual claims/dependencies/counterclaims")
    ap.add_argument("--as-of", help="ISO date for reproducible temporal assessment")
    ap.add_argument("--answer", action="store_true", help="answer only if gap assessment permits")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    plan = None
    if a.plan:
        with open(a.plan, encoding="utf-8") as f:
            plan = json.load(f)
    rep = investigate(root, a.question, plan=plan, as_of=a.as_of)
    if a.answer:
        try:
            print(answer(rep))
        except ValueError as exc:
            raise SystemExit(str(exc))
        return
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        print(render(rep) or "nothing to investigate")
        print(f"\nsupported coverage: {rep['coverage']:.0%}; "
              f"states: {rep['coverage_states']}")
    if a.save:
        print("saved:", save(root, a.question, rep))
    raise SystemExit(0 if rep.get("coverage") else 1)


if __name__ == "__main__":
    main()
