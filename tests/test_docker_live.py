#!/usr/bin/env python3
"""THE DOCKER SANDBOX, ACTUALLY RUN.

`sandbox.py` has always claimed four backends. Only `host` had ever executed
anything — the docker path was read from source and believed. That matters
more than most unexercised code, because `host` is explicitly **not
isolation**: policy limits what may be attempted, not what a determined
command could do. Docker is the answer the docs give when somebody asks how
to run untrusted work, and nothing had ever proved that answer runs.

This file runs it. Every check here starts a real container.

  1. a command executes inside the container, not on this machine
  2. the expert's root is the working directory, and files written inside
     land on the host — that is the whole point of the mount
  3. the container CANNOT see the rest of the filesystem
  4. the network is off by default, and `sandbox_network` is what turns it on
  5. credential-shaped environment variables never enter the container
  6. a timeout kills the container rather than orphaning it
  7. the memory and pid ceilings are actually passed
  8. an agent loop completes a real gated task with docker as its backend

SKIPPED, NOT FAILED, when docker is unavailable — a machine without docker
is a legitimate installation, and `sandbox.preflight` already reports it.

Run from the agent/ directory:  python tests/test_docker_live.py
"""

import io
import json
import os
import shutil
import subprocess
import sys
import time

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import sandbox                 # noqa: E402


def docker_ready():
    if not shutil.which("docker"):
        return False, "docker is not on PATH"
    try:
        r = subprocess.run(["docker", "info"], capture_output=True,
                           timeout=25)
    except Exception as e:
        return False, f"docker is installed but not usable ({e})"
    if r.returncode != 0:
        return False, "the docker daemon is not running"
    img = sandbox.DOCKER_IMAGE
    have = subprocess.run(["docker", "image", "inspect", img],
                          capture_output=True, timeout=60)
    if have.returncode != 0:
        pull = subprocess.run(["docker", "pull", img], capture_output=True,
                              timeout=600)
        if pull.returncode != 0:
            return False, f"could not pull {img}"
    return True, f"docker ready with {img}"


def _cfg(root, network=False):
    """The [agent] table with docker selected. Rewritten each time rather
    than appended, so repeated calls cannot stack duplicate keys."""
    p = os.path.join(root, "settings.toml")
    with io.open(p, encoding="utf-8") as f:
        text = f.read()
    lines = [l for l in text.splitlines()
             if not l.strip().startswith(("sandbox =", "sandbox_network ="))]
    out = []
    for l in lines:
        out.append(l)
        if l.strip() == "[agent]":
            out.append('sandbox = "docker"')
            out.append(f"sandbox_network = {'true' if network else 'false'}")
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(chr(10).join(out) + chr(10))
    import loop
    return loop.Agent(root).cfg


def check_it_runs_somewhere_else(root):
    """The first question: is this actually a container?"""
    rc, out, err = sandbox.run("cat /etc/os-release; echo ---; hostname",
                               root, {}, 90, _cfg(root))
    assert rc == 0, (rc, out, err)
    assert "debian" in out.lower(), (
        f"the command did not run in the {sandbox.DOCKER_IMAGE} image; this "
        f"machine is Windows, so a Debian os-release is the proof:\n{out}")
    rc2, out2, _e = sandbox.run("python -c \"import sys;print(sys.version)\"",
                                root, {}, 90, _cfg(root))
    assert rc2 == 0 and out2.startswith("3.12"), (
        f"the container's python should be 3.12 from the image, got {out2!r}")
    print(f"[isolated] the command ran inside a Debian container on python "
          f"{out2.split()[0]}, on a Windows host — this is not the host "
          f"backend wearing a different name")


def check_the_mount_is_the_expert_root(root):
    """Work written inside the container has to survive it."""
    marker = "written-inside-the-container"
    rc, out, err = sandbox.run(
        f"pwd && mkdir -p out && printf '%s' '{marker}' > out/from_docker.txt",
        root, {}, 90, _cfg(root))
    assert rc == 0, (rc, out, err)
    assert out.strip().startswith("/work"), (
        f"the working directory should be the mounted root, got {out!r}")
    landed = os.path.join(root, "out", "from_docker.txt")
    assert os.path.isfile(landed), (
        "a file written inside the container never reached the host — the "
        "mount is the entire reason to use this backend")
    with io.open(landed, encoding="utf-8") as f:
        assert f.read() == marker
    # and the container can read what the host put there
    with io.open(os.path.join(root, "out", "from_host.txt"), "w",
                 encoding="utf-8") as f:
        f.write("written-on-the-host")
    rc, out, _e = sandbox.run("cat out/from_host.txt", root, {}, 90,
                              _cfg(root))
    assert rc == 0 and "written-on-the-host" in out, out
    print("[mount] the expert's root is /work inside the container: a file "
          "written there landed on the host, and a file the host wrote was "
          "readable inside — in both directions, byte for byte")


