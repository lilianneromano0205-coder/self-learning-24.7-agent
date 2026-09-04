#!/usr/bin/env python3
"""Phase 9b exit benchmark — watchdog and safe mode, held green.

docs/DESIGN-P9b-watchdog.md preregistered exactly this: fault protection
beneath the model must show, before it becomes permanent, that

  1. CONTROL STATE   safe_mode.json is CONTROL (agent write refused,
                     harness allowed), enumerated in the leakage suite;
                     clear refuses inside an agent task, without a reason,
                     and when nothing is active
  2. LIMITS          from synthetic ledgers: a tool-error rate trips above
                     the ceiling and not at it; crashes inside the window
                     trip, old ones do not; a refusal streak trips, a broken
                     one does not; spend velocity trips; disabled never
                     trips; every metric is reported regardless
  3. LIFECYCLE       enter keeps the first episode; clear (owner, with a
                     reason) archives it and removes the mode
  4. SHED            with safe mode active a queued task is not claimed;
                     the loop says so, keeps its heartbeat and, draining,
                     returns; after clear the same task runs to done
  5. LIVE TRIP       a task that claims done twice against a failing gate
                     enters safe mode mid-task and stops at the boundary,
                     left running (not failed); after clear it resumes,
                     takes its next scripted step and finishes
  6. INVARIANTS      a reconciler still repairs a drift during safe mode
  7. REGISTRATION    run_all, evidence, proof, doctor, the manual

Run from the agent/ directory:  python tests/test_watchdog.py
"""
import io
import json
import os
import sys
import time

from common import AGENT_DIR, PY, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import doctor                   # noqa: E402
import fileauth                 # noqa: E402
import fleet                    # noqa: E402
import loop                     # noqa: E402
import reconciler               # noqa: E402
import runbook                  # noqa: E402
import watchdog                 # noqa: E402

PIN = '''import os, sys
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "config.txt")
os.makedirs(os.path.dirname(p), exist_ok=True)
open(p, "w", encoding="utf-8").write(sys.argv[1] + "\\n")
'''
CHECK = '''import os, sys
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "config.txt")
try:
    sys.exit(0 if open(p, encoding="utf-8").read() == sys.argv[1] + "\\n" else 1)
except OSError:
    sys.exit(1)
'''
WATCH = ['[agent.watchdog]', 'enabled = true', 'window_calls = 4',
         'tool_error_rate_max = 0.5', 'crash_max = 2',
         'refusal_streak_max = 3', 'spend_usd_per_hour_max = 1.0',
         'disk_free_gb_min = 0', 'window_s = 3600', '']


def _settings(root, providers, watch=None, max_done_rejects=2):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         f'max_done_rejects = {max_done_rejects}', 'max_task_retries = 0', '']
    s += list(watch or [])
    for name in providers:
        s += [f'[providers.{name}]', 'type = "mock"',
              f'script = "scripts/{name}.json"', '']
    s += ['[roles.default]', f'provider = "{providers[0]}"', 'model = "mock"', '']
    for name in providers:
        s += [f'[roles.r_{name}]', f'provider = "{name}"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)


def _script(root, name, steps):
    json.dump(steps, io.open(os.path.join(root, "scripts", f"{name}.json"),
                             "w", encoding="utf-8"))


def _desk(home, name, watch=None, max_done_rejects=2):
    root = fleet.create(home, name, "a fleet with fault protection")
    _settings(root, ["m"], watch, max_done_rejects)
    _script(root, "m", [])
    io.open(os.path.join(root, "pin.py"), "w", encoding="utf-8").write(PIN)
    io.open(os.path.join(root, "checkpin.py"), "w", encoding="utf-8").write(CHECK)
    return root


def _stamp(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) + ",000"


def _log(root, rows):
    """rows: [(epoch, dict)] -> logs/agent.log in the loop's own line shape."""
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with io.open(os.path.join(root, "logs", "agent.log"), "w",
                 encoding="utf-8") as f:
        for ts, rec in rows:
            f.write(f"{_stamp(ts)} {json.dumps(rec)}\n")


def _calls(root, rows):
    os.makedirs(os.path.join(root, "logs"), exist_ok=True)
    with io.open(os.path.join(root, "logs", "model-calls.jsonl"), "w",
                 encoding="utf-8") as f:
        for ts, usd in rows:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S",
                                                    time.localtime(ts)),
                                "purpose": "step", "cost_usd": usd}) + "\n")


