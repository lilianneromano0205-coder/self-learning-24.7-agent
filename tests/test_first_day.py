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
    # …and no key at all is a different message, naming the variable.
    # "No key at all" must mean no key in ANY declared source. The canonical
    # resolver (credentials.resolve) rightly falls back to the expert's own
    # agent.env when the environment variable is empty — fleet.create copies
    # the fleet's env file into every expert root. This check used to pass
    # only because the loop's private resolver modeled fewer sources than
    # the runtime; encoding that fork here is how it survived. So empty the
    # file source too, not just the variable.
    env_file = os.path.join(root, "agent.env")
    held = env_file + ".hold"
    os.replace(env_file, held)
    try:
        r2 = run(["loop.py", "check", "--root", root], cwd=AGENT_DIR,
                 timeout=180, env={"DEEPSEEK_API_KEY": ""})
    finally:
        os.replace(held, env_file)
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

    # CHEAP IS NOT FREE, AND FREE IS NOT INVISIBLE. Each of those requests is
    # a real chat/completions call against a real key. They were metered
    # nowhere, while modelgateway.py opened with "every provider call is
    # metered, attributed and bounded" — the docstring of the one module that
    # would have had to record them. The test above asserts the COUNT of
    # requests and could never have noticed, because a request that is never
    # recorded produces no row to contradict.
    import sys as _sys
    _sys.path.insert(0, AGENT_DIR)
    import modelgateway
    rows = [c for c in modelgateway.calls(root) if c["purpose"] == "probe"]
    assert len(rows) >= len(srv.requests), (
        f"{len(srv.requests)} live probe request(s) were made and "
        f"{len(rows)} reached the ledger — an unmetered provider path is "
        f"how the daily budget breaker stops seeing spend")
    assert all(r["provider"] and r["model"] for r in rows), rows[:2]
    print(f"[metered] all {len(rows)} probe call(s) landed in the model-call "
          f"ledger with their provider and model — `loop.py check` is a real "
          f"provider call and is now attributed like any other")


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

    agent_table = dict(cfg.get("agent") or {})
    # The fixture's subject is bootstrap -> key -> first task, not the
    # execution backend. The shipped default is `docker`, which is right for
    # a real install and unavailable on any machine without usable Linux
    # containers (every GitHub Windows runner) — there the first task fails
    # with rc 127 and this file reports "the first real task did not
    # complete", which names the wrong thing. It declares the trusted
    # developer host, as every other keyless fixture here does.
    agent_table["sandbox"] = "host"
    agent_table["allow_unsafe_host"] = True
    lines = ["[agent]"]
    for k, v in agent_table.items():
        lines.append(f"{k} = {emit(v)}")
    lines += ["", "[providers.deepseek]", f'base_url = {emit(base_url)}',
              f'api_key_env = {emit(key_env)}', ""]
    roles = cfg.get("roles") or {"practitioner": {}}
    for role in roles:
        lines += [f"[roles.{role}]", 'provider = "deepseek"',
                  'model = "probe-model"', ""]
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(chr(10).join(lines) + chr(10))