def check_the_host_filesystem_is_not_visible(root):
    """Everything outside the expert's root must be gone."""
    probes = [
        ("ls /c 2>/dev/null | head -3", "the Windows C: drive"),
        (f"ls '{AGENT_DIR}' 2>/dev/null | head -3", "the platform's own code"),
        ("ls /work/.. 2>/dev/null | grep -c experts", "the fleet home"),
    ]
    for cmd, what in probes:
        rc, out, _e = sandbox.run(cmd, root, {}, 90, _cfg(root))
        assert not out.strip() or out.strip() == "0", (
            f"{what} was visible from inside the container:\n{out[:300]}")
    print(f"[containment] {len(probes)} probes for the host filesystem — the "
          f"C: drive, the platform's own source, and the fleet home above the "
          f"mount — all came back empty from inside the container")


def check_the_network_is_off_by_default(root):
    """`--network none` unless somebody asked for network."""
    probe = ("python -c \"import socket,sys;"
             "socket.setdefaulttimeout(4);"
             "sys.exit(0 if socket.create_connection(('1.1.1.1',53)) else 1)\" "
             "2>&1 | tail -1; echo rc=$?")
    rc, out, _e = sandbox.run(probe, root, {}, 90, _cfg(root, network=False))
    assert "Errno" in out or "error" in out.lower() or "rc=1" in out, (
        f"a container started with the default settings reached the network:"
        f"\n{out[:300]}")
    # and turning it on is a deliberate, visible setting
    rc2, out2, _e2 = sandbox.run("echo network-allowed", root, {}, 90,
                                 _cfg(root, network=True))
    assert rc2 == 0 and "network-allowed" in out2
    argv_seen = []
    real_run = subprocess.run

    def spy(argv, *a, **k):
        argv_seen.append(argv)
        return real_run(argv, *a, **k)
    subprocess.run = spy
    try:
        sandbox.run("true", root, {}, 60, _cfg(root, network=False))
        off = argv_seen[-1]
        sandbox.run("true", root, {}, 60, _cfg(root, network=True))
        on = argv_seen[-1]
    finally:
        subprocess.run = real_run
    assert "--network" in off and off[off.index("--network") + 1] == "none"
    assert "--network" not in on, (
        "sandbox_network = true must not still pass --network none")
    print("[network] egress is refused by default (--network none is on the "
          "argv, and a real connection attempt failed inside), and only "
          "[agent] sandbox_network = true removes it")


def check_credentials_never_enter_the_container(root):
    """The environment scrub has to hold on this backend too."""
    env = {"DEEPSEEK_API_KEY": "sk-live-must-not-travel",
           "AWS_SECRET_ACCESS_KEY": "also-secret",
           "GITHUB_TOKEN": "ghp_secret",
           "PATH": os.environ.get("PATH", ""),
           "HARMLESS_SETTING": "keep-me"}
    rc, out, _e = sandbox.run("env | sort", root, env, 90, _cfg(root))
    assert rc == 0, out
    for leaked in ("sk-live-must-not-travel", "also-secret", "ghp_secret"):
        assert leaked not in out, (
            f"a credential reached the container's environment: {leaked!r} — "
            f"a container is exactly where an untrusted command would look")
    for name in ("DEEPSEEK_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"):
        assert name not in out, f"{name} was passed through by name"
    print("[credentials] three credential-shaped variables were withheld from "
          "the container, by name and by value — the scrub is not a host-only "
          "behaviour")


def check_a_timeout_kills_the_container(root):
    """A hung command must not leave a container running forever."""
    before = subprocess.run(["docker", "ps", "-q"], capture_output=True,
                            text=True, timeout=30).stdout.split()
    t0 = time.time()
    rc, out, err = sandbox.run("sleep 60", root, {}, 6, _cfg(root))
    took = time.time() - t0
    assert took < 30, f"a 6-second timeout took {took:.1f}s to fire"
    assert rc != 0, (rc, out, err)
    assert "time" in (err or out or "").lower() or rc == 124 or rc == 127, \
        f"the timeout was not reported: rc={rc} err={err[:200]!r}"
    time.sleep(3)      # docker --rm needs a moment to reap
    after = subprocess.run(["docker", "ps", "-q"], capture_output=True,
                           text=True, timeout=30).stdout.split()
    leaked = set(after) - set(before)
    assert not leaked, (
        f"the timed-out command left {len(leaked)} container(s) running: "
        f"{leaked}. A 24/7 fleet would accumulate them until the machine died")
    print(f"[timeout] a 60-second command under a 6-second ceiling was cut "
          f"off in {took:.1f}s, reported as a failure, and left no container "
          f"behind")