def _step(ts, result):
    return (ts, {"task": "t1", "role": "r_m", "step": 1, "provider": "m",
                 "tool": "run_command", "args": "{}", "result": result,
                 "status": "running"})


def _trips(verdict):
    return sorted(t["limit"] for t in verdict["trips"])


def _cfg(root):
    import tomllib
    with open(os.path.join(root, "settings.toml"), "rb") as f:
        return tomllib.loads(f.read().decode("utf-8-sig"))


# ------------------------------------------------------------ 1 control
def check_control_state(root):
    assert fileauth.zone_of("safe_mode.json") == fileauth.ZONE_CONTROL
    try:
        fileauth.resolve(root, "safe_mode.json", "write", "agent")
    except fileauth.Denied:
        pass
    else:
        raise AssertionError("the agent may write the safe-mode switch")
    assert fileauth.resolve(root, "safe_mode.json", "write", "harness")
    suite = io.open(os.path.join(AGENT_DIR, "tests", "test_promotion_leakage.py"),
                    encoding="utf-8").read()
    assert "safe_mode.json" in suite
    try:
        watchdog.clear(root, "nothing to clear")
    except ValueError as exc:
        assert "not active" in str(exc), exc
    else:
        raise AssertionError("clearing an inactive mode must refuse")
    watchdog.enter(root, [{"limit": "manual", "observed": 1, "max": 0}], by="test")
    os.environ["AGENT_TASK_ID"], os.environ["AGENT_ROLE"] = "t1", "practitioner"
    try:
        try:
            watchdog.clear(root, "an agent clearing its own fault protection")
        except SystemExit as exc:
            assert "REFUSED" in str(exc), exc
        else:
            raise AssertionError("an agent task cleared safe mode")
    finally:
        os.environ.pop("AGENT_TASK_ID", None)
        os.environ.pop("AGENT_ROLE", None)
    try:
        watchdog.clear(root, "   ")
    except ValueError as exc:
        assert "why" in str(exc), exc
    else:
        raise AssertionError("clearing without a reason must refuse")
    assert watchdog.active(root)
    watchdog.clear(root, "test teardown")
    assert watchdog.active(root) is None
    print("[control] safe_mode.json is CONTROL (agent refused, harness "
          "allowed) and enumerated; clearing refuses inside an agent task, "
          "without a reason, and when nothing is active")


# ------------------------------------------------------------ 2 limits
def check_limits_from_ledgers(root):
    now = time.time()
    cfg = _cfg(root)
    # tool error rate: 3 of the last 4 results are errors -> 0.75 > 0.5
    _log(root, [_step(now - 50, "exit=1\n--- stdout ---\nboom"),
                _step(now - 40, "ok"),
                _step(now - 30, "ERROR: refused"),
                _step(now - 20, "exit=2\n--- stdout ---\n")])
    v = watchdog.evaluate(root, cfg, now)
    assert _trips(v) == ["tool_error_rate_max"], v["trips"]
    assert v["observed"]["tool_error_rate"] == 0.75
    # exactly at the ceiling (2 of 4) does not trip
    _log(root, [_step(now - 50, "exit=1\nx"), _step(now - 40, "ok"),
                _step(now - 30, "ok"), _step(now - 20, "ERROR: y")])
    assert _trips(watchdog.evaluate(root, cfg, now)) == []
    # crashes: two inside the window trip; two older than the window do not
    _log(root, [(now - 100, {"event": "step_crash", "task": "a", "error": "x"}),
                (now - 90, {"event": "step_crash", "task": "b", "error": "y"})])
    assert _trips(watchdog.evaluate(root, cfg, now)) == ["crash_max"]
    _log(root, [(now - 7200, {"event": "step_crash", "task": "a", "error": "x"}),
                (now - 7100, {"event": "step_crash", "task": "b", "error": "y"})])
    assert _trips(watchdog.evaluate(root, cfg, now)) == []
    # refusal streak: three trailing done_refused trip; a task_start between
    # them breaks the streak
    ref = {"event": "done_refused", "task": "t1"}
    _log(root, [(now - 60, {"event": "task_start", "task": "t1"}),
                (now - 50, ref), (now - 40, ref), (now - 30, ref)])
    v = watchdog.evaluate(root, cfg, now)
    assert _trips(v) == ["refusal_streak_max"] and \
        v["observed"]["refusal_streak"] == 3, v
    _log(root, [(now - 60, ref), (now - 50, ref),
                (now - 40, {"event": "task_start", "task": "t2"}),
                (now - 30, ref)])
    assert _trips(watchdog.evaluate(root, cfg, now)) == []
    # spend velocity over the window: 1.2 USD in the last hour > 1.0
    _log(root, [])
    _calls(root, [(now - 600, 0.6), (now - 1200, 0.6), (now - 9000, 5.0)])
    v = watchdog.evaluate(root, cfg, now)
    assert _trips(v) == ["spend_usd_per_hour_max"] and \
        abs(v["observed"]["spend_usd_per_hour"] - 1.2) < 1e-6, v
    # every metric is reported, and a disabled watchdog never trips
    for key in ("tool_error_rate", "crashes", "refusal_streak",
                "spend_usd_per_hour", "disk_free_gb"):
        assert key in v["observed"], key
    off = json.loads(json.dumps(cfg))
    off["agent"]["watchdog"]["enabled"] = False
    v2 = watchdog.evaluate(root, off, now)
    assert v2["enabled"] is False and v2["trips"] == [] and \
        v2["observed"]["spend_usd_per_hour"] == v["observed"]["spend_usd_per_hour"]
    _calls(root, [])
    print("[limits] from the ledgers alone: a tool-error rate tripped above "
          "its ceiling and not at it, crashes inside the window tripped and "
          "old ones did not, a refusal streak tripped and a broken one did "
          "not, spend velocity tripped; disabled never trips and still reports")


