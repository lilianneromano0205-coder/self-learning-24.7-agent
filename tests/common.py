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
# Trusted keyless test fixtures deliberately exercise the developer backend.
sandbox = "host"
allow_unsafe_host = true
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

    Setting a key the table ALREADY defines used to insert a second copy,
    which tomllib rejects outright ("Cannot overwrite a value") -- the next
    trap along from the silent no-op above, and one that fails in the loader
    rather than at the call site. An existing key is now replaced in place.
    """
    p = os.path.join(root, "settings.toml")
    with open(p, "r", encoding="utf-8") as f:
        text = f.read()
    assert "[agent]" in text, "sandbox settings.toml has no [agent] table"
    key = line.split("=", 1)[0].strip()
    head, sep, rest = text.partition("[agent]\n")
    # the [agent] table ends at the next table header
    body, nxt, tail = rest.partition("\n[")
    lines = body.splitlines()
    for i, l in enumerate(lines):
        if l.split("=", 1)[0].strip() == key and "=" in l:
            lines[i] = line.strip()
            break
    else:
        lines.insert(0, line.strip())
    out = head + sep + "\n".join(lines) + nxt + tail
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


def seal_variant_protocol(root, vid, dev_battery=None, pass_gate="true",
                          seeds=(0, 1, 2), skip_dev_seed=None):
    """Owner-side sealed three-battery protocol for variant fixtures.

    The honest full battery — 42 distinct tasks x 3 seeds x 2 cloned arms,
    plus a 24-hour regression delay — cannot fit an acceptance suite. So the
    fixture fabricates the sealed RECEIPTS for the hidden phases through the
    same owner authority the real trial writes them with; promote() then
    verifies protocol hashes, receipt completeness, non-regression and the
    paired significance test exactly as in production. Development receipts
    can stay REAL: pass skip_dev_seed for the seed the test's own trial will
    seal itself. MIN_REGRESSION_DELAY is module state read at call time —
    the only seam — and shrinking it here changes no production default.

    Returns the sealed development battery (the caller's tasks, given the
    ids and families configure_evaluation demands)."""
    import variants as V
    import learning_authority as authority
    V.MIN_REGRESSION_DELAY = 0
    fams = ["fam-a", "fam-b", "fam-c", "fam-d", "fam-e"]
    dev = []
    for i, item in enumerate(dev_battery or
                             [{"goal": f"sealed dev goal {i}",
                               "done_check": pass_gate} for i in range(2)]):
        row = dict(item)
        row.setdefault("id", f"dev-{i}")
        row.setdefault("family", fams[i % 5])
        dev.append(row)

    def hidden(tag, n):
        return [{"id": f"{tag}-{i}", "goal": f"{tag} sealed goal {i}",
                 "done_check": pass_gate, "family": fams[i % 5]}
                for i in range(n)]

    batteries = {"development": dev, "promotion": hidden("prm", 20),
                 "regression": hidden("reg", 20)}
    V.configure_evaluation(root, vid, batteries, seeds=list(seeds),
                           delay_seconds=0)
    protocol = authority.load(root, "variant-protocol", vid)
    ph = authority.digest(protocol)
    for phase in ("development", "promotion", "regression"):
        n = len(batteries[phase])
        for s in seeds:
            if phase == "development" and s == skip_dev_seed:
                continue
            authority.store(root, "variant-result", f"{vid}-{phase}-{s}", {
                "results": {
                    "base": {"tasks": n, "passes": 0, "gate_rejects": n,
                             "task_ids": [], "outcomes": [False] * n},
                    "variant": {"tasks": n, "passes": n, "gate_rejects": 0,
                                "task_ids": [], "outcomes": [True] * n}},
                "completed": time.time(), "seed": s, "protocol_hash": ph})
    return dev


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
