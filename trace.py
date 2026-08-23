#!/usr/bin/env python3
"""ONE TRACE PER TASK — spans, costs, gates, and per-tool error rates.

Every serious 2026 agent-observability writeup converges on the same two
things, and neither is a dashboard: (1) one trace per request, with spans,
so a failure can be walked backwards; (2) per-tool error rates surfaced
SEPARATELY from model errors, because "the agent is flaky" is almost always
"one tool is flaky". NVIDIA's NeMo Agent Toolkit profiles agents down to the
token; AG-UI streams the same events to the user's screen.

This module builds that trace from what the harness already writes — the
task's own step list and its JSON log lines. Nothing new is instrumented and
nothing is inferred: a span exists because a line exists.

    python trace.py --root <expert> --task <id>
    python trace.py --root <expert> --tools      # per-tool error rates

`brief()` returns the three sentences an approval card needs — what was
done, what this step does, what comes next — which is the difference between
a human rubber-stamping a dialog and a human actually deciding.
"""

import json
import os
import re
import time

SPAN_EVENTS = {
    "task_start": "start", "task_end": "end", "escalated": "escalate",
    "done_refused": "gate", "retry_queued": "retry", "stop_condition": "stop",
    "compaction_incomplete": "compaction", "tool_results_cleared": "compaction",
    "premise_warning": "premise", "model_routed": "route",
    "approval_required": "approval", "command_refused": "refusal",
    "gotcha_filed": "memory", "budget_exceeded": "budget",
    "task_cost_ceiling": "budget", "provider_failure": "provider",
}
ERROR_MARKERS = ("ERROR", "REFUSED", "error:", "Traceback",
                 "not permitted", "unavailable")
EXIT_RE = re.compile(r"^exit=(-?\d+)")


def _log_path(root):
    return os.path.join(root, "logs", "agent.log")


