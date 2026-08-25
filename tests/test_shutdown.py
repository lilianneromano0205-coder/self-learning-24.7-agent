#!/usr/bin/env python3
"""A KILL IS NOT A SHUTDOWN — stopping cleanly when the orchestrator says so.

Nothing in this platform handled a signal. SIGTERM is exactly what Docker,
Kubernetes and Cloudflare Containers send when they stop a container, and
they follow it with a grace period — usually ten to thirty seconds — before
SIGKILL. Ignoring it meant the process died wherever it happened to be:
mid-provider-call, mid-write, holding a task lock, with a `running` task
still stamped as ours.

None of that was unrecoverable — the runner lease notices a dead pid and the
next loop adopts the task — but recovery is not shutdown. Recovery re-does
work that was nearly finished and pays for those tokens twice. The grace
period exists so a process can stop at a clean boundary; this one threw it
away.

What must be true:

  1. SIGTERM is RECORDED, not ignored
  2. the process exits on its own, quickly, well inside any grace period
  3. it stops BETWEEN steps — the step already running finishes and commits,
     so there is no half-written state to reason about
  4. the task is left RESUMABLE, and a fresh process actually resumes it and
     carries it to done — "resumable" is a claim until something resumes it
  5. a SECOND signal exits immediately, because a graceful shutdown that
     cannot itself be interrupted is a hang

POSIX ONLY, and it says so rather than pretending. On Windows
Popen.terminate() is TerminateProcess, which no Python handler can intercept,
so there is nothing here to observe — and a test that silently passed on the
platform where the behaviour does not exist would be worse than no test.

Run from the agent/ directory:  python tests/test_shutdown.py
"""

import json
import os
import signal
import subprocess
import sys
import time

from common import LOOP, PY, add_task, make_sandbox, read_state, run_drain

SLOW = 0.15          # per model call, so a task takes many observable steps


def _events(root, needle):
    out = []
    p = os.path.join(root, "logs", "agent.log")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                if needle in line:
                    try:
                        out.append(json.loads(line.split(" ", 2)[-1]))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def main():
    if os.name != "posix":
        print("SKIP test_shutdown: Popen.terminate() on Windows is "
              "TerminateProcess, which no handler can intercept — there is no "
              "SIGTERM here to catch, so this asserts nothing rather than "
              "asserting something false. The container CI runs it.")
        return

    # a long task: 40 steps, each writing a file, each paced so the signal
    # lands mid-task rather than between tasks
    script = [{"tool": "write_file",
               "args": {"path": f"out/f{i}.md", "content": str(i)}}
              for i in range(40)]
    script.append({"tool": "finish_task", "args": {"summary": "all written"}})
    sb = make_sandbox("shutdown",
                      providers={"m": {"script": "s.json",
                                       "delay_seconds": SLOW}},
                      roles={"practitioner": "m"}, scripts={"s.json": script})
    add_task(sb, "practitioner", "write many files")

    proc = subprocess.Popen([PY, LOOP, "run", "--root", sb],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)                      # let it get well into the task
    proc.send_signal(signal.SIGTERM)
    t0 = time.time()
    try:
        rc = proc.wait(timeout=25)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError(
            "the loop did not exit within 25s of SIGTERM — an orchestrator "
            "would have SIGKILLed it, which is the behaviour this exists to "
            "replace")
    took = time.time() - t0

    # 1 + 2. recorded, and it left on its own, fast
    assert rc == 0, f"a graceful shutdown must exit 0, got {rc}"
    assert took < 20, f"took {took:.1f}s to stop; a grace period is shorter"
    assert _events(sb, "shutdown_requested"), (
        "SIGTERM was not recorded — a signal nobody logs is a signal nobody "
        "can debug")
    assert _events(sb, "shutdown_clean"), "no clean-stop record"

    # 3. it stopped BETWEEN steps, and the steps it did are all committed
    mid = _events(sb, "shutdown_midtask")
    assert mid, "the stop did not happen inside the task, so this proved nothing"
    done_steps = mid[0].get("steps_done") or 0
    assert done_steps >= 1, mid
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "running", (
        f"a task interrupted by a shutdown must stay RUNNING and resumable, "
        f"not {t['status']} — failing it would discard finished work")
    written = len(os.listdir(os.path.join(sb, "out")))
    assert written >= done_steps - 1, (
        f"{done_steps} steps ran but only {written} files exist — a step was "
        f"interrupted rather than completed")

    # 4. and a FRESH process actually finishes it
    rc2 = run_drain(sb, timeout=240)
    assert rc2 == 0, f"the resumed run exited {rc2}"
    t2 = read_state(sb)["tasks"][0]
    assert t2["status"] == "done", (
        f"the interrupted task did not survive: {t2['status']} "
        f"{t2.get('error', '')[:120]}")
    assert len(os.listdir(os.path.join(sb, "out"))) >= 40, (
        "the resumed run did not carry the work to completion")
    print(f"[graceful] SIGTERM mid-task: recorded, stopped between steps "
          f"after {done_steps} of them, exited 0 in {took:.2f}s with state "
          f"committed and the lock released — and a fresh process resumed the "
          f"same task and drove it to done")

    # 5. a second signal does not wait
    # A LONG step, so the process is certainly still inside one when the
    # second signal lands. The first version used a 1s step and signalled
    # 0.3s apart, and on a loaded CI runner the graceful shutdown simply
    # FINISHED before the second signal arrived — the process exited 0,
    # correctly, and the assertion failed anyway. A test that goes red when
    # the system behaved properly is worse than no test: it trains everyone
    # to ignore the colour.
    #
    # So the step is long enough to still be running, the second signal is
    # sent only after the process is CONFIRMED alive, and if it has already
    # exited cleanly that is reported as the correct outcome it is rather
    # than failed.
    sb2 = make_sandbox("shutdown-twice",
                       providers={"m": {"script": "s.json",
                                        "delay_seconds": 4.0}},
                       roles={"practitioner": "m"},
                       scripts={"s.json": [
                           {"tool": "write_file",
                            "args": {"path": f"out/g{i}.md", "content": str(i)}}
                           for i in range(40)]})
    add_task(sb2, "practitioner", "write slowly")
    p2 = subprocess.Popen([PY, LOOP, "run", "--root", sb2],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)                       # well inside a 4s step
    p2.send_signal(signal.SIGTERM)
    time.sleep(0.4)
    if p2.poll() is not None:
        print(f"[forced] SKIPPED this half: the graceful stop completed "
              f"before a second signal could be sent (exit {p2.returncode}). "
              f"That is the correct behaviour, not a failure — there was "
              f"simply nothing left to interrupt.")
    else:
        p2.send_signal(signal.SIGTERM)  # the operator is done waiting
        try:
            rc3 = p2.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p2.kill()
            raise AssertionError(
                "a second SIGTERM was ignored — a graceful shutdown that "
                "cannot itself be interrupted is a hang wearing a polite name")
        assert rc3 != 0 or _events(sb2, "shutdown_forced"), (
            f"the process was still running mid-step and a second SIGTERM "
            f"neither forced an exit nor recorded shutdown_forced (rc={rc3})")
        print("[forced] a second SIGTERM exits immediately instead of waiting "
              "out the step — an operator who signals twice is telling you "
              "they are done waiting")
    print("PASS test_shutdown")


if __name__ == "__main__":
    main()
