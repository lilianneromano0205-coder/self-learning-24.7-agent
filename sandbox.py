#!/usr/bin/env python3
"""WHERE model-written commands actually run — a swappable execution backend.

The 2026 consensus on running model-generated code is blunt: containers
share a kernel, so for untrusted code the production answer is a microVM
(Firecracker/Kata — E2B, Northflank, Modal) or nothing. Teams that moved
agent execution off the host report roughly an order of magnitude fewer
security incidents. But a laptop-first platform cannot demand a microVM on
day one, and a platform that hard-codes `subprocess.run` can never move.

So execution is an INTERFACE with four backends, chosen by one setting:

    [agent] sandbox = "host"      # this machine, policy-gated (default)
                     "docker"     # a throwaway container, network off
                     "e2b"        # hosted Firecracker microVM  (E2B_API_KEY)
                     "daytona"    # hosted dev sandbox      (DAYTONA_API_KEY)

Two rules make the switch safe:

  * FAIL CLOSED. If a backend is configured but unavailable — docker not
    installed, key missing, image absent — the command does NOT quietly run
    on the host. It returns exit 127 and says exactly what is missing. A
    silent downgrade of an isolation boundary is the worst possible failure.
  * The policy layer still runs first, in every backend. The sandbox limits
    the blast radius; policy.py decides what may be attempted at all.

The command contract is identical everywhere: run in the expert's root, with
the AGENT_* environment variables, capture stdout/stderr, honour a timeout,
return (returncode, stdout, stderr).

WHAT THE BOUNDARY DOES AND DOES NOT COVER, on each backend. `docker` binds the
expert root read-write at /work — right for the workspace, and it used to be
wrong for everything else: an audit pointed out that switching backends
improved HOST isolation while leaving the agent free to edit its own
settings.toml, prompts and approvals, because they were inside the mount.
Every control path is now layered with a read-only bind
(controlplane.readonly_mounts), so on this backend the control plane is
immutable by the kernel. On `host` there is no such boundary and this module
does not pretend otherwise; controlplane.py reverts instead, and says so.
"""

import os
import shutil
import subprocess
import uuid

BACKENDS = ("host", "docker", "e2b", "daytona", "cloudflare")

# The hosted backends, in ONE table. The key name and the default base URL
# were previously written out twice — once in available() and once in
# _hosted() — which is the shape of defect this codebase keeps finding: two
# descriptions of one truth and nothing comparing them. Adding a third backend
# would have made it three copies.
#
# `url` of None means the endpoint has NO default and must be configured.
# Cloudflare's Sandbox SDK is TypeScript-called-from-a-Worker, so there is no
# public REST endpoint to default to: the operator deploys the small Worker in
# deploy/worker/ and points this at their own workers.dev URL. A backend that
# guessed a URL here would fail with a DNS error instead of an instruction.
HOSTED = {
    "e2b":        {"key": "E2B_API_KEY",
                   "url": "https://api.e2b.dev"},
    "daytona":    {"key": "DAYTONA_API_KEY",
                   "url": "https://app.daytona.io/api"},
    # DELIBERATELY NOT CLOUDFLARE_API_TOKEN. That token can create Workers,
    # read R2 and spend money across the whole account; sending it as a
    # bearer to a Worker means the Worker — and anything that ever reads its
    # logs or environment — holds full account authority in order to run
    # `ls`. This is a dedicated shared secret whose only power is "may ask
    # this one sandbox to run a command", so a leak costs exactly that.
    "cloudflare": {"key": "CLOUDFLARE_SANDBOX_TOKEN",
                   "url": None,
                   "url_env": "CLOUDFLARE_SANDBOX_URL"},
}
DOCKER_IMAGE = "python:3.12-slim"
AGENT_ENV_PREFIX = "AGENT_"
# A model-written command must never be handed the harness's own credentials.
# Without this, `run_command: env` prints every API key the platform holds --
# and the model may then put them in a file, a summary, or an HTTP request.
# (The rule is DeepSeek Harness's, from docs/defensive-patterns.md: "never
# hand untrusted output the ambient environment"; the hole it names was real
# here.) Names matching these markers are dropped unless the owner allows one
# by name in [agent] command_env_allow.
SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
                  "CREDENTIAL", "AUTH", "COOKIE", "SESSION_ID")
