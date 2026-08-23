#!/usr/bin/env python3
"""TEST-TIME COMPUTE: make several, keep the best, and say why (P1).

The research result this implements is that spending inference compute
intelligently can beat a much larger model doing one pass. The mechanism only
works if the SCORING is trustworthy, so nothing here asks a model for an
opinion: candidates are scored by the verifiers that already gate the work.

1. the task's own gate is HARD — a candidate that fails it can never win,
   whatever else it scores
2. each verifier contributes only where it applies: grounding to prose,
   the design gate to interfaces, honesty to contested material
3. snapshot/restore puts the world back exactly, including deleting files an
   attempt created
4. stash/promote brings the winner's bytes back
5. the escalation is adaptive: 1 attempt, then 3 after a gate failure, then 5
   — and the owner can cap or disable it
6. the choice is explainable: it names why the winner won

Run from the agent/ directory:  python tests/test_candidates.py
"""

import json
import os
import sys

from common import AGENT_DIR, PY, agent_setting, make_sandbox

sys.path.insert(0, AGENT_DIR)
import candidates
import conflicts
import loop
import sources

GOOD_HTML = """<!DOCTYPE html>
<html lang="en"><head><style>
  body { color: #14161a; background: #ffffff; }
  .p { max-width: 60ch; padding: 16px; }
  @media (max-width: 640px) { .p { padding: 12px; } }
</style></head><body><main class="p"><h1>Report</h1>
<img src="a.png" alt="A chart of monthly spend">
<label for="q">Amount</label><input id="q"><button>Send</button>
</main></body></html>
"""
SLOP_HTML = ('<html><head><style>.h{background:linear-gradient(#6366f1,#8b5cf6);'
             'color:#a5b4fc}</style></head><body><img src="a.png">'
             '<p>Lorem ipsum dolor sit amet.</p></body></html>')


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def task_with(paths, **kw):
    steps = [{"tool": "write_file",
              "args": json.dumps({"path": p, "content": "x"})} for p in paths]
    return dict({"id": "t-1", "role": "practitioner", "steps": steps}, **kw)


