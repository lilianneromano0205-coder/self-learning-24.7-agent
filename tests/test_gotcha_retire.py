#!/usr/bin/env python3
"""GOTCHAS THAT ARE NO LONGER TRUE MUST STOP BINDING.

A gotcha is the cheapest knowledge this fleet has and, until now, the only
kind it could never let go of. Two properties make a stale one actively
harmful rather than merely untidy:

  * it is BINDING. render() says so in as many words: "do not re-run a step
    that is listed here as failing". A gotcha that says pandoc is missing,
    written in March, is still forbidding pandoc in April.
  * only MAX_INJECT of them fit in the window. A stale one does not sit
    politely at the back; it EVICTS a live warning.

So they have to be retirable. The whole question is what counts as evidence,
and there is one tempting answer that is wrong:

    "nobody has hit this gotcha in 200 tasks, retire it"

Silence cannot distinguish an OBSOLETE gotcha from a LOAD-BEARING one that
every task is quietly obeying. Retiring on silence retires precisely the
fences that are still holding, and does it fastest for the ones working best.

The evidence used instead is direct: a later step RAN THE SAME THING AND IT
WORKED. That has no such ambiguity. This file pins the whole mechanism:

  1. a probe is recorded from the failing step, and it is SPECIFIC
  2. a later successful step retires the gotcha it disproves
  3. …and only that one — a different command retires nothing
  4. a FAILED step proves nothing, however many times it runs
  5. a failure with no runnable subject gets NO probe and never auto-retires
  6. retirement is a MARK, never a delete — the audit trail survives
  7. a retired gotcha leaves matching(), render() and the context window
  8. if it fails again it is UN-retired, and the resurrection is recorded
  9. gotcha files written before probes existed still parse, and never retire
 10. the loop actually calls this — an unwired retire() is a no-op that
     reports success

Run from the agent/ directory:  python tests/test_gotcha_retire.py
"""

import io
import json
import os
import sys

from common import AGENT_DIR, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import context                  # noqa: E402
import fleet                    # noqa: E402
import gotchas                  # noqa: E402
import loop                     # noqa: E402

GOAL = "convert the docx report to markdown with pandoc for the archive"


def failing_task(tid, cmd, result="ERROR: exit 127 command not found"):
    return {"id": tid, "role": "practitioner", "goal": GOAL, "status": "failed",
            "steps": [{"tool": "run_command", "args": json.dumps({"cmd": cmd}),
                       "result": result, "ts": "2026-08-25"}]}


def passing_task(tid, cmd, result="ok"):
    return {"id": tid, "role": "practitioner", "goal": GOAL, "status": "done",
            "steps": [{"tool": "run_command", "args": json.dumps({"cmd": cmd}),
                       "result": result, "ts": "2026-08-25"}]}


REC = {"category": "infrastructure", "failure_id": "F-1", "goal": GOAL,
       "cause": "pandoc is not on PATH inside the container",
       "actual": "exit 127 command not found"}


def read_lines(root):
    p = os.path.join(root, "gotchas", "general.md")
    return [l for l in io.open(p, encoding="utf-8").read().splitlines()
            if l.startswith("- [")]