TIMEOUT_RC = 124

# PRIVILEGE SEPARATION, not a blanket allowlist. Some of the platform's own
# helpers genuinely need one credential to do the job the owner asked for --
# transcription needs the Whisper key, vision needs the vision key. They get
# exactly that key, and only when the command really is that helper invoking
# that subcommand. `env`, `printenv` and a python one-liner match nothing
# here, so the credential stays invisible to anything that merely asks.
SCOPED_GRANTS = (
    (r"\bingest\.py\W+(?:transcribe|chunk-audio)\b", ("GROQ_API_KEY",)),
    (r"\bingest\.py\W+(?:vision|frames)\b",
     ("OPENROUTER_API_KEY", "NVIDIA_API_KEY", "HF_TOKEN")),
)


def granted_for(cmd):
    """Which credential names this exact command shape is entitled to."""
    import re
    out = set()
    for pattern, names in SCOPED_GRANTS:
        if re.search(pattern, str(cmd or ""), re.I):
            out.update(names)
    return out


def scrub_env(env, cfg=None, cmd=""):
    """-> (clean_env, dropped_names). Values are never returned or logged."""
    allow = {str(x).upper() for x in (_cfg(cfg).get("command_env_allow") or [])}
    allow |= granted_for(cmd)
    clean, dropped = {}, []
    for k, v in (env or {}).items():
        ku = str(k).upper()
        if ku in allow:
            clean[k] = v
            continue
        if any(m in ku for m in SECRET_MARKERS):
            dropped.append(k)
            continue
        clean[k] = v
    return clean, sorted(dropped)


def _cfg(cfg):
    return ((cfg or {}).get("agent", {}) or {})


def backend_name(cfg):
    b = str(_cfg(cfg).get("sandbox", "docker") or "docker").strip().lower()
    return b


def available(cfg):
    """-> (ok, why). Never raises; used by doctor and the harness manifest."""
    b = backend_name(cfg)
    if b == "host":
        if _cfg(cfg).get("allow_unsafe_host") is not True:
            return False, ('host is UNSAFE/developer-only; autonomous shell '
                           'work requires Docker isolation. An owner may explicitly '
                           'set allow_unsafe_host = true for trusted development fixtures')
        return True, "UNSAFE developer host: no filesystem or descendant containment"
    if b not in BACKENDS:
        return False, (f"unknown sandbox backend '{b}' "
                       f"(choose one of: {', '.join(BACKENDS)})")
    if b == "docker":
        if not shutil.which("docker"):
            return False, "docker is not installed or not on PATH"
        try:
            r = subprocess.run(["docker", "info"], capture_output=True,
                               text=True, timeout=20)
        except (OSError, subprocess.SubprocessError) as e:
            return False, f"docker is installed but not usable ({e})"
        if r.returncode != 0:
            return False, "the docker daemon is not running"
        # A REACHABLE daemon is not a USABLE one. Docker Desktop on Windows
        # runs in one of two modes, and in Windows-container mode the daemon
        # answers `docker info` perfectly while rejecting every container this
        # module launches: `--pids-limit` is a Linux cgroup control, so
        # `docker run` dies with exit 125 and "Windows does not support
        # PidsLimit" before any command runs.
        #
        # This function said "docker is ready (network off)" to that daemon.
        # The same shape as the harness health check that could never fail:
        # a readiness answer derived from something adjacent to the question
        # instead of from the question. Caught on GitHub's windows runners,
        # where acquisition refused every install and the test that expected
        # one failed — the platform was right to refuse and wrong to have
        # promised.
        ostype = ""
        try:
            q = subprocess.run(["docker", "info", "--format", "{{.OSType}}"],
                               capture_output=True, text=True, timeout=20)
            ostype = (q.stdout or "").strip().lower()
        except (OSError, subprocess.SubprocessError):
            ostype = ""
        if ostype and ostype != "linux":
            return False, (
                f"the docker daemon is in {ostype}-container mode; this "
                f"platform's sandbox needs Linux containers (it sets "
                f"--pids-limit, a Linux control, and runs {DOCKER_IMAGE}). "
                f"Right-click Docker Desktop in the tray and choose "
                f"'Switch to Linux containers…'")
        return True, f"docker is ready ({DOCKER_IMAGE}, network off)"
    spec = HOSTED[b]
    key = spec["key"]
    if not os.environ.get(key):
        return False, f"{key} is not set in the environment"
    url = _hosted_url(b, cfg)
    if not url:
        return False, (
            f"{b} has no endpoint. Its sandbox API is only callable from a "
            f"Worker, so this platform talks to a small REST Worker you "
            f"deploy (see deploy/worker/README.md). Set "
            f"[agent] cloudflare_url, or the {spec['url_env']} environment "
            f"variable, to your deployed Worker's URL.")
    return True, f"{b} configured via {key} -> {url}"


