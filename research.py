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


def investigate(root, question, per_sub=HITS_PER_SUB):
    """Retrieve for each sub-question separately. Never raises."""
    try:
        import recall
    except ImportError:
        return {"question": question, "subs": [], "error": "recall unavailable"}
    try:
        import citecheck
        known = citecheck.known_atoms(root)
    except Exception:
        known = set()
    subs, established, missing = [], set(), []
    for sub in facts_needed(question):
        try:
            hits = recall.search(root, " ".join(sub["terms"]), limit=per_sub)
        except Exception:
            hits = []
        rows, atoms = [], []
        for h in hits:
            # recall returns (score, "path:line", text) or a dict, tolerate both
            if isinstance(h, dict):
                where, text = h.get("where", ""), h.get("text", "")
            elif isinstance(h, (list, tuple)) and len(h) >= 3:
                where, text = h[1], h[2]
            else:
                continue
            found = [a for a in ATOM_RE.findall(text) if a in known] or \
                ATOM_RE.findall(text)
            atoms += found
            rows.append({"where": where, "text": text[:220], "atoms": found})
        atoms = list(dict.fromkeys(atoms))
        established.update(atoms)
        if not rows:
            missing.append(sub["ask"])
        subs.append({"ask": sub["ask"], "terms": sub["terms"],
                     "hits": rows, "atoms": atoms,
                     "established": bool(rows)})
    return {"question": question, "subs": subs,
            "atoms": sorted(established), "unestablished": missing,
            "coverage": round(
                sum(1 for s in subs if s["established"]) / len(subs), 2)
            if subs else 0.0}


def render(report):
    """The briefing block a consultant is handed before it writes anything."""
    if not report.get("subs"):
        return ""
    L = ["RESEARCH BRIEF — the facts this question rests on, retrieved before "
         "answering. Cite the atom IDs below; for anything marked NOTHING "
         "FOUND, write NOT IN MY TRAINING rather than filling the gap."]
    for s in report["subs"]:
        if not s["established"]:
            L.append(f"- {s['ask']}  -> NOTHING FOUND in this expert's memory")
            continue
        L.append(f"- {s['ask']}"
                 + (f"  (atoms: {', '.join(s['atoms'][:8])})" if s["atoms"] else ""))
        for h in s["hits"][:3]:
            L.append(f"    [{h['where']}] {h['text'][:150]}")
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
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    rep = investigate(root, a.question)
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        print(render(rep) or "nothing to investigate")
        print(f"\ncoverage: {rep['coverage']:.0%} of the sub-questions had "
              f"supporting material")
    if a.save:
        print("saved:", save(root, a.question, rep))
    raise SystemExit(0 if rep.get("coverage") else 1)


if __name__ == "__main__":
    main()
