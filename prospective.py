#!/usr/bin/env python3
"""Prospective memory — remembering to ACT, not just remembering facts.

PM-Bench (2026-07-14) measured what ordinary agent memory misses: recalling
that an action must happen LATER, when a condition appears, while doing other
work in between. Best system tested: 65.1% F1. The research conclusion is the
design here: future intentions must live in their own ledger and be fired by
the scheduler — deterministically — never left to a model's implicit recall.

An intention:  WHEN <condition>  THEN <queue this task>

Conditions (all evaluated mechanically, no model involved):
  at            an ISO timestamp has passed (deadlines, follow-ups)
  every_days    recurring: N days since it last fired (reviews, re-checks)
  file_exists   a file appeared inside this agent's world
  file_contains a file inside this agent's world gained a phrase
                (watch a report, a price file, a peer's deliverable...)
  task_done     a specific task finished as done (then do the next thing)

Firing queues a normal gated task on this agent's own board — so a fired
intention gets the same done-checks, retries, and budget brakes as any work.
The loop checks the ledger on every idle tick; fired one-shots keep their
record (status "fired", with the queued task id) — an intention's history is
never silently deleted.

Usage:
  python prospective.py add --root R --goal "..." [--role practitioner]
        (--at ISO | --in-days N | --every-days N | --file-exists REL |
         --file-contains "REL::needle" | --after-task TASKID)
        [--course C] [--done-check CMD] [--note "..."]
  python prospective.py list [--root R]
  python prospective.py cancel ID [--root R]
"""

import argparse
import json
import os
import re
import sys
import time
import uuid

sys_path_dir = os.path.dirname(os.path.abspath(__file__))

LEDGER = "prospective.json"


def _path(root):
    return os.path.join(root, LEDGER)


def load(root):
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def save(root, items):
    # a UNIQUE temp per writer: a fixed ".tmp" meant two processes wrote the
    # same scratch file and os.replace could publish a half-written mix
    tmp = f"{_path(root)}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1, ensure_ascii=False)
    for attempt in range(8):
        try:
            os.replace(tmp, _path(root))
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, _path(root))


def _contained(root, rel):
    """A watched path must stay inside the agent's world."""
    rel = (rel or "").replace("\\", "/")
    full = os.path.realpath(os.path.join(root, rel))
    if not (full + os.sep).startswith(os.path.realpath(root) + os.sep):
        raise ValueError(f"path escapes the agent root: {rel}")
    return rel


def add(root, when, then, note=""):
    kind = when.get("kind")
    if kind not in ("at", "every_days", "file_exists", "file_contains",
                    "task_done", "event", "check"):
        raise ValueError(f"unknown condition kind: {kind}")
    if kind in ("file_exists", "file_contains"):
        when["path"] = _contained(root, when.get("path"))
    if kind == "file_contains" and not when.get("needle"):
        raise ValueError("file_contains needs a needle")
    if kind == "check":
        # WHEN a probe command exits 0 — the condition kind that expresses
        # "when the competitor's price gap exceeds 15%", which no file
        # pattern can. The probe runs through the Execution Authority as a
        # gate (policy-screened, like a runbook's when.requires), and is
        # rate-limited per intention because a probe is a subprocess, not
        # a stat call.
        if not str(when.get("cmd") or "").strip():
            raise ValueError("check needs a cmd that exits 0 when the "
                             "condition holds")
        when["every_s"] = max(30, int(when.get("every_s") or 300))
        when["last_probe"] = 0.0
    if kind == "event":
        name = (when.get("name") or "").strip()
        if not re.fullmatch(r"[a-z0-9_.-]{1,64}", name):
            raise ValueError("event names are [a-z0-9_.-]{1,64}")
        when["name"] = name
        when["repeat"] = bool(when.get("repeat", False))
        when["consumed"] = []
    if not (then.get("goal") or "").strip():
        raise ValueError("the intention needs a goal to queue when it fires")
    item = {"id": f"pm-{uuid.uuid4().hex[:8]}", "when": when,
            "then": {"role": then.get("role", "practitioner"),
                     "goal": then["goal"].strip(),
                     "course": then.get("course"),
                     "done_check": then.get("done_check"),
                     "stop": then.get("stop"),
                     "memory_files": list(then.get("memory_files") or [])},
            "note": (note or "")[:300], "status": "armed",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "fired_at": None, "fired_task": None, "fire_count": 0}
    # every writer of this ledger takes the lock, not only check(): a lock
    # one writer skips is not a lock. add() racing a firing check() used to
    # lose whichever update saved second.
    sys.path.insert(0, sys_path_dir)
    import locks
    try:
        with locks.holding(_path(root), timeout=5.0):
            items = load(root)
            items.append(item)
            save(root, items)
    except TimeoutError:
        items = load(root)
        items.append(item)
        save(root, items)
    return item


