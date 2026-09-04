"""WATCHDOG AND SAFE MODE - spacecraft fault protection beneath the model.

docs/DESIGN-P9b-watchdog.md names the rules this module enforces. A
spacecraft does not reason about a fault: a small deterministic monitor
holds declared limits, and when one trips the vehicle enters SAFE MODE -
sheds everything non-essential, keeps attitude control and the radio, and
waits for the ground. This module is that shape for a fleet:

  [agent.watchdog]        the owner's limits (settings.toml; enabled = false
                          by default, so nothing changes until turned on)
  evaluate(root, cfg)     reads ledgers the harness already writes - the
                          tail of logs/agent.log, the model-call ledger,
                          the disk - and names every limit that tripped
  safe_mode.json          CONTROL state: written by the harness when a limit
                          trips, cleared by the OWNER only. While it exists
                          the loop claims no task, stops a running task at
                          its next step boundary, keeps its heartbeat and
                          its model-free ticks (intentions arm, reconcilers
                          still keep the owner's invariants)
  logs/safe-mode.jsonl    every episode, entered and cleared, with reasons

No diagnosis lives here: the watchdog says WHICH limit tripped, never why.
No automatic recovery: a person clears the mode, by design.
"""
import argparse
import json
import os
import shutil
import sys
import time

sys_path_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, sys_path_dir)

MODE_FILE = "safe_mode.json"
EPISODES = os.path.join("logs", "safe-mode.jsonl")
TAIL_LINES = 4000
DEFAULTS = {"enabled": False, "window_calls": 50, "tool_error_rate_max": 0.6,
            "crash_max": 3, "refusal_streak_max": 8,
            "spend_usd_per_hour_max": 0.0, "disk_free_gb_min": 1.0,
            "window_s": 3600}
LIMITS = ("tool_error_rate_max", "crash_max", "refusal_streak_max",
          "spend_usd_per_hour_max", "disk_free_gb_min")


def limits(cfg):
    """The owner's limits over the defaults; a malformed value falls back
    to the default rather than disabling the monitor silently."""
    raw = ((cfg or {}).get("agent", {}) or {}).get("watchdog") or {}
    out = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = raw.get(key, default)
        if key == "enabled":
            out[key] = value is True
        elif isinstance(value, (int, float)) and not isinstance(value, bool) \
                and value >= 0:
            out[key] = value
    out["window_calls"] = max(1, int(out["window_calls"]))
    out["window_s"] = max(60, int(out["window_s"]))
    return out


# ------------------------------------------------------------- ledgers

def _tail(path, lines):
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, 512 * 1024)
            f.seek(size - block)
            data = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    return data.splitlines()[-lines:]


def _events(root, lines=TAIL_LINES):
    """(epoch, event dict) for every JSON line in the log tail; the loop
    writes `<ts> {json}` lines, and lines that are not JSON are skipped."""
    out = []
    for line in _tail(os.path.join(root, "logs", "agent.log"), lines):
        i = line.find("{")
        if i < 0 or not line.rstrip().endswith("}"):
            continue
        try:
            rec = json.loads(line[i:])
        except ValueError:
            continue
        try:
            ts = time.mktime(time.strptime(line[:19], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            ts = 0.0
        out.append((ts, rec))
    return out


def _is_error(result):
    import trace
    return bool(trace._is_error(str(result or "")))


def observe(root, cfg=None, now=None):
    """Every metric, from the ledgers, whether or not it trips."""
    lim = limits(cfg)
    now = time.time() if now is None else now
    events = _events(root)
    # tool error rate over the last window_calls tool results
    calls = [(ts, r) for ts, r in events
             if "step" in r and "tool" in r and "result" in r]
    window = calls[-lim["window_calls"]:]
    errors = sum(1 for _ts, r in window if _is_error(r.get("result")))
    errors += sum(1 for _ts, r in events[-len(window) * 4:]
                  if r.get("event") == "tool_error") if window else 0
    rate = (min(errors, len(window)) / len(window)) if window else 0.0
    # crashes inside the window
    crashes = sum(1 for ts, r in events
                  if r.get("event") == "step_crash" and now - ts <= lim["window_s"])
    # trailing done_refused streak, reset by a task starting or ending
    streak = 0
    for _ts, r in reversed(events):
        ev = r.get("event")
        if ev == "done_refused":
            streak += 1
        elif ev in ("task_end", "task_start", "task_resumed"):
            break
    # spend per hour from the model-call ledger over the window
    spend = 0.0
    try:
        with open(os.path.join(root, "logs", "model-calls.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    ts = time.mktime(time.strptime(rec.get("at", "")[:19],
                                                   "%Y-%m-%dT%H:%M:%S"))
                except (ValueError, TypeError):
                    continue
                if now - ts <= lim["window_s"]:
                    spend += float(rec.get("cost_usd") or 0.0)
    except OSError:
        pass
    per_hour = spend * 3600.0 / lim["window_s"]
    try:
        free_gb = shutil.disk_usage(root).free / float(1 << 30)
    except OSError:
        free_gb = float("inf")
    return {"tool_error_rate": round(rate, 4), "tool_calls_seen": len(window),
            "crashes": crashes, "refusal_streak": streak,
            "spend_usd_per_hour": round(per_hour, 6),
            "disk_free_gb": round(free_gb, 3), "limits": lim}


def evaluate(root, cfg=None, now=None):
    """-> {"enabled", "trips": [{limit, observed, max}], "observed": {...}}.
    Disabled = never trips, whatever the ledgers say; the metrics are still
    reported so an owner can see what would trip."""
    obs = observe(root, cfg, now)
    lim = obs["limits"]
    trips = []
    if lim["enabled"]:
        if obs["tool_calls_seen"] >= min(lim["window_calls"], 4) and \
                obs["tool_error_rate"] > lim["tool_error_rate_max"]:
            trips.append({"limit": "tool_error_rate_max",
                          "observed": obs["tool_error_rate"],
                          "max": lim["tool_error_rate_max"]})
        if obs["crashes"] >= lim["crash_max"] and lim["crash_max"] > 0:
            trips.append({"limit": "crash_max", "observed": obs["crashes"],
                          "max": lim["crash_max"]})
        if lim["refusal_streak_max"] > 0 and \
                obs["refusal_streak"] >= lim["refusal_streak_max"]:
            trips.append({"limit": "refusal_streak_max",
                          "observed": obs["refusal_streak"],
                          "max": lim["refusal_streak_max"]})
        if lim["spend_usd_per_hour_max"] > 0 and \
                obs["spend_usd_per_hour"] > lim["spend_usd_per_hour_max"]:
            trips.append({"limit": "spend_usd_per_hour_max",
                          "observed": obs["spend_usd_per_hour"],
                          "max": lim["spend_usd_per_hour_max"]})
        if lim["disk_free_gb_min"] > 0 and \
                obs["disk_free_gb"] < lim["disk_free_gb_min"]:
            trips.append({"limit": "disk_free_gb_min",
                          "observed": obs["disk_free_gb"],
                          "max": lim["disk_free_gb_min"]})
    return {"enabled": lim["enabled"], "trips": trips, "observed": obs}


# ------------------------------------------------------------ the mode

def _mode_path(root):
    return os.path.join(root, MODE_FILE)


def active(root):
    """The safe-mode record, or None. The FILE is the state: a process that
    restarts reads the same answer as the one that entered it."""
    try:
        with open(_mode_path(root), "r", encoding="utf-8") as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else {"at": "?", "trips": []}
    except (OSError, ValueError):
        return None


def _episode(root, row):
    p = os.path.join(root, EPISODES)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(row, at=time.strftime("%Y-%m-%dT%H:%M:%S")),
                           ensure_ascii=False) + "\n")