def _hosted_url(kind, cfg):
    """Where this hosted backend lives: settings first, then environment,
    then the documented default. Returns "" when there is none, which is a
    refusal rather than a guess."""
    spec = HOSTED.get(kind) or {}
    configured = _cfg(cfg).get(f"{kind}_url")
    if not configured and spec.get("url_env"):
        configured = os.environ.get(spec["url_env"])
    return str(configured or spec.get("url") or "").rstrip("/")


def _agent_env(env):
    return {k: v for k, v in (env or {}).items()
            if k.startswith(AGENT_ENV_PREFIX) or k == "PYTHONUTF8"}


def _host(cmd, root, env, timeout):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, cwd=root, env=env)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        # Orthogonal outcomes, reported independently: a timeout is not an
        # exit code, and the output produced before the kill is still
        # evidence. Throwing it away turns "it hung after writing 900 rows"
        # into "nothing happened".
        return _timeout_result(e, timeout)


def _timeout_result(e, timeout):
    def _txt(b):
        if not b:
            return ""
        return b.decode("utf-8", errors="replace") if isinstance(b, bytes) else str(b)
    return (TIMEOUT_RC, _txt(getattr(e, "stdout", "")),
            f"TIMED OUT after {timeout}s -- killed before it exited, so there "
            f"is no exit code. Any output above is what it produced first.\n"
            + _txt(getattr(e, "stderr", "")))


