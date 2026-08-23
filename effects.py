#!/usr/bin/env python3
"""Effects ledger — exactly-once side effects across retries.

The harness retries failed tasks with a fresh context. That is right for
pure work and DANGEROUS for side effects: a task that sent an email through
an MCP tool, then failed its gate for an unrelated reason, would send the
email again on retry. Every 2026 agent survey says the same thing: "never
assume a retry is harmless — make external actions idempotent with
operation keys." This ledger is that key.

  key = (task lineage, server, tool, sha256(arguments))

The lineage is the ORIGINAL task id, shared by every retry of it. When a
tool call with an identical key was already performed inside the lineage,
the recorded result is replayed instead of re-executing — the agent still
gets the answer it needs, the world is not hit twice. Replays are labelled
so the agent knows; a caller can force a fresh call when the tool is known
to be pure (reads) and staleness matters.

The ledger is append-only JSONL under logs/effects.jsonl — an audit trail
of every external effect the agent ever caused, by task, by tool.
"""

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LEDGER = os.path.join("logs", "effects.jsonl")


def key_of(lineage, server, tool, arguments):
    blob = json.dumps(arguments or {}, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
    return f"{lineage}|{server}|{tool}|{h}"


def _path(root):
    return os.path.join(root, LEDGER)


def lookup(root, key):
    """The recorded result for this key inside this lineage, or None."""
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            hit = None
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("key") == key and rec.get("status") == "done":
                    hit = rec              # last wins
            return hit
    except OSError:
        return None


def begin(root, key, task_id, server, tool, arguments):
    """WRITE-AHEAD: record that we are ABOUT to hit the world.

    `call -> record` left a window: a crash between the two meant the effect
    had happened and nothing knew, so the next run repeated it. That made the
    guarantee at-least-once while the docs said exactly-once. An intent line
    written first closes it — after a crash the ledger still says "this call
    was started and never finished", which is the truth a retry needs.
    """
    os.makedirs(os.path.dirname(_path(root)), exist_ok=True)
    import locks
    rec = {"key": key, "task": task_id, "server": server, "tool": tool,
           "args": arguments, "result": None, "status": "started",
           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with locks.holding(_path(root), timeout=5.0):
        with open(_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def unfinished(root, key):
    """The last line for this key, when it says 'started' and nothing
    resolved it: an effect that may or may not have reached the world. The
    caller must ask a human rather than guess."""
    last = None
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("key") == key:
                    last = rec
    except OSError:
        return None
    return last if (last or {}).get("status") == "started" else None


def record(root, key, task_id, server, tool, arguments, result,
           is_error=False):
    os.makedirs(os.path.dirname(_path(root)), exist_ok=True)
    import locks
    rec = {"key": key, "task": task_id, "server": server, "tool": tool,
           "args": arguments, "result": result,
           "status": "error" if is_error else "done",
           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with locks.holding(_path(root), timeout=5.0):
        with open(_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def history(root, lineage=None, limit=200):
    """ONE entry per effect, latest state wins.

    The file is a write-ahead log — `started` then `done`/`error` — so the
    raw lines are bookkeeping, not events. Collapsing by key means the ledger
    still reads as "the external things this agent did", while a lone
    `started` line survives as exactly what it is: an effect whose outcome
    was never recorded.
    """
    seen = {}
    order = []
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if lineage and not rec.get("key", "").startswith(lineage + "|"):
                    continue
                k = rec.get("key")
                if k not in seen:
                    order.append(k)
                seen[k] = rec              # last state for this effect
    except OSError:
        pass
    return [seen[k] for k in order][-limit:]


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--lineage")
    a = ap.parse_args()
    for r in history(os.path.abspath(a.root), a.lineage):
        print(f"{r['at']}  {r['status']:<5} {r['server']}.{r['tool']}  "
              f"task={r['task']}  {json.dumps(r['args'])[:60]}")
