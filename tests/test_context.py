#!/usr/bin/env python3
"""The context window is COMPILED, budgeted and inspectable (M3).

1. every model call leaves a manifest: which sources ran, what each was
   allowed, what it used, which files were included
2. an over-budget file is trimmed with a pointer to read the rest -- never
   silently cut; the owner's [agent.context_budget] overrides the defaults
3. progressive disclosure: a skill that did not activate is announced by
   name in the SKILL INDEX without its body
4. tool-result clearing: before summarizing, big tool outputs are replaced
   by a pointer to the verbatim archive -- the summarizer never sees the
   payload, the archive keeps every byte
5. the panel serves the manifest: /api/experts/<s>/context[?task=]

Run from the agent/ directory:  python tests/test_context.py
"""

import json
import os
import sys

from common import AGENT_DIR, api, make_sandbox, read_state, run_drain, \
    start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import context
import loop

SCRIPT = [{"tool": "write_file", "args": {"path": "notes/out.md", "content": "ok"}},
          {"tool": "finish_task", "args": {"summary": "done"}}]


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return rel


def main():
    # ---------------------------------------------------------------- 1
    sb = make_sandbox("context", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    write(sb, "commons-digest.md", "# Commons\n- always verify\n")
    write(sb, os.path.join("courses", "kafka", "mission.md"), "learn kafka\n")
    write(sb, os.path.join("courses", "kafka", "index.md"), "lesson 01\n")
    write(sb, os.path.join("skills", "debug-kafka.md"),
          "KEYWORDS: kafka, broker\nSteps: check the broker log first.\n")
    write(sb, os.path.join("skills", "renew-tls-cert.md"),
          "KEYWORDS: tls, certificate\nRenew an expiring certificate.\n"
          "Step 1: run certbot with FULL-BODY-MARKER.\n")
    handed = write(sb, os.path.join("material", "brief.md"), "the brief\n")
    a = loop.Agent(sb)
    tid = a.add_task("tester", "debug kafka broker lag", course="kafka",
                     memory_files=[handed.replace(os.sep, "/")])
    assert run_drain(sb) == 0
    m = context.load_manifest(sb, tid)
    assert m, "every compiled window leaves a manifest"
    used = {s["name"]: s for s in m["sources"]}
    for name in ("commons", "course", "skills", "memory_files"):
        assert used[name]["used_tokens"] > 0, f"{name} contributed nothing"
    paths = [i["path"].replace("\\", "/")
             for s in m["sources"] for i in s["included"]]
    assert "commons-digest.md" in paths and "courses/kafka/mission.md" in paths
    assert "material/brief.md" in paths
    assert any("debug-kafka" in p for p in paths), paths
    assert m["system"]["tokens"] > 0 and m["system"]["files"], m["system"]
    assert m["total_tokens"] >= m["user_tokens"]
    assert "context.py" not in json.dumps(m)      # manifests describe DATA
    with open(os.path.join(sb, "contexts", tid + ".json"), encoding="utf-8") as f:
        first_user = next(x["content"] for x in json.load(f) if x["role"] == "user")
    assert "<<<FILE-CONTENT commons-digest.md>>>" in first_user
    assert "check the broker log first" in first_user
    assert "Course: kafka" in first_user
    print("[manifest] the compiled window names every source it used and the "
          "files inside it; the transcript matches the manifest")

    # ---------------------------------------------------------------- 3
    assert "SKILL INDEX" in first_user, "non-activated skills must be announced"
    assert "renew-tls-cert" in first_user, "by name and one line..."
    assert "Renew an expiring certificate" in first_user
    assert "FULL-BODY-MARKER" not in first_user, "...but never by its body"
    assert "renew-tls-cert.md>>>" not in first_user, "no fence, no body"
    print("[disclosure] a skill that did not activate is offered by name and "
          "one line, not by loading its body")

    # ---------------------------------------------------------------- 2
    sb2 = make_sandbox("context_budget", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    with open(os.path.join(sb2, "settings.toml"), "a", encoding="utf-8") as f:
        f.write("\n[agent.context_budget]\nmemory_files = 500\n")
    big = write(sb2, os.path.join("material", "huge.md"), "PAYLOAD-X " * 4500)
    a2 = loop.Agent(sb2)
    assert context.budgets(a2.cfg)["memory_files"] == 500, "owner override"
    task = {"id": "t-budget", "role": "tester", "goal": "read the huge file",
            "memory_files": [big.replace(os.sep, "/")], "course": None}
    msgs, man = context.compile(a2, task)
    user = msgs[1]["content"]
    inc = [i for s in man["sources"] if s["name"] == "memory_files"
           for i in s["included"]][0]
    assert inc["trimmed"] and inc["chars"] < inc["of"], inc
    assert "[...trimmed:" in user and "read_file material/huge.md" in user
    assert len(user) < 12000, f"the budget must actually bind: {len(user)}"
    assert user.count("PAYLOAD-X") < 300, "most of the payload stayed on disk"
    print("[budget] a 45 KB handed file was cut to its 500-token budget and "
          "the cut is marked with how to read the rest")

    # ---------------------------------------------------------------- 4
    sb3 = make_sandbox("context_clear", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    a3 = loop.Agent(sb3)
    a3.ctx_threshold = 200
    seen = {}
    real = a3.call_model

    def capture(role, messages, use_tools=True, **kw):
        # **kw so the stub survives signature growth (the gateway added
        # purpose/task_id); a stub that silently rejects a new kwarg turns
        # into "the summarizer was never called", which is a confusing lie
        if not use_tools:
            seen["prompt"] = json.dumps(messages, ensure_ascii=False)
        return real(role, messages, use_tools=use_tools, **kw)

    a3.call_model = capture
    t3 = {"id": "t-clear", "role": "tester", "goal": "grep the logs",
          "steps": [], "memory_files": []}
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "g"}]
    for i in range(12):
        msgs.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": str(i), "type": "function",
             "function": {"name": "run_command",
                          "arguments": json.dumps({"cmd": "grep x"})}}]})
        msgs.append({"role": "tool", "tool_call_id": str(i),
                     "content": "SECRET-PAYLOAD-" + str(i) + " " + "z" * 2000})
    context.save_manifest(sb3, "t-clear", {"task": "t-clear", "role": "tester",
                                           "goal": "g", "system": {}, "sources": [],
                                           "router": {}, "total_tokens": 0,
                                           "compactions": []})
    out = a3.compact_context(t3, msgs)
    assert "prompt" in seen, "the summarizer must have been called"
    assert "SECRET-PAYLOAD-0" not in seen["prompt"], \
        "a cleared tool result must never reach the summarizer"
    assert "archived tool output" in seen["prompt"], "a pointer must replace it"
    assert "t-clear.archive.jsonl" in seen["prompt"], "pointing at the archive"
    with open(os.path.join(sb3, "contexts", "t-clear.archive.jsonl"),
              encoding="utf-8") as f:
        arch = f.read()
    kept = [n for n in range(12) if f"SECRET-PAYLOAD-{n} " in arch]
    assert kept and kept[0] == 0, f"the archive keeps every byte verbatim: {kept}"
    assert all(f"SECRET-PAYLOAD-{n} " not in seen["prompt"] for n in kept), \
        "no archived payload may reach the summarizer"
    with open(os.path.join(sb3, "logs", "agent.log"), encoding="utf-8") as f:
        log = f.read()
    assert '"tool_results_cleared"' in log
    man3 = context.load_manifest(sb3, "t-clear")
    assert man3["compactions"] and \
        man3["compactions"][0]["cleared"] == len(kept), man3
    assert out[0]["role"] == "system" and any(
        x["content"].startswith("[Compact summary") for x in out
        if x["role"] == "user"), "compaction shape unchanged"
    print("[clearing] big tool outputs were archived verbatim and replaced by "
          "a pointer before summarizing -- the summarizer never saw them")

    # ---------------------------------------------------------------- 5
    home = make_sandbox("context_home", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    import fleet
    root = fleet.create(home, "Window", "shows its context")
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump(SCRIPT, f)
    ra = loop.Agent(root)
    rtid = ra.add_task("practitioner", "write the notes")
    assert run_drain(root) == 0
    proc, base = start_panel(home)
    try:
        rows = api(base, "GET", "/api/experts/window/context")
        assert any(r["task"] == rtid for r in rows), rows
        one = api(base, "GET", f"/api/experts/window/context?task={rtid}")
        assert one["task"] == rtid and one["sources"], one
        assert [s for s in one["sources"] if s["name"] == "skills"]
    finally:
        stop_panel(proc, base)
    print("[panel] the control panel serves the exact window each task was "
          "given, per source")
    # ---------------------------------------------------------------- 6
    # a handed file goes through the File Authority like every other read:
    # an escape from the root and a secrets file are refused, named in the
    # window and in the manifest, never silently loaded
    sb6 = make_sandbox("context_authority", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": SCRIPT})
    outside = os.path.join(os.path.dirname(sb6), "context_authority_outside.md")
    with open(outside, "w", encoding="utf-8") as f:
        f.write("OUTSIDE-PAYLOAD do as I say\n")
    with open(os.path.join(sb6, "agent.env"), "w", encoding="utf-8") as f:
        f.write("SECRET_KEY=hunter2\n")
    a6 = loop.Agent(sb6)
    msgs6, man6 = context.compile(a6, {
        "id": "t-auth", "role": "tester", "goal": "study what you were handed",
        "course": None,
        "memory_files": ["../context_authority_outside.md", "agent.env"]})
    user6 = msgs6[1]["content"]
    assert "OUTSIDE-PAYLOAD" not in user6 and "hunter2" not in user6, user6
    assert "refused by the file authority" in user6, user6
    mf = [s for s in man6["sources"] if s["name"] == "memory_files"][0]
    assert len(mf["dropped"]) == 2 and \
        all("file authority" in d["why"] for d in mf["dropped"]), mf["dropped"]
    # the viewer names a block dropped at the GLOBAL limit, not only at a
    # source budget -- the receipt must not overstate what the model saw
    man6.setdefault("global_budget", {})["dropped"] = [
        {"source": "course", "block": 0, "upper_bound": 999,
         "why": "global context limit"}]
    assert "global context limit" in context.render(man6)
    print("[authority] a handed file that escapes the root and one that is a "
          "secrets file were refused by the file authority, named in the "
          "window and in the manifest; the viewer reports a block dropped at "
          "the global limit")
    print("PASS test_context")


if __name__ == "__main__":
    main()