def _docker(cmd, root, env, timeout, cfg):
    """Run one command in a throwaway container.

    THE CONTAINER IS NAMED, and the name is what makes a timeout survivable.
    `docker run` is a CLIENT: killing it — which is all `subprocess.run`'s
    timeout does — leaves the container running on the daemon. Found by
    running it: a 60-second command under a 6-second ceiling was still up
    half a minute later, holding its memory and pid allowance. On a 24/7
    fleet every timed-out command would leak one until the machine died.

    So the caller can always reach the container by name, and `run()` removes
    it when the client is killed.
    """
    mount = os.path.abspath(root).replace("\\", "/")
    name = f"fleet-{uuid.uuid4().hex[:16]}"
    argv = ["docker", "run", "--rm", "--name", name,
            "--memory", "1g", "--pids-limit", "256",
            "-v", f"{mount}:/work", "-w", "/work"]
    # THE CONTROL PLANE IS READ-ONLY INSIDE THE CONTAINER. The bind above is
    # the whole expert root read-write, which is right for the workspace and
    # was wrong for everything else: an audit pointed out that switching to
    # docker improved HOST isolation and did nothing about the agent editing
    # its own settings.toml, prompts and approvals, because they were inside
    # the mount. Docker applies the most specific mount, so a read-only bind
    # at /work/settings.toml wins over the read-write /work beneath it, and
    # the boundary is the kernel's rather than a check's — which is the whole
    # reason to prefer this backend. On `host` there is no equivalent, and
    # controlplane.py reverts instead; see its docstring for that distinction.
    import controlplane
    for host_path, container_path in controlplane.readonly_mounts(root):
        argv += ["-v", f"{host_path}:{container_path}:ro"]
    argv += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges",
             "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m"]
    if os.name != "nt":
        # Files created in a bind mount belong to the user INSIDE the
        # container, and with no --user that user is root. On Linux — where
        # a 24/7 fleet actually runs, and where a bind mount is a real host
        # directory rather than a translating filesystem — the agent's own
        # workspace came back root-owned: it could no longer rewrite, gate,
        # archive or clean the artifacts it had just produced, in the very
        # backend the manual recommends for untrusted work. Docker Desktop
        # maps ownership away, so this was invisible on the machine it was
        # written on and surfaced the first time CI ran it on Linux.
        # Dropping root inside the container is also strictly better
        # isolation: container root writing through a bind mount is a way
        # to touch host files as root.
        # The consequence to know about: a command in the container is no
        # longer root, so a system-wide `pip install` fails there. `pip
        # install --user` works (HOME is writable below) and so does
        # --target. Nothing in the platform installs packages inside the
        # sandbox; this only affects commands a model writes.
        argv += ["--user", f"{os.getuid()}:{os.getgid()}",
                 # that uid has no passwd entry and therefore no home; give
                 # it a writable, disposable one so tools that expect $HOME
                 # do not scatter dotfiles into the expert root or fail
                 "-e", "HOME=/tmp"]
    if not _cfg(cfg).get("sandbox_network"):
        argv += ["--network", "none"]           # default-deny egress
    for k, v in sorted(_agent_env(env).items()):
        # the container sees its own paths, not the host's
        argv += ["-e", f"{k}={'/work' if k == 'AGENT_ROOT' else v}"]
    argv += [str(_cfg(cfg).get("sandbox_image") or DOCKER_IMAGE),
             "sh", "-lc", cmd]
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_container(name)
        raise
    return r.returncode, r.stdout, r.stderr


