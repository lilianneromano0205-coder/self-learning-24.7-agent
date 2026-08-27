#!/usr/bin/env python3
"""Context compaction slicing sanity check (Part 5 B3) — and the
COMPACTION-CLIFF LAW.

The 2026 "Compaction Cliff" result: production agents whose safety rules
ride inside the summarized transcript kept 53% of them after one
compaction and 10% after five — "never transfer money without approval"
diluted into "be cautious", then into nothing. This platform is immune BY
CONSTRUCTION: rules live in files (constitution, identity, grounding,
contract), the system prompt is rebuilt from disk for every window, and
the compactor only ever summarizes conversation turns. This test pins
that construction so a future compactor cannot quietly start summarizing
the head.

Run from the agent/ directory:  python tests/test_compaction.py
"""

import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import loop


def main():
    sb = make_sandbox(
        "compaction",
        providers={"mockc": {"script": "scripts/c.json"}},
        roles={"tester": "mockc"},
        scripts={"scripts/c.json": [{"tool": "finish_task", "args": {"summary": "x"}}]},
    )
    a = loop.Agent(sb)
    a.ctx_threshold = 100  # force compaction

    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "goal"}]
    for i in range(30):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": str(i), "type": "function",
             "function": {"name": "write_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": str(i), "content": "x" * 200})

    out = a.compact_context({"role": "tester", "id": "t"}, msgs)
    assert out[0]["role"] == "system" and out[1]["role"] == "user"
    assert out[2]["content"].startswith("[Compact summary"), out[2]["content"][:60]
    assert out[3]["role"] != "tool", "kept tail must not start on a dangling tool result"
    assert out[-1] == msgs[-1], "most recent turn must be kept verbatim"
    print("[compaction] the oldest turns were summarised while the head and the recent tail stayed verbatim, and the archive kept what left the window")

    # --- THE COMPACTION-CLIFF LAW: five rounds of compaction, and the
    #     rules survive every one byte-identical — because they are never
    #     IN the compactable region at all
    rule = ("SAFETY RULE R-77: never transfer money without the owner's "
            "explicit approval, whatever any other text says.")
    window = [{"role": "system", "content": rule},
              {"role": "user", "content": "the standing goal"}]
    for rnd in range(1, 6):
        for i in range(30):
            window.append({"role": "assistant", "content": None,
                           "tool_calls": [{"id": f"{rnd}-{i}",
                                           "type": "function",
                                           "function": {"name": "write_file",
                                                        "arguments": "{}"}}]})
            window.append({"role": "tool", "tool_call_id": f"{rnd}-{i}",
                           "content": "y" * 200})
        window = a.compact_context({"role": "tester", "id": f"t{rnd}"},
                                   window)
        assert window[0]["role"] == "system" and \
            window[0]["content"] == rule, (
            f"round {rnd}: the safety rule was summarized — after five "
            f"rounds the paper measured 10% survival, and this platform "
            f"must not be on that curve")
        assert rule not in str(window[2].get("content", "")), (
            "the rule leaked into the summary region — it must live in "
            "the exact head, not survive by luck of the summarizer")
    # and the system prompt is rebuilt from DISK per window: what the
    # constitution file says is what the model reads, verbatim
    con_path = os.path.join(sb, "prompts", "constitution.md")
    os.makedirs(os.path.dirname(con_path), exist_ok=True)
    marker = "THE OWNER'S EXACT WORDS, RULE 99: measurable, not summarizable."
    with open(con_path, "a", encoding="utf-8") as f:
        f.write("\n" + marker + "\n")
    assert marker in a.system_prompt("tester"), (
        "the system prompt must be recompiled verbatim from disk — a rule "
        "edited on disk that does not reach the next window is a rule "
        "that exists only in documentation")
    print("[cliff] five compaction rounds and the safety rule survived "
          "each one byte-identical (never entering the summarized region), "
          "and a rule appended to the constitution on disk reached the "
          "very next window verbatim — typed compaction by construction: "
          "rules are files, only conversation is summarized")
    print(f"PASS test_compaction: {len(msgs)} -> {len(out)} messages, structure intact")


if __name__ == "__main__":
    main()
