#!/usr/bin/env python3
"""Path containment (constitution rule 3, mechanically enforced).

File tools must refuse any path that escapes the agent root — the model gets
an ERROR result and keeps working; nothing is written or read outside.

Run from the agent/ directory:  python tests/test_paths.py
"""

import json
import os

from common import add_task, make_sandbox, read_state, run_drain

SCRIPT = [
    {"tool": "write_file", "args": {"path": "../escape.txt", "content": "leaked"}},
    {"tool": "read_file", "args": {"path": "../../../../etc/passwd"}},
    {"tool": "write_file", "args": {"path": "out/inside.txt", "content": "fine"}},
    {"tool": "finish_task", "args": {"summary": "done"}},
]


def main():
    sb = make_sandbox("paths", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    add_task(sb, "tester", "path escape attempt")
    assert run_drain(sb) == 0

    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done", f"{t['status']}: {t.get('error')}"
    assert not os.path.exists(os.path.join(os.path.dirname(sb), "escape.txt")), \
        "write escaped the agent root"
    assert os.path.exists(os.path.join(sb, "out", "inside.txt")), \
        "legitimate in-root write must still work"

    with open(os.path.join(sb, t["context_ref"]), "r", encoding="utf-8") as f:
        ctx = json.load(f)
    tool_results = [m["content"] for m in ctx if m.get("role") == "tool"]
    assert tool_results[0].startswith("ERROR:") and "escapes" in tool_results[0]
    assert tool_results[1].startswith("ERROR:") and "escapes" in tool_results[1]
    print("[paths] every escape spelling was refused with a clear ERROR the agent could recover from, and in-root writes were unaffected")
    print("PASS test_paths: escapes refused with ERROR, in-root writes unaffected, task completed")


if __name__ == "__main__":
    main()