def main():
    sb = make_sandbox("candidates", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    agent = loop.Agent(sb)
    PASS = f'"{PY}" -c "import sys;sys.exit(0)"'
    FAIL = f'"{PY}" -c "import sys;sys.exit(1)"'

    # --- 1. paths come from the task's own record
    t = task_with(["out/page.html", "notes/report.md"])
    assert candidates.written_paths(t) == ["out/page.html", "notes/report.md"]
    print("[artifacts] the scorer reads what the task actually wrote from its "
          "own step record, not from a guess")

    # --- 2. the gate is hard
    write(sb, "out/page.html", GOOD_HTML)
    winner = candidates.score(agent, task_with(["out/page.html"],
                                               done_check=PASS))
    loser = candidates.score(agent, task_with(["out/page.html"],
                                              done_check=FAIL))
    assert winner["passed"] and not loser["passed"]
    assert loser["score"] == winner["score"], \
        "both wrote the same artifact, so only the gate should separate them"
    ranked = candidates.rank([dict(loser, attempt=1), dict(winner, attempt=2)])
    assert ranked[0]["attempt"] == 2, "a gate failure must never rank first"
    print("[gate] two identical artifacts, one gate failure: the failure "
          "cannot win at any score")

    # --- 3. the design gate scores interfaces
    write(sb, "out/slop.html", SLOP_HTML)
    good = candidates.score(agent, task_with(["out/page.html"], done_check=PASS))
    slop = candidates.score(agent, task_with(["out/slop.html"], done_check=PASS))
    assert good["score"] > slop["score"], (good["score"], slop["score"])
    assert slop["detail"]["interface"]["blockers"] > 0
    assert "interface" in good["scored_by"]
    print(f"[interface] the considered page scored {good['score']} and the "
          f"generated filler {slop['score']}, both passing the same gate")

    # --- 4. grounding and honesty apply only where they mean something
    W3C, BLOG = "https://www.w3.org/TR/WCAG22/", "https://medium.com/@a/x"
    write(sb, "courses/design/notes.md",
          f"- C-0101 contrast is at least 4.5:1 [src: {W3C}]\n"
          f"- C-0501 dark mode should always be pure black [src: {BLOG}]\n"
          f"- C-0502 dark mode should never be pure black [src: {W3C}]\n")
    for ref in (W3C, BLOG):
        sources.record(sb, "design", ref)
    conflicts.write(sb, "design")
    honest = write(sb, "answers/honest.md",
                   "Contrast must clear 4.5:1 [C-0101]. On dark backgrounds "
                   "the material is divided: C-0501 and C-0502 disagree.\n")
    ghost = write(sb, "answers/ghost.md",
                  "As established in [C-9999], the answer is obvious.\n")
    h = candidates.score(agent, task_with(["answers/honest.md"],
                                          done_check=PASS, course="design"))
    g = candidates.score(agent, task_with(["answers/ghost.md"],
                                          done_check=PASS, course="design"))
    assert g["detail"]["grounding"]["problems"] > 0, g["detail"]
    assert h["score"] > g["score"], (h["score"], g["score"])
    assert "grounding" in h["scored_by"]
    ui_only = candidates.score(agent, task_with(["out/page.html"],
                                                done_check=PASS))
    assert "grounding" not in ui_only["scored_by"], \
        "a citation check has no opinion about an HTML page"
    print("[applies] a citation to a nonexistent atom sank its candidate; the "
          "same check stayed silent about an interface")

    # --- 5. snapshot / restore
    before = candidates.snapshot(sb, ["out/page.html", "out/new.txt"])
    write(sb, "out/page.html", "OVERWRITTEN")
    write(sb, "out/new.txt", "created by an attempt")
    candidates.restore(sb, before)
    assert open(os.path.join(sb, "out", "page.html"), encoding="utf-8").read() \
        == GOOD_HTML, "restore must return the original bytes"
    assert not os.path.exists(os.path.join(sb, "out", "new.txt")), \
        "restore must also remove what the attempt created"
    print("[isolation] an attempt's changes were undone byte-for-byte, "
          "including deleting the file it invented")

    # --- 6. stash and promote
    write(sb, "out/page.html", "ATTEMPT ONE")
    candidates.stash(sb, "t-1", 1, ["out/page.html"],
                     {"passed": True, "score": 0.4})
    write(sb, "out/page.html", "ATTEMPT TWO")
    candidates.stash(sb, "t-1", 2, ["out/page.html"],
                     {"passed": True, "score": 0.9})
    write(sb, "out/page.html", "SOMETHING ELSE ENTIRELY")
    restored = candidates.promote(sb, "t-1", 2)
    assert restored == ["out/page.html"]
    assert open(os.path.join(sb, "out", "page.html"),
                encoding="utf-8").read() == "ATTEMPT TWO"
    hist = candidates.history(sb, "t-1")
    assert [h["attempt"] for h in hist] == [1, 2]
    assert hist[1]["score"] == 0.9
    print("[promote] the winning attempt's bytes were put back and every "
          "attempt kept its own score on disk")

    # --- 7. adaptive escalation
    cfg = agent.cfg
    assert candidates.attempts_for({"candidate_rounds": 0}, cfg) == 1
    assert candidates.attempts_for({"candidate_rounds": 1}, cfg) == 3
    assert candidates.attempts_for({"candidate_rounds": 2}, cfg) == 5
    capped = {"agent": {"candidates_max": 2}}
    assert candidates.attempts_for({"candidate_rounds": 2}, capped) == 2
    off = {"agent": {"candidates_on_gate_failure": False}}
    assert candidates.attempts_for({"candidate_rounds": 2}, off) == 1
    print("[adaptive] one attempt until something fails, then 3, then 5 — "
          "capped by the owner's setting and switchable off")

    # --- 8. the choice is explainable
    text = candidates.explain([dict(loser, attempt=1), dict(winner, attempt=2)])
    assert "winner: attempt 2" in text and "failed its gate" in text
    print("[explain] the winner is reported with the reason every loser lost")
    print("PASS test_candidates")


if __name__ == "__main__":
    main()
