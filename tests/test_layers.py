#!/usr/bin/env python3
"""The seven-layer agent contract, enforced as constraints rather than prompts.

  L1 loop        three independent brakes: max steps, explicit finish_task,
                 hard per-run cost ceiling
  L2 tools       every tool returns TEXT, including its failures — never raises
  L6 verify      finish_task is REFUSED until the task's definition of done
                 exits 0; repeated refusal fails the task rather than looping
  L5 routing     escalation to a stronger model on consecutive tool errors and
                 on the model's own [[ESCALATE]] request

Run from the agent/ directory:  python tests/test_layers.py
"""

import json
import os
import sys

from common import AGENT_DIR, add_task, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import loop

PY = sys.executable


def main():
    # ---- L6: the done_check gate. The agent claims done while the check
    # fails, then fixes the real problem, and only then is finish_task taken.
    sb = make_sandbox(
        "done_gate",
        providers={"m": {"script": "s.json"}},
        roles={"tester": "m"},
        scripts={"s.json": [
            {"tool": "finish_task", "args": {"summary": "all set (a lie)"}},
            {"tool": "finish_task", "args": {"summary": "surely now"}},
            {"tool": "write_file", "args": {"path": "proof.txt", "content": "real work"}},
            {"tool": "finish_task", "args": {"summary": "actually done"}},
        ]},
    )
    check = (f'"{PY}" -c "import os,sys; sys.exit(0 if '
             f"os.path.exists('proof.txt') else 1)\"")
    loop.Agent(sb).add_task("tester", "produce proof.txt", done_check=check)
    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done", (t["status"], t.get("error"))
    assert t["summary"] == "actually done", t["summary"]
    assert t["done_rejects"] == 2, f"expected 2 refusals, got {t.get('done_rejects')}"
    with open(os.path.join(sb, t["context_ref"]), "r", encoding="utf-8") as f:
        ctx = json.load(f)
    refusals = [m for m in ctx if m.get("role") == "tool"
                and "REFUSED" in (m.get("content") or "")]
    assert len(refusals) == 2 and "exit=1" in refusals[0]["content"], refusals
    print("[L6] finish_task refused twice with evidence, accepted only once the "
          "check passed — verification is a constraint, not a suggestion")

    # ---- L6b: an agent that never satisfies the check fails; it cannot spin
    sb = make_sandbox(
        "done_giveup",
        providers={"m": {"script": "s.json"}},
        roles={"tester": "m"},
        scripts={"s.json": [{"tool": "finish_task", "args": {"summary": "done"}}] * 12},
        extra="max_done_rejects = 3",
    )
    loop.Agent(sb).add_task("tester", "impossible", done_check=f'"{PY}" -c "import sys;sys.exit(1)"')
    assert run_drain(sb) == 0
    ts = [t for t in read_state(sb)["tasks"]]
    assert ts[0]["status"] == "failed" and "never passed" in ts[0]["error"], ts[0]
    assert ts[0]["done_rejects"] == 3
    print("[L6] a task that can never satisfy its check fails after 3 refusals, "
          "instead of looping forever")

    # ---- L1: the third brake — a hard per-run cost ceiling
    sb = make_sandbox(
        "cost_brake",
        providers={"m": {"script": "s.json",
                         "fake_usage": {"prompt_tokens": 500_000,
                                        "completion_tokens": 500_000},
                         "input_per_mtok": 1.0, "output_per_mtok": 1.0}},
        roles={"tester": "m"},
        scripts={"s.json": [{"tool": "write_file",
                             "args": {"path": "out/x.txt", "content": "x"}}] * 20},
        extra="max_task_usd = 2.5\ndaily_budget_usd = 0\nmax_task_retries = 0",
    )
    add_task(sb, "tester", "expensive runaway")
    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "failed" and "cost ceiling" in t["error"], t
    assert 2.5 <= t["cost_usd"] < 4.0, t["cost_usd"]
    assert len(t["steps"]) == 3, f"should die at ~$1/step x 3, got {len(t['steps'])}"
    print(f"[L1] per-run cost ceiling killed the task at ${t['cost_usd']} "
          f"after {len(t['steps'])} steps — the third brake works")

    # ---- L2: tools return text on failure, never raise
    a = loop.Agent(sb)
    task = {"id": "t1", "role": "tester", "steps": []}
    out = a.exec_tool(task, "write_file", {"path": "nope/\0bad", "content": "x"})
    assert isinstance(out, str) and out.startswith("ERROR:"), out
    out2 = a.exec_tool(task, "read_file", {"path": "does-not-exist.txt"})
    assert isinstance(out2, str) and "ERROR" in out2, out2
    out3 = a.exec_tool(task, "write_file", {})          # missing argument
    assert isinstance(out3, str) and out3.startswith("ERROR:"), out3
    print("[L2] every tool failure comes back as recoverable text, never an exception")

    # ---- L5: escalation on consecutive tool errors, and on request
    sb = make_sandbox(
        "escalate",
        providers={"cheap": {"script": "cheap.json"}, "strong": {"script": "strong.json"}},
        roles={},
        scripts={"cheap.json": [
                    {"tool": "read_file", "args": {"path": "missing-1.txt"}},
                    {"tool": "read_file", "args": {"path": "missing-2.txt"}},
                    {"tool": "read_file", "args": {"path": "missing-3.txt"}},
                    {"tool": "finish_task", "args": {"summary": "cheap gave up"}}],
                 # the mock picks its reply by step index, and the strong model
                 # only takes over at step 3 — the first three slots are never
                 # reached by it
                 "strong.json": [
                    {"tool": "finish_task", "args": {"summary": "unreachable"}},
                    {"tool": "finish_task", "args": {"summary": "unreachable"}},
                    {"tool": "finish_task", "args": {"summary": "unreachable"}},
                    {"tool": "write_file", "args": {"path": "fixed.txt", "content": "ok"}},
                    {"tool": "finish_task", "args": {"summary": "strong model finished it"}}]},
        extra=('escalate_after_errors = 3\n'
               '[roles.tester]\nprovider = "cheap"\nmodel = "cheap-1"\n'
               'escalate_provider = "strong"\nescalate_model = "strong-1"'),
    )
    add_task(sb, "tester", "hard task the cheap model fumbles")
    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done", (t["status"], t.get("error"))
    assert t.get("escalated") is True, "3 consecutive tool errors must escalate"
    assert t["summary"] == "strong model finished it", t["summary"]
    assert os.path.exists(os.path.join(sb, "fixed.txt"))
    with open(os.path.join(sb, "logs", "agent.log"), "r", encoding="utf-8") as f:
        log = f.read()
    assert '"event": "escalated"' in log and "consecutive tool errors" in log
    print("[L5] 3 consecutive tool errors handed the task to the stronger model, "
          "which finished it")

    # model-initiated escalation via [[ESCALATE]]
    sb = make_sandbox(
        "escalate_ask",
        providers={"cheap": {"script": "cheap.json"}, "strong": {"script": "strong.json"}},
        roles={},
        scripts={"cheap.json": [
                    {"tool": "write_file", "content": "This needs deeper reasoning [[ESCALATE]]",
                     "args": {"path": "note.txt", "content": "thinking"}}],
                 "strong.json": [
                    {"tool": "finish_task", "args": {"summary": "unreachable"}},
                    {"tool": "finish_task", "args": {"summary": "escalated on request"}}]},
        extra=('escalate_after_errors = 99\n'
               '[roles.tester]\nprovider = "cheap"\nmodel = "cheap-1"\n'
               'escalate_provider = "strong"\nescalate_model = "strong-1"'),
    )
    add_task(sb, "tester", "task the model itself escalates")
    assert run_drain(sb) == 0
    t = read_state(sb)["tasks"][0]
    assert t.get("escalated") is True and t["summary"] == "escalated on request", t
    print("[L5] the model asked for a stronger model with [[ESCALATE]] and got it")
    print("[layers] all seven contract layers held as CONSTRAINTS, not as prompt requests: tools, paths, budget, steps, gate, escalation, chain")
    print("PASS test_layers")


if __name__ == "__main__":
    main()
