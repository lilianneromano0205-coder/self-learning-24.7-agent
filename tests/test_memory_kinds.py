#!/usr/bin/env python3
"""Memory has KINDS, and the harness routes between them (M4).

LongMemEval-V2 lists five abilities an "experienced operator" agent needs.
Three of them are new here and each gets a mechanism:

1. environment gotchas  -- a failed task writes a scoped gotcha line, and the
   next matching task is warned before it repeats the mistake (an unrelated
   task is not)
2. workflow scope       -- a failure inside an MCP call is filed against that
   server, not the course
3. premise awareness    -- a goal whose premise this expert already retracted
   raises a warning in the window and a log line; a clean goal raises nothing
4. memory routing       -- the student stays closed-book, a practitioner sees
   everything, an owner override is honoured but may not break the exam
5. ACE curation         -- duplicate lessons merge into a curated view while
   the append-only ledger stays untouched

Run from the agent/ directory:  python tests/test_memory_kinds.py
"""

import json
import os
import sys

from common import AGENT_DIR, PY, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import commons
import context
import fleet
import gotchas
import loop
import memrouter
import premise

FAIL_GATE = f'"{PY}" -c "import sys;sys.exit(1)"'


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return rel.replace(os.sep, "/")


def main():
    home = make_sandbox("memkinds", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Kinds", "learns from its own scars")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\nmax_task_retries = 0\nmax_done_rejects = 1\n\n'
                '[providers.m]\ntype = "mock"\nscript = "script.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n')
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "finish_task", "args": {"summary": "claimed"}}] * 4, f)
    write(root, os.path.join("courses", "kafka", "mission.md"), "run kafka\n")

    # --- 1. a failure becomes a scoped, triggered gotcha
    a = loop.Agent(root)
    a.add_task("practitioner", "debug the kafka broker lag spike",
               course="kafka", done_check=FAIL_GATE)
    assert run_drain(root) == 0
    t = read_state(root)["tasks"][0]
    assert t["status"] == "failed", t["status"]
    body = open(os.path.join(root, "courses", "kafka", "gotchas.md"),
                encoding="utf-8").read()
    assert "TRIGGER:" in body and "| DO " in body and "src: task" in body, body
    assert "(F-" in body, "the gotcha cites the structured failure record"
    assert "kafka" in body and "false_success" in body, body
    entries = gotchas.load(root, "kafka")
    assert len(entries) == 1 and entries[0]["repeats"] == 1
    print("[file] a failed gated task wrote one scoped gotcha carrying its "
          "failure id, trigger words, cause and remedy")

    # --- 2. the next matching task is warned; an unrelated one is not
    hit = gotchas.matching(root, "debug the kafka broker once more", "kafka")
    assert hit and "false_success" in hit[0]["when"], hit
    assert not gotchas.matching(root, "write the quarterly budget report",
                                "kafka"), "gotchas must not fire on anything"
    a2 = loop.Agent(root)
    t2 = {"id": "t-warned", "role": "practitioner", "course": "kafka",
          "goal": "debug the kafka broker once more", "memory_files": []}
    msgs, man = context.compile(a2, t2)
    assert "GOTCHAS" in msgs[1]["content"], "the warning must be IN the window"
    assert "BINDING" in msgs[1]["content"]
    gsrc = [s for s in man["sources"] if s["name"] == "gotchas"][0]
    assert gsrc["used_tokens"] > 0, gsrc
    t3 = dict(t2, id="t-clean", goal="write the quarterly budget report")
    msgs3, man3 = context.compile(a2, t3)
    assert "GOTCHAS" not in msgs3[1]["content"]
    print("[recall] the next kafka task carried the gotcha into its window; "
          "an unrelated task did not")

    # --- 2b. a failure inside an MCP call is filed against the server
    written = gotchas.from_failure(root, {
        "id": "t-mcp", "goal": "load the customer table",
        "steps": [{"tool": "run_command", "args": '{"cmd": "python mcp.py call db '
                                                  'query --json ..."}',
                   "result": "server error"}]},
        {"failure_id": "F-777", "category": "tool_misuse",
         "cause": "db.query returned 500", "goal": "load the customer table"})
    assert written == ["gotchas/mcp-db.md"], written
    mbody = open(os.path.join(root, "gotchas", "mcp-db.md"), encoding="utf-8").read()
    assert "db.query returned 500" in mbody
    again = gotchas.from_failure(root, {"id": "t-mcp2", "goal": "load the customer table",
                                        "steps": [{"tool": "run_command",
                                                   "args": "mcp.py call db query"}]},
                                 {"failure_id": "F-777", "category": "tool_misuse",
                                  "cause": "db.query returned 500"})
    mbody2 = open(os.path.join(root, "gotchas", "mcp-db.md"), encoding="utf-8").read()
    assert mbody2.count("- [") == 1 and "x2 hit again" in mbody2, mbody2
    print("[scope] a failure inside an MCP call was filed against that server "
          "and a repeat became a count, not a second line")

    # --- 3. premise awareness
    write(root, os.path.join("courses", "kafka", "notes.md"),
          "- C-0101 brokers keep an in-sync replica set [src: docs]\n")
    write(root, os.path.join("courses", "kafka", "retractions.md"),
          "- C-0100 retracted: the redis migration was cancelled\n")
    w = premise.check(root, "continue the work from C-0100", "kafka")
    assert w and w[0]["kind"] == "retracted_atom", w
    w2 = premise.check(root, "summarize the redis migration; it was cancelled",
                       "kafka")
    assert any(x["kind"] == "retracted_topic" for x in w2), w2
    w3 = premise.check(root, "explain atom C-0999 in detail", "kafka")
    assert any(x["kind"] == "unknown_atom" for x in w3), w3
    assert premise.check(root, "explain C-0101 to a new hire", "kafka") == []
    t4 = {"id": "t-premise", "role": "practitioner", "course": "kafka",
          "goal": "continue the work from C-0100", "memory_files": []}
    msgs4, man4 = context.compile(a2, t4)
    assert "PREMISE CHECK" in msgs4[1]["content"], msgs4[1]["content"][:400]
    assert man4["premise"] and man4["premise"][0]["kind"] == "retracted_atom"
    assert "PREMISE CHECK" not in msgs3[1]["content"], "clean goals stay clean"
    log = open(os.path.join(root, "logs", "agent.log"), encoding="utf-8").read()
    assert '"premise_warning"' in log, "the owner must see it in the feed"
    print("[premise] a goal built on a retracted atom raised a warning in the "
          "window and in the feed; a clean goal raised none")

    # --- 4. the memory router
    stu = memrouter.decide({"role": "student", "goal": "sit the exam"})
    assert "commons" not in stu["kinds"] and "skills" not in stu["kinds"]
    # `self` rides along even in a closed-book exam: knowing what you have
    # NOT studied is not course material, it is what makes honest refusal
    # possible (test_awareness proves it smuggles no content).
    assert set(stu["kinds"]) == {"self", "course", "memory_files"}, stu
    pra = memrouter.decide({"role": "practitioner", "goal": "do the work"})
    assert set(pra["kinds"]) == set(memrouter.ALL_KINDS), pra
    over = memrouter.decide({"role": "practitioner", "goal": "do the work"},
                            {"agent": {"memory_router": {"practitioner": {
                                "kinds": ["course", "memory_files"]}}}})
    assert set(over["kinds"]) == {"course", "memory_files"} and \
        "override" in over["rule"], over
    cheat = memrouter.decide({"role": "student", "goal": "sit the exam"},
                             {"agent": {"memory_router": {"student": {
                                 "kinds": memrouter.ALL_KINDS}}}})
    assert "commons" not in cheat["kinds"] and "skills" not in cheat["kinds"], \
        "an override must never re-open a closed book"
    assert "refused" in cheat["why"], cheat["why"]
    team = memrouter.decide({"role": "reflector", "goal": "TEAM handoff review"})
    assert "commons" in team["kinds"], "coordination always sees the commons"
    t5 = {"id": "t-student", "role": "student", "course": "kafka",
          "goal": "debug the kafka broker once more", "memory_files": []}
    msgs5, man5 = context.compile(a2, t5)
    ex = {s["name"]: s["excluded_by_router"] for s in man5["sources"]}
    assert ex["commons"] and ex["skills"] and ex["gotchas"], ex
    assert "GOTCHAS" not in msgs5[1]["content"], "closed book stays closed"
    assert man5["router"]["rule"] == "student"
    print("[router] the student stayed closed-book even against an owner "
          "override; the practitioner kept every kind; the manifest says why")

    # --- 5. ACE-style curation
    commons.learn(home, "always run the gate before claiming a task is done",
                  "kinds")
    commons.learn(home, "Always run the gate before claiming a task is done!",
                  "other")
    commons.learn(home, "rate limit the crawler to 3 requests per second",
                  "kinds")
    ledger_before = open(os.path.join(home, "commons", "lessons.md"),
                         encoding="utf-8").read()
    rep = commons.curate(home)
    assert rep["entries"] == 3 and rep["curated"] == 2 and rep["merged"] == 1, rep
    cur = open(os.path.join(home, "commons", "lessons.curated.md"),
               encoding="utf-8").read()
    assert cur.count("- [") == 2 and "x2" in cur and "kinds, other" in cur
    assert open(os.path.join(home, "commons", "lessons.md"),
                encoding="utf-8").read() == ledger_before, \
        "curation must NEVER rewrite the append-only ledger"
    edits = [json.loads(x) for x in open(
        os.path.join(home, "commons", "edits.jsonl"), encoding="utf-8")
        if x.strip()]
    assert [e["op"] for e in edits].count("merge") == 1
    assert commons.digest(home).count("always run the gate") <= 1, \
        "the injected digest carries the curated view, not the duplicates"
    print("[curation] duplicate lessons merged into a curated view with every "
          "contributor kept, and the ledger was not rewritten")
    print("PASS test_memory_kinds")


if __name__ == "__main__":
    main()