# ------------------------------------------------------------ 3 lifecycle
def check_lifecycle(root):
    first = watchdog.enter(root, [{"limit": "crash_max", "observed": 2, "max": 2}])
    again = watchdog.enter(root, [{"limit": "spend_usd_per_hour_max",
                                   "observed": 9, "max": 1}])
    assert again == first and watchdog.active(root)["trips"][0]["limit"] == "crash_max", \
        "a second trip must not overwrite the first episode"
    mode, entered = watchdog.check(root, _cfg(root))
    assert mode and not entered
    watchdog.clear(root, "investigated: a flapping disk")
    assert watchdog.active(root) is None
    rows = [json.loads(l) for l in io.open(
        os.path.join(root, "logs", "safe-mode.jsonl"), encoding="utf-8")]
    kinds = [r["event"] for r in rows]
    assert kinds[-2:] == ["safe_mode_entered", "safe_mode_cleared"], kinds
    assert rows[-1]["why"] == "investigated: a flapping disk"
    print("[lifecycle] enter kept the first episode whole, check reported it "
          "without re-entering, clear archived it with the reason and removed "
          "the mode")


# ------------------------------------------------------------ 4 shed
def check_loop_sheds_work(home):
    root = _desk(home, "Shedding Desk")
    _script(root, "m", [{"tool": "finish_task", "args": {"summary": "done"}}])
    agent = loop.Agent(root)
    tid = agent.add_task("r_m", "say done")
    watchdog.enter(root, [{"limit": "manual", "observed": 1, "max": 0}], by="owner")
    assert run_drain(root, timeout=120) == 0
    task = loop.Agent(root).find_task(tid)
    assert task["status"] == "queued", task["status"]
    log = io.open(os.path.join(root, "logs", "agent.log"), encoding="utf-8",
                  errors="replace").read()
    assert '"event": "safe_mode_active"' in log and \
        '"event": "drain_safe_mode_stop"' in log, log[-800:]
    hb = json.load(io.open(os.path.join(root, "logs", "heartbeat.json"),
                           encoding="utf-8"))
    assert "safe_mode" in hb.get("note", ""), hb
    watchdog.clear(root, "cleared for the test")
    assert run_drain(root, timeout=120) == 0
    assert loop.Agent(root).find_task(tid)["status"] == "done"
    print("[shed] with safe mode active the loop claimed nothing, said so, "
          "kept its heartbeat and returned from the drain; cleared, the same "
          "task ran to done")


