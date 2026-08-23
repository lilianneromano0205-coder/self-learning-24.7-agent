#!/usr/bin/env python3
"""When the material disagrees with itself, the harness rules on it (M9).

Feed an expert a spec, a design system, a 2018 blog post and two opposing
Medium takes and they will contradict each other. This test builds exactly
that situation and proves the four verdicts are reached mechanically:

  authority   a tier-1 spec beats a tier-3 blog post
  superseded  2026 guidance beats 2018 guidance at equal authority
  context     two rules that hold under different stated conditions are NOT
              a contradiction, and both survive with their condition
  contested   two equals, same era, no condition -> neither may be asserted

and that the CONTESTED verdict is enforced: an answer that states one side
as settled is refused by the gate, while one that presents the disagreement
passes.

Run from the agent/ directory:  python tests/test_conflicts.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import conflicts
import context
import loop
import sources

W3C = "https://www.w3.org/TR/WCAG22/"
MEDIUM = "https://medium.com/@someone/contrast-tips"
CSSTRICKS = "https://css-tricks.com/floats"
WEBDEV = "https://web.dev/layout"
MATERIAL = "https://m3.material.io/foundations/navigation"
DEVTO = "https://dev.to/b/dark-mode-truths"
MEDIUM2 = "https://medium.com/@a/dark-mode-tips"

NOTES = f"""# Notes

