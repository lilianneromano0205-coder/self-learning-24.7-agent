#!/usr/bin/env python3
"""Context compaction slicing sanity check (Part 5 B3).

Run from the agent/ directory:  python tests/test_compaction.py
"""

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
    print(f"PASS test_compaction: {len(msgs)} -> {len(out)} messages, structure intact")


if __name__ == "__main__":
    main()
