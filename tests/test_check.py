#!/usr/bin/env python3
"""Provider connectivity check (`loop.py check`).

Probes every role's provider with one live request. A healthy provider
reports OK; a dead endpoint or missing key reports FAIL with the reason, and
the command exits nonzero so wiring mistakes are caught BEFORE the daemon
burns a night on them. This is the command that certifies an OpenRouter (or
any OpenAI-compatible) provider is correctly plugged in.

Run from the agent/ directory:  python tests/test_check.py
"""

import subprocess
import sys

from common import LOOP, PY, make_sandbox

DEAD_PROVIDER = """\
[providers.dead]
base_url = "http://127.0.0.1:9"
api_key = "not-a-real-key"
"""


def run_check(sb):
    return subprocess.run([PY, LOOP, "check", "--root", sb],
                          capture_output=True, text=True, timeout=60)


def main():
    # all-mock sandbox: everything OK, exit 0
    sb_ok = make_sandbox("check_ok", providers={"m": {"script": "s.json"}},
                         roles={"tester": "m"}, scripts={"s.json": []})
    r = run_check(sb_ok)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK (mock" in r.stdout and "all providers OK" in r.stdout, r.stdout
    print("[healthy] all roles probed, exit 0")

    # one role wired to a dead endpoint: named FAIL, exit 1
    sb_bad = make_sandbox("check_bad", providers={"m": {"script": "s.json"}},
                          roles={"tester": "m", "badrole": "dead"},
                          scripts={"s.json": []}, extra=DEAD_PROVIDER)
    r = run_check(sb_bad)
    assert r.returncode == 1, f"a failing provider must exit 1\n{r.stdout}"
    assert "badrole" in r.stdout and "FAIL:" in r.stdout, r.stdout
    assert "SOME PROVIDERS FAILED" in r.stdout, r.stdout
    assert "OK (mock" in r.stdout, "healthy roles must still report OK"
    print("[broken] dead endpoint named with reason, exit 1, healthy roles unaffected")
    print("PASS test_check: provider wiring is verifiable in one command")


if __name__ == "__main__":
    main()
