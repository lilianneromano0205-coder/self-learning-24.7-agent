#!/usr/bin/env python3
"""Remote access: token auth on the control panel.

With a token set, every /api call must present it (header or query param);
without it the API returns 401 and touches nothing. The page itself stays
servable so the browser can prompt for the token.

Run from the agent/ directory:  python tests/test_remote.py
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from common import free_port, AGENT_DIR, make_sandbox

PY = sys.executable
PORT = free_port()
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "test-token-xyz"


def call(path, token=None, method="GET", body=None):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body else None)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read()


def main():
    home = make_sandbox("remote", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    env = {**os.environ, "UI_TOKEN": TOKEN}
    proc = subprocess.Popen([PY, os.path.join(AGENT_DIR, "ui.py"),
                             "--home", home, "--port", str(PORT)],
                            env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                call("/", None)
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise AssertionError("panel did not come up")

        # the page is servable (it holds no data), the API is not
        status, body = call("/", None)
        assert status == 200 and b"Expert Fleet" in body
        try:
            call("/api/experts", None)
            raise AssertionError("unauthenticated API access must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 401, e.code
        print("[deny] page served; unauthenticated API call rejected with 401")

        # a wrong token is still refused; the right one works
        try:
            call("/api/experts", "wrong-token")
            raise AssertionError("wrong token must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        status, body = call("/api/experts", TOKEN)
        assert status == 200 and json.loads(body) == []
        print("[allow] wrong token refused; correct token authorized")

        # write endpoints are protected too — no expert may be created anonymously
        try:
            call("/api/experts", None, "POST", {"name": "Ghost", "identity": "x"})
            raise AssertionError("anonymous create must be refused")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        assert not os.path.isdir(os.path.join(home, "experts", "ghost")), \
            "a rejected request must not create anything"
        status, body = call("/api/experts", TOKEN, "POST",
                            {"name": "Ghost", "identity": "x"})
        assert json.loads(body)["created"] == "ghost"
        print("[writes] anonymous create refused and created nothing; authorized create worked")
        print("PASS test_remote")
    finally:
        proc.terminate()
        proc.wait(10)


if __name__ == "__main__":
    main()
