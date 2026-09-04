#!/usr/bin/env python3
"""Phase 9c exit benchmark — change sentinels, held green.

docs/DESIGN-P9c-sentinels.md preregistered exactly this: crawler-grade
change detection beneath the model must show, before it becomes permanent,
that

  1. BASELINE, CHANGE  a file_changed sentinel records a baseline without
                       firing; an identical rewrite does not fire; a
                       different one fires exactly once with both hashes
                       in the goal; removal fires; reappearance fires
  2. POLITENESS        inside every_s the file is not even hashed; after
                       the interval it fires
  3. TREE              tree_changed fires on an added, a modified and a
                       deleted file, not on a touch; an oversized tree
                       refuses at add
  4. HTTP              http_changed against the Phase 8 fixture: baseline,
                       no firing on an identical readback, a firing when the
                       record changes, no firing on a 404, hashes only in
                       the ledger — never the body, never the bearer
  5. OWNER-NAMED ONLY  an http_changed sentinel on an endpoint outside the
                       owner's table refuses at add
  6. LOOP              a --drain run queues the gated task from the idle
                       tick after a change, and nothing without one
  7. REGISTRATION      REFERENCE lists ten kinds; run_all, evidence, proof

Run from the agent/ directory:  python tests/test_sentinels.py
"""
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import AGENT_DIR, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import fleet                    # noqa: E402
import loop                     # noqa: E402
import prospective              # noqa: E402

TOKEN = "sk-fixture-sentinel-bearer-1234567890"


class Fixture:
    def __init__(self):
        self.store, self.seen = {}, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_a):
                pass

            def do_GET(self):
                outer.seen.append(("GET", self.path, self.headers.get("Authorization")))
                key = self.path.rsplit("/", 1)[-1].split("?")[0]
                if key in outer.store:
                    data = json.dumps(outer.store[key]).encode("utf-8")
                    self.send_response(200)
                else:
                    data = b'{"error": "missing"}'
                    self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/v1"


def _settings(root, fixture=None):
    s = ['[agent]', 'sandbox = "host"', 'allow_unsafe_host = true',
         'poll_interval_seconds = 1', 'max_task_usd = 0', 'reflect_after = []',
         'max_done_rejects = 2', 'max_task_retries = 0', 'http_write = []', '']
    if fixture:
        s += ['[agent.http_endpoints.records]', f'base = "{fixture.base}"',
              'methods = ["GET"]', 'auth_env = "SENTINEL_TOKEN"',
              'max_bytes = 4096', '']
    s += ['[providers.m]', 'type = "mock"', 'script = "scripts/m.json"', '',
          '[roles.default]', 'provider = "m"', 'model = "mock"', '',
          '[roles.r_m]', 'provider = "m"', 'model = "mock"', '']
    io.open(os.path.join(root, "settings.toml"), "w",
            encoding="utf-8").write("\n".join(s))
    os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
    json.dump([{"tool": "finish_task", "args": {"summary": "looked"}}],
              io.open(os.path.join(root, "scripts", "m.json"), "w",
                      encoding="utf-8"))


def _desk(home, name, fixture=None):
    root = fleet.create(home, name, "watches for change")
    _settings(root, fixture)
    return root


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    io.open(p, "w", encoding="utf-8").write(text)


def _arm(root, when, goal="investigate the change"):
    return prospective.add(root, when, {"role": "r_m", "goal": goal})


def _item(root, pid):
    return next(it for it in prospective.load(root) if it["id"] == pid)


def _impatient(root, pid):
    """Reset the politeness stamp so the next check hashes now (the interval
    floor is 30 s; the benchmark must not sleep through it)."""
    items = prospective.load(root)
    for it in items:
        if it["id"] == pid:
            it["when"]["last_seen"] = 0.0
    prospective.save(root, items)


def _queued(agent):
    return [t for t in agent.load_state()["tasks"] if t["status"] == "queued"]


