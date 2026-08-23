#!/usr/bin/env python3
"""ROUTINES — show the work once, then have it done forever.

Grok Bot's most-copied interaction is not a model capability at all: you do a
task with the bot once, then press a button and it becomes a scheduled
routine that runs without you. The platform already had both halves — skills
(procedural memory) and prospective intentions (future triggers) — but no
single gesture that turned a task that WORKED into a standing arrangement.

`save()` is that gesture. Given a finished task it writes:

  skills/<name>/SKILL.md   the procedure, reconstructed from what actually
                           happened: the goal, the definition of done, the
                           exact tool steps in order, and the verification
  prospective intention    every_days / at / on-event, whose fired task
                           carries the same gate the original passed
  routines/<name>.json     the link between them, so the panel can show and
                           cancel the arrangement as one thing

Two rules keep this honest:
  * only a task that FINISHED may become a routine — a routine is a promise
    that this works, so an unfinished or failed task is refused;
  * the routine keeps the original's done_check. A scheduled task with no
    gate is how a fleet quietly produces garbage every morning at 07:00.
"""

import json
import os
import re
import time

DIR = "routines"


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return (s[:48] or "routine")


def _dir(root):
    d = os.path.join(root, DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _find_task(root, task_id):
    try:
        with open(os.path.join(root, "state.json"), "r", encoding="utf-8") as f:
            for t in json.load(f).get("tasks", []):
                if t.get("id") == task_id:
                    return t
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(root, "archive", "tasks.jsonl"), "r",
                  encoding="utf-8") as f:
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


def skill_from_task(task, name):
    """Reconstruct the procedure from the trajectory that actually worked."""
    steps = task.get("steps", []) or []
    lines = ["---", f"name: {name}",
             f"description: {(task.get('goal') or name)[:180]}",
             "keywords: [" + ", ".join(sorted({
                 w for w in re.findall(r"[a-z0-9]{4,}", (task.get("goal") or "").lower())
             })[:8]) + "]",
             "provenance: own", "version: 1", "---", "",
             f"# {name}", "",
             f"Goal that worked: {task.get('goal', '')[:400]}", ""]
    if task.get("course"):
        lines.append(f"Course: {task['course']}")
    lines += ["", "## Definition of done",
              f"`{task.get('done_check')}`" if task.get("done_check")
              else "(this task carried no gate — add one before trusting it "
                   "unattended)", "", "## Steps that worked"]
    for i, s in enumerate(steps, 1):
        args = str(s.get("args") or "")[:200].replace("\n", " ")
        lines.append(f"{i}. `{s.get('tool')}` {args}")
    if task.get("summary"):
        lines += ["", "## What it produced", task["summary"][:600]]
    lines += ["", "## Verification",
              "Re-run the definition of done above. If it fails, the routine "
              "did NOT work — fix the procedure instead of re-running it."]
    return "\n".join(lines) + "\n"


def save(root, task_id, name=None, every_days=None, at=None, event=None,
         role=None):
    """Turn a finished task into a skill + an armed intention. Returns the
    routine record."""
    task = _find_task(root, task_id)
    if not task:
        raise KeyError(f"no task {task_id} in this expert's state or archive")
    if task.get("status") != "done":
        raise ValueError(f"task {task_id} is '{task.get('status')}' — only a "
                         f"task that finished may become a routine")
    if not (every_days or at or event):
        raise ValueError("a routine needs a schedule: every_days, at, or event")
    name = _slug(name or task.get("goal") or task_id)
    skill_dir = os.path.join(root, "skills", name)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(skill_from_task(task, name))
    # register it: trust lives in the graph, never in the file's own words, so
    # a skill this platform WROTE has to say so through the graph like any
    # other. An unregistered folder skill is third-party until the owner says
    # otherwise, which is what makes that default safe.
    try:
        import skills as _sk
        _sk.set_provenance(root, name, "own")
    except Exception:
        pass

    import prospective
    goal = (f"Routine '{name}': {task.get('goal', '')[:300]} "
            f"(the procedure that worked is in skills/{name}/SKILL.md — "
            f"follow it, and prove the same definition of done)")
    when = {}
    if event:
        when = {"kind": "event", "name": str(event), "repeat": True}
    elif at:
        when = {"kind": "at", "iso": at}
    else:
        when = {"kind": "every_days", "n": float(every_days)}
    rec = prospective.add(
        root, when,
        {"role": role or task.get("role") or "practitioner", "goal": goal,
         "course": task.get("course"),
         "done_check": task.get("done_check"),
         "memory_files": [f"skills/{name}/SKILL.md"]},
        note=f"routine saved from task {task_id}")
    routine = {"name": name, "from_task": task_id, "intention": rec["id"],
               "skill": f"skills/{name}/SKILL.md", "when": when,
               "role": role or task.get("role"),
               "done_check": task.get("done_check"),
               "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(os.path.join(_dir(root), f"{name}.json"), "w",
              encoding="utf-8") as f:
        json.dump(routine, f, indent=1, ensure_ascii=False)
    return routine


def load(root):
    out = []
    d = os.path.join(root, DIR)
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), "r", encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            continue
    return out


def status(root):
    """Routines with the live status of their intention."""
    import prospective
    armed = {r["id"]: r for r in prospective.load(root)}
    out = []
    for r in load(root):
        pm = armed.get(r.get("intention")) or {}
        out.append({**r, "status": pm.get("status", "gone"),
                    "fired": pm.get("fired_at") or pm.get("last_fired")})
    return out


def cancel(root, name):
    import prospective
    recs = [r for r in load(root) if r["name"] == name]
    if not recs:
        raise KeyError(f"no routine '{name}'")
    r = recs[0]
    try:
        prospective.cancel(root, r["intention"])
    except Exception:
        pass
    p = os.path.join(_dir(root), f"{name}.json")
    if os.path.exists(p):
        os.remove(p)
    return r


def main():
    import argparse
    ap = argparse.ArgumentParser(description="save a task as a routine")
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("save")
    p.add_argument("task_id")
    p.add_argument("--name")
    p.add_argument("--every-days", type=float)
    p.add_argument("--at")
    p.add_argument("--event")
    sub.add_parser("list")
    p = sub.add_parser("cancel")
    p.add_argument("name")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.cmd == "save":
        r = save(root, a.task_id, a.name, a.every_days, a.at, a.event)
        print(f"routine '{r['name']}' saved: {r['skill']} + intention "
              f"{r['intention']} ({r['when'].get('kind')})")
        return
    if a.cmd == "cancel":
        print(f"cancelled routine '{cancel(root, a.name)['name']}'")
        return
    rows = status(root)
    if not rows:
        print("no routines yet — finish a task, then save it as one")
    for r in rows:
        print(f"{r['name']:<34} {r['when'].get('kind'):<12} "
              f"{r['status']:<10} gate={'yes' if r.get('done_check') else 'NO'}")


if __name__ == "__main__":
    main()