def main():
    home = make_sandbox("gotcha-retire", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Retirer", "learns what stopped being true")

    # --- 1. the probe is recorded, and it is SPECIFIC ---------------------
    gotchas.from_failure(root, failing_task("t1", "pandoc report.docx -o r.md"),
                         REC)
    entries = gotchas.load(root)
    assert len(entries) == 1, entries
    assert entries[0]["probe"] == "cmd:pandoc", entries[0]
    assert entries[0]["retired"] is None

    # a generic runner must carry its subcommand, or `git push` failing on
    # credentials would be retired by any `git status` that works
    assert gotchas.probe_of({"tool": "run_command", "result": "x",
                             "args": json.dumps({"cmd": "git push origin hf"})
                             }) == "cmd:git:push"
    assert gotchas.probe_of({"tool": "run_command", "result": "x",
                             "args": json.dumps({"cmd": "git status"})
                             }) == "cmd:git:status"
    print("[probe] the failing step recorded `cmd:pandoc`, and a generic "
          "runner keeps its subcommand so `git push` and `git status` are "
          "not the same claim")

    # --- 3 + 4. the wrong evidence retires NOTHING ------------------------
    other = gotchas.probes_that_passed(passing_task("t2", "soffice --convert"),
                                       loop.step_failed)
    assert gotchas.retire(root, other, "t2") == [], (
        "a different command retired a gotcha it says nothing about")
    still_failing = gotchas.probes_that_passed(
        failing_task("t3", "pandoc a.docx", "ERROR: exit 127"), loop.step_failed)
    assert still_failing == set(), still_failing
    assert gotchas.retire(root, still_failing, "t3") == [], (
        "a step that FAILED was treated as proof the failure is gone")
    assert len(gotchas.load(root)) == 1, "the gotcha should still be binding"
    print("[specific] a different command proved nothing, and pandoc failing "
          "again proved nothing — the gotcha still binds")

    # --- 2 + 6. the right evidence retires it, as a MARK not a delete -----
    good = gotchas.probes_that_passed(passing_task("t4", "pandoc b.docx -o b.md"),
                                      loop.step_failed)
    assert good == {"cmd:pandoc"}, good
    dropped = gotchas.retire(root, good, "t4")
    assert len(dropped) == 1 and dropped[0]["probe"] == "cmd:pandoc", dropped
    assert gotchas.load(root) == [], "a disproved gotcha is still binding"

    kept = gotchas.load(root, include_retired=True)
    assert len(kept) == 1, "the line was DELETED — the audit trail is gone"
    assert kept[0]["retired"] and kept[0]["retired"][1] == "t4", kept[0]
    raw = read_lines(root)[0]
    assert "RETIRED" in raw and "by task t4" in raw, raw
    assert "pandoc is not on PATH" in raw, (
        "the original cause must survive retirement — an auditor needs to "
        "read what was withdrawn, not just that something was")
    # retiring twice must not stack markers
    assert gotchas.retire(root, good, "t5") == [], "retired twice"
    assert read_lines(root)[0].count("RETIRED") == 1, read_lines(root)[0]
    print(f"[retired] a later step ran pandoc successfully and the gotcha was "
          f"withdrawn — MARKED, not deleted: the line still carries its cause, "
          f"the date, and the task that disproved it")

    # --- 7. and it leaves the window the model actually reads -------------
    a = loop.Agent(root)
    assert gotchas.matching(root, GOAL) == [], "a retired gotcha still matches"
    assert gotchas.render(gotchas.matching(root, GOAL)) == ""
    msgs, _m = context.compile(a, {"id": "w1", "role": "practitioner",
                                   "goal": GOAL, "course": None})
    assert "pandoc is not on PATH" not in msgs[1]["content"], (
        "the withdrawn warning is still being injected, so it still costs a "
        "slot and still forbids a step that works")
    print("[window] the withdrawn gotcha no longer reaches the context window, "
          "so it stops evicting live warnings and stops forbidding a step "
          "that now works")

    # --- 8. a resurrection is the most valuable line in the file ----------
    gotchas.from_failure(root, failing_task("t6", "pandoc c.docx"), REC)
    back = gotchas.load(root)
    assert len(back) == 1, "the gotcha did not come back when it failed again"
    raw = read_lines(root)[0]
    assert "UNRETIRED" in raw, raw
    assert "then failed again" in raw and "by task t4" in raw, (
        f"the resurrection must name the retirement it overturned: {raw}")
    assert back[0]["repeats"] == 2, back[0]
    print("[resurrection] the same failure came back after being withdrawn — "
          "the gotcha binds again, and the line permanently records that it "
          "was disproved once and returned, which is the signature of a "
          "FLAPPING environment rather than a fixed one")

    # --- 5 + 9. no probe, no auto-retirement ------------------------------
    reason = {"category": "premature_stop", "failure_id": "F-2",
              "goal": "summarise the findings and stop when they are covered",
              "cause": "stopped while the goal was still reachable",
              "actual": "3 of 8 findings covered"}
    gotchas.from_failure(root, {"id": "t7", "role": "practitioner",
                                "goal": reason["goal"], "status": "failed",
                                "steps": [{"tool": "write_file", "result": "ok",
                                           "args": json.dumps({"path": "a.md"})}]},
                         reason)
    noprobe = [e for e in gotchas.load(root) if e["probe"] is None]
    assert noprobe, "a reasoning failure should carry no probe"
    # (the pandoc gotcha is binding again after its resurrection above, so
    # this sweep legitimately withdraws THAT one; the claim under test is
    # only that the un-probed entry survives it)
    swept = gotchas.retire(root, {"cmd:pandoc", "cmd:git:push", None}, "t8")
    assert not any("premature_stop" in d["when"] for d in swept), swept
    survived = [e for e in gotchas.load(root) if e["probe"] is None]
    assert survived, (
        "a gotcha with no probe was auto-retired — nothing a later task does "
        "could possibly disprove 'you stopped too early', so retiring it is "
        "a guess wearing the costume of evidence")

    # a file written before probes existed must still parse AND never retire
    legacy = os.path.join(root, "gotchas", "legacy.md")
    io.open(legacy, "w", encoding="utf-8", newline="").write(
        gotchas.HEADER +
        "- [2026-01-05] (F-9) TRIGGER: pandoc, docx, infrastructure | WHEN "
        "infrastructure: pandoc missing | DO retry with backoff | src: task old\n")
    old = [e for e in gotchas.load(root) if e["scope"].endswith("legacy.md")]
    assert len(old) == 1 and old[0]["probe"] is None, old
    assert not any(d["scope"].endswith("legacy.md")
                   for d in gotchas.retire(root, {"cmd:pandoc"}, "t9")), (
        "an entry written before probes existed was retired on no evidence")
    print("[conservative] a failure with no runnable subject gets no probe and "
          "never auto-retires, and gotcha files written before probes existed "
          "still parse and still bind — under-retiring costs a context slot, "
          "over-retiring deletes a warning that was still true")

    # --- 10. the loop actually calls it -----------------------------------
    # A retire() nothing invokes is a no-op that reports success, which is the
    # defect this codebase keeps finding. So a REAL task is run through the
    # real loop, and the gotcha it disproves is one the loop had no idea was
    # there.
    live = fleet.create(home, "Wired", "proves the loop calls retire")
    with io.open(os.path.join(live, "settings.toml"), "w",
                 encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\nmax_task_retries = 0\n\n'
                '[providers.m]\ntype = "mock"\nscript = "script.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n')
    with io.open(os.path.join(live, "script.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "run_command", "args": {"cmd": "echo probe-ok"}},
                   {"tool": "finish_task", "args": {"summary": "ran it"}}], f)
    gotchas.from_failure(live, failing_task("p1", "echo something"),
                         dict(REC, cause="echo blew up once"))
    planted = gotchas.load(live)
    assert len(planted) == 1 and planted[0]["probe"] == "cmd:echo", planted

    la = loop.Agent(live)
    la.add_task("practitioner", GOAL)
    assert run_drain(live) == 0
    after = gotchas.load(live)
    assert after == [], (
        f"the loop ran a task that successfully executed `echo`, and the "
        f"gotcha claiming echo is broken is STILL BINDING: {after}. retire() "
        f"works and nothing calls it.")
    audit = gotchas.load(live, include_retired=True)
    assert len(audit) == 1 and audit[0]["retired"], audit
    logged = io.open(os.path.join(live, "logs", "agent.log"),
                     encoding="utf-8", errors="replace").read()
    assert "gotcha_retired" in logged, (
        "the retirement was silent — an operator cannot audit what they "
        "cannot see happen")
    s = gotchas.summary(live)
    assert s["total"] == 0 and s["retired"] == 1, s
    print(f"[wired] a real task through the real loop ran `echo`, and the "
          f"gotcha claiming echo was broken was withdrawn automatically, "
          f"logged as gotcha_retired, and counted in the ledger "
          f"({s['retired']} retired, {s['total']} still binding)")
    print("PASS test_gotcha_retire")


if __name__ == "__main__":
    main()