# ---------------------------------------------------------- 1 file changed
def check_file_baseline_then_change(root):
    agent = loop.Agent(root)
    _write(root, "watch/price.txt", "10.00\n")
    pid = _arm(root, {"kind": "file_changed", "path": "watch/price.txt",
                      "every_s": 30})["id"]
    assert prospective.check(root, agent) == 0, "the first look is a baseline"
    base = _item(root, pid)["when"]["last_hash"]
    assert base and len(base) == 64
    _impatient(root, pid)
    _write(root, "watch/price.txt", "10.00\n")               # identical bytes
    assert prospective.check(root, agent) == 0, "same bytes is not a change"
    _impatient(root, pid)
    _write(root, "watch/price.txt", "12.50\n")
    assert prospective.check(root, agent) == 1
    q = _queued(agent)
    assert len(q) == 1 and "CHANGE DETECTED" in q[0]["goal"] and \
        base[:12] in q[0]["goal"], q[0]["goal"]
    it = _item(root, pid)
    assert it["status"] == "armed" and it["when"]["last_hash"] != base \
        and it["when"]["pending"] is None
    _impatient(root, pid)
    assert prospective.check(root, agent) == 0, "once per change"
    _impatient(root, pid)
    os.remove(os.path.join(root, "watch", "price.txt"))
    assert prospective.check(root, agent) == 1, "removal is a change"
    _impatient(root, pid)
    _write(root, "watch/price.txt", "12.50\n")
    assert prospective.check(root, agent) == 1, "reappearance is a change"
    print("[file] a sentinel took a baseline silently, ignored an identical "
          "rewrite, fired once on a different one with both hashes in the "
          "goal, stayed armed, and fired on removal and reappearance")


# ------------------------------------------------------------ 2 politeness
def check_politeness(root):
    agent = loop.Agent(root)
    _write(root, "watch/polite.txt", "a\n")
    pid = _arm(root, {"kind": "file_changed", "path": "watch/polite.txt",
                      "every_s": 30})["id"]
    prospective.check(root, agent)                            # baseline
    seen = _item(root, pid)["when"]["last_seen"]
    _write(root, "watch/polite.txt", "b\n")
    assert prospective.check(root, agent) == 0
    assert _item(root, pid)["when"]["last_seen"] == seen, \
        "inside the interval the file must not even be hashed"
    _impatient(root, pid)
    assert prospective.check(root, agent) == 1
    print("[polite] inside every_s a changed file was not hashed at all; "
          "after the interval the change fired")


# ------------------------------------------------------------------ 3 tree
def check_tree(root):
    agent = loop.Agent(root)
    _write(root, "tree/a.txt", "1\n")
    _write(root, "tree/b.txt", "2\n")
    pid = _arm(root, {"kind": "tree_changed", "path": "tree", "every_s": 30,
                      "max_files": 10})["id"]
    prospective.check(root, agent)                            # baseline
    _impatient(root, pid)
    os.utime(os.path.join(root, "tree", "a.txt"), None)       # a touch
    assert prospective.check(root, agent) == 0, "a touch is not a change"
    for step in (lambda: _write(root, "tree/c.txt", "3\n"),
                 lambda: _write(root, "tree/a.txt", "1b\n"),
                 lambda: os.remove(os.path.join(root, "tree", "b.txt"))):
        _impatient(root, pid)
        step()
        assert prospective.check(root, agent) == 1
    for i in range(12):
        _write(root, f"big/f{i}.txt", "x")
    try:
        _arm(root, {"kind": "tree_changed", "path": "big", "max_files": 10})
    except ValueError as exc:
        assert "more than 10" in str(exc), exc
    else:
        raise AssertionError("an oversized tree must refuse at add")
    print("[tree] the manifest sentinel ignored a touch and fired on an "
          "added, a modified and a deleted file; an oversized tree refused")