def _lines(root, limit=200_000):
    try:
        with open(_log_path(root), "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()[-limit:]
    except OSError:
        return []


def _parse(line):
    """Log lines are '<ts> <json>' — return (ts, obj) or (None, None)."""
    i = line.find("{")
    if i < 0:
        return None, None
    try:
        return line[:i].strip(), json.loads(line[i:])
    except (ValueError, json.JSONDecodeError):
        return None, None


def _secs(ts):
    try:
        return time.mktime(time.strptime(ts.split(",")[0], "%Y-%m-%d %H:%M:%S"))
    except (ValueError, AttributeError):
        return None


def _task(root, task_id):
    """Find the task in the live state or in the archive."""
    try:
        with open(os.path.join(root, "state.json"), "r", encoding="utf-8") as f:
            for t in json.load(f).get("tasks", []):
                if t.get("id") == task_id:
                    return t
    except (OSError, ValueError):
        pass
    arch = os.path.join(root, "archive", "tasks.jsonl")
    try:
        with open(arch, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    t = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if t.get("id") == task_id:
                    return t
    except OSError:
        pass
    return None


def build(root, task_id):
    """-> {task, spans[], totals{}} — the whole life of one task."""
    spans, prev, totals = [], None, {
        "steps": 0, "tool_ms": 0, "cost_usd": 0.0, "tokens_in": 0,
        "tokens_out": 0, "gates_refused": 0, "errors": 0, "model_calls": 0}
    for line in _lines(root):
        ts, ev = _parse(line)
        if not ev or ev.get("task") != task_id:
            continue
        at = _secs(ts)
        if "step" in ev and "tool" in ev:
            ms = int(((at - prev) * 1000) if (at and prev) else 0)
            spans.append({"kind": "tool", "name": ev.get("tool"),
                          "at": ts, "ms": max(0, ms), "step": ev.get("step"),
                          "provider": ev.get("provider"),
                          "cost_usd": ev.get("cost_usd", 0.0),
                          "tokens_in": ev.get("tokens_in", 0),
                          "tokens_out": ev.get("tokens_out", 0),
                          "args": (ev.get("args") or "")[:160],
                          "result": (ev.get("result") or "")[:200],
                          "error": _is_error(ev.get("result"))})
            totals["steps"] += 1
            totals["model_calls"] += 1
            totals["tool_ms"] += max(0, ms)
            totals["cost_usd"] += float(ev.get("cost_usd") or 0)
            totals["tokens_in"] += int(ev.get("tokens_in") or 0)
            totals["tokens_out"] += int(ev.get("tokens_out") or 0)
            totals["errors"] += 1 if _is_error(ev.get("result")) else 0
            prev = at or prev
            continue
        kind = SPAN_EVENTS.get(ev.get("event"))
        if kind:
            spans.append({"kind": kind, "name": ev.get("event"), "at": ts,
                          "ms": 0, "detail": {k: v for k, v in ev.items()
                                              if k not in ("event", "task")}})
            if kind == "gate":
                totals["gates_refused"] += 1
            if prev is None:
                prev = at
    t = _task(root, task_id) or {}
    return {"task": task_id, "goal": (t.get("goal") or "")[:300],
            "role": t.get("role"), "status": t.get("status"),
            "done_check": t.get("done_check"), "stop": t.get("stop"),
            "spans": spans, "totals": totals}


def _is_error(result):
    """A command that exited non-zero is an error whatever it printed; for
    every other tool, the harness's own refusal/error words decide."""
    r = str(result or "")
    m = EXIT_RE.match(r)
    if m:
        return m.group(1) != "0"
    return any(x in r for x in ERROR_MARKERS)


def tool_stats(root, limit=20_000):
    """Per-tool calls / errors / error rate — the number that tells an owner
    WHICH tool is unreliable, instead of 'the agent is flaky'."""
    stats = {}
    for line in _lines(root, limit):
        _, ev = _parse(line)
        if not ev or "tool" not in ev or "step" not in ev:
            continue
        s = stats.setdefault(ev["tool"], {"tool": ev["tool"], "calls": 0,
                                          "errors": 0, "cost_usd": 0.0})
        s["calls"] += 1
        s["cost_usd"] += float(ev.get("cost_usd") or 0)
        if _is_error(ev.get("result")):
            s["errors"] += 1
    out = []
    for s in stats.values():
        s["error_rate"] = round(s["errors"] / s["calls"], 3) if s["calls"] else 0
        s["cost_usd"] = round(s["cost_usd"], 4)
        out.append(s)
    return sorted(out, key=lambda s: (-s["error_rate"], -s["calls"]))


def fleet_tool_stats(home, limit=12):
    """Tool error rates across every expert in the fleet."""
    merged = {}
    experts = os.path.join(home, "experts")
    try:
        slugs = sorted(os.listdir(experts))
    except OSError:
        slugs = []
    for slug in slugs:
        for s in tool_stats(os.path.join(experts, slug)):
            m = merged.setdefault(s["tool"], {"tool": s["tool"], "calls": 0,
                                              "errors": 0, "cost_usd": 0.0})
            m["calls"] += s["calls"]
            m["errors"] += s["errors"]
            m["cost_usd"] = round(m["cost_usd"] + s["cost_usd"], 4)
    out = []
    for m in merged.values():
        m["error_rate"] = round(m["errors"] / m["calls"], 3) if m["calls"] else 0
        out.append(m)
    return sorted(out, key=lambda s: (-s["error_rate"], -s["calls"]))[:limit]


def brief(root, task_id):
    """{done[], this_step, next} — what an approval card must say before a
    human is asked to sign anything."""
    tr = build(root, task_id)
    done, this_step, nxt = [], None, None
    for sp in tr["spans"]:
        if sp["kind"] == "tool":
            line = f"{sp['name']}: {sp.get('args', '')[:90]}"
            if sp.get("error"):
                line += "  (failed)"
            done.append(line)
        elif sp["kind"] == "gate":
            done.append("the done-gate refused a premature finish")
        elif sp["kind"] == "approval":
            this_step = (f"waiting for you: "
                         f"{sp['detail'].get('tool') or 'a guarded action'}"
                         + (f" on {sp['detail'].get('server')}"
                            if sp["detail"].get("server") else ""))
    if not this_step:
        this_step = {"done": "the task finished", "failed": "the task failed",
                     "blocked": "the task is blocked on a question to you",
                     "running": "the task is working"}.get(
                         tr.get("status"), "the task is waiting")
    if tr.get("status") == "running":
        nxt = ("it continues until its definition of done passes"
               if tr.get("done_check") else "it continues to its stop condition")
    elif tr.get("status") == "failed":
        nxt = "a retry may be queued; the failure is filed in memory"
    elif tr.get("status") == "done":
        nxt = "nothing — the gate accepted the work"
    else:
        nxt = "your decision unblocks it"
    return {"done": done[-6:], "this_step": this_step, "next": nxt,
            "totals": tr["totals"], "goal": tr["goal"], "status": tr["status"]}


def render(tr):
    out = [f"trace {tr['task']} ({tr.get('role')}, {tr.get('status')})",
           f"  goal: {tr['goal']}"]
    for sp in tr["spans"]:
        if sp["kind"] == "tool":
            out.append(f"  [{sp['at']}] {sp['ms']:>6}ms  {sp['name']:<14} "
                       f"{'ERR ' if sp.get('error') else '    '}"
                       f"{sp.get('args', '')[:70]}")
        else:
            out.append(f"  [{sp['at']}]         {sp['kind']:<14} "
                       f"{json.dumps(sp.get('detail', {}))[:80]}")
    t = tr["totals"]
    out.append(f"  TOTAL {t['steps']} step(s), {t['tool_ms']}ms in tools, "
               f"${t['cost_usd']:.4f}, {t['tokens_in']}+{t['tokens_out']} tok, "
               f"{t['gates_refused']} gate refusal(s), {t['errors']} error(s)")
    return "\n".join(out)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="per-task traces and tool health")
    ap.add_argument("--root", default=".")
    ap.add_argument("--task")
    ap.add_argument("--tools", action="store_true")
    ap.add_argument("--brief", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.tools:
        rows = tool_stats(root)
        print(json.dumps(rows, indent=1) if a.json else
              "\n".join(f"{r['tool']:<16} {r['calls']:>5} calls  "
                        f"{r['errors']:>4} errors  {r['error_rate']:>6.1%}  "
                        f"${r['cost_usd']:.4f}" for r in rows)
              or "no tool calls logged yet")
        return
    if not a.task:
        raise SystemExit("--task <id> or --tools")
    if a.brief:
        b = brief(root, a.task)
        print(json.dumps(b, indent=1) if a.json else
              "DONE SO FAR:\n  " + "\n  ".join(b["done"] or ["nothing yet"]) +
              f"\nTHIS STEP:\n  {b['this_step']}\nNEXT:\n  {b['next']}")
        return
    tr = build(root, a.task)
    print(json.dumps(tr, indent=1) if a.json else render(tr))


if __name__ == "__main__":
    main()
