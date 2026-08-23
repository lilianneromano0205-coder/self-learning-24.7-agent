#!/usr/bin/env python3
"""Trajectory replay — measure a model (or charter) against recorded
decisions BEFORE trusting it with live work.

The 2026 evaluation consensus: a mature harness runs four loops — offline
regression, REPLAY OF PRODUCTION TRACES, adversarial tests, and online
experiments. This is the replay loop. Every task the fleet ever ran left a
verbatim transcript (contexts/<id>.json). Replay feeds the recorded context
up to each decision point to the CURRENTLY wired model and compares what it
would do with what was done:

  agreement   same tool chosen with equivalent arguments
  drift       a different tool or materially different arguments
  refusal     the model produced no valid tool call at all

Swap a role's model in settings (or select a charter variant with
AGENT_PROMPT_VARIANT), run replay over the last N done tasks, and you get a
number — "this model agrees with our proven trajectories 94% of the time" —
instead of a hope. No live task is touched; no side effect is caused:
replay never EXECUTES the model's choice, it only reads it.

Usage:
  python replay.py --root R [--last 20] [--role practitioner] [--task ID]
                   [--json]
"""

import argparse
import json
import os
import sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)


def _args_equivalent(a, b):
    """Argument equality that ignores whitespace/ordering noise."""
    def norm(x):
        if isinstance(x, dict):
            return {k: norm(v) for k, v in sorted(x.items())}
        if isinstance(x, str):
            return " ".join(x.split())
        return x
    return norm(a or {}) == norm(b or {})


def decision_points(ctx):
    """(messages_before, recorded_tool, recorded_args) for every assistant
    tool call in a recorded transcript."""
    out = []
    for i, m in enumerate(ctx):
        if m.get("role") != "assistant":
            continue
        calls = m.get("tool_calls") or []
        if not calls:
            continue
        fn = calls[0].get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {"_raw": fn.get("arguments")}
        out.append((ctx[:i], fn.get("name"), args))
    return out


def replay_task(agent, task, max_points=None):
    import loop
    ref = task.get("context_ref")
    if not ref:
        return None
    try:
        with open(os.path.join(agent.root, ref), "r", encoding="utf-8") as f:
            ctx = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    points = decision_points(ctx)
    if max_points:
        points = points[:max_points]
    res = {"task": task["id"], "role": task["role"], "points": len(points),
           "agree": 0, "drift": 0, "refusal": 0, "details": []}
    for before, tool, args in points:
        try:
            msg, _usage, _ = agent.call_model(task["role"], before)
            calls = msg.get("tool_calls") or []
            if not calls:
                tc = loop.parse_content_tool_call(msg.get("content"))
                calls = [tc] if tc else []
            if not calls:
                res["refusal"] += 1
                res["details"].append({"recorded": tool, "got": None})
                continue
            fn = calls[0]["function"]
            got_tool = fn.get("name")
            try:
                got_args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                got_args = {"_raw": fn.get("arguments")}
            if got_tool == tool and _args_equivalent(got_args, args):
                res["agree"] += 1
            else:
                res["drift"] += 1
                res["details"].append({"recorded": tool, "got": got_tool,
                                       "recorded_args": args,
                                       "got_args": got_args})
        except Exception as e:
            res["refusal"] += 1
            res["details"].append({"recorded": tool, "error": str(e)[:200]})
    return res


def _write_agreement(root, results):
    """modelrouter._replay_agreement() reads logs/replay.jsonl — and NOTHING
    in the repository ever wrote it, so that routing signal was permanently
    dead. Replay is the module that measures it; it persists it now."""
    import loop
    path = os.path.join(root, "logs", "replay.jsonl")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    agent = loop.Agent(root)
    with open(path, "a", encoding="utf-8") as f:
        for r in results:
            rc = agent.role_cfg(r["role"])
            for _ in range(r["agree"]):
                f.write(json.dumps({"task": r["task"], "role": r["role"],
                                    "provider": rc.get("provider"),
                                    "model": rc.get("model"),
                                    "agreed": True}) + chr(10))
            for _ in range(r["drift"] + r["refusal"]):
                f.write(json.dumps({"task": r["task"], "role": r["role"],
                                    "provider": rc.get("provider"),
                                    "model": rc.get("model"),
                                    "agreed": False}) + chr(10))


def replay(root, last=20, role=None, task_id=None, max_points=None):
    import loop
    agent = loop.Agent(root)
    tasks = []
    if task_id:
        t = agent.find_task(task_id)
        tasks = [t] if t else []
    else:
        hot = agent.load_state().get("tasks", [])
        hist = agent.task_history(limit=500)
        seen = set()
        for t in list(reversed(hot)) + list(reversed(hist)):
            if t["id"] in seen or t.get("status") != "done":
                continue
            if role and t.get("role") != role:
                continue
            seen.add(t["id"])
            tasks.append(t)
            if len(tasks) >= last:
                break
    results = [r for r in (replay_task(agent, t, max_points) for t in tasks)
               if r and r["points"]]
    if results:
        try:
            _write_agreement(root, results)
        except Exception:
            pass                       # measuring must never break on logging
    tot = sum(r["points"] for r in results) or 1
    agree = sum(r["agree"] for r in results)
    drift = sum(r["drift"] for r in results)
    refusal = sum(r["refusal"] for r in results)
    return {"tasks": len(results), "decision_points": tot if results else 0,
            "agreement": round(agree / tot, 3) if results else None,
            "drift": drift, "refusals": refusal, "per_task": results}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    ap.add_argument("--last", type=int, default=20)
    ap.add_argument("--role")
    ap.add_argument("--task")
    ap.add_argument("--max-points", type=int)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = replay(os.path.abspath(a.root), a.last, a.role, a.task, a.max_points)
    if a.json:
        print(json.dumps(r, indent=2))
        return
    if not r["tasks"]:
        print("nothing to replay — no done tasks with transcripts")
        return
    print(f"REPLAY  {r['tasks']} task(s), {r['decision_points']} decision "
          f"points\n  agreement {r['agreement']:.0%}   drift {r['drift']}   "
          f"refusals {r['refusals']}")
    for t in r["per_task"]:
        flag = "" if not (t["drift"] or t["refusal"]) else "  <- review"
        print(f"  {t['task']}  {t['role']:<13} agree {t['agree']}/{t['points']}"
              f"{flag}")
    if r["agreement"] is not None and r["agreement"] < 0.8:
        print("\nVERDICT: below 80% agreement with proven trajectories — "
              "do not promote this wiring without a gated trial.")


if __name__ == "__main__":
    main()
