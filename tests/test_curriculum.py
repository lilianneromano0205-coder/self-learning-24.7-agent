#!/usr/bin/env python3
"""Study in a considered order, not the order things arrived (P2).

Ten videos and forty PDFs used to be studied in arrival order: a blog post
before the specification, the same idea learned four times, and no notion of
what the mission needed. This proves the four rules a good student follows:

1. AUTHORITY FIRST — the spec is studied before the tutorial covering the
   same ground, so everything after it is read against a baseline
2. FOUNDATIONS FIRST — an introduction outranks an advanced deep-dive, and a
   lesson defining atoms others cite is pulled forward as a prerequisite
3. DON'T RE-READ — a near-duplicate is skimmed for its differences or skipped
   entirely, never studied from scratch again
4. KNOW WHY — every lesson carries the reason for its depth, and --apply
   queues skims with a goal that forbids re-deriving what is known

Run from the agent/ directory:  python tests/test_curriculum.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox, read_state

sys.path.insert(0, AGENT_DIR)
import curriculum
import loop
import sources

SPEC = ("Introduction to contrast requirements. Body text contrast must be at "
        "least 4.5 to 1 against its background. Large text may use 3 to 1. "
        "Focus indicators must remain visible on every interactive control. "
        "These requirements apply to all conforming content.")
BLOG = ("A friendly guide to contrast. Body text contrast should be about 4.5 "
        "to 1 against its background. Large text can use 3 to 1. Focus rings "
        "ought to stay visible on interactive controls. These rules apply to "
        "most content you will write.")
MOTION = ("Advanced motion choreography internals. Springs, damping ratios "
          "and interruptible transitions for gesture-driven interfaces at "
          "scale, including performance tuning of the compositor.")
PAYROLL = ("Payroll tax withholding schedules for seasonal agricultural "
           "workers, including quarterly remittance deadlines and penalty "
           "computation for late filings in each province.")

W3C = "https://www.w3.org/TR/WCAG22/"
MEDIUM = "https://medium.com/@someone/contrast-guide"
DEVTO = "https://dev.to/someone/motion"
BLOGX = "https://example.blog/payroll"


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def lesson(root, nn, body, src):
    write(root, f"courses/design/lessons/{nn}/transcript.txt",
          f"SOURCE-FILE: {src}\n\n{body}\n")


def main():
    sb = make_sandbox("curriculum", providers={"m": {"script": "s.json"}},
                      roles={"watcher": "m"}, scripts={"s.json": []})
    write(sb, "identity.md", "You design accessible interfaces.\n")
    write(sb, "courses/design/mission.md",
          "- master colour contrast and focus visibility for accessible "
          "interfaces\n- know the conforming requirements for body text\n")
    # arrival order is deliberately WRONG: the blog lands before the spec
    lesson(sb, "01", BLOG, MEDIUM)
    lesson(sb, "02", MOTION, DEVTO)
    lesson(sb, "03", SPEC, W3C)
    lesson(sb, "04", PAYROLL, BLOGX)
    for ref in (MEDIUM, DEVTO, W3C, BLOGX):
        sources.record(sb, "design", ref)

    rep = curriculum.plan(sb, "design")
    order = [r["nn"] for r in rep["lessons"]]
    by_nn = {r["nn"]: r for r in rep["lessons"]}

    # --- 1. authority first
    assert order[0] == "03", f"the specification must be studied first: {order}"
    assert by_nn["03"]["tier"] == 1 and by_nn["03"]["depth"] == "study"
    assert order.index("03") < order.index("01"), \
        "the tier-1 spec must precede the tier-3 blog on the same ground"
    print(f"[authority] arrival order was 01,02,03,04; the plan studies the "
          f"tier-1 specification first: {', '.join(order)}")

    # --- 2. the duplicate is not studied twice
    blog = by_nn["01"]
    assert blog["depth"] == "skim", blog
    assert blog["novelty"] < 0.75, blog["novelty"]
    assert "lesson 03" in blog["reason"], blog["reason"]
    print(f"[duplicate] the blog covering the same ground as the spec was "
          f"marked '{blog['depth']}': {blog['reason']}")

    # --- 3. irrelevant material is not studied in depth
    payroll = by_nn["04"]
    assert payroll["depth"] in ("skim", "skip"), payroll
    assert payroll["relevance"] < by_nn["03"]["relevance"], \
        (payroll["relevance"], by_nn["03"]["relevance"])
    print(f"[relevance] payroll tax law scored {payroll['relevance']} against "
          f"a contrast mission and was not studied in full")

    # --- 4. every lesson carries its reason, and the plan is on disk
    assert all(r["reason"] for r in rep["lessons"])
    assert rep["counts"]["study"] >= 1
    saved = json.load(open(os.path.join(sb, "courses", "design",
                                        "curriculum.json"), encoding="utf-8"))
    assert len(saved["lessons"]) == 4
    text = curriculum.render(rep)
    assert "STUDY" in text and "lesson 03" in text
    print("[why] each lesson states why it earned its depth, and the whole "
          "plan is written to curriculum.json before anything is queued")

    # --- 5. prerequisites pull forward
    sb2 = make_sandbox("curriculum_prereq",
                       providers={"m": {"script": "s.json"}},
                       roles={"watcher": "m"}, scripts={"s.json": []})
    write(sb2, "courses/k/mission.md", "- learn the ledger model\n")
    lesson(sb2, "01", "Advanced ledger reconciliation at scale, deep dive "
                      "into partitioned settlement internals.", BLOGX)
    lesson(sb2, "02", "Defining the ledger primitives everything else uses.",
           BLOGX)
    write(sb2, "courses/k/lessons/02/notes.md",
          "- C-0101 a ledger entry is immutable [src: x]\n"
          "- C-0102 settlement is eventual [src: x]\n")
    write(sb2, "courses/k/lessons/01/notes.md",
          "- C-0201 reconciliation batches use C-0101 and C-0102 [src: x]\n")
    p2 = curriculum.plan(sb2, "k")
    o2 = [r["nn"] for r in p2["lessons"]]
    assert o2[0] == "02", f"the lesson defining cited atoms must come first: {o2}"
    by_k = {r["nn"]: r for r in p2["lessons"]}
    assert by_k["02"]["prereq_pull"] >= 2, by_k["02"]
    print(f"[prerequisite] the lesson defining the atoms the other one cites "
          f"was pulled to the front ({by_k['02']['prereq_pull']} atoms cited "
          f"elsewhere)")

    # --- 6. applying it queues the work in that order, skims told not to redo
    queued = curriculum.apply(sb, "design")
    assert queued and [q["nn"] for q in queued][0] == "03", queued
    tasks = read_state(sb)["tasks"]
    assert len(tasks) == len(queued)
    study = next(t for t in tasks if "Study lesson 03" in t["goal"])
    assert "curriculum order" in study["goal"] and study["course"] == "design"
    skims = [t for t in tasks if t["goal"].startswith("SKIM")]
    assert skims, [t["goal"][:40] for t in tasks]
    assert "ONLY what it adds" in skims[0]["goal"], skims[0]["goal"]
    assert not any("skip" == q["depth"] for q in queued), \
        "a redundant lesson must not be queued at all"
    print(f"[apply] {len(queued)} lessons queued in curriculum order; the "
          f"skims are told to record only what they add")

    # --- 7. coverage names what the mission still lacks
    cov = curriculum.coverage(sb, "design")
    assert cov["topics"] and isinstance(cov["uncovered"], list)
    assert all("support" in t for t in cov["topics"])
    print(f"[coverage] {len(cov['topics'])} mission topics checked against "
          f"what the notes actually support")
    print("PASS test_curriculum")


if __name__ == "__main__":
    main()
