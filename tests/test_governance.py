#!/usr/bin/env python3
"""Governance of the learner, and compaction as a contract.

1. SELF-MODIFICATION BOUNDARY: a charter variant can never target the
   constitution, the grounding contract, the examiner, or the student —
   refused in code for every caller (CLI and panel alike).
2. COMPACTION CONTRACT: when the window is compacted, the harness appends
   what it KNOWS mechanically — the task goal, the definition of done, every
   file written in the compacted turns — independent of the summarizer; and
   when the model's note omits required sections, the omission is named
   and logged so no guess is ever promoted to a fact.
3. SKILL TRIGGERS: a skill with a TRIGGER: line is summoned by the
   situation words, not only by its name.

Run from the agent/ directory:  python tests/test_governance.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import loop
import variants as V


def main():
    sb = make_sandbox("governance", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "x"}}]})
    # --- 1. protected charters
    for role in ("constitution", "_grounding", "examiner", "student"):
        try:
            V.spawn(sb, "evil", role, "# weakened rules\n")
            raise AssertionError(f"variant on '{role}' must be refused")
        except SystemExit as e:
            assert "protected charter" in str(e)
    assert not os.path.exists(os.path.join(sb, "variants", "evil"))
    V.spawn(sb, "fine", "practitioner", "# ROLE: practitioner — terser\n")
    print("[boundary] constitution, grounding, examiner and student charters "
          "cannot be evolved; worker charters can")

    # --- 2. compaction contract
    a = loop.Agent(sb)
    a.ctx_threshold = 100
    task = {"id": "t-compact", "role": "tester", "goal": "ship the pricing page",
            "done_check": "python check.py", "steps": []}
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "goal"}]
    for i in range(20):
        path = f"out/file{i % 3}.html"
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": str(i), "type": "function",
             "function": {"name": "write_file",
                          "arguments": json.dumps({"path": path, "content": "x"})}}]})
        msgs.append({"role": "tool", "tool_call_id": str(i), "content": "ok " * 60})
    out = a.compact_context(task, msgs)
    note = next(m["content"] for m in out if m["role"] == "user"
                and m["content"].startswith("[Compact summary"))
    assert "HARNESS FACTS" in note
    assert "Task goal: ship the pricing page" in note
    assert "Definition of done: python check.py" in note
    for p in ("out/file0.html", "out/file1.html", "out/file2.html"):
        assert p in note, f"written file {p} must be listed mechanically"
    assert "COMPACTION CONTRACT" in note and "NEXT ACTION" in note, \
        "a note without the required sections must be flagged, naming them"
    with open(os.path.join(sb, "logs", "agent.log"), encoding="utf-8") as f:
        assert '"compaction_incomplete"' in f.read()
    # the archive still holds every compacted turn verbatim
    arch = os.path.join(sb, "contexts", "t-compact.archive.jsonl")
    with open(arch, encoding="utf-8") as f:
        assert sum(1 for _ in f) >= 30
    print("[contract] compaction carried goal, gate and every written file "
          "mechanically; the model's missing sections were named and logged; "
          "verbatim archive intact")

    # --- 3. skill triggers
    os.makedirs(os.path.join(sb, "skills"), exist_ok=True)
    with open(os.path.join(sb, "skills", "pagination-guard.md"), "w",
              encoding="utf-8") as f:
        f.write("KEYWORDS: pagination\nTRIGGER: infinite scroll, load more, next page\n"
                "PREVENTS: looping on the same page forever\n"
                "verify the page identifier before paginating\n")
    got = a.matching_skills("handle the load more button on the results list")
    assert "skills/pagination-guard.md" in [g.replace("\\", "/") for g in got], got
    assert not a.matching_skills("write the quarterly report")
    print("[trigger] a skill is summoned by its TRIGGER situation words, and "
          "stays out of unrelated tasks")
    print("PASS test_governance")


if __name__ == "__main__":
    main()