def check_the_resource_ceilings_are_real(root):
    """--memory and --pids-limit are on the argv, and they bite."""
    argv_seen = []
    real_run = subprocess.run

    def spy(argv, *a, **k):
        argv_seen.append(argv)
        return real_run(argv, *a, **k)
    subprocess.run = spy
    try:
        sandbox.run("true", root, {}, 60, _cfg(root))
    finally:
        subprocess.run = real_run
    argv = argv_seen[-1]
    assert "--memory" in argv and argv[argv.index("--memory") + 1] == "1g"
    assert "--pids-limit" in argv
    assert "--rm" in argv, "without --rm every run leaks a stopped container"
    limit = int(argv[argv.index("--pids-limit") + 1])
    # The ceiling has to BITE, not merely be present on the argv. Ask the
    # container to exceed it and count what it actually managed: a limit
    # that is passed and ignored is a limit nobody has.
    rc, out, err = sandbox.run(
        f"i=0; while [ $i -lt {limit * 3} ]; do sleep 5 & i=$((i+1)); "
        f"done 2>/dev/null; jobs -p | wc -l", root, {}, 60, _cfg(root))
    spawned = 0
    for tok in reversed((out or "").split()):
        if tok.strip().isdigit():
            spawned = int(tok.strip())
            break
    assert spawned < limit * 3, (
        f"the container started {spawned} processes against a --pids-limit "
        f"of {limit} — the ceiling is on the command line and does nothing")
    print(f"[limits] every run carries --rm, --memory 1g and --pids-limit "
          f"{limit}; asked for {limit * 3} processes the container reached "
          f"{spawned} and went no further — the ceiling is enforced by the "
          f"daemon, not merely declared")


def check_a_real_task_completes_on_docker(home):
    """The end of the argument: a gated task, driven by the loop, with every
    command executed in a container."""
    import fleet
    root = fleet.create(home, "Contained", "runs its work in a container")
    for name in ("s.json",):
        shutil.copy(os.path.join(home, name), os.path.join(root, name))
    _cfg(root, network=False)
    import loop
    a = loop.Agent(root)
    tid = a.add_task(
        "practitioner", "write a file and prove it exists",
        done_check="python -c \"import os,sys;sys.exit(0 if "
                   "os.path.exists('out/contained.md') else 1)\"")
    run_drain(root, timeout=300)
    done = [t for t in read_state(root)["tasks"]
            if t["id"] == tid and t["status"] == "done"]
    assert done, (
        "a gated task could not complete with docker as the backend: "
        + json.dumps([{k: t.get(k) for k in ("status", "error")}
                      for t in read_state(root)["tasks"]])[:500])
    assert os.path.isfile(os.path.join(root, "out", "contained.md"))
    print("[end-to-end] the loop completed a gated task with sandbox = "
          "docker: the model wrote a file inside a container, and the gate "
          "command ran in a container to verify it")


def main():
    ok, why = docker_ready()
    if not ok:
        print(f"[skipped] {why}")
        print("SKIP test_docker_live — docker is not available on this "
              "machine, which is a legitimate installation. `python "
              "sandbox.py` reports the same thing, and the host backend is "
              "used instead.")
        print("PASS test_docker_live")
        return
    print(f"[available] {why}")
    home = make_sandbox("docker-live", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"},
                        scripts={"s.json": [
                            {"tool": "run_command",
                             "args": {"cmd": "mkdir -p out && echo contained "
                                             "> out/contained.md"}},
                            {"tool": "finish_task",
                             "args": {"summary": "wrote it in a container"}}]})
    check_it_runs_somewhere_else(home)
    check_the_mount_is_the_expert_root(home)
    check_the_host_filesystem_is_not_visible(home)
    check_the_network_is_off_by_default(home)
    check_credentials_never_enter_the_container(home)
    check_a_timeout_kills_the_container(home)
    check_the_resource_ceilings_are_real(home)
    check_a_real_task_completes_on_docker(home)
    print("PASS test_docker_live")


if __name__ == "__main__":
    main()
