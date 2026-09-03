"""RECONCILERS - the cluster-controller pattern as a standing responsibility.

docs/DESIGN-P9a-reconcilers.md names the rules this module enforces. The
pre-AI machinery that ran regulated, hard work reliably did not think: a
cluster controller holds a DESIRED state, observes the ACTUAL state, and
reconciles with idempotent actions, level-triggered, backing off, halting
when it cannot converge. This module is that shape, applied to the states
this platform can observe (the operator algebra: files, tables, SQLite,
git, workbooks, owner-named endpoints) and restore (a PROVEN runbook or
compiled procedure). The model is never called. Where the machine stops -
a drift no proven procedure repairs, a restore that cannot converge - it
halts and asks the owner, which is exactly where a model or a person is the
right tool.

  reconcilers.json      CONTROL state: the owner's declarations (the worker's
                        file tool cannot write it); status, failures and the
                        next due time live beside each declaration
  logs/reconciler.jsonl one row per evaluated reconciler per tick

Every action runs through runbook.run - the same executor every proven
procedure uses - under the authority the OWNER declared (procedure.owner_grant:
workspace-write plus db_write / git_write / http_write), with the desired
state itself as the acceptance test, so the trust ledger records an accepted
win only when the state was actually restored.
"""
import argparse
import json
import os
import sys
import time
import uuid

sys_path_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, sys_path_dir)

LEDGER = "reconcilers.json"
LOG = os.path.join("logs", "reconciler.jsonl")
MIN_EVERY_S = 30
DEFAULT_EVERY_S = 300
DEFAULT_BACKOFF = {"base_s": 60, "max_s": 3600}
DEFAULT_MAX_FAILURES = 3
STATUSES = ("armed", "paused", "halted", "removed")


def _path(root):
    return os.path.join(root, LEDGER)


