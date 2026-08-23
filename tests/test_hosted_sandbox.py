#!/usr/bin/env python3
"""THE HOSTED SANDBOX CLIENT, EXERCISED WITHOUT AN ACCOUNT.

`sandbox.py` speaks to E2B and Daytona over REST. Nothing had ever executed
that code: it needs a paid account and a key, so the first time it runs is
the first time somebody depends on it. That is the same problem the live
provider path had, and it has the same answer — a loopback server that
implements the documented shape, and can be told to misbehave.

What is proved here:

  1. the key is read from the environment at CALL TIME and never stored
  2. no key means a clear refusal, and NOTHING runs on the host instead —
     a hosted sandbox that silently degrades to local execution is worse
     than one that fails
  3. the request carries the command, the working directory, the scrubbed
     environment and a millisecond timeout
  4. credentials are withheld from the remote environment, exactly as they
     are from a local container
  5. both response spellings (`exitCode` and `exit_code`) are read
  6. an HTTP refusal, an unreachable host and a malformed body each become a
     reported failure rather than a crash or a false success
  7. `[agent] e2b_url` / `daytona_url` redirect the client, which is what
     makes this testable at all

WHAT THIS DOES NOT PROVE: that E2B or Daytona behave like this server. It
proves this platform's client is correct against the shape it was written
for. Neither service has ever been contacted from this codebase.

Run from the agent/ directory:  python tests/test_hosted_sandbox.py
"""

import http.server
import io
import json
import os
import sys
import threading

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import sandbox                 # noqa: E402


class FakeHosted:
    """A stand-in for the E2B / Daytona exec endpoint."""

    def __init__(self, require_key=None):
        self.require_key = require_key
        self.requests = []
        self.next = None          # a dict to return, or ("http", code)
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                raw = body if isinstance(body, bytes) else \
                    json.dumps(body).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {}
                outer.requests.append({
                    "path": self.path, "payload": payload,
                    "headers": {k.lower(): v for k, v in self.headers.items()}})
                nxt = outer.next
                outer.next = None
                if isinstance(nxt, tuple) and nxt[0] == "http":
                    self._send(nxt[1], {"error": "refused"})
                    return
                if isinstance(nxt, tuple) and nxt[0] == "garbage":
                    self._send(200, b"<html>not json</html>", "text/html")
                    return
                if outer.require_key:
                    ok = (self.headers.get("Authorization") ==
                          f"Bearer {outer.require_key}"
                          or self.headers.get("X-API-Key") == outer.require_key)
                    if not ok:
                        self._send(401, {"error": "bad key"})
                        return
                self._send(200, nxt or {"exitCode": 0, "stdout": "hello\n",
                                        "stderr": ""})

        os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
        os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
        self._srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self._srv.server_address[1]}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def stop(self):
        try:
            self._srv.shutdown()
            self._srv.server_close()
        except Exception:
            pass


def cfg_for(root, kind, url=None):
    """Point the [agent] table at a hosted backend, and optionally at our
    own server instead of the real service."""
    p = os.path.join(root, "settings.toml")
    with io.open(p, encoding="utf-8") as f:
        text = f.read()
    drop = ("sandbox =", "sandbox_network =", "e2b_url =", "daytona_url =")
    lines = [l for l in text.splitlines()
             if not l.strip().startswith(drop)]
    out = []
    for l in lines:
        out.append(l)
        if l.strip() == "[agent]":
            out.append(f'sandbox = "{kind}"')
            if url:
                out.append(f'{kind}_url = "{url}"')
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(chr(10).join(out) + chr(10))
    import loop
    return loop.Agent(root).cfg


ENV_FOR = {"e2b": "E2B_API_KEY", "daytona": "DAYTONA_API_KEY"}


def check_no_key_refuses_and_runs_nothing(root):
    """The most important property: a missing key must NOT fall back to the
    host. Silent local execution of work the operator sent to an isolated
    sandbox is the worst possible failure mode."""
    for kind in ("e2b", "daytona"):
        saved = os.environ.pop(ENV_FOR[kind], None)
        try:
            marker = os.path.join(root, f"escaped-{kind}.txt")
            rc, out, err = sandbox.run(
                f"echo escaped > {marker!r}", root, {}, 30,
                cfg_for(root, kind))
            assert rc != 0, f"{kind} with no key reported success"
            assert "key" in err.lower(), err
            assert not os.path.exists(marker), (
                f"{kind} with no key EXECUTED THE COMMAND ON THIS MACHINE — "
                f"work sent to an isolated sandbox must never quietly run "
                f"locally")
        finally:
            if saved is not None:
                os.environ[ENV_FOR[kind]] = saved
    print("[no-key] both hosted backends refuse without a key, name the key "
          "as the reason, and — the property that matters — run nothing on "
          "this machine instead")


def check_the_request_carries_the_contract(root):
    srv = FakeHosted(require_key="hosted-key-xyz")
    try:
        os.environ["E2B_API_KEY"] = "hosted-key-xyz"
        cfg = cfg_for(root, "e2b", srv.base)
        rc, out, err = sandbox.run("echo hello", root,
                                   {"HARMLESS": "keep"}, 45, cfg)
        assert rc == 0 and "hello" in out, (rc, out, err)
        req = srv.requests[-1]
        assert req["path"].endswith("/sandboxes/exec"), req["path"]
        assert req["payload"]["cmd"] == "echo hello"
        assert req["payload"]["cwd"], "no working directory was sent"
        assert req["payload"]["timeoutMs"] == 45_000, req["payload"]
        assert req["headers"]["authorization"] == "Bearer hosted-key-xyz"
        assert req["headers"]["x-api-key"] == "hosted-key-xyz"
        print(f"[contract] the exec request carried the command, a working "
              f"directory, a {req['payload']['timeoutMs']}ms deadline and the "
              f"key in both header styles the two services use")
    finally:
        srv.stop()
        os.environ.pop("E2B_API_KEY", None)


