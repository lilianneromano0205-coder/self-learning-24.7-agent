#!/usr/bin/env python3
"""The three-tier memory contract (MemGPT/Letta pattern): context that leaves
the working window is NEVER lost — it is archived verbatim and searchable.

1. Compaction archives every removed turn to contexts/<task>.archive.jsonl
   before summarizing (tier 2 compresses; tier 3 keeps the original).
2. recall.py finds a fact wherever it lives — notes, skills, or an archived
   turn — ranks the better match first, and handles accented queries.

Run from the agent/ directory:  python tests/test_recall.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import loop
import recall


def main():
    sb = make_sandbox("recall", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "x"}}]})
    a = loop.Agent(sb)
    a.ctx_threshold = 100  # force compaction

    # --- 1. compaction archives, never destroys
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "goal"}]
    for i in range(30):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": str(i), "type": "function",
             "function": {"name": "write_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": str(i),
                     "content": f"turn-{i}: the secret constant is 42 " + "x" * 150})
    task = {"role": "tester", "id": "arch1"}
    out = a.compact_context(task, msgs)
    assert len(out) < len(msgs), "compaction must have removed turns"
    archive = os.path.join(sb, "contexts", "arch1.archive.jsonl")
    assert os.path.exists(archive), "removed turns must be archived"
    with open(archive, "r", encoding="utf-8") as f:
        archived = [json.loads(l) for l in f]
    removed = len(msgs) - len(out) + 1   # +1 for the inserted summary message
    assert len(archived) == removed, (len(archived), removed)
    assert any("turn-3: the secret constant is 42" in (m.get("content") or "")
               for m in archived), "archived turns must be VERBATIM"
    print(f"[archive] compaction removed {removed} turns from the window; "
          f"all {len(archived)} archived verbatim — context is never lost")

    # --- 2. recall searches the whole mind and ranks sensibly
    def write(rel, text):
        p = os.path.join(sb, rel)
        os.makedirs(os.path.dirname(p) or sb, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    write("courses/net/lessons/01/notes.md",
          "# L01\n- C-0101 Exponential backoff doubles the delay per retry "
          "[src: transcript 00:01]\n- P-0102 unrelated point about logging\n")
    write("skills/retry-client.md",
          "KEYWORDS: retry\nPitfall: exponential backoff needs jitter too\n")
    write("courses/net/retractions.md", "- G-001 retracted: nothing relevant\n")

    hits = recall.search(sb, "exponential backoff delay")
    assert hits, "recall must find the fact"
    top_loc = hits[0][1]
    assert "notes.md" in top_loc, \
        f"the line containing ALL terms must rank first, got {top_loc}"
    locs = " ".join(h[1] for h in hits)
    assert "skills/retry-client.md" in locs, "skills are part of the mind"
    assert any("arch1.archive.jsonl" in h[1] for h in
               recall.search(sb, "secret constant 42")), \
        "archived turns must be recallable — that's the never-lose guarantee"

    # accented content is findable (the user's material is French)
    write("courses/eco/lessons/01/notes.md",
          "- C-0201 Le taux d'actualisation détermine la valeur présente "
          "[src: leçon 00:02]\n")
    assert recall.search(sb, "actualisation présente"), \
        "accented queries must match accented notes"
    print("[recall] one query reaches notes, skills, AND archived turns; "
          "all-term lines outrank partials; French text findable")
    print("PASS test_recall")


if __name__ == "__main__":
    main()