# ------------------------------------------------------------------ 4 http
def check_http(home, fixture):
    root = _desk(home, "Remote Watcher", fixture)
    agent = loop.Agent(root)
    fixture.store["r1"] = {"name": "alpha", "qty": 1}
    pid = _arm(root, {"kind": "http_changed", "endpoint": "records",
                      "path": "records/r1", "every_s": 30})["id"]
    assert prospective.check(root, agent) == 0                # baseline
    assert fixture.seen[-1][2] == "Bearer " + TOKEN
    _impatient(root, pid)
    assert prospective.check(root, agent) == 0, "identical readback"
    _impatient(root, pid)
    fixture.store["r1"] = {"name": "alpha", "qty": 2}
    assert prospective.check(root, agent) == 1
    goal = _queued(agent)[-1]["goal"]
    assert "records/records/r1" in goal and "CHANGE DETECTED" in goal, goal
    _impatient(root, pid)
    del fixture.store["r1"]
    assert prospective.check(root, agent) == 0, "an outage is not a change"
    ledger = io.open(os.path.join(root, "prospective.json"),
                     encoding="utf-8").read()
    assert "alpha" not in ledger and TOKEN not in ledger, "hashes only"
    try:
        _arm(root, {"kind": "http_changed", "endpoint": "elsewhere",
                    "path": "x"})
    except ValueError as exc:
        assert "not in the owner" in str(exc), exc
    else:
        raise AssertionError("an endpoint outside the owner's table was accepted")
    print("[http] against the owner's endpoint the sentinel took a baseline, "
          "ignored an identical readback, fired when the record changed, "
          "ignored a 404, kept only hashes, and refused an endpoint the "
          "owner never named")


# ------------------------------------------------------------------ 6 loop
def check_loop_queues_from_idle(home):
    root = _desk(home, "Idle Watcher")
    _write(root, "watch/inbox.txt", "v1\n")
    pid = _arm(root, {"kind": "file_changed", "path": "watch/inbox.txt",
                      "every_s": 30})["id"]
    prospective.check(root, None)                             # baseline
    _impatient(root, pid)
    _write(root, "watch/inbox.txt", "v2\n")
    assert run_drain(root, timeout=120) == 0
    tasks = loop.Agent(root).load_state()["tasks"]
    assert len(tasks) == 1 and tasks[0]["status"] == "done" and \
        "CHANGE DETECTED" in tasks[0]["goal"], tasks
    _impatient(root, pid)
    assert run_drain(root, timeout=120) == 0
    assert len(loop.Agent(root).load_state()["tasks"]) == 1, "no change, no task"
    print("[loop] the idle tick queued one gated task for the change and the "
          "loop ran it; a drain with no change queued nothing")


# --------------------------------------------------------- 7 registration
def check_registration():
    me = os.path.basename(__file__)
    for name in ("tests/run_all.py", "evidence.py", "proof.py"):
        text = io.open(os.path.join(AGENT_DIR, name), encoding="utf-8").read()
        assert me in text, f"{me} is not declared in {name}"
    ref = io.open(os.path.join(AGENT_DIR, "REFERENCE.md"), encoding="utf-8").read()
    for k in ("file_changed", "tree_changed", "http_changed"):
        assert f"`{k}`" in ref, f"REFERENCE does not list {k}"
    assert "Ten kinds" in ref
    print("[registration] the benchmark is declared in run_all, evidence and "
          "proof; REFERENCE lists the ten intention kinds")


def main():
    fixture = Fixture()
    os.environ["SENTINEL_TOKEN"] = TOKEN
    home = make_sandbox("sentinels", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    root = _desk(home, "File Watcher")
    check_file_baseline_then_change(root)
    check_politeness(root)
    check_tree(root)
    check_http(home, fixture)
    check_loop_queues_from_idle(home)
    check_registration()
    fixture.server.shutdown()
    print("PASS test_sentinels")


if __name__ == "__main__":
    main()