def cancel(root, pid):
    sys.path.insert(0, sys_path_dir)
    import locks
    try:
        with locks.holding(_path(root), timeout=5.0):
            return _cancel_locked(root, pid)
    except TimeoutError:
        return _cancel_locked(root, pid)


def _cancel_locked(root, pid):
    items = load(root)
    for it in items:
        if it["id"] == pid and it["status"] == "armed":
            it["status"] = "cancelled"
            it["fired_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            save(root, items)
            return it
    raise KeyError(pid)


def _due(root, it, agent, now, fired_map=None):
    w = it["when"]
    k = w["kind"]
    if k == "at":
        return time.strftime("%Y-%m-%dT%H:%M:%S") >= w.get("iso", "9999")
    if k == "every_days":
        last = w.get("last") or it["created"]
        try:
            last_t = time.mktime(time.strptime(last[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            return False
        return now - last_t >= float(w.get("n", 1)) * 86400
    if k == "file_exists":
        return os.path.exists(os.path.join(root, w["path"]))
    if k == "file_contains":
        try:
            with open(os.path.join(root, w["path"]), "r", encoding="utf-8",
                      errors="replace") as f:
                return w["needle"] in f.read(2_000_000)
        except OSError:
            return False
    if k == "task_done":
        if agent is None:
            return False
        tid = w.get("task", "")
        # a workflow stage chains on the task that a PREVIOUS intention
        # fired; resolve the marker through the ledger
        if tid.startswith("intention:"):
            tid = (fired_map or {}).get(tid[len("intention:"):])
            if not tid:
                return False
        t = agent.find_task(tid)
        return bool(t) and t.get("status") == "done"
    if k == "event":
        # wake-on-event: an events/<ts>-<name>.json file this intention has
        # not consumed yet (written by POST /api/experts/<s>/wake)
        return bool(_unconsumed_events(root, w))
    if k == "check":
        if now - float(w.get("last_probe") or 0) < float(w.get("every_s",
                                                               300)):
            return False
        w["last_probe"] = now                # persisted by the caller's save
        try:
            sys.path.insert(0, sys_path_dir)
            import execution
            rc, _o, _e = execution.run(
                "gate", w["cmd"], root, cfg=None, role="practitioner",
                timeout=int(w.get("timeout") or 30),
                reason=f"prospective probe {it['id']}")
            return rc == 0
        except Exception:
            return False                     # an unrunnable probe never fires
    return False


def _unconsumed_events(root, w):
    d = os.path.join(root, "events")
    if not os.path.isdir(d):
        return []
    suffix = f"-{w.get('name')}.json"
    seen = set(w.get("consumed") or [])
    return sorted(f for f in os.listdir(d)
                  if f.endswith(suffix) and f not in seen)


def check(root, agent=None):
    """Evaluate every armed intention; fire the due ones by queueing their
    task. Returns the number fired. Deterministic, cheap, model-free.

    The whole evaluate->fire->save is ONE held critical section: with several
    loop processes on the same expert, an unserialized check fired the same
    intention twice (measured live) — the owner's action queued double. A
    busy lock means another process is already handling this tick: skip."""
    sys.path.insert(0, sys_path_dir)
    import locks
    try:
        with locks.holding(_path(root), timeout=5.0):
            return _check_locked(root, agent)
    except TimeoutError:
        return 0


def _check_locked(root, agent=None):
    items = load(root)
    if not items:
        return 0
    now = time.time()
    fired = 0
    # probe rate-limiting bookkeeping (when.last_probe) mutates in _due;
    # it must persist even when nothing fires, or every idle tick re-runs
    # every probe subprocess and the rate limit is decorative
    probe_before = {it["id"]: it["when"].get("last_probe")
                    for it in items if it["when"].get("kind") == "check"}
    fired_map = {x["id"]: x.get("fired_task") for x in items if x.get("fired_task")}
    for it in items:
        if it["status"] != "armed":
            continue
        try:
            due = _due(root, it, agent, now, fired_map)
        except Exception:
            continue
        if not due:
            continue
        w, then = it["when"], it["then"]
        memory_files = list(then.get("memory_files") or [])
        event_file = None
        if w["kind"] == "event":
            pending = _unconsumed_events(root, w)
            event_file = pending[0]
            memory_files.append(f"events/{event_file}")
        trig = {"at": lambda: f"the deadline {w.get('iso')} passed",
                "every_days": lambda: f"{w.get('n')} day(s) elapsed",
                "file_exists": lambda: f"{w.get('path')} appeared",
                "file_contains": lambda: f"{w.get('path')} now contains "
                                         f"\"{w.get('needle')}\"",
                "task_done": lambda: f"task {w.get('task')} completed",
                "event": lambda: f"event '{w.get('name')}' arrived "
                                 f"(payload fenced in context at events/{event_file})",
                "check": lambda: f"the probe `{(w.get('cmd') or '')[:80]}` "
                                 f"exited 0 — the condition now holds",
                }[w["kind"]]()
        goal = (f"PROSPECTIVE INTENTION FIRED — {trig}.\n{then['goal']}"
                + (f"\n(Why this was armed: {it['note']})" if it["note"] else ""))
        tid = None
        if agent is not None:
            tid = agent.add_task(then["role"], goal,
                                 memory_files=memory_files or None,
                                 course=then.get("course"),
                                 done_check=then.get("done_check"),
                                 stop=then.get("stop"))
            try:
                agent.log.info(json.dumps({"event": "prospective_fired",
                                           "intention": it["id"],
                                           "task": tid, "trigger": w["kind"]}))
            except Exception:
                pass
        it["fire_count"] += 1
        it["fired_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        it["fired_task"] = tid
        if tid:
            fired_map[it["id"]] = tid      # later stages in this tick can chain
        if w["kind"] == "every_days":
            w["last"] = it["fired_at"]      # recurring: stays armed
        elif w["kind"] == "event":
            consumed = (w.get("consumed") or []) + [event_file]
            w["consumed"] = consumed[-200:]
            if not w.get("repeat"):
                it["status"] = "fired"      # one-shot; repeat stays armed
        else:
            it["status"] = "fired"
        fired += 1
    probed = any(it["when"].get("last_probe") != probe_before.get(it["id"])
                 for it in items if it["when"].get("kind") == "check")
    if fired or probed:
        save(root, items)
    return fired


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("--root", default=".")
    p.add_argument("--goal", required=True)
    p.add_argument("--role", default="practitioner")
    p.add_argument("--course")
    p.add_argument("--done-check")
    p.add_argument("--note", default="")
    p.add_argument("--at")
    p.add_argument("--in-days", type=float)
    p.add_argument("--every-days", type=float)
    p.add_argument("--file-exists")
    p.add_argument("--file-contains", help='REL::needle')
    p.add_argument("--after-task")
    p.add_argument("--when-check",
                   help="a probe command; the intention fires when it "
                        "exits 0 (policy-screened, rate-limited)")
    p.add_argument("--probe-every-s", type=int, default=300)
    p = sub.add_parser("list")
    p.add_argument("--root", default=".")
    p = sub.add_parser("cancel")
    p.add_argument("id")
    p.add_argument("--root", default=".")
    p = sub.add_parser("check")
    p.add_argument("--root", default=".")
    a = ap.parse_args()
    root = os.path.abspath(a.root)

    if a.cmd == "add":
        if a.at:
            when = {"kind": "at", "iso": a.at}
        elif a.in_days is not None:
            when = {"kind": "at", "iso": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(time.time()
                                                    + a.in_days * 86400))}
        elif a.every_days is not None:
            when = {"kind": "every_days", "n": a.every_days}
        elif a.file_exists:
            when = {"kind": "file_exists", "path": a.file_exists}
        elif a.file_contains:
            rel, _, needle = a.file_contains.partition("::")
            when = {"kind": "file_contains", "path": rel, "needle": needle}
        elif a.after_task:
            when = {"kind": "task_done", "task": a.after_task}
        elif a.when_check:
            when = {"kind": "check", "cmd": a.when_check,
                    "every_s": a.probe_every_s}
        else:
            raise SystemExit("pick a condition: --at/--in-days/--every-days/"
                             "--file-exists/--file-contains/--after-task/"
                             "--when-check")
        it = add(root, when, {"role": a.role, "goal": a.goal,
                              "course": a.course, "done_check": a.done_check},
                 a.note)
        print(f"armed {it['id']}: when {it['when']['kind']} -> "
              f"{it['then']['goal'][:60]}")
    elif a.cmd == "list":
        for it in load(root):
            print(f"{it['id']}  {it['status']:<9} {it['when']['kind']:<13} "
                  f"{it['then']['goal'][:70]}"
                  + (f"  (fired {it['fire_count']}x)" if it["fire_count"] else ""))
    elif a.cmd == "cancel":
        cancel(root, a.id)
        print("cancelled", a.id)
    elif a.cmd == "check":
        print(f"fired {check(root)} (queueing needs the running loop)")


if __name__ == "__main__":
    main()
