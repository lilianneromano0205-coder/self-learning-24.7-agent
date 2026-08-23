#!/usr/bin/env python3
"""Approval-gated side effects, end to end through the real loop.

A destructive MCP tool (annotated per the spec) is called by a working
agent. The harness refuses to execute it, records a pending approval, and
tells the agent to ask_human — which blocks the task. The owner grants the
approval (via the same API the panel uses); the task is answered and
retried; the SAME call now executes — exactly once, and the ground truth
(the server's own deleted.log) proves it. A denial is final: the agent is
told to find another route and the world is never touched. Read-only tools
never pause. Owner policy per server (none/destructive/effects/all) and
per-tool require/no lists are honoured. The chief ranks pending approvals
first.

Run from the agent/ directory:  python tests/test_approvals.py
"""

import json
import os
import sys

from common import AGENT_DIR, add_task, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import approvals as ap
import chief
import fleet
import loop
import mcp

PY = sys.executable
MOCK = os.path.join(AGENT_DIR, "tests", "mock_mcp_server.py")


def main():
    home = make_sandbox("approvals_home", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Records Clerk", "keeps the records straight")
    deleted_log = os.path.join(root, "deleted.log")
    with open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as f:
        f.write('[agent]\npoll_interval_seconds = 1\nmax_task_usd = 0\n'
                'reflect_after = []\nmax_task_retries = 0\n\n'
                '[providers.m]\ntype = "mock"\nscript = "script.json"\n\n'
                '[roles.default]\nprovider = "m"\nmodel = "mock"\n\n'
                '[roles.practitioner]\nprovider = "m"\nmodel = "mock"\n')
    with open(os.path.join(root, "mcp.json"), "w", encoding="utf-8") as f:
        json.dump({"servers": {"db": {"cmd": PY, "args": [MOCK],
                                      "env": {"DELETED_LOG": deleted_log}}}}, f)
    call = (f'"{PY}" "{os.path.join(AGENT_DIR, "mcp.py")}" call db delete_record '
            f'--args "{{\\"id\\": \\"rec-7\\"}}"')
    # the model: try the deletion; when told approval is required, ask_human
    # (exactly what the fenced instruction says); after the retry, delete
    # again (now granted) and finish
    script = [{"tool": "run_command", "args": {"cmd": call}},
              {"tool": "ask_human", "args": {"question": "Approve the deletion?"}},
              {"tool": "run_command", "args": {"cmd": call}},
              {"tool": "finish_task", "args": {"summary": "record deleted"}}]
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump(script, f)

    agent = loop.Agent(root)
    tid = agent.add_task("practitioner", "delete record rec-7 from the db")
    assert run_drain(root) == 0
    t = agent.find_task(tid)
    assert t["status"] == "blocked", t["status"]
    pend = ap.pending(root)
    assert len(pend) == 1 and pend[0]["tool"] == "delete_record", pend
    assert pend[0]["reason"] == "destructive tool"
    assert not os.path.exists(deleted_log), \
        "the destructive call must NOT have run before approval"
    with open(os.path.join(root, "contexts", tid + ".json"), encoding="utf-8") as f:
        ctx = " ".join(m.get("content") or "" for m in json.load(f)
                       if m.get("role") == "tool")
    assert "APPROVAL REQUIRED" in ctx and pend[0]["id"] in ctx
    assert "exit=3" in ctx, "the paused call must exit 3, not fail as a crash"
    print("[pause] destructive tool (MCP annotations) refused to run; "
          "approval recorded; agent asked the owner; task blocked; world "
          "untouched")

    # the chief puts it first
    b = chief.briefing(home)
    assert b["recommendations"][0]["verb"] == "APPROVE", b["recommendations"][:2]
    assert "delete_record" in b["recommendations"][0]["what"]
    print("[chief] the pending approval outranks everything in the briefing")

    # --- owner grants; the task is answered and retried; the call runs ONCE
    rec = ap.decide(root, pend[0]["id"], True, note="ok, it is a duplicate")
    assert rec["status"] == "granted"
    agent.answer_task(tid, f"Approval {rec['id']} granted")
    assert run_drain(root) == 0
    tasks = read_state(root)["tasks"]
    assert any(x["status"] == "done" and "rec-7" in x["goal"] for x in tasks), \
        [(x["goal"][:30], x["status"]) for x in tasks]
    with open(deleted_log, encoding="utf-8") as f:
        lines = [l for l in f.read().splitlines() if l]
    assert lines == ["rec-7"], f"the world was hit {len(lines)} times"
    print("[grant] after approval the exact call ran once; task finished")

    # decisions are final; a second grant/deny cannot flip it
    assert ap.decide(root, rec["id"], False)["status"] == "granted"

    # --- denial is final and the world stays untouched
    with open(os.path.join(root, "script.json"), "w", encoding="utf-8") as f:
        json.dump([{"tool": "run_command", "args": {"cmd": call.replace("rec-7", "rec-9")}},
                   {"tool": "finish_task", "args": {"summary": "could not"}}], f)
    tid2 = agent.add_task("practitioner", "delete record rec-9")
    env_key = None
    # pre-deny: simulate the owner denying the pending record once it appears
    os.environ.update({"AGENT_ROOT": root, "AGENT_TASK_LINEAGE": "manual-deny"})
    try:
        s = mcp.connect(root, "db", timeout=15)
        res, how = mcp.guarded_call(s, "delete_record", {"id": "rec-9"}, root=root)
        assert how == "approval_required"
        aid = ap.pending(root)[0]["id"]
        ap.decide(root, aid, False, note="no")
        res2, how2 = mcp.guarded_call(s, "delete_record", {"id": "rec-9"}, root=root)
        assert how2 == "denied" and "DENIED by the owner" in res2["content"][0]["text"]
        # read-only tools never pause; non-destructive effects pass under the
        # default policy; owner can widen to 'effects'
        r, how3 = mcp.guarded_call(s, "add", {"a": 1, "b": 2}, root=root)
        assert how3 == "live"
        r, how4 = mcp.guarded_call(s, "append_note", {"line": "x"}, root=root)
        assert how4 == "live", "non-destructive effect passes under 'destructive' policy"
        s.spec = {**s.spec, "approval": "effects"}
        r, how5 = mcp.guarded_call(s, "append_note", {"line": "y"}, root=root)
        assert how5 == "approval_required", "policy 'effects' gates every write"
        s.spec = {**s.spec, "approval": "destructive", "require_approval": ["add"]}
        r, how6 = mcp.guarded_call(s, "add", {"a": 5, "b": 5}, root=root)
        assert how6 == "approval_required", "require_approval lists win"
        s.close()
    finally:
        os.environ.pop("AGENT_ROOT", None); os.environ.pop("AGENT_TASK_LINEAGE", None)
    with open(deleted_log, encoding="utf-8") as f:
        assert f.read().splitlines() == ["rec-7"], "a denied call must never run"
    print("[policy] denial is final and untouched; read-only never pauses; "
          "'effects' and require_approval widen the gate as the owner chooses")
    print("PASS test_approvals")


if __name__ == "__main__":
    main()
