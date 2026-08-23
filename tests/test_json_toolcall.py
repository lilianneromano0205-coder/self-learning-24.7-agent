#!/usr/bin/env python3
"""Inline-JSON tool calls (the grounding-header format).

A provider that emits {"tool": "...", "args": {...}} as plain message content
— no native tool_calls — must be parsed and executed identically. This is the
path used by models without function-calling support.

Run from the agent/ directory:  python tests/test_json_toolcall.py
"""

import os

from common import add_task, make_sandbox, read_state, run_drain

SCRIPT = [
    {"tool": "write_file", "args": {"path": "out/json.txt", "content": "via inline json"}},
    {"tool": "finish_task", "args": {"summary": "json style works"}},
]


def main():
    sb = make_sandbox(
        "jsoncall",
        providers={"mockj": {"script": "scripts/j.json", "style": "json"}},
        roles={"tester": "mockj"},
        scripts={"scripts/j.json": SCRIPT},
    )
    add_task(sb, "tester", "inline json tool call test")
    rc = run_drain(sb)
    assert rc == 0

    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done", f"{t['status']}: {t.get('error')}"
    assert t["summary"] == "json style works"
    p = os.path.join(sb, "out", "json.txt")
    with open(p, "r", encoding="utf-8") as f:
        assert f.read() == "via inline json"
    print("[json-tools] a model that cannot emit native tool calls is still usable: inline JSON in the content parses and executes")
    print("PASS test_json_toolcall: content-embedded JSON tool calls parse and execute")


if __name__ == "__main__":
    main()
