#!/usr/bin/env python3
"""Establish the facts BEFORE answering the question (P3).

One search and one answer is the weakest use of a knowledge base. A question
is an investigation: decompose it, retrieve for each part separately, and —
the part that matters — hand the answerer an explicit list of what could NOT
be established, so a gap is declared instead of filled.

1. a compound question decomposes into the parts it rests on
2. an atom named in the question becomes a fact to establish in its own right
3. each part is retrieved separately, carrying its citation
4. a part with no supporting material is reported as NOTHING FOUND, and the
   brief tells the answerer to declare it rather than improvise
5. the brief is persisted and handed to the consultant as a fenced file
6. decomposition is deterministic: the same question gives the same plan,
   with no model call anywhere

Run from the agent/ directory:  python tests/test_research.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox, read_state

sys.path.insert(0, AGENT_DIR)
import consult
import research


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


QUESTION = ("What contrast ratio does body text need and how should focus "
            "indicators behave, and what is our refund policy?")


def main():
    sb = make_sandbox("research", providers={"m": {"script": "s.json"}},
                      roles={"consultant": "m"}, scripts={"s.json": []})
    write(sb, "courses/design/notes.md",
          "- C-0101 body text contrast is at least 4.5:1 against its "
          "background [src: https://www.w3.org/TR/WCAG22/]\n"
          "- C-0102 focus indicators stay visible on every interactive "
          "control [src: https://www.w3.org/TR/WCAG22/]\n")
    write(sb, "courses/design/index.md", "01 | contrast and focus\n")

    # --- 1 + 2. decomposition
    subs = research.facts_needed(QUESTION)
    asks = " | ".join(s["ask"] for s in subs)
    assert len(subs) >= 3, asks
    assert any("contrast" in s["terms"] for s in subs), asks
    assert any("focus" in s["terms"] for s in subs), asks
    assert any("refund" in s["terms"] for s in subs), asks
    atomq = research.facts_needed("does C-0101 still hold?")
    assert any(s.get("atom") == "C-0101" for s in atomq), atomq
    print(f"[decompose] one compound question became {len(subs)} facts to "
          f"establish, and a named atom became its own")

    # --- 3 + 4. retrieval, and the gap reported as a gap
    rep = research.investigate(sb, QUESTION)
    got = {s["ask"]: s for s in rep["subs"]}
    covered = [s for s in rep["subs"] if s["retrieved"]]
    assert covered, rep
    assert "C-0101" in rep["atoms"] and "C-0102" in rep["atoms"], rep["atoms"]
    assert any(h["where"].startswith("courses/design/notes.md")
               for s in covered for h in s["hits"]), covered[0]["hits"][:2]
    refund = [s for s in rep["subs"] if "refund" in s["terms"]]
    assert refund and not refund[0]["established"], refund
    assert any("refund" in u for u in rep["unestablished"]), rep["unestablished"]
    assert rep["coverage"] == 0, rep["coverage"]
    assert not any(s["established"] for s in rep["subs"]), rep
    assert rep["coverage_states"]["retrieved"] > 0, rep
    print(f"[retrieve] the two design questions found their atoms "
          f"({', '.join(rep['atoms'])}); the refund question found nothing and "
          f"is listed as unestablished; retrieval is not proposition support")

    # --- the brief tells the answerer what to do about the gap
    text = research.render(rep)
    assert "NOTHING FOUND" in text and "NOT IN MY TRAINING" in text
    assert "C-0101" in text
    print("[brief] the brief names the gap and instructs an honest refusal "
          "for it rather than an improvisation")

    # --- 5. it reaches the consultant as a fenced file
    rel = research.save(sb, QUESTION, rep)
    assert os.path.isfile(os.path.join(sb, rel.replace("/", os.sep)))
    cid = consult.start_consult(sb, QUESTION)
    task = read_state(sb)["tasks"][0]
    briefs = [m for m in task["memory_files"] if m.startswith("research/")]
    assert briefs, task["memory_files"]
    assert "RESEARCH BRIEF" in task["goal"], task["goal"][-200:]
    assert "declare" in task["goal"]
    body = open(os.path.join(sb, briefs[0].replace("/", os.sep)),
                encoding="utf-8").read()
    assert "NOTHING FOUND" in body and "C-0101" in body
    print("[handoff] the consultation carries the brief as a memory file and "
          "its goal points at it")

    # --- 6. deterministic
    again = research.investigate(sb, QUESTION)
    assert [s["ask"] for s in again["subs"]] == [s["ask"] for s in rep["subs"]]
    assert again["atoms"] == rep["atoms"] and again["coverage"] == rep["coverage"]
    print("[deterministic] the same question produced the identical plan and "
          "the identical evidence, with no model call anywhere")
    print("PASS test_research")


if __name__ == "__main__":
    main()