- C-0201 Body text contrast should be at least 3:1 for readability [src: {MEDIUM}]
- C-0202 Body text contrast must be at least 4.5:1 [src: {W3C}]
- C-0301 Layout columns should use float clearfix techniques (2018 guidance) [src: {CSSTRICKS}]
- C-0302 Layout columns should use CSS grid, not float clearfix (2026 guidance) [src: {WEBDEV}]
- C-0401 Navigation should be a bottom bar when on mobile [src: {MATERIAL}]
- C-0402 Navigation should never be a bottom bar when on desktop [src: {MATERIAL}]
- C-0501 Dark mode should always use pure black backgrounds [src: {MEDIUM2}]
- C-0502 Dark mode should never use pure black backgrounds [src: {DEVTO}]
"""


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return rel


def main():
    sb = make_sandbox("conflicts", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    write(sb, "courses/design/notes.md", NOTES)
    write(sb, "courses/design/mission.md", "learn interface design\n")
    for ref, title in ((W3C, "WCAG 2.2"), (MEDIUM, "contrast tips"),
                       (CSSTRICKS, "floats"), (WEBDEV, "layout"),
                       (MATERIAL, "Material navigation"),
                       (MEDIUM2, "dark mode tips"), (DEVTO, "dark mode truths")):
        sources.record(sb, "design", ref, title)

    # --- the ledger rates each source, and says why
    assert sources.tier_of(sb, "design", W3C) == 1
    assert sources.tier_of(sb, "design", MEDIUM) == 3
    assert sources.tier_of(sb, "design", MATERIAL) == 2
    assert sources.tier_of(sb, "design", DEVTO) == 3
    again = sources.record(sb, "design", W3C, "WCAG 2.2")
    assert len(sources.load(sb, "design")) == 7, "recording is idempotent"
    over = sources.set_tier(sb, "design", again["id"], 2,
                            "we only use the AA subset")
    assert over["tier"] == 2 and over["override"]["from"] == 1
    assert "AA subset" in over["why"], over
    sources.set_tier(sb, "design", again["id"], 1, "back to normative")
    print("[ledger] every source carries an authority tier with its reason, "
          "and an owner overrule is recorded, not silent")

    # --- the scan reaches four different verdicts
    found = conflicts.scan(sb, "design")
    by_pair = {tuple(sorted((c["a"]["id"], c["b"]["id"]))): c for c in found}
    assert ("C-0201", "C-0202") in by_pair, sorted(by_pair)
    auth = by_pair[("C-0201", "C-0202")]
    assert auth["verdict"] == "authority" and auth["winner"] == "C-0202", auth
    assert "tier-1" in auth["ruling"] and "4.5" in auth["a"]["text"] + auth["b"]["text"]

    sup = by_pair[("C-0301", "C-0302")]
    assert sup["verdict"] == "superseded" and sup["winner"] == "C-0302", sup
    assert "2026" in sup["ruling"] and "out of date" in sup["ruling"]

    ctx = by_pair[("C-0401", "C-0402")]
    assert ctx["verdict"] == "context" and ctx["winner"] is None, ctx
    assert "mobile" in ctx["ruling"] and "desktop" in ctx["ruling"], ctx["ruling"]

    con = by_pair[("C-0501", "C-0502")]
    assert con["verdict"] == "contested" and con["winner"] is None, con
    assert "CONTESTED" in con["ruling"] and "not assert" in con["ruling"]
    print("[verdicts] the spec outranked the blog post, 2026 superseded 2018, "
          "the two conditional rules were kept as conditions, and the two "
          "equals were declared contested")

    # --- it is written down, and it is stable
    rep = conflicts.write(sb, "design")
    assert rep["found"] == len(found)
    body = open(os.path.join(sb, "courses", "design", "conflicts.md"),
                encoding="utf-8").read()
    assert "AUTHORITY" in body and "CONTESTED" in body and "RULING:" in body
    assert conflicts.refresh(sb, "design") is False, "no rescan when nothing changed"
    write(sb, "courses/design/notes.md", NOTES +
          f"- C-0601 Buttons should never use pure black borders [src: {DEVTO}]\n")
    assert conflicts.refresh(sb, "design") is True, "new material must rescan"
    # ...and the new atom shares only a MODIFIER with the dark-mode pair
    # ("pure black"), not a subject. That is not a contradiction, and calling
    # it one would be the confusion this module exists to remove.
    pairs = {tuple(sorted((c["a"]["id"], c["b"]["id"])))
             for c in conflicts.load(sb, "design")}
    assert ("C-0501", "C-0601") not in pairs, \
        "a shared adjective is not a shared subject"
    assert ("C-0501", "C-0502") in pairs, "the real conflict survived"
    print("[ledger] the rulings are written to conflicts.md, rescanned only "
          "when the material changes, and a claim that merely shares an "
          "adjective is not called a contradiction")

    # --- the ruling reaches the window that needs it
    a = loop.Agent(sb)
    msgs, man = context.compile(a, {"id": "t-dark", "role": "practitioner",
                                    "course": "design", "memory_files": [],
                                    "goal": "review the dark mode palette"})
    user = msgs[1]["content"]
    assert "CONFLICTING MATERIAL" in user, user[:600]
    assert "contested" in user and "C-0501" in user and "C-0502" in user
    assert "SOURCE AUTHORITY" in user, "the window states who outranks whom"
    csrc = [s for s in man["sources"] if s["name"] == "conflicts"][0]
    assert csrc["used_tokens"] > 0
    msgs2, _ = context.compile(a, {"id": "t-other", "role": "practitioner",
                                   "course": "design", "memory_files": [],
                                   "goal": "write the release notes"})
    assert "CONFLICTING MATERIAL" not in msgs2[1]["content"], \
        "conflicts load for the goal that hits them, not for every task"
    print("[context] the dark-mode task carried the contested ruling into its "
          "window; an unrelated task did not")

    # --- the gate enforces it
    bad = write(sb, "answers/bad.md",
                "Dark mode backgrounds should be pure black [C-0501]. "
                "That is the rule.\n")
    problems, touched = conflicts.check(sb, os.path.join(sb, bad), "design")
    assert touched == 1 and problems, (touched, problems)
    assert "CONTESTED POINT ASSERTED AS SETTLED" in problems[0]
    good = write(sb, "answers/good.md",
                 "The material is divided on dark mode backgrounds: C-0501 "
                 "argues for pure black, C-0502 argues against it. Both are "
                 "instructional sources of equal standing, so the choice is "
                 "yours; I would follow C-0502 for OLED smearing reasons.\n")
    problems2, touched2 = conflicts.check(sb, os.path.join(sb, good), "design")
    assert touched2 == 1 and not problems2, (touched2, problems2)
    unrelated = write(sb, "answers/other.md", "The build pipeline is green.\n")
    p3, t3 = conflicts.check(sb, os.path.join(sb, unrelated), "design")
    assert (p3, t3) == ([], 0)
    print("[gate] an answer that stated a contested point as settled was "
          "refused; the one that presented both sides passed")
    print("PASS test_conflicts")


if __name__ == "__main__":
    main()
