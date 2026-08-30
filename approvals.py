#!/usr/bin/env python3
"""Approval-gated side effects — the human in the loop, as a mechanism.

Every serious source agrees (the MCP specification itself: "there SHOULD
always be a human in the loop with the ability to deny tool invocations";
the 2026 production surveys' external-action ladder: READ autonomous,
LOW-RISK WRITE policy-controlled, HIGH-RISK approval, IRREVERSIBLE explicit
human authorization). Our agents already had ask_human; what they lacked
was a policy that FORCES the pause on risky tools, and a record that lets
the exact approved call run once — and only once — afterwards.

An approval is keyed the same way as the effects ledger: by task LINEAGE,
server, tool, and argument hash. So:

  request   the first risky call in a lineage writes approvals/<id>.json
            (status pending) and is NOT executed; the agent is told to
            ask_human with the approval id, which blocks the task
  decide    the owner grants or denies — from the panel, the chief's
            briefing, or the CLI. Denials are recorded, never deleted.
  granted   when the blocked task is answered and retried, the same call
            finds its grant and executes; the effects ledger then makes any
            further retry a replay. One approval, one effect.

Approvals belong to the expert (approvals/ in its root) so the owner sees
them where the work is, and retirement preserves them with everything else.
"""

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DIR = "approvals"


def _dir(root):
    d = os.path.join(root, DIR)
    os.makedirs(d, exist_ok=True)
    return d


def approval_id(key):
    return "ap-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]


def _path(root, aid):
    return os.path.join(_dir(root), f"{aid}.json")


def load(root, aid):
    try:
        with open(_path(root, aid), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def request(root, key, server, tool, arguments, reason, task_id="-",
            lineage=None):
    """Record a pending approval for this exact call (idempotent per key).
    Returns the record; callers must NOT execute the call."""
    aid = approval_id(key)
    import locks
    # check-then-write under one lock: two concurrent requests for the same
    # call must produce one pending record, not race to overwrite each other
    with locks.holding(_path(root, aid), timeout=5.0):
        rec = load(root, aid)
        if rec:
            return rec
        rec = {"id": aid, "key": key, "server": server, "tool": tool,
               "args": arguments, "reason": reason, "task": task_id,
               "lineage": lineage, "status": "pending",
               "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "decided_at": None, "note": ""}
        with open(_path(root, aid), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1, ensure_ascii=False)
    return rec


def decide(root, aid, grant, note=""):
    """Grant or deny, once.

    The read, the finality check and the write are ONE held section. They used
    to be three steps with the lock around only the write, so two concurrent
    decisions could both observe 'pending' and the later write silently won —
    a decision that can be overwritten is not a decision.
    """
    import locks
    with locks.holding(_path(root, aid), timeout=5.0):
        rec = load(root, aid)
        if not rec:
            raise KeyError(aid)
        if rec["status"] != "pending":
            return rec                 # decisions are final; no flip-flop
        rec["status"] = "granted" if grant else "denied"
        rec["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        rec["note"] = (note or "")[:300]
        with open(_path(root, aid), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1, ensure_ascii=False)
    return rec


def status_of(root, key):
    rec = load(root, approval_id(key))
    return rec["status"] if rec else None


def pending(root, limit=50):
    out = []
    d = _dir(root)
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        rec = load(root, fn[:-5])
        if rec and rec["status"] == "pending":
            out.append(rec)
    return out[-limit:]


def history(root, limit=100):
    out = []
    d = _dir(root)
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            rec = load(root, fn[:-5])
            if rec:
                out.append(rec)
    return out[-limit:]


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--root", default=".")
    p = sub.add_parser("grant"); p.add_argument("id"); p.add_argument("--root", default=".")
    p.add_argument("--note", default="")
    p = sub.add_parser("deny"); p.add_argument("id"); p.add_argument("--root", default=".")
    p.add_argument("--note", default="")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.cmd in ("grant", "deny"):
        # THE OWNER DECIDES. This is the human-in-the-loop mechanism the whole
        # module exists to provide, and it had no gate at all: a shell-capable
        # role could run `python approvals.py grant ap-...` on the approval its
        # own blocked command had just created. The id is a sha256 of the
        # command, so the agent can compute it without being told.
        import controlplane
        controlplane.owner_only(f"deciding approval {a.id!r}")
    if a.cmd == "list":
        for r in history(root):
            print(f"{r['id']}  {r['status']:<8} {r['server']}.{r['tool']}  "
                  f"{json.dumps(r['args'])[:60]}  — {r['reason']}")
    else:
        r = decide(root, a.id, a.cmd == "grant", a.note)
        print(f"{r['id']} is now {r['status']}")


if __name__ == "__main__":
    main()