def check_one_key_produces_a_working_fleet():
    """The gap between "I gave you a key" and "it works".

    A key is only ONE of the three things a provider needs: the endpoint has
    to be configured and every role has to point at it. Until this existed an
    owner pasted a key and the fleet went on aiming at whatever the template
    shipped with -- silently, because a role pointing at a provider with no
    key looks exactly like a role that is simply idle.
    """
    import tomllib
    sys.path.insert(0, AGENT_DIR)
    import bootstrap, fleet

    saved = {k: os.environ.pop(k, None) for k in
             ("GROQ_API_KEY", "DEEPSEEK_API_KEY", "CLOUDFLARE_API_TOKEN",
              "CLOUDFLARE_ACCOUNT_ID", "OPENAI_API_KEY", "NVIDIA_API_KEY",
              "HF_TOKEN", "OPENROUTER_API_KEY", "MISTRAL_API_KEY")}
    home = tempfile.mkdtemp(prefix="activate-")
    try:
        def fresh(keys):
            for k in list(saved):
                os.environ.pop(k, None)
            h = tempfile.mkdtemp(prefix="act-", dir=home)
            bootstrap.ensure_env(h, keys)
            bootstrap.load_env(h)
            fleet.create(h, "T", "x")
            return h, os.path.join(h, "experts", "t")

        def roles_of(root):
            with io.open(os.path.join(root, "settings.toml"),
                         encoding="utf-8-sig") as f:
                d = tomllib.loads(f.read())
            return d, sorted({r.get("provider") for r in d["roles"].values()})

        # --- no key at all: refuse, do not guess
        h0, r0 = fresh([])
        assert bootstrap.activate(h0, root=r0) == {}, \
            "activation invented a provider with no credentials present"

        # --- one key: every role moves, and the endpoint is written
        h1, r1 = fresh(["GROQ_API_KEY=gsk-not-a-real-key"])
        _d, before = roles_of(r1)
        res = bootstrap.activate(h1, root=r1)
        d, after = roles_of(r1)
        assert res["provider"] == "groq", res
        assert after == ["groq"], (before, after)
        assert res["roles"] >= 8, f"only {res['roles']} roles were repointed"
        assert d["providers"]["groq"]["base_url"] == \
            "https://api.groq.com/openai/v1", d["providers"]["groq"]
        # the owner's own annotations survive: this file is full of comments
        # explaining each choice, and a TOML round-trip would delete them all
        with io.open(os.path.join(r1, "settings.toml"), encoding="utf-8-sig") as f:
            assert "#" in f.read(), "rewriting settings.toml stripped its comments"
        # and re-running changes nothing
        assert bootstrap.activate(h1, root=r1) == res, "activation is not idempotent"

        # --- credentials that cannot form a working URL are REFUSED, not
        #     half-applied. Cloudflare needs an account id in the path, so a
        #     token alone would produce .../accounts/{CLOUDFLARE_ACCOUNT_ID}/...
        #     and fail as a 404 much later. Fail closed, like every backend.
        h2, r2 = fresh(["CLOUDFLARE_API_TOKEN=cf-not-real"])
        assert bootstrap.activate(h2, root=r2) == {}, \
            "a token with no account id was activated into a broken URL"
        h3, r3 = fresh(["CLOUDFLARE_API_TOKEN=cf-not-real",
                        "CLOUDFLARE_ACCOUNT_ID=acct-123"])
        res3 = bootstrap.activate(h3, root=r3)
        d3, _ = roles_of(r3)
        assert res3["provider"] == "cloudflare", res3
        assert "acct-123" in d3["providers"]["cloudflare"]["base_url"], \
            d3["providers"]["cloudflare"]["base_url"]
        assert "{" not in d3["providers"]["cloudflare"]["base_url"], \
            "an unsubstituted placeholder reached the configuration"

        # --- with several keys present, the ranking is by what the provider
        #     actually GIVES AWAY, not by model size: a standing free
        #     allowance outranks a paid account.
        h4, r4 = fresh(["OPENAI_API_KEY=sk-not-real", "GROQ_API_KEY=gsk-not-real"])
        res4 = bootstrap.activate(h4, root=r4)
        assert res4["provider"] == "groq", \
            f"picked {res4['provider']} over a free tier"
        names = [p[0] for p in bootstrap.PROVIDER_CATALOG]
        assert names.index("cloudflare") < names.index("openai"), \
            "the catalogue no longer ranks a standing free tier first"

        # --- every base_url in the catalogue is a real absolute https URL
        #     with no leftover placeholder except the ones declared in `needs`
        for name, url, key_env, model, needs, note in bootstrap.PROVIDER_CATALOG:
            assert url.startswith("https://"), (name, url)
            assert not url.endswith("/"), f"{name}: trailing slash doubles the path"
            assert "/chat/completions" not in url, \
                f"{name}: base_url must NOT include the endpoint path"
            for ph in re.findall(r"\{(\w+)\}", url):
                assert ph in needs, f"{name}: {ph} is unsubstitutable"
            assert key_env.isupper() and model, (name, key_env, model)
        print(f"[activate] one key repoints every role at the provider that key "
              f"belongs to, writes its verified endpoint and leaves the file's "
              f"comments intact; {len(bootstrap.PROVIDER_CATALOG)} providers are "
              f"catalogued, ranked by what they actually give away; incomplete "
              f"credentials are refused rather than half-applied; and running "
              f"it twice changes nothing")
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)
        shutil.rmtree(home, ignore_errors=True)

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
        check_one_key_produces_a_working_fleet()
        print("PASS test_first_day")
    finally:
        srv.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
