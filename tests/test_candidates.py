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

import io
import json
import os
import sys

from common import AGENT_DIR, PY, agent_setting, make_sandbox

sys.path.insert(0, AGENT_DIR)
import candidates          # noqa: E402
import conflicts           # noqa: E402
import fileauth            # noqa: E402
import loop                # noqa: E402
import sources             # noqa: E402

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

    # --- 9. AND THE LOOP ACTUALLY CALLS IT.
    #
    # Everything above passed for as long as this module has existed while
    # the engine was reachable from nothing. `grep -rn "import candidates"`
    # returned confidence.py (which uses it only for written_paths) and this
    # file. `task["candidate_rounds"]` — the counter attempts_for reads to
    # decide how many attempts a task has earned — was READ here and WRITTEN
    # nowhere, so it was always 0 and the answer was always 1. settings.toml
    # advertised candidates_max and candidates_on_gate_failure as live
    # settings that loop.py never mentioned.
    #
    # A unit-tested engine with no call site is not a feature, and no unit
    # test can notice that. So this drives the real loop.
    import json as _json
    from common import run_drain
    script = []
    for body in ("short.", "a much longer and more careful answer.", "x"):
        script += [{"tool": "write_file",
                    "args": {"path": "out/answer.md", "content": body}},
                   {"tool": "finish_task", "args": {"summary": "done"}}]
    sb2 = make_sandbox("candidates-wired",
                       providers={"m": {"script": "s.json"}},
                       roles={"practitioner": "m"}, scripts={"s.json": script})
    ag = loop.Agent(sb2)
    tid = ag.add_task("practitioner", "write the answer",
                      done_check='python -c "import sys; sys.exit(1)"')
    run_drain(sb2, timeout=240)
    events = []
    with io.open(os.path.join(sb2, "logs", "agent.log"),
                 encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"candidate_' in line:
                try:
                    events.append(_json.loads(line.split(" ", 2)[-1]))
                except ValueError:
                    pass
    kinds = [e["event"] for e in events]
    assert "candidate_stashed" in kinds, (
        "the loop never stashed an attempt — best-of-N is still dead code, "
        "which every test above would happily keep reporting as green")
    assert len(candidates.history(sb2, tid)) >= 2, (
        "fewer than two attempts were kept, so nothing could be compared")

    # AND it must not churn. Measured on ordinary tasks, score() returns 0.0
    # for every attempt — there is no spec and no interface to measure, so
    # the composite has nothing to discriminate on. Ranking a set of ties is
    # a stable sort, so "the winner" would be whichever attempt happened to
    # be first, and swapping the last attempt for an arbitrary earlier one
    # can replace a better answer with a worse one. A tie must leave the
    # last attempt exactly where it is.
    scores = {float(h.get("score") or 0) for h in candidates.history(sb2, tid)}
    if len(scores) == 1:
        assert "candidate_promoted" not in kinds, (
            "every attempt scored the same and one was promoted anyway — "
            "that is not test-time compute, it is churn")
        assert "candidate_tie" in kinds, (
            "a tie was neither promoted nor reported; silence is how this "
            "stops being auditable")
        final = io.open(os.path.join(sb2, "out", "answer.md"),
                        encoding="utf-8").read()
        assert final == "x", (
            f"the last attempt was replaced on a tie: {final!r}")
    print(f"[wired] the loop stashes every refused attempt "
          f"({kinds.count('candidate_stashed')} of them here) and promotes "
          f"one only when it strictly beats the last — on a task where the "
          f"verifier cannot discriminate it reports a tie and changes "
          f"nothing, which is the honest answer rather than a shuffle")
    # --- 10. AND IT DISCRIMINATES. Wiring is not the same as working.
    #
    # The previous commit connected best-of-N to the loop and then measured
    # it honestly: six attempts at one goal all scored 0.0, because every
    # component declined to answer on an ordinary task — no citations to
    # check, no interface, no course spec. rank() over a set of ties is a
    # stable sort, so the "winner" was whichever attempt happened to come
    # first, and the feature was wired, safe, and worth nothing.
    #
    # `substance` is the component that always applies: exists, parses,
    # carries no placeholder, is not trivially shorter than the request. It
    # does not measure whether work is GOOD — it measures whether work is
    # REAL, which is the distinction the tie could not see.
    junk = write(sb, "answers/junk.md", "x")
    thin = write(sb, "answers/thin.md", "short.")
    real = write(sb, "answers/real.md",
                 "A considered answer with genuine detail that addresses the "
                 "question rather than gesturing at it.")
    todo = write(sb, "answers/todo.md",
                 "A long enough answer in every other respect, but TODO: "
                 "finish the second half of this before shipping it.")
    broken = write(sb, "answers/broken.json", '{"a": 1,,}')
    goal = "write a considered answer about retry budgets"
    def sub(rel):
        return candidates.score(agent, task_with([rel], done_check=PASS,
                                                 goal=goal))["score"]
    s_junk, s_thin, s_real = sub("answers/junk.md"), sub("answers/thin.md"), sub("answers/real.md")
    s_todo, s_broken = sub("answers/todo.md"), sub("answers/broken.json")
    assert s_real > s_junk, (
        f"a real answer ({s_real}) did not outscore 'x' ({s_junk}) — this is "
        f"the exact tie that made best-of-N pick arbitrarily")
    assert s_real > s_thin, (s_real, s_thin)
    assert s_real > s_todo, (
        f"an answer carrying TODO ({s_todo}) scored as well as a finished one "
        f"({s_real})")
    assert s_broken < s_real, (
        f"a .json file that does not parse ({s_broken}) was not penalised")
    # and it must not invent an opinion where there is no artifact
    assert candidates._substance(sb, []) is None, (
        "substance scored a task that wrote nothing; a component with no "
        "evidence must decline, not guess")
    print(f"[discriminates] a real answer scores {s_real}, a one-character "
          f"one {s_junk}, an unfinished one carrying TODO {s_todo}, and a "
          f".json that does not parse {s_broken} — the composite can now tell "
          f"attempts apart on ordinary work, where every other component "
          f"declines to answer and six attempts previously tied at 0.0")

    check_the_stash_cannot_be_used_as_a_write_primitive(sb)
    print("PASS test_candidates")


def check_the_stash_cannot_be_used_as_a_write_primitive(sb):
    """A best-of-N artifact list is MODEL-SUPPLIED DATA, never a licence.

    Both halves of this were reproduced against the shipped code, and neither
    needed a shell — so the Rule-of-Two roles that hold no run_command could
    do it with write_file alone:

      * `written_paths` reads the artifact list out of the task's own
        write_file STEPS, and a REFUSED write_file is still recorded as a
        step — so the list could name any path the model ever typed. The
        stash directory itself classified as ZONE_ROOT, so the worker could
        also write candidates/<id>/<n>/score.json declaring
        `artifacts: ["prompts/constitution.md"]`, drop its own constitution
        beside it, and let the loop's own _promote_best_attempt copy that
        over the FIRST block of every system prompt.
      * naming `../../../../OUT.txt` as an artifact made promote() write
        outside the expert root entirely. It did: the reproduction created a
        file in the user's home directory.

    The File Authority existed the whole time; this module simply reached the
    filesystem with os.path.join instead of asking it.
    """
    import io as _io
    import json as _json
    import shutil
    import tempfile
    root = tempfile.mkdtemp(prefix="cand-contain-")
    try:
        os.makedirs(os.path.join(root, "prompts"), exist_ok=True)
        real = os.path.join(root, "prompts", "constitution.md")
        _io.open(real, "w", encoding="utf-8").write("THE REAL CONSTITUTION\n")

        # a planted stash whose "artifact" is a control file, plus one that
        # walks out of the root
        d = os.path.join(root, "candidates", "t1", "1")
        os.makedirs(os.path.join(d, "prompts"), exist_ok=True)
        _io.open(os.path.join(d, "prompts", "constitution.md"), "w",
                 encoding="utf-8").write("PWNED\n")
        escapee = os.path.normpath(os.path.join(root, "..", "CAND-ESCAPE.txt"))
        if os.path.exists(escapee):
            os.remove(escapee)
        _io.open(os.path.join(d, "score.json"), "w", encoding="utf-8").write(
            _json.dumps({"attempt": 1, "passed": True, "score": 1.0,
                         "artifacts": ["prompts/constitution.md",
                                       "../CAND-ESCAPE.txt"]}))

        restored = candidates.promote(root, "t1", 1)
        assert restored == [], (
            f"promote() restored {restored} — a path the agent could not "
            f"have written is not a path it may have restored")
        assert _io.open(real, encoding="utf-8").read() == \
            "THE REAL CONSTITUTION\n", \
            "the stash overwrote prompts/constitution.md"
        assert not os.path.exists(escapee), \
            f"promote() wrote {escapee}, outside the expert root"

        # stash() is contained in both directions too
        kept = candidates.stash(root, "t2", 1,
                                ["prompts/constitution.md",
                                 "../../etc/passwd"], {"score": 1.0})
        meta = _json.load(_io.open(os.path.join(kept, "score.json"),
                                   encoding="utf-8"))
        assert meta["artifacts"] == [], meta
        assert meta.get("refused_paths"), (
            "a refused artifact must be RECORDED, not dropped in silence — "
            "a stash that quietly keeps nothing reads as a stash that had "
            "nothing to keep")

        # and the score itself is control state: rank() is gate-first, so a
        # writable "passed": true would restore the attempt the gate refused
        try:
            fileauth.resolve(root, "candidates/t1/1/score.json", "write",
                             "agent")
            raise AssertionError("the agent may write a candidate's score")
        except fileauth.Denied:
            pass
        fileauth.resolve(root, "candidates/t1/1/out/page.html", "write",
                         "agent")        # its own artifacts stay writable
        print("[contained] a planted stash could not overwrite "
              "prompts/constitution.md nor write outside the expert root, a "
              "traversal artifact was refused and RECORDED, and the score "
              "that decides which attempt wins is control state while the "
              "attempt's own files stay the agent's")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
