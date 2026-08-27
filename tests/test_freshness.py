#!/usr/bin/env python3
"""FRESHNESS — learned claims age, get superseded, get retracted; the
platform flags the decay instead of embalming the claim (register #26).

  1. an atom past its [expires:] date is flagged with both dates named;
     one still inside its window is not
  2. [supersedes: X] flags the OLD atom and names its successor — lineage
     kept, preference made mechanical
  3. a retraction in org/retractions.jsonl flags every atom whose [src:]
     contains the ref; the ledger is CONTROL-zoned so the worker cannot
     retract the source of a claim it wants to dodge, and a too-short ref
     is refused (it would retract half the library)
  4. nothing is deleted — scan() is a report, and the atoms all remain
  5. the Crossref retraction verdict is a pure function: a fixture with an
     update-to retraction says retracted, a clean record says not —
     no network in any test
  6. freshness reads the SAME notes files citecheck validates (one walker)

Run from the agent/ directory:  python tests/test_freshness.py
"""

import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import fileauth                # noqa: E402
import fleet                   # noqa: E402
import freshness               # noqa: E402
import knowledge               # noqa: E402

NOTES = """# lesson notes

SOURCES:
- S1: https://doi.org/10.9999/retracted.2024.001
- S2: https://example.org/stable-reference

- C-01 the API's rate limit is 100/min [expires: 2020-01-01] [src: https://example.org/stable-reference]
- C-02 the drug reduced symptoms by 40% [src: https://doi.org/10.9999/retracted.2024.001]
- C-03 the old parser handles only ASCII [src: https://example.org/stable-reference]
- C-04 the new parser handles UTF-8 and replaces the ASCII claim [supersedes: C-03] [src: https://example.org/stable-reference]
- C-05 the framework is stdlib-only [expires: 2099-01-01] [src: https://example.org/stable-reference]
"""


def main():
    home = make_sandbox("freshness", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Archivist", "knows what it no longer knows")
    d = os.path.join(root, "courses", "aging-course", "lessons", "01")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "notes.md"), "w", encoding="utf-8") as f:
        f.write(NOTES)

    # 6. same walker as the rest of the platform: knowledge sees the atoms
    seen = {a["id"] for a in knowledge.atoms(root)}
    assert {"C-01", "C-02", "C-03", "C-04", "C-05"} <= seen, seen

    r = freshness.scan(root)
    assert r["checked"] == 5, r

    # 1. expiry: past date flagged with both dates, future date not
    exp = {x["atom"]: x["why"] for x in r["expired"]}
    assert "C-01" in exp and "2020-01-01" in exp["C-01"], r["expired"]
    assert "C-05" not in exp, "an atom inside its window was called stale"

    # 2. supersession: the OLD atom is flagged, successor named
    sup = {x["atom"]: x["why"] for x in r["superseded"]}
    assert sup == {"C-03": "superseded by C-04"}, r["superseded"]

    # 3. retraction: ledger entry flags the citing atom; short ref refused;
    #    worker cannot write the ledger
    assert r["retracted"] == [], "nothing was retracted yet"
    try:
        freshness.retract(root, "10.9999", "x", by="owner")
        raise AssertionError("an 8-char-short ref was accepted — it would "
                            "retract half the library")
    except freshness.FreshnessError as e:
        assert "substring" in str(e), e
    freshness.retract(root, "10.9999/retracted.2024.001",
                      "publisher withdrew the study", by="owner")
    r2 = freshness.scan(root)
    ret = {x["atom"]: x["why"] for x in r2["retracted"]}
    assert "C-02" in ret and "publisher withdrew" in ret["C-02"], r2
    assert "C-03" not in ret and "C-05" not in ret, r2
    try:
        fileauth.resolve(root, "org/retractions.jsonl", mode="write",
                         actor="agent")
        raise AssertionError("the worker can write the retraction ledger — "
                             "it can retract the source of any claim it "
                             "wants to dodge")
    except fileauth.Denied:
        pass

    # 4. a report, not a purge: every atom is still on disk
    assert {a["id"] for a in knowledge.atoms(root)} >= {
        "C-01", "C-02", "C-03", "C-04", "C-05"}
    assert r2["fresh"] == 2, r2      # C-04 and C-05 carry no flags

    # 5. the Crossref verdict is pure and offline
    hit = freshness._crossref_verdict({"message": {"update-to": [
        {"type": "retraction", "updated": {"date-parts": [[2025, 3, 1]]}}]}})
    assert hit["retracted"] and "retraction" in hit["why"], hit
    ok = freshness._crossref_verdict({"message": {"title": ["fine paper"]}})
    assert not ok["retracted"], ok

    print("[freshness] 5 atoms scanned: the expired one flagged with both "
          "dates, the superseded one flagged naming its successor, the "
          "retracted source flagged through the CONTROL-zoned ledger "
          "(short refs refused, worker locked out), nothing deleted, and "
          "the Crossref retraction verdict proven pure and offline")
    print("PASS test_freshness")


if __name__ == "__main__":
    main()
