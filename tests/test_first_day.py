#!/usr/bin/env python3
"""THE FIRST TEN MINUTES WITH A REAL KEY, REHEARSED WITHOUT ONE.

There is a specific sequence a new operator runs on day one:

    python bootstrap.py --key DEEPSEEK_API_KEY=sk-...
    python loop.py check --root experts/<slug>
    python loop.py run --drain --root experts/<slug>

Every step of that had a gap. `bootstrap.py` was tested, but never from a
genuinely empty directory with a key going in. `loop.py check` — the ONLY
live probe this platform has, and therefore the first command whose output
somebody will trust — had never been run against anything that answers, so
nobody knew what a healthy probe even looks like. And nothing had ever
verified that a key written by bootstrap is the key that later reaches the
wire.

`fake_provider.py` closes it: a loopback server that speaks the provider API,
so the whole first day can be rehearsed end to end with a key that costs
nothing.

  1. bootstrap turns an empty directory into a running fleet, and never
     prints the key it was given
  2. the key it wrote is the key `loop.py check` presents
  3. a healthy probe says OK; a wrong key says FAIL and says why; an
     unreachable provider says so without hanging
  4. the probe is CHEAP — one small request per provider/model pair, not
     one per role
  5. after the probe passes, a real task runs to completion over the same
     provider
  6. exit codes are what a script would need them to be

Run from the agent/ directory:  python tests/test_first_day.py
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from common import AGENT_DIR
from fake_provider import FakeProvider

PY = sys.executable
KEY = "sk-" + "firstday-" + "0123456789abcdef"


def run(argv, cwd, timeout=300, env=None):
    return subprocess.run([PY] + argv, cwd=cwd, capture_output=True,
                          text=True, timeout=timeout,
                          env={**os.environ, "PYTHONUTF8": "1", **(env or {})})


def check_bootstrap_from_nothing(work, srv):
    """An empty directory, one command, a running fleet — and the key never
    printed."""
    home = os.path.join(work, "brand-new-fleet")
    os.makedirs(home)
    r = run(["bootstrap.py", "--home", home, "--offline", "--no-panel",
             "--key", f"DEEPSEEK_API_KEY={KEY}",
             "--expert", "First Day", "--identity", "prove day one works",
             "--json"], cwd=AGENT_DIR, timeout=420)
    combined = r.stdout + r.stderr
    assert KEY not in combined, (
        "bootstrap printed the API key it was given. Everything else it does "
        "is irrelevant if the first command echoes the credential into a "
        "terminal, a CI log or a screen recording")
    assert r.returncode in (0, 2), (r.returncode, combined[-600:])
    env_file = os.path.join(home, "agent.env")
    assert os.path.isfile(env_file), combined[-500:]
    with io.open(env_file, encoding="utf-8") as f:
        assert KEY in f.read(), "the key was not written to agent.env"
    mode_ok = True
    try:
        mode_ok = (os.stat(env_file).st_mode & 0o077) == 0
    except Exception:
        pass                                  # Windows ACLs differ
    for must in ("prompts", "settings.toml", "experts"):
        assert os.path.exists(os.path.join(home, must)), must
    experts = os.listdir(os.path.join(home, "experts"))
    assert experts, "no first expert was created"
    slug = experts[0]
    for must in ("identity.md", "settings.toml", "prompts"):
        assert os.path.exists(os.path.join(home, "experts", slug, must)), must
    print(f"[bootstrap] an empty directory became a fleet with an expert "
          f"({slug!r}) in one command; the key reached agent.env"
          f"{' with owner-only permissions' if mode_ok else ''} and appears "
          f"nowhere in {len(combined)} characters of output")
    return home, slug


def check_the_key_reaches_the_wire(home, slug, srv):
    """The key bootstrap wrote must be the key the probe presents.

    A key that is stored correctly and sent as an empty string is the most
    frustrating possible failure: everything looks configured and nothing
    works.
    """
    root = os.path.join(home, "experts", slug)
    _point_at(root, srv.base_url, "DEEPSEEK_API_KEY")
    srv.require_key = KEY
    srv.always(text="ok")
    r = run(["loop.py", "check", "--root", root], cwd=AGENT_DIR, timeout=180,
            env={"DEEPSEEK_API_KEY": KEY})
    out = r.stdout + r.stderr
    assert "OK" in out, f"a healthy provider did not probe OK:\n{out[-600:]}"
    assert KEY not in out, "the probe printed the key"
    assert srv.requests, "the probe never made a request"
    assert srv.last["headers"]["authorization"] == f"Bearer {KEY}", (
        "the key bootstrap stored is not the key that reached the wire")
    body = srv.last["payload"]
    assert body["max_tokens"] <= 32, (
        f"the probe asked for {body['max_tokens']} output tokens — a health "
        f"check should cost approximately nothing")
    assert len(json.dumps(body["messages"])) < 400, body["messages"]
    print(f"[probe-ok] `loop.py check` reported OK, presented exactly the key "
          f"bootstrap had stored, asked for {body['max_tokens']} output "
          f"tokens, and printed the key nowhere")


def check_a_bad_key_says_so(home, slug, srv):
    """The failure a new operator is most likely to hit."""
    root = os.path.join(home, "experts", slug)
    srv.require_key = "a-different-key"
    r = run(["loop.py", "check", "--root", root], cwd=AGENT_DIR, timeout=180,
            env={"DEEPSEEK_API_KEY": KEY})
    out = r.stdout + r.stderr
    assert "FAIL" in out, f"a rejected key did not report FAIL:\n{out[-500:]}"
    assert "401" in out or "unauthor" in out.lower(), out[-400:]
    assert r.returncode != 0, (
        "a failing probe must exit non-zero, or a setup script cannot branch "
        "on it")
    # …and no key at all is a different message, naming the variable
    r2 = run(["loop.py", "check", "--root", root], cwd=AGENT_DIR, timeout=180,
             env={"DEEPSEEK_API_KEY": ""})
    out2 = r2.stdout + r2.stderr
    assert "FAIL" in out2 and "DEEPSEEK_API_KEY" in out2, out2[-400:]
    assert "no API key" in out2, out2[-400:]
    print("[probe-fail] a rejected key reports FAIL with the HTTP status and "
          "exits non-zero; a missing key reports FAIL naming the exact "
          "environment variable to set — the two failures a first day "
          "actually produces, told apart")
    srv.require_key = KEY


def check_an_unreachable_provider_does_not_hang(home, slug):
    """The other day-one failure: a typo in base_url."""
    root = os.path.join(home, "experts", slug)
    _point_at(root, "http://127.0.0.1:1/v1", "DEEPSEEK_API_KEY")
    import time
    t0 = time.time()
    r = run(["loop.py", "check", "--root", root], cwd=AGENT_DIR, timeout=120,
            env={"DEEPSEEK_API_KEY": KEY})
    took = time.time() - t0
    out = r.stdout + r.stderr
    assert "FAIL" in out, out[-400:]
    assert took < 60, f"a refused connection took {took:.0f}s to report"
    print(f"[unreachable] a base_url nothing is listening on reported FAIL in "
          f"{took:.1f}s instead of hanging on a 20-second timeout per role")


def check_the_probe_is_cheap(home, slug, srv):
    """One request per provider/model PAIR, not per role.

    Nine roles pointing at one model must not mean nine paid calls every
    time somebody checks their setup.
    """
    root = os.path.join(home, "experts", slug)
    _point_at(root, srv.base_url, "DEEPSEEK_API_KEY")
    srv.requests.clear()
    srv.always(text="ok")
    r = run(["loop.py", "check", "--root", root], cwd=AGENT_DIR, timeout=180,
            env={"DEEPSEEK_API_KEY": KEY})
    with io.open(os.path.join(root, "settings.toml"), encoding="utf-8") as f:
        n_roles = len(re.findall(r"^\[roles\.", f.read(), re.M))
    pairs = {(rq["payload"]["model"],) for rq in srv.requests}
    assert len(srv.requests) <= max(2, len(pairs) + 1), (
        f"{n_roles} roles produced {len(srv.requests)} probe requests for "
        f"{len(pairs)} distinct model(s) — the probe must cache by pair")
    print(f"[cheap] {n_roles} roles sharing {len(pairs)} model(s) produced "
          f"{len(srv.requests)} probe request(s): the check caches by "
          f"provider/model pair rather than charging once per role")


def check_the_first_task_completes(home, slug, srv):
    """After the probe passes, the thing the operator actually wants."""
    root = os.path.join(home, "experts", slug)
    _point_at(root, srv.base_url, "DEEPSEEK_API_KEY")
    srv.script.clear()
    srv.reply(tool="write_file",
              args={"path": "out/first-day.md", "content": "it works"})
    srv.reply(tool="finish_task", args={"summary": "wrote the file"})
    srv.always(tool="finish_task", args={"summary": "ok"})
    r = run(["loop.py", "add", "--root", root, "--role", "practitioner",
             "--goal", "write the first-day file",
             "--done-check",
             "python -c \"import os,sys;sys.exit(0 if "
             "os.path.exists('out/first-day.md') else 1)\""],
            cwd=AGENT_DIR, timeout=120, env={"DEEPSEEK_API_KEY": KEY})
    assert r.returncode == 0, (r.stdout + r.stderr)[-400:]
    r2 = run(["loop.py", "run", "--drain", "--root", root], cwd=AGENT_DIR,
             timeout=420, env={"DEEPSEEK_API_KEY": KEY})
    with io.open(os.path.join(root, "state.json"), encoding="utf-8") as f:
        tasks = json.load(f)["tasks"]
    done = [t for t in tasks if t["status"] == "done"]
    assert done, (
        "the first real task did not complete:\n"
        + json.dumps([{k: t.get(k) for k in ("status", "error")}
                      for t in tasks])[:400]
        + (r2.stdout + r2.stderr)[-400:])
    assert os.path.isfile(os.path.join(root, "out", "first-day.md"))
    log = io.open(os.path.join(root, "logs", "agent.log"),
                  encoding="utf-8", errors="replace").read()
    assert KEY not in log, "the API key reached the agent log"
    print(f"[first-task] with the probe green, a gated task ran to completion "
          f"over the same provider — the artefact exists, the gate passed, "
          f"and the key appears nowhere in {len(log)} characters of log")


def _point_at(root, base_url, key_env):
    """Rewrite this expert's providers to one live provider.

    Rebuilt from the PARSED table rather than by regex over the text: the
    real settings.toml has nested tables, inline tables and comments, and a
    line-oriented rewrite produced a file tomllib would not read — which
    showed up as "the probe failed" rather than "the test broke its own
    fixture".
    """
    import tomllib
    p = os.path.join(root, "settings.toml")
    with io.open(p, "rb") as f:
        cfg = tomllib.load(f)

    def emit(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "[" + ", ".join(emit(x) for x in v) + "]"
        if isinstance(v, dict):
            return "{" + ", ".join(f"{k} = {emit(x)}"
                                   for k, x in v.items()) + "}"
        return json.dumps(str(v))

    lines = ["[agent]"]
    for k, v in (cfg.get("agent") or {}).items():
        lines.append(f"{k} = {emit(v)}")
    lines += ["", "[providers.deepseek]", f'base_url = {emit(base_url)}',
              f'api_key_env = {emit(key_env)}', ""]
    roles = cfg.get("roles") or {"practitioner": {}}
    for role in roles:
        lines += [f"[roles.{role}]", 'provider = "deepseek"',
                  'model = "probe-model"', ""]
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(chr(10).join(lines) + chr(10))


def main():
    work = tempfile.mkdtemp(prefix="first-day-")
    srv = FakeProvider()
    try:
        home, slug = check_bootstrap_from_nothing(work, srv)
        check_the_key_reaches_the_wire(home, slug, srv)
        check_a_bad_key_says_so(home, slug, srv)
        check_an_unreachable_provider_does_not_hang(home, slug)
        check_the_probe_is_cheap(home, slug, srv)
        check_the_first_task_completes(home, slug, srv)
        print("PASS test_first_day")
    finally:
        srv.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