def check_credentials_do_not_travel(root):
    """A remote sandbox is somebody else's machine. Nothing changes."""
    srv = FakeHosted()
    try:
        os.environ["E2B_API_KEY"] = "hosted-key"
        os.environ["DEEPSEEK_API_KEY"] = "sk-live-must-not-travel"
        cfg = cfg_for(root, "e2b", srv.base)
        sandbox.run("env", root, {"GITHUB_TOKEN": "ghp_secret"}, 30, cfg)
        sent = json.dumps(srv.requests[-1]["payload"])
        for leaked in ("sk-live-must-not-travel", "ghp_secret",
                       "DEEPSEEK_API_KEY", "GITHUB_TOKEN"):
            assert leaked not in sent, (
                f"{leaked!r} was sent to a third-party sandbox service — the "
                f"scrub must not be a local-only behaviour")
        assert "hosted-key" not in sent, (
            "the sandbox provider's OWN key was placed in the command "
            "environment, where the command can read it")
        print("[credentials] four credential-shaped values, including the "
              "sandbox service's own key, were all absent from the JSON sent "
              "to a third-party machine")
    finally:
        srv.stop()
        for k in ("E2B_API_KEY", "DEEPSEEK_API_KEY"):
            os.environ.pop(k, None)


def check_both_response_spellings(root):
    """E2B returns `exitCode`; other services return `exit_code`."""
    srv = FakeHosted()
    try:
        os.environ["DAYTONA_API_KEY"] = "k"
        cfg = cfg_for(root, "daytona", srv.base)
        srv.next = {"exitCode": 7, "stdout": "a", "stderr": "b"}
        rc, out, err = sandbox.run("x", root, {}, 30, cfg)
        assert (rc, out, err) == (7, "a", "b"), (rc, out, err)
        srv.next = {"exit_code": 9, "stdout": "c", "stderr": "d"}
        rc, out, err = sandbox.run("x", root, {}, 30, cfg)
        assert (rc, out, err) == (9, "c", "d"), (rc, out, err)
        print("[spellings] a non-zero exit is reported as a failure in both "
              "`exitCode` and `exit_code` forms — reading only one would turn "
              "every failed remote command into a success")
    finally:
        srv.stop()
        os.environ.pop("DAYTONA_API_KEY", None)


def check_every_failure_is_reported_not_raised(root):
    """`run()` promises never to raise for a backend problem."""
    srv = FakeHosted()
    try:
        os.environ["E2B_API_KEY"] = "k"
        cfg = cfg_for(root, "e2b", srv.base)
        cases = [
            (("http", 402), "402", "a billing refusal"),
            (("http", 500), "500", "a server error"),
            (("garbage",), "", "a body that is not JSON"),
        ]
        for nxt, expect, what in cases:
            srv.next = nxt
            rc, out, err = sandbox.run("x", root, {}, 30, cfg)
            assert rc != 0, f"{what} was reported as success"
            assert err, f"{what} produced no message"
            if expect:
                assert expect in err, (what, err)
        # and a host that is not listening at all
        dead = cfg_for(root, "e2b", "http://127.0.0.1:1")
        rc, out, err = sandbox.run("x", root, {}, 15, dead)
        assert rc != 0 and "unreachable" in err.lower(), err
        print(f"[failures] {len(cases) + 1} failure shapes — a billing "
              f"refusal, a server error, a non-JSON body and a host that is "
              f"not listening — each became a reported non-zero result with a "
              f"message, and none raised")
    finally:
        srv.stop()
        os.environ.pop("E2B_API_KEY", None)


def check_availability_is_honest(root):
    """`sandbox.py` must say what it can and cannot do, per backend."""
    for kind in ("e2b", "daytona"):
        os.environ.pop(ENV_FOR[kind], None)
        cfg = cfg_for(root, kind)
        ok, why = sandbox.available(cfg)
        assert not ok and ENV_FOR[kind] in why, (kind, ok, why)
        os.environ[ENV_FOR[kind]] = "present"
        ok2, why2 = sandbox.available(cfg_for(root, kind))
        assert ok2, (kind, why2)
        # The two messages must DIFFER, and the second must not claim the
        # service was contacted: a key present is not a service reachable,
        # and an audit that cannot tell those apart is worth nothing.
        assert why2 != why, (kind, why, why2)
        for overclaim in ("reachable", "verified", "working", "responded"):
            assert overclaim not in why2.lower(), (
                f"{kind} reports {overclaim!r} on the strength of an "
                f"environment variable — no request has been made")
        os.environ.pop(ENV_FOR[kind], None)
    print("[honesty] with no key each hosted backend reports itself "
          "unavailable and names the variable; with a key present it reports "
          "itself configured — which is all a key can honestly establish")


def main():
    home = make_sandbox("hosted-sandbox",
                        providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": []})
    check_no_key_refuses_and_runs_nothing(home)
    check_the_request_carries_the_contract(home)
    check_credentials_do_not_travel(home)
    check_both_response_spellings(home)
    check_every_failure_is_reported_not_raised(home)
    check_availability_is_honest(home)
    print("PASS test_hosted_sandbox")


if __name__ == "__main__":
    main()
