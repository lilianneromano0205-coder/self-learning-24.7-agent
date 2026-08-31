#!/usr/bin/env python3
"""The agent works from an accurate model of ITSELF (M9).

Not a persona and not a claim about consciousness: a compiled, factual
account of what this expert has verified, what it has proven, what it has
failed at, and where its knowledge ends -- read from the ledgers the harness
already writes, so it cannot flatter itself.

1. a brand-new expert is told plainly that it has studied nothing
2. after study, it reports its courses, verified atoms, exam result and the
   authority tiers its knowledge rests on
3. an unexamined course is named as unproven; a lucky single success is
   reported as "insufficient evidence"; a quarantined playbook is named as
   do-not-use
4. it knows the constraints of THIS run: role, tools, where commands execute
5. the block reaches the window -- including a closed-book exam, because
   knowing what you have not studied is not course material

Run from the agent/ directory:  python tests/test_awareness.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import context
import fleet
import loop
import memory
import selfmodel
import skills
import sources


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return rel


def main():
    home = make_sandbox("awareness", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Aware One", "designs interfaces that work")

    # --- 1. a fresh expert admits it knows nothing
    block = selfmodel.render(selfmodel.build(root))
    assert "studied NOTHING" in block, block
    assert "Aware One" in block or "aware-one" in block
    assert "not in my training" in block.lower() or "stop" in block.lower()
    print("[fresh] a new expert is told it has verified nothing yet, instead "
          "of being handed a confident persona")

    # --- 2. after study it reports what it actually has
    write(root, "courses/design/notes.md",
          "- C-0101 Contrast for body text is at least 4.5:1 "
          "[src: https://www.w3.org/TR/WCAG22/]\n"
          "- C-0102 Focus rings must remain visible on every control "
          "[src: https://www.w3.org/TR/WCAG22/]\n")
    write(root, "courses/design/exam-results.md",
          "# Exam 1\nScore: 92%\nVerdict: PASS\n")
    write(root, "courses/design/gaps.md",
          "- motion and animation timing is not covered by any source yet\n")
    write(root, "courses/typography/notes.md",
          "- C-0201 Line length reads best near 66 characters "
          "[src: https://practicaltypography.com]\n")
    sources.record(root, "design", "https://www.w3.org/TR/WCAG22/", "WCAG 2.2")
    sources.record(root, "typography", "https://practicaltypography.com",
                   "Practical Typography")
    m = selfmodel.build(root)
    by_course = {s["course"]: s for s in m["studied"]}
    assert by_course["design"]["atoms"] == 2, by_course["design"]
    assert by_course["design"]["exam"]["score"] == 92
    assert by_course["design"]["exam"]["verdict"] == "pass"
    assert by_course["typography"]["exam"] is None
    block = selfmodel.render(m)
    assert "studied design: 2 verified atom(s); exam 92% (pass)" in block, block
    assert "tier 1" in block, "the tier its knowledge rests on is stated"
    assert "NEVER EXAMINED" in block, "typography was never examined"
    assert "motion and animation timing" in block, "its own gap is named"
    print("[studied] it reports each course by verified atoms, exam result and "
          "source tier -- and names the course it was never examined on")

    # --- 3. evidence, not flattery
    memory.record_outcome(home, "aware-one", "design", success=True,
                          verified=True, task_id="t-1")
    m2 = selfmodel.build(root)
    comp = m2["proven"]["competence"]["design"]
    assert comp["claim"] == "insufficient evidence", comp
    assert "insufficient evidence" in selfmodel.render(m2)
    for i in range(3):
        skills.record_use(root, ["skills/guess-the-spacing.md"],
                          f"t-loss-{i}", success=False)
    assert skills.status_of(root, "skills/guess-the-spacing.md") == "candidate", \
        "co-occurrence losses alone must not quarantine"
    # quarantine is now an ablation verdict: the same cases run with and
    # without the skill, and only measured harm earns "do NOT use"
    os.makedirs(os.path.join(root, "skills"), exist_ok=True)
    with open(os.path.join(root, "skills", "guess-the-spacing.md"), "w",
              encoding="utf-8") as f:
        f.write("KEYWORDS: spacing\nguess the spacing by eye\n")
    harm_cases = [{"id": f"sp-{i}", "input": {"x": i}, "expected": i * 2}
                  for i in range(1, 7)]
    skills.run_ablation(
        root, "skills/guess-the-spacing.md", harm_cases,
        lambda case, wd, injected, seed: case["input"]["x"] * (1 if injected else 2),
        lambda case, out: out == case["expected"], seed=5)
    assert skills.status_of(root, "skills/guess-the-spacing.md") == "quarantined"
    block3 = selfmodel.render(selfmodel.build(root))
    assert "quarantined playbooks (do NOT use): guess-the-spacing" in block3
    print("[evidence] one lucky success is reported as insufficient evidence, "
          "and a playbook whose ablation showed measured harm is named "
          "do-not-use — losses alone no longer convict")

    # --- 4. the constraints of this run
    n = selfmodel.build(root, role="tester",
                        task={"id": "t-x", "role": "tester",
                              "stop": {"max_steps": 4}})["now"]
    assert n["role"] == "tester" and n["sandbox"] == "host"
    assert "finish_task" in (n.get("tools") or []), n
    assert n["stop"] == {"max_steps": 4}
    # a role with no provider configured is a fact about itself, not a crash
    unconfigured = selfmodel.build(root, role="student")
    assert "[roles.student]" in unconfigured["now"].get("role_problem", ""), \
        unconfigured["now"]
    assert "WARNING" in selfmodel.render(unconfigured)
    print("[now] it knows its role, its allowed tools, its stop condition and "
          "where commands run -- and says so when a role has no provider")

    # --- 5. it reaches the window, closed book included
    a = loop.Agent(root)
    msgs, man = context.compile(a, {"id": "t-self", "role": "practitioner",
                                    "course": "design", "memory_files": [],
                                    "goal": "improve the contrast of the app"})
    user = msgs[1]["content"]
    assert user.startswith("SELF —") or "SELF —" in user[:400], user[:200]
    ssrc = [s for s in man["sources"] if s["name"] == "self"][0]
    assert ssrc["used_tokens"] > 0 and not ssrc["excluded_by_router"]
    exam_msgs, exam_man = context.compile(
        a, {"id": "t-exam", "role": "student", "course": "design",
            "memory_files": [], "goal": "sit the closed-book exam on design"})
    ex = {s["name"]: s["excluded_by_router"] for s in exam_man["sources"]}
    assert not ex["self"], "a student keeps its self-model"
    assert ex["commons"] and ex["skills"], "and stays closed-book otherwise"
    assert "4.5:1" not in exam_msgs[1]["content"], \
        "the self-model must never smuggle the answers in"
    print("[window] the self-model leads every context window, survives a "
          "closed-book exam, and carries no course content with it")
    # ---- can it tell a national laboratory from an SEO blog? ------------
    # The whole "learn only from real sources" claim rests on this one
    # function, and it was the United States plus the Commonwealth and
    # nothing else. Measured before the fix, `ec.europa.eu` — the European
    # Commission — came back tier 3 with the reason "unrecognised origin",
    # the SAME rating as `someseoblog.example/top-10`. So did CERN, Max
    # Planck, INRIA, RIKEN, CSIRO, and the governments of France, New
    # Zealand, Switzerland and Japan. A learner told to prefer government
    # and university sources could not tell them from a content farm.
    #
    # Both directions, enumerated, because a bar that admits everything is
    # the same as no bar and a bar that admits nothing gets removed.
    AUTHORITATIVE = [
        "https://ec.europa.eu/info/x", "https://home.cern/science/y",
        "https://www.mpg.de/z", "https://www.inria.fr/a",
        "https://www.riken.jp/b", "https://www.csiro.au/c",
        "https://www.gouv.fr/d", "https://www.canada.gc.ca/e",
        "https://www.govt.nz/f", "https://www.admin.ch/g",
        "https://www.go.jp/h", "https://www.bund.de/i",
        "https://www.un.org/j", "https://www.oecd.org/k",
        "https://www.worldbank.org/l", "https://www.ieee.org/m",
        "https://www.iso.org/n", "https://ocw.mit.edu/o",
        "https://www.nasa.gov/p", "https://www.cam.ac.uk/q",
        "https://www.who.int/r", "https://www.nih.gov/s",
    ]
    NOT_AUTHORITATIVE = [
        "https://medium.com/@someone/how-i-did-it",
        "https://someseoblog.example/top-10-tips",
        "https://www.reddit.com/r/programming/x",
        "https://randomtips.example/blog/post",
        "https://mit.edu.evil.example/pretending",   # lookalike, not MIT
    ]
    low = [(u, sources.classify(u)[1]) for u in AUTHORITATIVE
           if sources.classify(u)[1] > sources.LEARN_MIN_TIER]
    assert not low, (
        f"{len(low)} public institution(s) rate below the learn bar and would "
        f"be refused as material: {low[:5]}. This is the function the whole "
        f"'real sources, not generic internet trash' claim rests on.")
    high = [(u, sources.classify(u)[1]) for u in NOT_AUTHORITATIVE
            if sources.classify(u)[1] <= sources.LEARN_MIN_TIER]
    assert not high, (
        f"content-farm material cleared the learn bar: {high}. A bar that "
        f"admits everything is the same as no bar.")
    assert sources.classify("https://mit.edu.evil.example/x")[1] >= 3, (
        "a lookalike domain inherited MIT's standing — trust must come from "
        "the registered domain, never from a substring of it")
    print(f"[institutions] {len(AUTHORITATIVE)} real public bodies — the EU, "
          f"CERN, Max Planck, INRIA, RIKEN, CSIRO, four national governments, "
          f"the UN, OECD, IEEE, ISO, MIT OpenCourseWare — all clear the learn "
          f"bar, while {len(NOT_AUTHORITATIVE)} content-farm and lookalike "
          f"URLs do not; before this, the European Commission rated exactly "
          f"the same as an SEO blog")

    print("PASS test_awareness")


if __name__ == "__main__":
    main()
