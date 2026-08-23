#!/usr/bin/env python3
"""Associative memory expansion in recall (RippleMem/CABLE, 2026-08).

A real answer often lives in a CHAIN: the decision note names an atom the
query never mentions, and the atom's definition lives in another file. Flat
retrieval returns the fragment; associative recall chases the anchors one
hop — atom IDs to their definition lines, [[links]] to their files — and
returns the chain.

Run from the agent/ directory:  python tests/test_associative.py
"""

import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import recall


def write(sb, rel, text):
    p = os.path.join(sb, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    sb = make_sandbox("associative", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    # the DECISION mentions atoms defined elsewhere, plus a skill link
    write(sb, "courses/fintech/lessons/03/notes.md",
          "# L03 decisions\n"
          "- C-0301 we abandoned the fintech idea because of C-0105 and "
          "P-0201; procedure in [[source-verification]] [src: mtg 00:12]\n")
    write(sb, "courses/fintech/lessons/01/notes.md",
          "# L01 regulation\n"
          "- C-0105 the regulator requires a banking licence for custody "
          "[src: reg-pdf p4]\n"
          "- C-0106 unrelated fact about onboarding [src: reg-pdf p9]\n")
    write(sb, "courses/fintech/lessons/02/notes.md",
          "# L02 partners\n"
          "- P-0201 partner email: their bank pulled out of the deal "
          "[src: email 2026-03-02]\n")
    write(sb, "skills/source-verification.md",
          "KEYWORDS: verify, source\nsteps to verify a claim...\n")

    hits = recall.search(sb, "why abandoned fintech idea", limit=6)
    locs = [loc for _, loc, _ in hits]
    texts = " | ".join(t for _, _, t in hits)

    # the anchor itself
    assert any("lessons/03" in l for l in locs), locs
    # the CHAIN: definitions of the atoms the anchor cites, never named in
    # the query, retrieved as linked evidence
    assert any(l.startswith("linked:") and "lessons/01" in l for l in locs), \
        f"C-0105's definition must come back as linked evidence: {locs}"
    assert any(l.startswith("linked:") and "lessons/02" in l for l in locs), \
        f"P-0201's definition must come back as linked evidence: {locs}"
    assert "banking licence" in texts and "pulled out" in texts
    # the [[skill link]] resolves too
    assert any("source-verification" in l for l in locs), locs
    # precision: the unrelated atom in the same file is NOT dragged in
    assert not any("C-0106" in t for _, _, t in hits), \
        "expansion must chase cited atoms only, not whole files"
    # anchors outrank linked evidence
    first_linked = next(i for i, l in enumerate(locs) if l.startswith("linked:"))
    assert first_linked > 0, "anchors come first, the chain follows"
    print("[chain] the decision anchored retrieval; both cited atoms and the "
          "linked skill came back as one evidence chain; unrelated atoms in "
          "the same files stayed out")

    # no anchors -> no expansion, and empty queries stay empty
    assert recall.search(sb, "zzz-nothing-matches") == []
    print("[empty] no anchors, no expansion — recall stays quiet")
    print("PASS test_associative")


if __name__ == "__main__":
    main()
