#!/usr/bin/env python3
"""The memory institution: the categories that outlive models and agents.

1. FAILURES are structured and self-classifying: the harness's own error text
   determines the category (no model guesses), identical failures increment a
   recurrence count instead of duplicating, and the record survives the fix.
2. COMPETENCE is earned from verified outcomes, never self-reported: gated
   work counts double, tiny samples are labelled as such, and 'who should do
   this' is answerable from evidence.
3. RETIREMENT preserves everything — a retired agent's whole world stays
   queryable and restorable; only an explicit purge destroys it.
4. THE MAP indexes living and retired agents together.
5. SEARCH is hybrid: structured filters first, ranked text second.
6. The loop files all of this automatically when a task ends.

Run from the agent/ directory:  python tests/test_memory.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet
import loop
import memory

PY = sys.executable


def main():
    home = make_sandbox("memory", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})

    # --- 1. classification is deterministic, from the harness's own errors
    cases = {
        "done_check never passed after 6 attempts": "false_success",
        "repetition loop: identical write_file call 5 times": "planning",
        "cost ceiling reached: $2.1 spent": "budget",
        "ERROR: path escapes the agent root: ../x": "security",
        "malformed tool call: unknown tool: summon": "model_limitation",
        "All providers failed. Last error: HTTP 503": "infrastructure",
        "max steps ceiling (150) reached": "planning",
        "something nobody anticipated": "unknown",
    }
    for text, expect in cases.items():
        got = memory.classify(text)
        assert got == expect, f"{text!r} -> {got}, expected {expect}"
    print(f"[classify] {len(cases)} harness errors mapped to fixed categories "
          f"deterministically — no model asked to guess why it failed")

    # --- failures: structured, deduplicated by signature, recurrence counted
    t = {"id": "t1", "role": "practitioner", "course": "seo",
         "goal": "rebuild the pricing page",
         "error": "done_check never passed after 6 attempts", "cost_usd": 0.4}
    r1 = memory.record_failure(home, "page-surgeon", t)
    assert r1["category"] == "false_success" and r1["recurrence"] == 1
    r2 = memory.record_failure(home, "page-surgeon", t)
    assert r2["failure_id"] == r1["failure_id"] and r2["recurrence"] == 2, r2
    r3 = memory.record_failure(home, "other-agent", t)
    assert r3["failure_id"] != r1["failure_id"], \
        "a different agent hitting it is a different record"
    memory.record_failure(home, "page-surgeon",
                          {"id": "t9", "error": "cost ceiling reached: $3"})
    s = memory.failure_summary(home, "page-surgeon")
    assert s["by_category"]["false_success"] == 2 and s["by_category"]["budget"] == 1
    assert s["most_recurrent"][0]["recurrence"] == 2
    only_budget = memory.failures(home, category="budget")
    assert all(f["category"] == "budget" for f in only_budget) and only_budget
    print("[failures] structured records, deduplicated by signature with "
          "recurrence counts, filterable by agent and category")

    # --- 2. competence is earned, not declared
    for i in range(6):
        memory.record_outcome(home, "page-surgeon", "seo", success=True,
                              verified=True, task_id=f"v{i}")
    memory.record_outcome(home, "page-surgeon", "seo", success=False,
                          verified=True, task_id="v6")
    memory.record_outcome(home, "page-surgeon", "copywriting", success=True,
                          verified=False, task_id="c1")
    c = memory.competence(home)["page-surgeon"]
    assert c["seo"]["attempts"] == 7 and c["seo"]["verified_attempts"] == 7
    assert 0.8 <= c["seo"]["score"] <= 0.9, c["seo"]
    assert c["seo"]["claim"] == "demonstrated" and c["seo"]["confidence"] == "low"
    assert c["copywriting"]["claim"] == "insufficient evidence", \
        "one success is never mastery"
    memory.record_outcome(home, "rival", "seo", success=True, verified=True)
    memory.record_outcome(home, "rival", "seo", success=False, verified=True)
    memory.record_outcome(home, "rival", "seo", success=False, verified=True)
    ranked = memory.best_for(home, "seo")
    assert ranked[0]["expert"] == "page-surgeon", ranked
    assert all(r["attempts"] >= 3 for r in ranked), "thin records are excluded"
    print("[competence] computed from verified outcomes (gated work counts "
          "double); small samples labelled; routing answerable from evidence")

    # --- 3. retirement preserves an entire world
    root = fleet.create(home, "Old Timer", "the first specialist")
    os.makedirs(os.path.join(root, "courses", "history", "lessons", "01"),
                exist_ok=True)
    with open(os.path.join(root, "courses/history/lessons/01/notes.md"), "w",
              encoding="utf-8") as f:
        f.write("- C-0101 what we learned in the beginning [src: t 00:01]\n")
    memory.record_outcome(home, "old-timer", "history", True, verified=True)
    man = memory.retire(home, "old-timer", reason="superseded by v2")
    assert not os.path.exists(os.path.join(home, "experts", "old-timer"))
    kept = os.path.join(home, "retired", "old-timer")
    assert os.path.exists(os.path.join(kept, "courses/history/lessons/01/notes.md")), \
        "a retired agent keeps its entire memory"
    assert man["reason"] == "superseded by v2" and man["courses"] == ["history"]
    assert "history" in man["competence"], "its record retires with it"
    listed = {r["expert"] for r in memory.retired(home)}
    assert "old-timer" in listed
    back = memory.restore(home, "old-timer")
    assert os.path.exists(os.path.join(back, "courses/history/lessons/01/notes.md"))
    assert "old-timer" in {e["name"] for e in fleet.list_experts(home)}
    print("[retired] retirement moves a whole world aside intact — queryable, "
          "listed, and restorable years later")

    # deletion preserves unless explicitly purged
    fleet.create(home, "Doomed One", "x")
    res = fleet.delete_expert(home, "doomed-one", reason="test")
    assert res.get("expert") == "doomed-one"
    assert os.path.isdir(os.path.join(home, "retired", "doomed-one")), \
        "default deletion must PRESERVE"
    fleet.create(home, "Truly Gone", "x")
    res = fleet.delete_expert(home, "truly-gone", purge=True)
    assert "purged" in res and not os.path.isdir(
        os.path.join(home, "retired", "truly-gone"))
    print("[preserve] delete retires by default; only an explicit purge destroys")

    # --- 4 & 5. the map, and hybrid search
    m = memory.fleet_map(home)
    names = {a["expert"] for a in m["active"]} | {a["expert"] for a in m["retired"]}
    assert "old-timer" in names and "doomed-one" in names
    assert m["totals"]["failures"] >= 3
    hits = memory.search(home, "pricing page", kind="failures")
    assert hits and hits[0]["kind"] == "failure", hits
    assert all(h["kind"] == "failure" for h in hits), "the kind filter must hold"
    scoped = memory.search(home, "pricing page", kind="failures",
                           expert="other-agent")
    assert scoped and all(h["expert"] == "other-agent" for h in scoped), \
        "filtering by agent must happen BEFORE ranking"
    print("[map+search] one index over living and retired agents; filters "
          "applied before ranking, so scopes stay clean")

    # --- 6. the loop files memory by itself
    sb2 = make_sandbox("memory_loop", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": []})
    exp = fleet.create(sb2, "Auto Filer", "records its own history")
    with open(os.path.join(exp, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\nsandbox = "host"\nallow_unsafe_host = true\n'
                'poll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\nmax_done_rejects = 2\n\n'
                '[providers.m]\ntype = "mock"\nscript = "s.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n\n'
                '[roles.practitioner]\nprovider = "m"\nmodel = "mock"\n')
    with open(os.path.join(exp, "s.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "write_file", "args": {"path": "out/a.txt",
                                                   "content": "x"}},
                   {"tool": "finish_task", "args": {"summary": "ok"}}], f)
    a = loop.Agent(exp)
    a.add_task("practitioner", "a task that succeeds", course="ops",
               done_check=f'"{PY}" -c "import sys;sys.exit(0)"')
    a.add_task("practitioner", "a task that cannot finish", course="ops",
               done_check=f'"{PY}" -c "import sys;sys.exit(1)"')
    assert run_drain(exp) == 0
    comp = memory.competence(sb2).get("auto-filer", {})
    assert comp.get("ops", {}).get("attempts") == 2, \
        f"one success + one FINALLY-failed task = 2 outcomes, not one per " \
        f"retry attempt: {comp}"
    assert comp["ops"]["successes"] == 1
    fails = memory.failures(sb2, expert="auto-filer")
    assert fails and fails[0]["category"] == "false_success", fails[:1]
    assert fails[0]["goal"].startswith("a task that cannot finish")
    assert fails[0]["recurrence"] >= 3, \
        "every retry attempt is still recorded as a failure occurrence"
    print("[automatic] finishing a task files its own competence outcome and, "
          "on failure, a categorized failure record — retries count as "
          "occurrences but never as extra competence attempts")
    print("PASS test_memory")


if __name__ == "__main__":
    main()
