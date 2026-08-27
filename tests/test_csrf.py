#!/usr/bin/env python3
"""THE PANEL REFUSES CROSS-ORIGIN WRITES, AGAINST A LIVE SERVER.

The audit's worst finding was here, and it needs a live test because it is a
property of the HTTP surface, not of a function:

  a loopback bind stops other MACHINES; it does not stop other ORIGINS. Any
  page the owner visits can POST to 127.0.0.1. A `text/plain` body is a CORS
  "simple request" — no preflight — so the browser sends it and the server
  acted on it. Measured, cross-origin, with no token: created an expert,
  queued a task carrying a `done_check`, started the loop, and the gate
  executed that command on the owner's machine.

So this test plays the attacker: the same requests, with the headers a real
browser would attach, against a real panel.

Run from the agent/ directory:  python tests/test_csrf.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from common import AGENT_DIR, free_port, make_sandbox

PY = sys.executable
PORT = free_port()   # never a fixed port: the suite runs many servers
BASE = f"http://127.0.0.1:{PORT}"


def call(method, path, body=None, headers=None):
    """-> (status, payload). Never raises for an HTTP error status.

    Retries a handful of times on a TRANSPORT abort: Windows CI runners
    occasionally kill the first connection to a just-started local server
    (WinError 10053, seen on windows-3.12) — a socket teardown race, not a
    panel behavior. Retrying a request that never reached the handler
    cannot mask a CSRF verdict: every assertion in this file is about the
    STATUS the panel answers, and an aborted connection has no status."""
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(4):
        req = urllib.request.Request(BASE + path, data=data, method=method)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8"))
            except Exception:
                return e.code, {}
        except (ConnectionError, urllib.error.URLError) as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise last


# what a browser attaches to a cross-origin simple request
HOSTILE = {"Origin": "https://evil.example",
           "Content-Type": "text/plain;charset=UTF-8"}
HOSTILE_FETCH = {"Sec-Fetch-Site": "cross-site",
                 "Content-Type": "text/plain;charset=UTF-8"}
# what the panel's own page sends
SAME = {"Origin": BASE, "Content-Type": "application/json"}


def main():
    home = make_sandbox("csrf", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"},
                        scripts={"s.json": [{"tool": "finish_task",
                                             "args": {"summary": "ok"}}]})
    proc = subprocess.Popen([PY, os.path.join(AGENT_DIR, "ui.py"),
                             "--home", home, "--port", str(PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                if call("GET", "/api/experts")[0] == 200:
                    break
            except Exception:
                time.sleep(0.2)
        else:
            raise AssertionError("panel did not start")

        # --- 1. the attack that worked, by both browser signals
        for hdrs, label in ((HOSTILE, "Origin"), (HOSTILE_FETCH, "Sec-Fetch-Site")):
            code, r = call("POST", "/api/experts",
                           {"name": "csrf probe", "identity": "x"}, hdrs)
            assert code == 403, f"{label}: expected 403, got {code} {r}"
            assert "cross-origin" in json.dumps(r).lower(), r
        assert not os.path.isdir(os.path.join(home, "experts", "csrf-probe")), \
            "no expert may be created cross-origin"
        print("[csrf] a cross-origin POST is refused by Origin AND by "
              "Sec-Fetch-Site; nothing was created")

        # --- 2. the panel's own page still works
        code, r = call("POST", "/api/experts",
                       {"name": "legit", "identity": "real work"}, SAME)
        assert code == 200 and r.get("created") == "legit", (code, r)
        print("[same-origin] the panel's own requests are unaffected")

        # --- 3. a raw shell done_check is refused even same-origin
        code, r = call("POST", "/api/experts/legit/task",
                       {"role": "practitioner", "goal": "x",
                        "done_check": "python -c \"open('pwned','w')\""}, SAME)
        assert code == 400, (code, r)
        assert "free-form done_check" in json.dumps(r), r
        print("[rce] a free-form shell done_check over HTTP is refused — "
              "defence in depth, even from a same-origin caller")

        # --- 4. a NAMED gate is accepted and becomes a real command
        code, r = call("POST", "/api/experts/legit/task",
                       {"role": "practitioner", "goal": "build it",
                        "done_check": {"gate": "exists",
                                       "path": "out/index.html"}}, SAME)
        assert code == 200 and r.get("queued"), (code, r)
        with open(os.path.join(home, "experts", "legit", "state.json"),
                  encoding="utf-8") as f:
            task = json.load(f)["tasks"][-1]
        assert "out/index.html" in task["done_check"], task["done_check"]
        assert "pwned" not in task["done_check"]

        # and hostile parameters inside a named gate are refused
        code, r = call("POST", "/api/experts/legit/task",
                       {"role": "practitioner", "goal": "x",
                        "done_check": {"gate": "exists",
                                       "path": "../../../etc/passwd"}}, SAME)
        assert code == 400 and "inside the expert" in json.dumps(r), (code, r)
        print("[gates] a named gate becomes the command; a traversing "
              "parameter inside one is still refused")

        # --- 5. the catalogue is discoverable, so the panel can offer it
        code, r = call("GET", "/api/gates")
        assert code == 200 and {g["gate"] for g in r["gates"]} >= {
            "exists", "verify", "citecheck"}, r
        print("[catalogue] GET /api/gates lists what a caller may ask for")
    finally:
        try:
            call("POST", "/api/shutdown", {}, SAME)
        except Exception:
            pass
        time.sleep(0.5)
        if proc.poll() is None:
            proc.terminate()
    print("PASS test_csrf")


if __name__ == "__main__":
    main()