def load(root):
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            items = json.load(f)
        return items if isinstance(items, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def save(root, items):
    # a UNIQUE temp per writer, then an atomic replace (prospective.py's
    # pattern): two processes must never publish a half-written mix
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


def _log(root, row):
    p = os.path.join(root, LOG)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    row = dict(row, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _settings(root):
    import tomllib
    try:
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------ declaring

def validate(item):
    """A declaration is refused, never repaired: a malformed reconciler that
    ran would be a controller nobody declared."""
    import operators
    import re
    name = item.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("reconciler name must be [a-z0-9][a-z0-9_-]{0,63}")
    desired = item.get("desired")
    if not isinstance(desired, list) or not desired or len(desired) > 32:
        raise ValueError("desired must be a list of 1..32 predicates")
    for pred in desired:
        try:
            operators.validate_predicate(pred)
        except Exception as exc:
            raise ValueError(f"desired predicate refused: {exc}")
    # a desired state is CONCRETE: an {"input": ...} placeholder is a
    # procedure's business, not a controller's; binding with no inputs
    # raises on any placeholder
    operators.bind(desired, {})
    restore = item.get("restore")
    if not isinstance(restore, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", restore):
        raise ValueError("restore must name a runbook ([a-z0-9][a-z0-9_-]{0,63})")
    inputs = item.get("inputs") or {}
    if not isinstance(inputs, dict) or any(not isinstance(k, str) for k in inputs):
        raise ValueError("inputs must be an object of named values")
    every_s = item.get("every_s", DEFAULT_EVERY_S)
    if type(every_s) is not int or every_s < MIN_EVERY_S:
        raise ValueError(f"every_s must be an integer of at least {MIN_EVERY_S}")
    backoff = item.get("backoff") or dict(DEFAULT_BACKOFF)
    if not isinstance(backoff, dict) or set(backoff) != {"base_s", "max_s"} or \
            type(backoff["base_s"]) is not int or type(backoff["max_s"]) is not int or \
            backoff["base_s"] < 1 or backoff["max_s"] < backoff["base_s"]:
        raise ValueError("backoff must be {base_s >= 1, max_s >= base_s}")
    max_failures = item.get("max_failures", DEFAULT_MAX_FAILURES)
    if type(max_failures) is not int or max_failures < 1:
        raise ValueError("max_failures must be a positive integer")
    return {"name": name, "desired": desired, "restore": restore,
            "inputs": inputs, "every_s": every_s, "backoff": backoff,
            "max_failures": max_failures}


def _owner_only(action):
    import controlplane
    controlplane.owner_only(action)


def _locked(root, fn):
    import locks
    os.makedirs(root, exist_ok=True)
    with locks.holding(_path(root), timeout=10.0, stale=8.0):
        items = load(root)
        out = fn(items)
        save(root, items)
        return out


def add(root, name, desired, restore, inputs=None, every_s=DEFAULT_EVERY_S,
        backoff=None, max_failures=DEFAULT_MAX_FAILURES, note=""):
    """Declare a reconciler. OWNER work: the declaration is control state."""
    _owner_only("declare a reconciler")
    spec = validate({"name": name, "desired": desired, "restore": restore,
                     "inputs": inputs or {}, "every_s": every_s,
                     "backoff": backoff or dict(DEFAULT_BACKOFF),
                     "max_failures": max_failures})
    item = dict(spec, id=f"rc-{uuid.uuid4().hex[:8]}", status="armed",
                failures=0, next_due=0.0, repairs=0, observations=0,
                last_outcome=None, note=(note or "")[:300],
                created=time.strftime("%Y-%m-%dT%H:%M:%S"))

    def _add(items):
        if any(it.get("name") == name and it.get("status") != "removed"
               for it in items):
            raise ValueError(f"a reconciler named {name!r} already exists")
        items.append(item)
        return item
    return _locked(root, _add)


def _set_status(root, rid, status, why=""):
    def _set(items):
        for it in items:
            if it.get("id") == rid:
                it["status"] = status
                if status == "armed":
                    it["failures"] = 0
                    it["next_due"] = 0.0
                it["last_outcome"] = why or status
                return it
        raise KeyError(rid)
    return _locked(root, _set)


def pause(root, rid):
    _owner_only("pause a reconciler")
    return _set_status(root, rid, "paused")


def resume(root, rid):
    _owner_only("resume a reconciler")
    return _set_status(root, rid, "armed", why="resumed by the owner")


def remove(root, rid):
    _owner_only("remove a reconciler")
    return _set_status(root, rid, "removed")


# ------------------------------------------------------------ observing

def observe_all(root, desired):
    """(all_true, [failing predicate summaries]). Observation only."""
    import operators
    failing = []
    for pred in desired:
        try:
            ok = bool(operators.observe(root, pred))
        except Exception:
            ok = False
        if not ok:
            failing.append(f"{pred.get('predicate')}({pred.get('path')})")
    return not failing, failing


def _halt_question(root, it, failing):
    """The fault-protection response: stop and ask, never loop. The
    question lands in blocked.md exactly as ask_human's do."""
    import locks
    bm = os.path.join(root, "blocked.md")
    line = (f"- reconciler {it['name']} ({it['id']}) HALTED after "
            f"{it['failures']} consecutive failures: {', '.join(failing)} "
            f"could not be restored by {it['restore']!r}. Fix the procedure "
            f"or the state, then: python reconciler.py resume --root "
            f"<expert> {it['id']}\n")
    try:
        with locks.holding(bm, timeout=10.0, stale=8.0):
            with open(bm, "a", encoding="utf-8") as f:
                f.write(line)
    except TimeoutError:
        with open(bm, "a", encoding="utf-8") as f:
            f.write(line)


def _emit(agent, root, row):
    row = _log(root, row)
    if agent is not None and getattr(agent, "log", None) is not None:
        try:
            agent.log.info(json.dumps(row, ensure_ascii=False))
        except Exception:
            pass
    return row


def tick(root, agent=None, now=None, cfg=None):
    """Evaluate every armed reconciler that is due. Model-free. ONE held
    critical section per expert: a busy lock means another process is
    handling this tick, so this one skips rather than acting twice."""
    import locks
    try:
        with locks.holding(_path(root), timeout=5.0, stale=20.0):
            return _tick_locked(root, agent, now, cfg)
    except TimeoutError:
        return {"skipped": True, "evaluated": 0, "in_spec": 0, "repaired": 0,
                "failed": 0, "blocked": 0, "halted": 0}


def _tick_locked(root, agent, now, cfg):
    import procedure
    import runbook
    items = load(root)
    now = time.time() if now is None else now
    summary = {"skipped": False, "evaluated": 0, "in_spec": 0, "repaired": 0,
               "failed": 0, "blocked": 0, "halted": 0}
    if not items:
        return summary
    cfg = cfg if cfg is not None else _settings(root)
    grant = procedure.owner_grant(cfg)
    changed = False
    for it in items:
        if it.get("status") != "armed" or float(it.get("next_due") or 0) > now:
            continue
        summary["evaluated"] += 1
        changed = True
        it["observations"] = int(it.get("observations") or 0) + 1
        ok, failing = observe_all(root, it["desired"])
        if ok:
            it["failures"] = 0
            it["next_due"] = now + it["every_s"]
            it["last_outcome"] = "in_spec"
            summary["in_spec"] += 1
            _emit(agent, root, {"event": "reconciler_observed", "reconciler": it["id"],
                                "name": it["name"], "outcome": "in_spec"})
            continue
        # drift. TRUST FIRST: an unproven restore never acts unsupervised.
        status = runbook.status(root, it["restore"])
        if status != "proven":
            it["next_due"] = now + _backoff(it)
            it["last_outcome"] = f"blocked: restore {it['restore']!r} is {status}"
            summary["blocked"] += 1
            _emit(agent, root, {"event": "reconciler_blocked", "reconciler": it["id"],
                                "name": it["name"], "failing": failing,
                                "restore": it["restore"], "trust": status,
                                "why": "an unproven procedure does not act unsupervised"})
            continue
        # ACT, with the desired state itself as the acceptance test: the
        # trust ledger records an accepted win only if the state came back
        rr = runbook.run(root, it["restore"], inputs=it.get("inputs") or {},
                         authority=grant, cfg=cfg,
                         accept=lambda: observe_all(root, it["desired"])[0])
        ok_after, failing_after = observe_all(root, it["desired"])
        if rr.get("ok") and ok_after:
            it["failures"] = 0
            it["repairs"] = int(it.get("repairs") or 0) + 1
            it["next_due"] = now + it["every_s"]
            it["last_outcome"] = "repaired"
            summary["repaired"] += 1
            _emit(agent, root, {"event": "reconciler_repaired", "reconciler": it["id"],
                                "name": it["name"], "was_failing": failing,
                                "restore": it["restore"], "model_calls": 0})
            continue
        it["failures"] = int(it.get("failures") or 0) + 1
        why = (rr.get("why") or "") if not rr.get("ok") else \
            f"restore ran but the state is still not as declared: {', '.join(failing_after)}"
        it["last_outcome"] = f"failed: {why[:200]}"
        if it["failures"] >= it["max_failures"]:
            it["status"] = "halted"
            summary["halted"] += 1
            _emit(agent, root, {"event": "reconciler_halted", "reconciler": it["id"],
                                "name": it["name"], "failures": it["failures"],
                                "failing": failing_after or failing, "why": why[:300]})
            _halt_question(root, it, failing_after or failing)
            continue
        it["next_due"] = now + _backoff(it)
        summary["failed"] += 1
        _emit(agent, root, {"event": "reconciler_failed", "reconciler": it["id"],
                            "name": it["name"], "failures": it["failures"],
                            "next_in_s": round(it["next_due"] - now),
                            "why": why[:300]})
    if changed:
        save(root, items)
    return summary


def _backoff(it):
    b = it.get("backoff") or DEFAULT_BACKOFF
    n = max(1, int(it.get("failures") or 1))
    return float(min(b["max_s"], b["base_s"] * (2 ** (n - 1))))


def status(root):
    """Every declaration with its live state, for a person."""
    now = time.time()
    out = []
    for it in load(root):
        out.append({"id": it["id"], "name": it["name"], "status": it["status"],
                    "restore": it["restore"], "failures": it.get("failures", 0),
                    "repairs": it.get("repairs", 0),
                    "observations": it.get("observations", 0),
                    "due_in_s": max(0, round(float(it.get("next_due") or 0) - now)),
                    "last_outcome": it.get("last_outcome"),
                    "desired": [f"{p.get('predicate')}({p.get('path')})"
                                for p in it["desired"]]})
    return out


# --------------------------------------------------------------- owner CLI

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(
        description="Reconcilers: keep a declared state true with a PROVEN "
                    "procedure, model-free, backing off and halting to the "
                    "owner when it cannot converge (docs/DESIGN-P9a).")
    ap.add_argument("--root", required=True, help="the expert root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="declare a reconciler (owner)")
    a.add_argument("--name", required=True)
    a.add_argument("--desired", required=True,
                   help="JSON list of predicates over the observable algebra")
    a.add_argument("--restore", required=True, help="a PROVEN runbook name")
    a.add_argument("--inputs", default="{}", help="JSON object of inputs")
    a.add_argument("--every-s", type=int, default=DEFAULT_EVERY_S)
    a.add_argument("--max-failures", type=int, default=DEFAULT_MAX_FAILURES)
    a.add_argument("--backoff-base-s", type=int, default=DEFAULT_BACKOFF["base_s"])
    a.add_argument("--backoff-max-s", type=int, default=DEFAULT_BACKOFF["max_s"])
    a.add_argument("--note", default="")
    sub.add_parser("list", help="every declaration and its live state")
    sub.add_parser("status", help="same as list")
    sub.add_parser("tick", help="evaluate every due reconciler once (cron/timer)")
    for name in ("pause", "resume", "remove"):
        p = sub.add_parser(name, help=f"{name} a reconciler by id (owner)")
        p.add_argument("id")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    try:
        if args.cmd == "add":
            item = add(root, args.name, json.loads(args.desired), args.restore,
                       inputs=json.loads(args.inputs), every_s=args.every_s,
                       backoff={"base_s": args.backoff_base_s,
                                "max_s": args.backoff_max_s},
                       max_failures=args.max_failures, note=args.note)
            print(f"declared {item['id']} {item['name']}: keep "
                  f"{len(item['desired'])} predicate(s) true with "
                  f"{item['restore']!r}, every {item['every_s']}s")
        elif args.cmd in ("list", "status"):
            rows = status(root)
            if not rows:
                print("no reconcilers declared")
            for r in rows:
                print(f"{r['id']} {r['name']:<24} {r['status']:<7} "
                      f"restore={r['restore']} failures={r['failures']} "
                      f"repairs={r['repairs']} due_in={r['due_in_s']}s "
                      f"last={r['last_outcome']}")
                for d in r["desired"]:
                    print(f"    keep {d}")
        elif args.cmd == "tick":
            s = tick(root)
            print(json.dumps(s))
        else:
            it = {"pause": pause, "resume": resume, "remove": remove}[args.cmd](root, args.id)
            print(f"{it['id']} {it['name']} -> {it['status']}")
    except (ValueError, KeyError) as exc:
        print(f"REFUSED: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
