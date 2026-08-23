#!/usr/bin/env python3
"""THE MEMORY ROUTER — which kinds of memory this task is allowed to see.

The 2026 production consensus on agent memory is that no substrate wins
everywhere (Mem0, Zep/Graphiti, Letta blocks, file corpora all top different
benchmarks), so the winning move is to ROUTE between memory kinds per task
rather than to pick one and inject it always. The survey work on autonomous
agent memory (arXiv 2603.07670) frames the same thing as the read half of
the write-manage-read loop: reading everything is not "more memory", it is
noise plus a bigger bill.

Here the routing table is explicit, deterministic and inspectable — the
compiler asks first, and the answer is recorded in the context manifest, so
the owner can always see WHY a source was left out:

  student      course + handed files only        (exams are closed-book)
  examiner     course, handed files, premise, gotchas
  consultant   course, handed files, premise, gotchas
  reflector    handed files, skills, gotchas     (it studies its own run)
  ripper       handed files, gotchas, course     (mechanical ingestion)
  everyone else  every kind

Two rules protect the guarantees above it:
  * a goal that starts a PLAN cycle, a TEAM run or a JUDGE pass always gets
    the commons — coordination without shared lessons repeats fleet-wide
    mistakes;
  * the STUDENT rule may only ever REMOVE sources. An owner override cannot
    hand an examinee the notes it is being tested on.

Owner override, per role, in settings.toml:

    [agent.memory_router.practitioner]
    kinds = ["commons", "course", "memory_files", "skills"]
"""

import json
import os

ALL_KINDS = ["self", "commons", "course", "standards", "authority",
             "conflicts", "cases", "gotchas", "premise", "skills",
             "memory_files"]

# `self` is in every row on purpose: knowing what you have verified is not
# course material, it is the thing that makes an honest "I have not studied
# that" possible — including in a closed-book exam.
TABLE = {
    "student": ["self", "course", "memory_files"],
    "examiner": ["self", "course", "memory_files", "premise", "gotchas",
                 "authority", "conflicts", "cases"],
    "consultant": ["self", "course", "memory_files", "premise", "gotchas",
                   "authority", "conflicts"],
    "reflector": ["self", "memory_files", "skills", "gotchas", "cases"],
    "ripper": ["self", "memory_files", "gotchas", "course", "authority"],
}
# goal prefixes that always need the fleet's shared lessons
COMMONS_PREFIXES = ("PLAN cycle", "TEAM", "JUDGE")
CLOSED_BOOK = "student"


def decide(task, cfg=None):
    """-> {rule, kinds, excluded, why}. Never raises: the compiler must
    always get an answer, and the safe default is 'everything'."""
    task = task or {}
    role = str(task.get("role") or "").lower()
    goal = str(task.get("goal") or "")
    base = list(TABLE.get(role, ALL_KINDS))
    rule = role if role in TABLE else "default"
    why = (f"role '{role}': {', '.join(base)}" if role in TABLE
           else "no role-specific rule; every memory kind is available")

    over = (((cfg or {}).get("agent", {}) or {})
            .get("memory_router", {}) or {}).get(role, {}) or {}
    wanted = over.get("kinds")
    if isinstance(wanted, (list, tuple)) and wanted:
        picked = [k for k in wanted if k in ALL_KINDS]
        if role == CLOSED_BOOK:
            # the closed-book guarantee outranks the owner's convenience
            blocked = [k for k in picked if k not in base]
            picked = [k for k in picked if k in base]
            why = (f"owner override for '{role}', narrowed to the closed-book "
                   f"set" + (f" (refused: {', '.join(blocked)})" if blocked else ""))
        else:
            why = f"owner override [agent.memory_router.{role}]"
        rule = f"{rule}+override"
        base = picked or base

    if any(goal.startswith(p) for p in COMMONS_PREFIXES) and role != CLOSED_BOOK:
        if "commons" not in base:
            base = base + ["commons"]
            why += "; coordination goal -> the commons is forced in"
            rule += "+coordination"

    kinds = [k for k in ALL_KINDS if k in base]
    return {"rule": rule, "kinds": kinds,
            "excluded": [k for k in ALL_KINDS if k not in kinds], "why": why}


def explain(task, cfg=None):
    d = decide(task, cfg)
    lines = [f"role: {task.get('role')}  rule: {d['rule']}",
             f"why:  {d['why']}",
             f"in:   {', '.join(d['kinds']) or 'nothing'}",
             f"out:  {', '.join(d['excluded']) or 'nothing'}"]
    return "\n".join(lines)


def main():
    import argparse
    import tomllib
    ap = argparse.ArgumentParser(description="explain a memory routing decision")
    ap.add_argument("--root", default=".")
    ap.add_argument("--role", default="practitioner")
    ap.add_argument("--goal", default="do the work")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    cfg = {}
    try:
        with open(os.path.join(a.root, "settings.toml"), "rb") as f:
            cfg = tomllib.loads(f.read().decode("utf-8-sig"))
    except OSError:
        pass
    task = {"role": a.role, "goal": a.goal}
    print(json.dumps(decide(task, cfg), indent=1) if a.json
          else explain(task, cfg))


if __name__ == "__main__":
    main()