def _kill_container(name):
    """Stop and remove a container by name. Best effort, never raises.

    `docker rm -f` is used rather than `stop`: the command has already
    exceeded its deadline, so a graceful shutdown period would only extend
    the overrun this exists to end.
    """
    try:
        subprocess.run(["docker", "rm", "-f", name],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def _hosted(kind, cmd, root, env, timeout, cfg):
    """E2B / Daytona / Cloudflare: create a sandbox, run one command, tear
    it down.

    Kept to the documented REST shape and stdlib-only. The platform never
    stores the key: it is read from the environment at call time.
    """
    import json
    import urllib.error
    import urllib.request
    key = os.environ.get(HOSTED[kind]["key"])
    if not key:
        return 127, "", f"sandbox '{kind}' unavailable: key not set"
    base = _hosted_url(kind, cfg)
    if not base:
        return 127, "", (f"sandbox '{kind}' unavailable: no endpoint "
                         f"configured. Nothing ran on the host.")
    body = json.dumps({"cmd": cmd, "cwd": "/home/user",
                       "envs": _agent_env(env),
                       "timeoutMs": int(timeout * 1000)}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/sandboxes/exec", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}",
                 "X-API-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout + 15) as r:
            out = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return 127, "", (f"sandbox '{kind}' refused the command: HTTP "
                         f"{e.code} {e.reason}")
    except Exception as e:
        return 127, "", f"sandbox '{kind}' unreachable: {e}"
    return (int(out.get("exitCode", out.get("exit_code", 0)) or 0),
            str(out.get("stdout", "")), str(out.get("stderr", "")))


def run(cmd, root, env=None, timeout=300, cfg=None):
    """Run one command in the configured backend. Returns (rc, out, err).
    Never raises for a backend problem — it reports it as a refusal."""
    if cfg is None:
        import tomllib
        try:
            with open(os.path.join(root, "settings.toml"), "rb") as f:
                cfg = tomllib.loads(f.read().decode("utf-8-sig"))
        except FileNotFoundError:
            cfg = {}
        except (OSError, ValueError) as e:
            return 127, "", f"sandbox configuration cannot be read: {e}"
    b = backend_name(cfg)
    if b in HOSTED and _cfg(cfg).get("sandbox_workload", "workspace") != "stateless":
        return 127, "", (f"sandbox '{b}' has no authorized workspace round-trip "
                         "implementation. Workspace execution is refused; no remote "
                         "or local command ran. Stateless execution must be explicit.")
    ok, why = available(cfg)
    if not ok:
        return 127, "", (f"sandbox '{b}' unavailable: {why}. Nothing was run "
                         f"on the host: fix the configured backend.")
    env, dropped = scrub_env({**os.environ, **(env or {})}, cfg, cmd)
    env["AGENT_ENV_SCRUBBED"] = str(len(dropped))
    if b == "host":
        rc, out, err = _host(cmd, root, env, timeout)
        err += "\n[UNSAFE developer host: descendants and authority files are NOT isolated.]"
    elif b == "docker":
        try:
            rc, out, err = _docker(cmd, root, env, timeout, cfg)
        except subprocess.TimeoutExpired as e:
            rc, out, err = _timeout_result(e, timeout)
        except Exception as e:
            return 127, "", f"sandbox 'docker' failed to start: {e}"
    else:
        rc, out, err = _hosted(b, cmd, root, env, timeout, cfg)
    if dropped and _looks_for_secrets(cmd):
        err += (f"\n[{len(dropped)} credential variable(s) were withheld from "
                f"this command: {', '.join(dropped[:8])}"
                f"{'...' if len(dropped) > 8 else ''}. The harness never hands "
                f"its keys to a command it did not write. If one is genuinely "
                f"needed, the owner adds it to [agent] command_env_allow.]")
    return rc, out, err


def _looks_for_secrets(cmd):
    """Only explain the scrub to a command that went looking — otherwise the
    note is noise on every single call."""
    low = str(cmd).lower()
    return any(w in low for w in ("env", "printenv", "os.environ", "getenv",
                                  "$env:", "set "))


def describe(cfg):
    b = backend_name(cfg)
    ok, why = available(cfg)
    return {"backend": b, "available": ok, "why": why,
            "env_scrubbed": list(SECRET_MARKERS),
            "env_allowed": list(_cfg(cfg).get("command_env_allow") or []),
            "network": bool(_cfg(cfg).get("sandbox_network")) if b != "host"
            else "host network",
            "image": str(_cfg(cfg).get("sandbox_image") or DOCKER_IMAGE)
            if b == "docker" else None}


def main():
    import argparse
    import json
    import tomllib
    ap = argparse.ArgumentParser(description="the execution backend")
    ap.add_argument("--root", default=".")
    ap.add_argument("--run", help="run one command through the backend")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    cfg = {}
    try:
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            cfg = tomllib.loads(f.read().decode("utf-8-sig"))
    except OSError:
        pass
    if a.run:
        rc, out, err = run(a.run, root, {"AGENT_ROOT": root}, 120, cfg)
        if a.json:
            print(json.dumps({"rc": rc, "stdout": out, "stderr": err}, indent=1))
        else:
            print(f"exit={rc}\n--- stdout ---\n{out}\n--- stderr ---\n{err}")
        raise SystemExit(0 if rc == 0 else 1)
    d = describe(cfg)
    print(json.dumps(d, indent=1) if a.json else
          f"sandbox backend: {d['backend']} — "
          f"{'READY' if d['available'] else 'UNAVAILABLE'}: {d['why']}")


if __name__ == "__main__":
    main()