def enter(root, trips, by="watchdog"):
    """Enter safe mode. Idempotent: an existing episode is kept whole - the
    FIRST trip is the one to investigate, later ones are consequences."""
    existing = active(root)
    if existing:
        return existing
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": by,
           "trips": list(trips or []),
           "clear": "python watchdog.py clear --root <expert> --why '...'"}
    tmp = f"{_mode_path(root)}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    os.replace(tmp, _mode_path(root))
    _episode(root, {"event": "safe_mode_entered", "by": by, "trips": trips})
    return rec


def clear(root, why):
    """Leave safe mode. OWNER work, with a reason: clearing fault protection
    without saying why is how the next fault arrives unannounced."""
    import controlplane
    controlplane.owner_only("clear safe mode")
    if not (why or "").strip():
        raise ValueError("clearing safe mode needs --why")
    rec = active(root)
    if rec is None:
        raise ValueError("safe mode is not active")
    _episode(root, {"event": "safe_mode_cleared", "why": why.strip()[:300],
                    "entered_at": rec.get("at"), "trips": rec.get("trips")})
    os.remove(_mode_path(root))
    return rec


def check(root, cfg=None, now=None):
    """What the loop calls: evaluate, enter on a trip, report the mode.
    -> (mode or None, entered_now: bool)."""
    mode = active(root)
    if mode:
        return mode, False
    if not limits(cfg)["enabled"]:
        return None, False           # the FILE still rules; the monitor sleeps
    verdict = evaluate(root, cfg, now)
    if verdict["trips"]:
        return enter(root, verdict["trips"]), True
    return None, False


def enter_manually(root, why):
    """The owner's own safe mode: pause the fleet's model-driven work while
    the model-free machinery keeps running. Owner work, with a reason."""
    import controlplane
    controlplane.owner_only("enter safe mode")
    if not (why or "").strip():
        raise ValueError("entering safe mode needs --why")
    return enter(root, [{"limit": "owner", "observed": why.strip()[:200],
                         "max": None}], by="owner")


# --------------------------------------------------------------- owner CLI

def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(
        description="Watchdog and safe mode: declared limits with one "
                    "response the model cannot override (docs/DESIGN-P9b).")
    ap.add_argument("--root", required=True, help="the expert root")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="is safe mode active, and since when")
    sub.add_parser("evaluate", help="every metric now, and what would trip")
    c = sub.add_parser("clear", help="leave safe mode (owner, with a reason)")
    c.add_argument("--why", required=True)
    e = sub.add_parser("enter", help="enter safe mode by hand (owner, with a reason)")
    e.add_argument("--why", required=True)
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    import tomllib
    try:
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            cfg = tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    try:
        if args.cmd == "status":
            mode = active(root)
            print(json.dumps(mode, indent=1) if mode else "safe mode: not active")
        elif args.cmd == "evaluate":
            print(json.dumps(evaluate(root, cfg), indent=1))
        elif args.cmd == "enter":
            rec = enter_manually(root, args.why)
            print(f"safe mode entered at {rec['at']} by the owner: "
                  f"{args.why.strip()[:120]}")
        else:
            rec = clear(root, args.why)
            print(f"safe mode cleared (entered {rec.get('at')}: "
                  f"{', '.join(t['limit'] for t in rec.get('trips', []))})")
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
