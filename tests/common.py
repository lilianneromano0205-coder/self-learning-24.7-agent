"""Shared harness for the acceptance tests.

Each test gets an isolated sandbox root under tests/tmp/<name>/ with its own
settings.toml (mock providers only — no network, no keys), a copy of prompts/,
and whatever mock scripts it declares. Production state.json is never touched.
"""

import json
import os
import shutil
import subprocess
import sys
import time

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOP = os.path.join(AGENT_DIR, "loop.py")
PY = sys.executable

BASE_SETTINGS = """\
[agent]
max_steps = 50
command_timeout_seconds = 30
poll_interval_seconds = 1
context_token_threshold = 50000
lock_stale_minutes = 30
reflect_after = [{reflect_after}]
exam_threshold = 90
reexam_days = [0]
inbox_settle_seconds = 0

{extra}

{providers}

{roles}
"""


def agent_setting(root, line):
    """Add a key to the [agent] TABLE of a sandbox's settings.toml.

    Appending to the end of the file would land the key inside whatever
    section happens to be last (a [roles.*] table), where the loop never
    reads it -- a silent no-op that makes a test look green for the wrong
    reason. This inserts it where it belongs.
    """
    p = os.path.join(root, "settings.toml")
    with open(p, "r", encoding="utf-8") as f:
        text = f.read()
    assert "[agent]" in text, "sandbox settings.toml has no [agent] table"
    out = text.replace("[agent]\n", "[agent]\n" + line.strip() + "\n", 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(out)
    return p


def make_sandbox(name, providers, roles, scripts, reflect_after="", extra="",
                 role_tools=None):
    """providers: dict prov_name -> dict(script=..., delay_seconds=..., style=...)
    roles: dict role_name -> prov_name
    scripts: dict relpath -> list (mock script content)
    role_tools: optional dict role_name -> tool allowlist (Rule of Two)"""
    # sandboxes live in the REAL temp dir, never under OneDrive: its
    # background sync holds freshly written files and made heavy suite runs
    # flake at random (different test each run, all passing solo). Override
    # with AGENT_TEST_TMP if you want them elsewhere.
    import tempfile
    base = os.environ.get("AGENT_TEST_TMP") or os.path.join(
        tempfile.gettempdir(), "agent-suite")
    sb = os.path.join(base, name)
    # OneDrive/antivirus can hold a just-deleted directory for a moment, so
    # rmtree "succeeds" while the path still exists — retry instead of dying
    for attempt in range(10):
        shutil.rmtree(sb, ignore_errors=True)
        try:
            os.makedirs(sb)
            break
        except FileExistsError:
            if attempt == 9:
                raise
            time.sleep(0.3)
    shutil.copytree(os.path.join(AGENT_DIR, "prompts"), os.path.join(sb, "prompts"))

    prov_blocks = []
    for pname, p in providers.items():
        lines = [f"[providers.{pname}]", 'type = "mock"']
        for k, v in p.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, dict):
                inner = ", ".join(f"{ik} = {iv}" for ik, iv in v.items())
                lines.append(f"{k} = {{{inner}}}")
            else:
                lines.append(f"{k} = {v}")
        prov_blocks.append("\n".join(lines))
    role_tools = role_tools or {}
    role_blocks = []
    for r, p in roles.items():
        block = f'[roles.{r}]\nprovider = "{p}"\nmodel = "mock"'
        if r in role_tools:
            quoted = ", ".join(f'"{t}"' for t in role_tools[r])
            block += f"\ntools = [{quoted}]"
        role_blocks.append(block)
    with open(os.path.join(sb, "settings.toml"), "w", encoding="utf-8") as f:
        f.write(BASE_SETTINGS.format(
            reflect_after=reflect_after,
            extra=extra,
            providers="\n\n".join(prov_blocks),
            roles="\n\n".join(role_blocks),
        ))
    for rel, content in scripts.items():
        p = os.path.join(sb, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(content, f)
    return sb


def free_port():
    """An OS-assigned free port. Fixed test ports collide when the suite runs
    tests back to back — a socket left in TIME_WAIT from the previous test is
    enough to fail a bind, which showed up as random test failures that always
    passed in isolation. A flaky suite is a broken instrument, so never
    hard-code a port."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def add_task(root, role, goal, course=None):
    cmd = [PY, LOOP, "add", "--role", role, "--goal", goal, "--root", root]
    if course:
        cmd += ["--course", course]
    subprocess.run(cmd, check=True, capture_output=True)


def run_drain(root, timeout=60):
    return subprocess.run([PY, LOOP, "run", "--drain", "--root", root],
                          timeout=timeout).returncode


def start(root):
    return subprocess.Popen([PY, LOOP, "run", "--drain", "--root", root])


def read_state(root):
    with open(os.path.join(root, "state.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def wait_for(predicate, timeout, what):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for: {what}")


# ------------------------------------------------------------- the panel
# Shared by every test that drives ui.py: start it on a free port, talk to
# it, and shut it down GRACEFULLY (POST /api/shutdown) so the panel
# terminates its own child drivers — a bare terminate() on Windows orphans
# them, and orphans were the cause of random in-suite failures.

def api(base, method, path, body=None, raw=False, token=None, timeout=20):
    import urllib.request
    data = body if raw else (json.dumps(body).encode("utf-8")
                             if body is not None else None)
    headers = {"Content-Type": "application/json"} if not raw else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def start_panel(home, token=None, extra_args=()):
    """Launch ui.py for a sandbox home; returns (proc, base_url)."""
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    cmd = [PY, os.path.join(AGENT_DIR, "ui.py"), "--home", home,
           "--port", str(port)] + list(extra_args)
    if token:
        cmd += ["--token", token]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            env={**os.environ, "PYTHONUTF8": "1"})
    for _ in range(75):
        try:
            api(base, "GET", "/api/experts", token=token)
            return proc, base
        except Exception:
            time.sleep(0.2)
    proc.terminate()
    raise AssertionError("panel did not come up")


def stop_panel(proc, base, token=None):
    try:
        api(base, "POST", "/api/shutdown", {}, token=token, timeout=5)
    except Exception:
        pass
    try:
        proc.wait(10)
    except Exception:
        proc.terminate()
        proc.wait(10)


def serve_dir(directory):
    """A loopback HTTP server over `directory`, for tests that need a real
    fetch. Ingestion accepts http/https only — a file:// stand-in used to be
    the offline trick, but it also meant the suite never exercised the real
    scheme and silently blessed reading the local disk. Returns (base_url,
    shutdown_callable)."""
    import functools
    import http.server
    import os as _os
    import threading
    _os.environ["no_proxy"] = "127.0.0.1,localhost"
    _os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    # Ingestion refuses private/loopback destinations by default (SSRF: a
    # public URL that redirects to 169.254.169.254 is the classic attack).
    # A test fixture IS a deliberate loopback target, so it opts in the same
    # way an operator ingesting an intranet page would — visibly.
    _os.environ["ALLOW_PRIVATE_INGEST"] = "1"
    handler = functools.partial(_QuietFiles, directory=directory)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}", srv.shutdown


class _QuietFiles(__import__("http.server", fromlist=["x"]).SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass
