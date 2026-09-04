#!/usr/bin/env python3
"""CHAOS: attack the platform on purpose and watch what survives (P0).

A green suite proves the paths we thought to write down. This one attacks the
paths nobody writes down: kill the process mid-task, corrupt every ledger in
turn, break the provider, run two loops at the same expert, fail the disk,
hand it an absurd input, move the clock.

The bar is not "no errors". The bar is: FAIL LOUDLY, LOSE NOTHING, KEEP
RUNNING. Every assertion below states which of those three it is checking.

Run from the agent/ directory:  python tests/test_chaos.py
"""

import json
import os
import subprocess
import sys
import time

from common import AGENT_DIR, LOOP, PY, agent_setting, make_sandbox, \
    read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import loop

SLOW = [{"tool": "write_file", "args": {"path": "out/a.txt", "content": "x"}},
        {"tool": "write_file", "args": {"path": "out/b.txt", "content": "y"}},
        {"tool": "write_file", "args": {"path": "out/c.txt", "content": "z"}},
        {"tool": "finish_task", "args": {"summary": "done"}}]


def write(root, rel, text):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def main():
    # ---------------------------------------------------------------- 1
    # kill -9 mid-task: the work resumes, the state is never torn
    sb = make_sandbox("chaos_kill", providers={"m": {"script": "s.json",
                                                     "delay_seconds": 0.4}},
                      roles={"tester": "m"}, scripts={"s.json": SLOW})
    loop.Agent(sb).add_task("tester", "survive being killed")
    proc = subprocess.Popen([PY, LOOP, "run", "--drain", "--root", sb],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Wait for the first step to land before killing. The window is generous
    # on purpose: this test is about surviving a kill, not about how fast a
    # loaded machine gets to its first step, and a tight bound here would
    # make the suite fail for a reason that has nothing to do with the
    # invariant.
    deadline = time.time() + 120
    stepped = False
    raced = 0
    while time.time() < deadline:
        # The child replaces state.json (temp file + os.replace) on every
        # step, so a poll that lands inside the replace is the reader racing
        # the writer, not a torn file: on Windows open() raises
        # PermissionError while the rename holds the target (CI run
        # 33776721150, job 100720144752), and a half-visible file would
        # raise JSONDecodeError. Retry for the rest of the deadline. The read
        # AFTER the kill below has no writer to race and stays strict.
        try:
            st = read_state(sb)
        except (json.JSONDecodeError, OSError):
            raced += 1
            time.sleep(0.05)
            continue
        if st["tasks"] and st["tasks"][0].get("steps"):
            stepped = True
            break
        time.sleep(0.2)
    proc.kill()                      # SIGKILL equivalent: no cleanup runs
    proc.wait(timeout=60)
    st = read_state(sb)              # must still parse: never a torn file
    assert isinstance(st.get("tasks"), list), "state.json was left torn"
    assert run_drain(sb) == 0, "the loop must pick the work back up"
    t = read_state(sb)["tasks"][0]
    assert t["status"] == "done", (
        f"after kill -9 the task must still finish; status={t['status']!r} "
        f"error={(t.get('error') or '')[:200]!r} "
        f"(a step had{'' if stepped else ' NOT'} started before the kill)")
    for f in ("out/a.txt", "out/b.txt", "out/c.txt"):
        assert os.path.exists(os.path.join(sb, f.replace("/", os.sep))), f
    print(f"[kill] killed mid-task with no cleanup: state parsed, the task "
          f"resumed and finished, every artifact landed; {raced} poll "
          f"read(s) raced the writer's replace and were retried, not failed")

    # ---------------------------------------------------------------- 2
    # every ledger corrupted in turn: quarantine or ignore, never a crash
    survived = []
    for rel, garbage in (("state.json", "{not json at all"),
                         ("skills/graph.json", "]]]broken["),
                         ("prospective.json", "{"),
                         ("logs/effects.jsonl", "not-a-json-line\n"),
                         ("courses/c/sources.json", "@@@"),
                         ("courses/c/conflicts.json", "%%%")):
        sbx = make_sandbox(f"chaos_led_{rel.split('/')[-1].split('.')[0]}",
                           providers={"m": {"script": "s.json"}},
                           roles={"tester": "m"},
                           scripts={"s.json": SLOW})
        write(sbx, "courses/c/notes.md", "- C-0101 a fact [src: https://x.dev]\n")
        loop.Agent(sbx).add_task("tester", "work despite a corrupt ledger",
                                 course="c")
        write(sbx, rel, garbage)
        rc = run_drain(sbx)
        assert rc == 0, f"a corrupt {rel} killed the loop (rc={rc})"
        survived.append(rel)
        if rel == "state.json":
            # the queue is quarantined for forensics, not silently dropped
            quarantined = [n for n in os.listdir(sbx)
                           if n.startswith("state.json.corrupt-")]
            assert quarantined, "a corrupt queue must be kept for forensics"
            with open(os.path.join(sbx, "logs", "agent.log"),
                      encoding="utf-8") as f:
                assert '"state_corrupt"' in f.read()
    print(f"[ledgers] {len(survived)} corrupted ledgers, zero crashes; the "
          f"queue was quarantined rather than discarded")

    # ---------------------------------------------------------------- 3
    # the provider dies: the fallback carries the work
    sb3 = make_sandbox("chaos_provider",
                       providers={"dead": {"script": "s.json"},
                                  "alive": {"script": "s.json"}},
                       roles={"tester": "dead"}, scripts={"s.json": SLOW})
    cfg = os.path.join(sb3, "settings.toml")
    body = open(cfg, encoding="utf-8").read()
    # point the primary at a port nothing listens on, keep a working fallback
    body = body.replace('[providers.dead]\ntype = "mock"',
                        '[providers.dead]\ntype = "openai"\n'
                        'base_url = "http://127.0.0.1:9"\n'
                        'api_key_env = "NOPE_KEY"')
    body = body.replace('[roles.tester]\nprovider = "dead"',
                        '[roles.tester]\nprovider = "dead"\n'
                        'fallback_provider = "alive"\nfallback_model = "mock"')
    open(cfg, "w", encoding="utf-8").write(body)
    agent_setting(sb3, "model_timeout_seconds = 5")
    loop.Agent(sb3).add_task("tester", "survive a dead provider")
    assert run_drain(sb3) == 0
    t3 = read_state(sb3)["tasks"][0]
    assert t3["status"] == "done", f"the fallback did not carry it: {t3}"
    assert t3.get("provider") == "alive", t3.get("provider")
    print("[provider] the primary provider refused every connection; the "
          "fallback finished the task and the record names which one ran")

    # ---------------------------------------------------------------- 4
    # two loops, one expert: every task runs exactly once
    sb4 = make_sandbox("chaos_race", providers={"m": {"script": "s.json",
                                                      "delay_seconds": 0.2}},
                       roles={"tester": "m"}, scripts={"s.json": SLOW})
    a4 = loop.Agent(sb4)
    for i in range(4):
        a4.add_task("tester", f"racing job {i}")
    procs = [subprocess.Popen([PY, LOOP, "run", "--drain", "--root", sb4],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL) for _ in range(2)]
    for p in procs:
        p.wait(timeout=180)
    tasks = read_state(sb4)["tasks"]
    assert len(tasks) == 4, f"tasks were duplicated or lost: {len(tasks)}"
    assert all(t["status"] == "done" for t in tasks), \
        [(t["goal"], t["status"]) for t in tasks]
    ids = [t["id"] for t in tasks]
    assert len(set(ids)) == 4, "the same task was claimed twice"
    for t in tasks:
        assert len(t["steps"]) == 4, \
            f"a task ran more than once: {len(t['steps'])} steps"
    print("[race] two loops drained one expert at the same time: four tasks, "
          "four completions, no task claimed twice")

    # ---------------------------------------------------------------- 5
    # the disk refuses the write: the OLD state survives intact
    sb5 = make_sandbox("chaos_disk", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": SLOW})
    a5 = loop.Agent(sb5)
    a5.add_task("tester", "the state that must not be lost")
    before = open(a5.state_path, encoding="utf-8").read()
    real_replace = os.replace

    def enospc(src, dst, *a, **k):
        if str(dst).endswith("state.json"):
            raise OSError(28, "No space left on device")
        return real_replace(src, dst, *a, **k)

    os.replace = enospc
    try:
        try:
            a5.save_state(a5.load_state())
            raise AssertionError("a failed write must not report success")
        except OSError as e:
            assert e.errno == 28
    finally:
        os.replace = real_replace
    after = open(a5.state_path, encoding="utf-8").read()
    assert after == before, "a failed write corrupted the previous state"
    assert json.loads(after)["tasks"], "the queue survived the failed write"
    assert run_drain(sb5) == 0 and \
        read_state(sb5)["tasks"][0]["status"] == "done"
    print("[disk] a write that failed with ENOSPC left the previous state "
          "byte-identical and the loop recovered")

    # ---------------------------------------------------------------- 6
    # an absurd input: the budgets bind instead of the window exploding
    sb6 = make_sandbox("chaos_size", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": SLOW})
    import context
    huge = write(sb6, "material/huge.md", "PAYLOAD " * 1_400_000)   # ~11 MB
    assert os.path.getsize(huge) > 10_000_000
    write(sb6, "courses/big/notes.md",
          "".join(f"- C-{i:04d} fact number {i} [src: https://x.dev]\n"
                  for i in range(1000)))
    for i in range(200):
        write(sb6, f"skills/skill-{i}.md", f"KEYWORDS: k{i}\nbody {i}\n")
    started = time.time()
    msgs, man = context.compile(loop.Agent(sb6), {
        "id": "t-huge", "role": "tester", "course": "big",
        "goal": "summarise the huge file", "memory_files": ["material/huge.md"]})
    elapsed = time.time() - started
    window = len(msgs[1]["content"])
    assert window < 400_000, f"the window was not bounded: {window} chars"
    assert man["total_tokens"] < 60_000, man["total_tokens"]
    assert elapsed < 60, f"compiling took {elapsed:.1f}s"
    assert "[...trimmed:" in msgs[1]["content"], "the cut must be marked"
    print(f"[size] an 11 MB file, 1,000 atoms and 200 skills compiled to a "
          f"{man['total_tokens']} token window in {elapsed:.1f}s, cut marked")

    # ---------------------------------------------------------------- 7
    # the clock moves: stop conditions still mean what they say
    sb7 = make_sandbox("chaos_clock", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": SLOW})
    a7 = loop.Agent(sb7)
    a7.add_task("tester", "deadline far in the future",
                stop={"deadline": "2099-01-01T00:00:00"})
    a7.add_task("tester", "deadline long past",
                stop={"deadline": "1999-01-01T00:00:00"})
    assert run_drain(sb7) == 0
    by_goal = {t["goal"]: t for t in read_state(sb7)["tasks"]}
    future = by_goal["deadline far in the future"]
    past = by_goal["deadline long past"]
    assert future["status"] == "done", future["status"]
    assert past["status"] == "failed" and "stop condition" in past["error"]
    print("[clock] a far-future deadline ran to completion and a long-past "
          "one refused to start, both naming the reason")
    print("PASS test_chaos")


if __name__ == "__main__":
    main()
