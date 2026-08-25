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

    # ---- PARALLEL tool calls: every id must get an answer ----------------
    # Every OpenAI-compatible provider can return several tool calls in one
    # message — that is what parallel tool use IS. The loop handled
    # tool_calls[0] while appending the assistant message with ALL of them, so
    # the extra ids got no `tool` response. Two failures at once: the work was
    # silently dropped, and the transcript became invalid, because the
    # protocol requires one `tool` message per tool_call_id. The next request
    # then carries orphaned ids and providers answer 400 — a failure that
    # surfaces far from its cause and reads like provider weather.
    #
    # The mock could only ever emit ONE call, so this case was untestable and
    # therefore untested. A harness that cannot express what real providers do
    # will certify a loop that cannot survive them.
    import json as _json
    home2 = make_sandbox(
        "json-parallel", providers={"m": {"script": "s.json"}},
        roles={"practitioner": "m"},
        scripts={"s.json": [
            {"tools": [
                {"tool": "write_file", "args": {"path": "out/a.md", "content": "A"}},
                {"tool": "write_file", "args": {"path": "out/b.md", "content": "B"}},
                {"tool": "write_file", "args": {"path": "out/c.md", "content": "C"}}]},
            {"tool": "finish_task", "args": {"summary": "done"}}]})
    add_task(home2, "practitioner", "write three files")
    run_drain(home2, timeout=180)

    # add_task does not hand back an id, so read whichever transcript the run
    # produced — there is exactly one task in this sandbox
    cdir = os.path.join(home2, "contexts")
    files = [n for n in os.listdir(cdir)
             if n.endswith(".json") and not n.endswith(".compile.json")]
    assert files, "the run produced no transcript"
    with open(os.path.join(cdir, files[0]), encoding="utf-8") as f:
        ctx = _json.load(f)
    msgs = ctx if isinstance(ctx, list) else ctx.get("messages", [])
    asked = {c.get("id") for m in msgs for c in (m.get("tool_calls") or [])}
    answered = {m.get("tool_call_id") for m in msgs if m.get("role") == "tool"}
    assert asked, "the parallel-call fixture produced no tool calls at all"
    orphans = asked - answered
    assert not orphans, (
        f"{len(orphans)} tool_call_id(s) got no response: {sorted(orphans)}. "
        f"The protocol requires one `tool` message per id — a transcript with "
        f"an orphan makes the NEXT provider request a 400, and the work in "
        f"those calls vanished with nothing recording that it had.")
    # and the agent was TOLD, rather than left to wonder where the work went
    told = [m for m in msgs if m.get("role") == "tool"
            and "NOT RUN" in str(m.get("content", ""))]
    assert len(told) >= 2, (
        "the un-run calls were answered but not explained; an agent that "
        "cannot tell 'done' from 'silently skipped' will not re-issue them")
    print(f"[parallel-tools] a single message carrying 3 tool calls left "
          f"0 orphaned ids of {len(asked)}: the first ran, the other "
          f"{len(told)} were answered with NOT RUN and asked for again, so "
          f"the transcript stays valid and no work disappears")

    print("PASS test_json_toolcall: content-embedded JSON tool calls parse and execute")


if __name__ == "__main__":
    main()
