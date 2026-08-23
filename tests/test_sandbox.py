#!/usr/bin/env python3
"""WHERE commands run is a setting, and it FAILS CLOSED (M5).

1. host backend: the command runs in the expert's root and sees the AGENT_*
   environment the harness promises
2. an unknown or unavailable backend NEVER silently falls back to the host --
   it returns exit 127 and names what is missing, and the loop surfaces that
   text to the model instead of running anything
3. policy still runs first, in every backend
4. docker: exercised for real when a docker daemon and the image are present,
   skipped loudly otherwise (never silently "passing")

Run from the agent/ directory:  python tests/test_sandbox.py
"""

import json
import os
import shutil
import subprocess
import sys

from common import AGENT_DIR, PY, agent_setting, make_sandbox, read_state, \
    run_drain

sys.path.insert(0, AGENT_DIR)
import loop
import sandbox

SENTINEL = "sandbox-was-here.txt"


def main():
    sb = make_sandbox("sandbox", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []})
    cfg_host = {"agent": {"sandbox": "host"}}

    # --- 1. host
    ok, why = sandbox.available(cfg_host)
    assert ok and "policy" in why, why
    rc, out, err = sandbox.run(
        f'"{PY}" -c "import os;print(os.environ.get(\'AGENT_TASK_ID\'));'
        f'print(os.getcwd())"',
        sb, {"AGENT_TASK_ID": "t-42", "AGENT_ROOT": sb}, 60, cfg_host)
    assert rc == 0, (rc, err)
    lines = out.strip().splitlines()
    assert lines[0] == "t-42", out
    assert os.path.realpath(lines[1]) == os.path.realpath(sb), out
    print("[host] the default backend runs in the expert's own root with the "
          "AGENT_* environment the harness promises")

    # --- 2. fail closed
    for bad, needle in (({"agent": {"sandbox": "wat"}}, "unknown sandbox backend"),
                        ({"agent": {"sandbox": "e2b"}}, "E2B_API_KEY"),
                        ({"agent": {"sandbox": "daytona"}}, "DAYTONA_API_KEY")):
        os.environ.pop("E2B_API_KEY", None)
        os.environ.pop("DAYTONA_API_KEY", None)
        rc, out, err = sandbox.run(
            f'"{PY}" -c "open(r\'{os.path.join(sb, SENTINEL)}\',\'w\').write(\'x\')"',
            sb, {}, 30, bad)
        assert rc == 127, (bad, rc, out, err)
        assert needle in err, err
        assert "Nothing was run on the host" in err, err
        assert not os.path.exists(os.path.join(sb, SENTINEL)), \
            "an unavailable backend must never execute on the host"
    print("[closed] an unknown backend and unconfigured hosted backends refuse "
          "the command instead of quietly running it on this machine")

    # --- 3. through the loop, with policy first
    sb2 = make_sandbox("sandbox_loop", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"},
                       scripts={"s.json": [
                           {"tool": "run_command", "args": {"cmd": "echo hello"}},
                           {"tool": "finish_task", "args": {"summary": "ran"}}]})
    agent_setting(sb2, 'sandbox = "e2b"')
    a = loop.Agent(sb2)
    tid = a.add_task("tester", "run a command in the sandbox")
    assert run_drain(sb2) == 0
    t = read_state(sb2)["tasks"][0]
    step = t["steps"][0]
    assert "sandbox 'e2b' unavailable" in step["result"], step["result"]
    assert "E2B_API_KEY" in step["result"] and "not set" in step["result"]
    print("[loop] with a hosted backend configured but no key, the agent was "
          "told exactly what is missing -- and nothing ran locally")

    sb3 = make_sandbox("sandbox_policy", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"},
                       scripts={"s.json": [
                           {"tool": "run_command",
                            "args": {"cmd": "sudo rm -rf /"}},
                           {"tool": "finish_task", "args": {"summary": "x"}}]})
    agent_setting(sb3, 'sandbox = "docker"')
    loop.Agent(sb3).add_task("tester", "try something destructive")
    assert run_drain(sb3) == 0
    step = read_state(sb3)["tasks"][0]["steps"][0]
    assert "REFUSED" in step["result"].upper(), step["result"]
    assert "docker" not in step["result"].lower(), \
        "policy must refuse BEFORE the backend is even consulted"
    print("[order] policy.py still decides what may be attempted at all, "
          "before any backend is asked to run it")

    # --- 4. docker for real, or a loud skip
    ok, why = sandbox.available({"agent": {"sandbox": "docker"}})
    if not ok:
        print(f"[docker] skipped -- {why} (the backend is present and fails "
              f"closed; install docker to exercise it here)")
    else:
        img = subprocess.run(["docker", "image", "inspect", sandbox.DOCKER_IMAGE],
                             capture_output=True, text=True)
        if img.returncode != 0:
            print(f"[docker] skipped -- image {sandbox.DOCKER_IMAGE} not pulled")
        else:
            rc, out, err = sandbox.run(
                "python -c \"import os;print(os.getcwd());"
                "print(os.environ.get('AGENT_TASK_ID'))\"",
                sb, {"AGENT_TASK_ID": "t-99"}, 120,
                {"agent": {"sandbox": "docker"}})
            assert rc == 0, (rc, out, err)
            assert "/work" in out and "t-99" in out, out
            rc2, out2, err2 = sandbox.run(
                "python -c \"import urllib.request;"
                "urllib.request.urlopen('http://example.com', timeout=5)\"",
                sb, {}, 120, {"agent": {"sandbox": "docker"}})
            assert rc2 != 0, "the container must have no network by default"
            print("[docker] ran inside a throwaway container at /work with no "
                  "network, and the AGENT_* environment intact")
    print("PASS test_sandbox")


if __name__ == "__main__":
    main()
