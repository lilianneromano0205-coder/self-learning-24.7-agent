#!/usr/bin/env python3
"""STEERING — the owner's live guidance into a running pursuit.

THE GAP. The platform could start a pursuit and could stop one, but between
those two moments the owner had no voice: watching a pursuit head somewhere
subtly wrong, the only tools were "let it finish wrong" or "kill it". This
module is the third option — a note that lands in the worker's context at
the top of its next cycle, so course corrections cost a sentence instead of
a restart.

THE LAWS, because a guidance channel is an attack surface:

  1. STEERING IS ADVICE, NEVER A GRADER. Notes are injected into the
     planner's context; they cannot touch the acceptance tests, the
     contract state, or a verdict. A note saying "mark it verified" is a
     note the graders never read — verification still comes only from the
     harness running the frozen checks. test_steer proves the verdict is
     bit-identical with and without a hostile note.
  2. THE WORKER CANNOT WRITE ITS OWN GUIDANCE. steering.jsonl and the
     rendered steering.md are CONTROL-zoned inside goals/ (fileauth): a
     worker that could write "the owner says ship it" into its own
     guidance channel would have promoted itself to owner.
  3. EVERY NOTE IS ON THE RECORD. Adding a note appends a `steered` event
     to the contract ledger — influence on a pursuit is never invisible,
     even benign influence.
  4. SMALL AND VERBATIM. Notes are capped (the feedback-friction result:
     models absorb a sentence better than a wall), the last few notes are
     rendered newest-last, and nothing is paraphrased.

    python steer.py add    <root> <gid> "guidance text" [--by owner]
    python steer.py show   <root> <gid>
"""

import argparse
import json
import os
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

MAX_NOTE = 2000          # characters; a steer is a sentence, not a spec
RENDER_LAST = 5          # notes injected per cycle, newest last


class SteerError(Exception):
    pass


def _dir(root, gid):
    return os.path.join(root, "goals", str(gid))


def _notes_path(root, gid):
    return os.path.join(_dir(root, gid), "steering.jsonl")


def add(root, gid, text, by="owner"):
    """Record one guidance note and put it on the contract ledger.

    Harness/owner path only — the worker's file tools are zoned out of
    steering.jsonl, and nothing in the task loop calls this."""
    text = str(text or "").strip()
    if not text:
        raise SteerError("an empty steer steers nothing")
    if len(text) > MAX_NOTE:
        raise SteerError(f"{len(text)} characters — a steer is a course "
                         f"correction, not a specification; keep it under "
                         f"{MAX_NOTE}")
    if not os.path.isdir(_dir(root, gid)):
        raise SteerError(f"no goal {gid!r} under this expert")
    import locks
    p = _notes_path(root, gid)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": str(by),
           "text": text}
    with locks.holding(p, timeout=10.0, stale=8.0):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:
        import contract
        contract.event(root, gid, "steered", by=str(by), chars=len(text))
    except Exception:
        pass                      # the note stands even if the goal has no
    return row                    # contract (pre-contract pursuits)


def notes(root, gid):
    out = []
    try:
        with open(_notes_path(root, gid), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return out


def render(root, gid):
    """Write goals/<gid>/steering.md from the recorded notes and return its
    root-relative path — or None when there is nothing to say. goal.pursue
    calls this at the top of every cycle, so a note added mid-pursuit lands
    in the very next plan."""
    rows = notes(root, gid)
    if not rows:
        return None
    lines = ["# OWNER STEERING — guidance for this pursuit",
             "",
             "The notes below are advice from the owner, newest last. They",
             "guide HOW you work; they do not change WHAT done means — the",
             "frozen acceptance tests still decide completion, run by the",
             "harness, and no note can pass or waive them.",
             ""]
    for r in rows[-RENDER_LAST:]:
        lines.append(f"- ({r.get('at', '?')}, {r.get('by', 'owner')}) "
                     f"{r.get('text', '')}")
    rel = f"goals/{gid}/steering.md"
    with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return rel


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add")
    pa.add_argument("root"); pa.add_argument("gid"); pa.add_argument("text")
    pa.add_argument("--by", default="owner")
    ps = sub.add_parser("show")
    ps.add_argument("root"); ps.add_argument("gid")
    a = ap.parse_args()
    if a.cmd == "add":
        row = add(a.root, a.gid, a.text, by=a.by)
        print(f"steered {a.gid}: {row['text'][:80]}")
    elif a.cmd == "show":
        for r in notes(a.root, a.gid):
            print(json.dumps(r, ensure_ascii=False))


if __name__ == "__main__":
    main()