# ------------------------------------------------------------ 5 live trip
def check_live_trip_stops_at_boundary(home):
    watch = ['[agent.watchdog]', 'enabled = true', 'refusal_streak_max = 2',
             'window_calls = 50', 'tool_error_rate_max = 1.0', 'crash_max = 0',
             'spend_usd_per_hour_max = 0', 'disk_free_gb_min = 0', '']
    root = _desk(home, "Tripping Desk", watch, max_done_rejects=5)
    _script(root, "m", [
        {"tool": "finish_task", "args": {"summary": "done?"}},
        {"tool": "finish_task", "args": {"summary": "done??"}},
        {"tool": "write_file", "args": {"path": "out/config.txt",
                                        "content": "v1\n"}},
        {"tool": "finish_task", "args": {"summary": "done, really"}}])
    agent = loop.Agent(root)
    tid = agent.add_task("r_m", "pin the config",
                         done_check=f'"{PY}" checkpin.py v1')
    assert run_drain(root, timeout=120) == 0
    task = loop.Agent(root).find_task(tid)
    assert task["status"] == "running", task["status"]
    mode = watchdog.active(root)
    assert mode and mode["trips"][0]["limit"] == "refusal_streak_max", mode
    log = io.open(os.path.join(root, "logs", "agent.log"), encoding="utf-8",
                  errors="replace").read()
    assert '"event": "safe_mode_entered"' in log and \
        '"event": "safe_mode_midtask"' in log
    assert not os.path.exists(os.path.join(root, "out", "config.txt")), \
        "the loop must have stopped BEFORE the next scripted step"
    watchdog.clear(root, "the gate was right; letting it continue")
    assert run_drain(root, timeout=120) == 0
    task = loop.Agent(root).find_task(tid)
    assert task["status"] == "done", task
    assert io.open(os.path.join(root, "out", "config.txt"),
                   encoding="utf-8").read() == "v1\n"
    assert watchdog.active(root) is None, "a resumed task must not re-trip on the old streak"
    print("[live-trip] two consecutive refused finishes tripped the streak "
          "limit mid-task; the loop stopped at the step boundary with the "
          "task resumable; cleared, it resumed, wrote the file and finished")


# ------------------------------------------------------------ 6 invariants
def check_invariants_survive_safe_mode(home):
    root = _desk(home, "Steady Desk")
    os.makedirs(os.path.join(root, "runbooks"), exist_ok=True)
    with open(runbook.path(root, "pin-config"), "w", encoding="utf-8") as f:
        json.dump({"name": "pin-config", "triggers": ["pin config"],
                   "steps": [{"do": f'"{PY}" pin.py v1',
                              "verify": f'"{PY}" checkpin.py v1'}]}, f)
    cfg_path = os.path.join(root, "out", "config.txt")
    for _ in range(runbook.PROMOTE_WINS):
        r = runbook.run(root, "pin-config", allow_candidate=True,
                        accept=lambda: io.open(cfg_path, encoding="utf-8").read() == "v1\n")
        assert r["ok"] and r["accepted"], r
    io.open(cfg_path, "w", encoding="utf-8").write("v0\n")
    reconciler.add(root, "config-pinned",
                   [{"predicate": "file_equals", "path": "out/config.txt",
                     "value": "v1\n"}], "pin-config", every_s=60)
    watchdog.enter(root, [{"limit": "manual", "observed": 1, "max": 0}], by="owner")
    assert run_drain(root, timeout=120) == 0
    assert io.open(cfg_path, encoding="utf-8").read() == "v1\n"
    log = io.open(os.path.join(root, "logs", "agent.log"), encoding="utf-8",
                  errors="replace").read()
    assert '"event": "reconciler_repaired"' in log and \
        '"event": "drain_safe_mode_stop"' in log
    watchdog.clear(root, "test teardown")
    print("[invariants] in safe mode the loop still ran the model-free "
          "reconciler: the drifted file was restored while no task was claimed")


# ------------------------------------------------------------ 7 registration
def check_registration():
    me = os.path.basename(__file__)
    for name in ("tests/run_all.py", "evidence.py", "proof.py"):
        text = io.open(os.path.join(AGENT_DIR, name), encoding="utf-8").read()
        assert me in text, f"{me} is not declared in {name}"
    manual = io.open(os.path.join(AGENT_DIR, "MANUAL.md"), encoding="utf-8").read()
    assert "python watchdog.py" in manual
    assert "watchdog" in doctor.CORE_MODULES
    settings = io.open(os.path.join(AGENT_DIR, "settings.toml"),
                       encoding="utf-8").read()
    assert "[agent.watchdog]" in settings
    print("[registration] the benchmark is declared in run_all, evidence and "
          "proof; the manual names the commands; the doctor imports the "
          "module; settings.toml documents the limits")


def main():
    home = make_sandbox("watchdog", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = _desk(home, "Limits Desk", WATCH)
    check_control_state(root)
    check_limits_from_ledgers(root)
    check_lifecycle(root)
    check_loop_sheds_work(home)
    check_live_trip_stops_at_boundary(home)
    check_invariants_survive_safe_mode(home)
    check_registration()
    print("PASS test_watchdog")


if __name__ == "__main__":
    main()
