#!/usr/bin/env python3
"""Deterministic workflows — fixed stages with gates, before autonomy.

The frontier guidance (Anthropic's agent-design ladder, reproduced in every
2026 survey) is blunt: start with a predefined code path — "draft, review,
revise" — and add autonomy only where it measurably helps. A workflow is
more predictable, testable, securable, and cheaper than an agent loop,
because the DEVELOPER chooses the legal transitions and the model only
fills in each stage.

This module gives the fleet that lane with zero new runtime: a workflow is
an ordered list of stages, each a normal gated task for one role; stage N+1
is armed as a prospective intention that fires when stage N's task is DONE.
The running loop does the rest. A stage that fails its gate never fires
the next stage — the pipeline halts exactly where the evidence stopped,
and the owner sees it on the board.

Stage handoff is by file: every stage is told to write its deliverable to
workflows/<id>/stage-<n>.md, and the next stage is told to read the
previous one. No shared scratch state, no hidden context.

  spec = {"name": "draft-review-revise",
          "stages": [
            {"role": "practitioner", "goal": "Draft the memo on {topic}"},
            {"role": "consultant",   "goal": "Review the draft for errors"},
            {"role": "practitioner", "goal": "Revise the memo using the review",
             "done_check": "..."}]}

Usage:
  python workflows.py run --root R --spec spec.json [--var topic="..."]
  python workflows.py list --root R
"""

import argparse
import json
import os
import sys
import time
import uuid

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)


def _stage_goal(wf_id, n, total, stage, vars_):
    goal = stage["goal"]
    for k, v in (vars_ or {}).items():
        goal = goal.replace("{" + k + "}", str(v))
    out_rel = f"workflows/{wf_id}/stage-{n}.md"
    prev = f"workflows/{wf_id}/stage-{n - 1}.md" if n > 1 else None
    text = (f"WORKFLOW '{wf_id}' — stage {n} of {total}.\n{goal}\n"
            + (f"Input: read the previous stage's deliverable at {prev} first.\n"
               if prev else "")
            + f"Write this stage's complete deliverable to {out_rel}, then "
              f"finish_task. The next stage can only see that file.")
    return text, out_rel


def run(root, spec, vars_=None):
    """Queue stage 1 now and arm the chain. Returns the workflow record."""
    import loop
    import prospective as pm
    stages = spec.get("stages") or []
    if len(stages) < 2:
        raise SystemExit("a workflow needs at least two stages (one task is "
                         "just a task)")
    wf_id = (spec.get("name") or "wf").replace(" ", "-")[:24] + "-" + \
        uuid.uuid4().hex[:6]
    wdir = os.path.join(root, "workflows", wf_id)
    os.makedirs(wdir, exist_ok=True)
    agent = loop.Agent(root)
    total = len(stages)
    py = sys.executable
    rec = {"id": wf_id, "name": spec.get("name"), "vars": vars_ or {},
           "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "stages": []}
    prev_task = None
    for n, stage in enumerate(stages, 1):
        goal, out_rel = _stage_goal(wf_id, n, total, stage, vars_)
        # every stage is gated at least on its own deliverable existing
        check = stage.get("done_check") or (
            f'"{py}" -c "import os,sys;sys.exit(0 if os.path.exists(r\'{out_rel}\') else 1)"')
        entry = {"n": n, "role": stage.get("role", "practitioner"),
                 "out": out_rel, "task": None, "intention": None}
        if n == 1:
            entry["task"] = agent.add_task(entry["role"], goal,
                                           course=stage.get("course"),
                                           done_check=check,
                                           stop=stage.get("stop"))
        else:
            it = pm.add(root, {"kind": "task_done", "task": prev_task},
                        {"role": entry["role"], "goal": goal,
                         "course": stage.get("course"), "done_check": check,
                         "stop": stage.get("stop")},
                        note=f"workflow {wf_id} stage {n}")
            entry["intention"] = it["id"]
        rec["stages"].append(entry)
        # the NEXT stage must chain on THIS stage's task id; for armed stages
        # the task id is only known when the intention fires, so we chain on
        # a marker the loop resolves: the intention's fired_task
        prev_task = entry["task"] if entry["task"] else f"intention:{entry['intention']}"
    with open(os.path.join(wdir, "workflow.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    return rec


def status(root, wf_id):
    """Resolve each stage's current task status (fired intentions included)."""
    import loop
    import prospective as pm
    with open(os.path.join(root, "workflows", wf_id, "workflow.json"),
              encoding="utf-8") as f:
        rec = json.load(f)
    agent = loop.Agent(root)
    intents = {it["id"]: it for it in pm.load(root)}
    out = []
    for st in rec["stages"]:
        tid = st["task"]
        if not tid and st.get("intention"):
            tid = (intents.get(st["intention"]) or {}).get("fired_task")
        t = agent.find_task(tid) if tid else None
        out.append({**st, "task": tid,
                    "status": (t or {}).get("status", "waiting")})
    rec["stages"] = out
    done = sum(1 for s in out if s["status"] == "done")
    rec["status"] = ("complete" if done == len(out)
                     else "failed" if any(s["status"] == "failed" for s in out)
                     else "running")
    return rec


def list_workflows(root):
    base = os.path.join(root, "workflows")
    out = []
    if os.path.isdir(base):
        for wf in sorted(os.listdir(base), reverse=True):
            try:
                out.append(status(root, wf))
            except (OSError, json.JSONDecodeError):
                continue
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--root", required=True); p.add_argument("--spec", required=True)
    p.add_argument("--var", action="append", default=[], help="key=value")
    p = sub.add_parser("list"); p.add_argument("--root", required=True)
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.cmd == "run":
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
        vars_ = dict(v.split("=", 1) for v in a.var if "=" in v)
        rec = run(root, spec, vars_)
        print(f"workflow {rec['id']}: stage 1 queued, {len(rec['stages']) - 1} "
              f"stage(s) armed — start the loop and it runs itself")
    else:
        for w in list_workflows(root):
            print(f"{w['id']:<34} {w['status']:<9} "
                  + " → ".join(f"{s['n']}:{s['status']}" for s in w["stages"]))


if __name__ == "__main__":
    main()
