#!/usr/bin/env python3
"""MODEL GATEWAY — every provider call is metered, attributed and bounded.

Manual §19: *"Model Gateway — every caller must use it for every provider
call; mandatory controls: budget; attribution; retry; routing; cost; trace;
version."*
Manual §25.8: *"Make all provider calls pass through universal
cost/attribution/budget gateway."*
Manual §15 invariants: *"attribution is per call; all calls including
compaction/replay/benchmark are metered."*

The audit found four `call_model` sites and spend recorded at exactly one of
them, so the compaction summarizer — which fires on the longest, most
expensive tasks — spent money the daily breaker never saw. Recording spend
inside `call_model` fixed the metering. This module fixes the other half the
manual asks for: **attribution per call**, not per task.

Task-level attribution credited a whole task's outcome to whichever
provider happened to serve its LAST step, so a task that failed over once
mis-credited the fallback with the entire verdict. Here every call writes its
own line — purpose, role, provider, model, tokens, cost, milliseconds — and
the task-level ledger keeps its meaning as a summary of those lines rather
than a substitute for them.

    gateway.record(root, purpose="step"|"compaction"|"replay"|"benchmark"|...,
                   role=..., provider=..., model=..., usage=..., cost=...,
                   task=..., ms=...)

`spend_today()` and `by_purpose()` read the same ledger, so "what did today
cost" and "what did compaction cost" are the same question asked twice.
"""

import json
import os
import time

LEDGER = os.path.join("logs", "model-calls.jsonl")

# every purpose a provider call can serve; an unknown one is still recorded,
# but naming them makes "which of these is eating the budget" answerable
PURPOSES = ("step", "compaction", "replay", "benchmark", "probe",
            "candidate", "judge", "research", "unknown")


def _path(root):
    return os.path.join(root, LEDGER)


def record(root, purpose="unknown", role="", provider="", model="",
           usage=None, cost=0.0, task=None, ms=0, ok=True, note=""):
    """One line per PROVIDER CALL. Never raises: metering must not be able to
    break the work it is measuring."""
    usage = usage or {}
    rec = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "purpose": purpose if purpose in PURPOSES else "unknown",
        "role": role, "provider": provider, "model": model,
        "task": task, "ms": int(ms or 0), "ok": bool(ok),
        "tokens_in": int(usage.get("prompt_tokens") or 0),
        "tokens_out": int(usage.get("completion_tokens") or 0),
        "cost_usd": round(float(cost or 0.0), 6),
    }
    if note:
        rec["note"] = note[:200]
    try:
        os.makedirs(os.path.dirname(_path(root)), exist_ok=True)
        with open(_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


def calls(root, limit=20000, since=None, task=None):
    out = []
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            for line in f.readlines()[-limit:]:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if since and r.get("at", "") < since:
                    continue
                if task and r.get("task") != task:
                    continue
                out.append(r)
    except OSError:
        pass
    return out


def _blank():
    return {"calls": 0, "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0,
            "ms": 0, "failures": 0}


def _add(acc, r):
    acc["calls"] += 1
    acc["cost_usd"] = round(acc["cost_usd"] + float(r.get("cost_usd") or 0), 6)
    acc["tokens_in"] += int(r.get("tokens_in") or 0)
    acc["tokens_out"] += int(r.get("tokens_out") or 0)
    acc["ms"] += int(r.get("ms") or 0)
    acc["failures"] += 0 if r.get("ok", True) else 1
    return acc


def by_purpose(root, since=None):
    """Where the money actually went. Compaction used to be invisible here."""
    out = {}
    for r in calls(root, since=since):
        _add(out.setdefault(r.get("purpose", "unknown"), _blank()), r)
    return out


def by_model(root, since=None):
    out = {}
    for r in calls(root, since=since):
        key = f"{r.get('provider')}:{r.get('model')}"
        _add(out.setdefault(key, _blank()), r)
    return out


def by_task(root, task):
    acc = _blank()
    for r in calls(root, task=task):
        _add(acc, r)
    return acc


def spend_today(root):
    today = time.strftime("%Y-%m-%d")
    total = 0.0
    for r in calls(root):
        if str(r.get("at", "")).startswith(today):
            total += float(r.get("cost_usd") or 0)
    return round(total, 6)


def attribution(root, task):
    """Per-call attribution for one task: which model did which part.

    The routing ledger records ONE pair per task, so a task that failed over
    mid-way credits its whole verdict to the fallback. This shows the truth.
    """
    rows = calls(root, task=task)
    per = {}
    for r in rows:
        _add(per.setdefault(f"{r.get('provider')}:{r.get('model')}", _blank()), r)
    return {"task": task, "calls": len(rows), "models": per,
            "mixed": len(per) > 1}


def summary(root, since=None):
    p, m = by_purpose(root, since), by_model(root, since)
    total = _blank()
    for acc in p.values():
        for k in total:
            total[k] = round(total[k] + acc[k], 6) if k == "cost_usd" \
                else total[k] + acc[k]
    return {"total": total, "by_purpose": p, "by_model": m,
            "spend_today_usd": spend_today(root)}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="the model gateway ledger")
    ap.add_argument("--root", default=".")
    ap.add_argument("--task", help="per-call attribution for one task")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.task:
        rep = attribution(root, a.task)
        if a.json:
            print(json.dumps(rep, indent=1))
            return
        print(f"task {rep['task']}: {rep['calls']} provider call(s)"
              + ("  MIXED MODELS" if rep["mixed"] else ""))
        for k, v in sorted(rep["models"].items()):
            print(f"  {k:<34} {v['calls']:>3} call(s)  ${v['cost_usd']:.4f}  "
                  f"{v['tokens_in']}+{v['tokens_out']} tok")
        return
    rep = summary(root)
    if a.json:
        print(json.dumps(rep, indent=1))
        return
    t = rep["total"]
    print(f"{t['calls']} provider call(s), ${t['cost_usd']:.4f}, "
          f"{t['tokens_in']}+{t['tokens_out']} tokens, "
          f"{t['failures']} failure(s)")
    print("\nby purpose (every call is metered, including compaction):")
    for k, v in sorted(rep["by_purpose"].items(), key=lambda x: -x[1]["cost_usd"]):
        print(f"  {k:<12} {v['calls']:>4} call(s)  ${v['cost_usd']:.4f}")
    print("\nby model:")
    for k, v in sorted(rep["by_model"].items(), key=lambda x: -x[1]["cost_usd"]):
        print(f"  {k:<34} {v['calls']:>4} call(s)  ${v['cost_usd']:.4f}")


if __name__ == "__main__":
    main()
