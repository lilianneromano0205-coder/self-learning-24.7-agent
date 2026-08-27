#!/usr/bin/env python3
"""Plug in any model, from any platform — and any tool you provide.

1. Known rails add by name; a custom OpenAI-compatible endpoint adds by URL;
   settings.toml round-trips through the writer WITHOUT losing anything (the
   agent block, chains, role tool-allowlists, provider headers all survive)
   and never gains key material.
2. Roles can be re-pointed at any provider/model, including fallback and
   escalation, and the loop actually uses what was written.
3. A model catalog is fetched from a provider's /models endpoint (served
   locally here, so the contract is proven without spending a cent).
4. Tools YOU provide (tools.json) appear as capabilities, honour their
   ready_check, and reach agents through the capability note.

Run from the agent/ directory:  python tests/test_providers.py
"""

import json
import os
import sys
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer

from common import free_port, AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import loop
import providers as P
import toolbox

PORT = free_port()
CATALOG = {"data": [
    {"id": "vendor/big-model", "context_length": 200000,
     "pricing": {"prompt": "0.5"}},
    {"id": "vendor/small-model:free", "context_length": 32000,
     "pricing": {"prompt": "0"}},
    {"id": "other/thing", "pricing": {"prompt": "1.0"}},
]}


class Cat(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps(CATALOG).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    sb = make_sandbox("providers", providers={"m": {"script": "s.json"}},
                      roles={"tester": "m"}, scripts={"s.json": []},
                      extra=('max_task_usd = 1.5\n[agent.chain]\n'
                             'ripper = "watcher"'),
                      role_tools={"tester": ["write_file"]})

    # --- 1. adding providers, and a lossless settings round-trip
    before = P.load(sb)
    P.add(sb, "openrouter")                       # known rail, by name alone
    P.add(sb, "mygateway", base_url="https://gw.internal.example/v1/",
          key_env="GW_TOKEN", native_tools=False,
          headers={"X-Team": "fleet"})
    cfg = P.load(sb)
    assert cfg["providers"]["openrouter"]["base_url"] == \
        "https://openrouter.ai/api/v1"
    assert cfg["providers"]["openrouter"]["api_key_env"] == "OPENROUTER_API_KEY"
    gw = cfg["providers"]["mygateway"]
    assert gw["base_url"] == "https://gw.internal.example/v1"   # trailing / gone
    assert gw["native_tools"] is False and gw["extra_headers"]["X-Team"] == "fleet"
    # nothing from the original settings was lost
    assert cfg["agent"]["max_task_usd"] == 1.5
    assert cfg["agent"]["chain"]["ripper"] == "watcher"
    assert cfg["roles"]["tester"]["tools"] == ["write_file"]
    assert cfg["providers"]["m"]["type"] == "mock"
    assert before["agent"]["poll_interval_seconds"] == \
        cfg["agent"]["poll_interval_seconds"]
    raw = open(os.path.join(sb, "settings.toml"), encoding="utf-8").read()
    tomllib.loads(raw)          # still valid TOML
    assert "sk-" not in raw and "GW_TOKEN" in raw, "env NAMES only, never values"
    print("[add] known rail + custom endpoint added; settings round-tripped "
          "losslessly; only key NAMES are written")

    # --- 2. re-pointing roles, and the loop honouring it
    P.set_role(sb, "watcher", "mygateway", "vendor/big-model",
               fallback_provider="openrouter", fallback_model="a/b",
               escalate_model="vendor/huge")
    r = P.load(sb)["roles"]["watcher"]
    assert r["provider"] == "mygateway" and r["model"] == "vendor/big-model"
    assert r["fallback_provider"] == "openrouter" and r["escalate_model"] == "vendor/huge"
    a = loop.Agent(sb)
    rc = a.role_cfg("watcher")
    assert rc["model"] == "vendor/big-model", "the loop must read the new wiring"
    assert a.provider_cfg("mygateway")["native_tools"] is False, \
        "a no-function-calling endpoint keeps its inline-JSON setting"
    try:
        P.set_role(sb, "watcher", "ghostprovider", "x")
        raise AssertionError("an unknown provider must be refused")
    except SystemExit:
        pass
    print("[roles] any role re-pointed at any provider/model incl. fallback + "
          "escalation; unknown providers refused")

    # --- 3. a real catalog fetch from an OpenAI-compatible /models endpoint
    srv = HTTPServer(("127.0.0.1", PORT), Cat)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        P.add(sb, "localrail", base_url=f"http://127.0.0.1:{PORT}/v1",
              key_env="LOCAL_KEY")
        models = P.catalog(sb, "localrail")
        assert [m["id"] for m in models] == ["vendor/big-model",
                                             "vendor/small-model:free",
                                             "other/thing"]
        assert models[0]["context"] == 200000
        free = P.catalog(sb, "localrail", free_only=True)
        assert [m["id"] for m in free] == ["vendor/small-model:free"]
        filt = P.catalog(sb, "localrail", filt="vendor")
        assert len(filt) == 2 and all("vendor" in m["id"] for m in filt)
        print("[catalog] models listed from a live /models endpoint; free-only "
              "and text filters work")
    finally:
        srv.shutdown()

    # --- 4. tools YOU provide become capabilities agents can see and use
    with open(os.path.join(sb, "tools.json"), "w", encoding="utf-8") as f:
        json.dump([
            {"name": "my_api", "cmd": "python tools/my_api.py --json",
             "desc": "our internal API", "ready_check": f'"{sys.executable}" -c "pass"'},
            {"name": "needs_setup", "cmd": "python tools/x.py",
             "desc": "not wired yet",
             "ready_check": f'"{sys.executable}" -c "import sys;sys.exit(3)"'},
        ], f)
    tools = {t["name"]: t for t in toolbox.custom_tools(sb)}
    assert tools["my_api"]["ready"] is True
    assert tools["needs_setup"]["ready"] is False
    s = toolbox.scan(sb)
    assert s["capabilities"]["my_api"]["ready"] is True
    assert "our internal API" in s["capabilities"]["my_api"]["how"]
    note = toolbox.capability_note(sb)
    assert "my_api" in note and "python tools/my_api.py --json" in note
    assert "needs_setup" in note.split("MISSING")[-1], \
        "an unready custom tool must land under MISSING, not READY"
    print("[custom] your own tools appear as capabilities, honour ready_check, "
          "and reach agents with the exact command to run")

    # --- 5. a tools.json at the FLEET home reaches every expert in it
    # (found live: only the expert dir and the code dir were searched, so a
    #  fleet-wide tools.json was silently invisible)
    import fleet
    home2 = make_sandbox("providers_fleet", providers={"m": {"script": "s.json"}},
                         roles={"tester": "m"}, scripts={"s.json": []})
    with open(os.path.join(home2, "tools.json"), "w", encoding="utf-8") as f:
        json.dump([{"name": "fleet_wide_tool", "cmd": "python tools/f.py",
                    "desc": "shared across the whole fleet"}], f)
    root2 = fleet.create(home2, "Any Expert", "x")
    names = [t["name"] for t in toolbox.custom_tools(root2)]
    assert "fleet_wide_tool" in names, \
        f"a fleet-home tools.json must reach its experts, got {names}"
    assert "fleet_wide_tool" in toolbox.capability_note(root2)
    print("[fleet-tools] a tools.json at the fleet home reaches every expert in it")

    # --- 6. PLUG AND PLAY: a key in the environment is a provider, no
    #     settings edit needed — and every refusal names its fix
    sb6 = make_sandbox("providers_auto", providers={"m": {"script": "s.json"}},
                       roles={"tester": "m"}, scripts={"s.json": []})
    a6 = loop.Agent(sb6)
    saved = {k: os.environ.get(k) for k in
             ("XAI_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")}
    try:
        # no key -> a KNOWN rail refuses NAMING the env var and the command
        os.environ.pop("XAI_API_KEY", None)
        try:
            a6.provider_cfg("xai")
            raise AssertionError("a keyless rail was wired anyway")
        except RuntimeError as e:
            assert "XAI_API_KEY" in str(e) and "providers.py add" in str(e), e
        # key present -> wired from the catalog at runtime, correct base_url
        os.environ["XAI_API_KEY"] = "test-not-a-real-key"
        p = a6.provider_cfg("xai")
        assert p["base_url"] == "https://api.x.ai/v1", p
        assert a6.cfg["providers"]["xai"] is p, "not cached for the session"
        # an unknown name still fails plainly
        try:
            a6.provider_cfg("nonexistent-rail")
            raise AssertionError("an unknown provider resolved")
        except RuntimeError as e:
            assert "settings.toml" in str(e)
        # cloudflare: the URL needs the account id, and its absence is a
        # NAMED error at wire time, not an opaque 404 months later
        os.environ["CLOUDFLARE_API_TOKEN"] = "test-not-a-real-token"
        os.environ.pop("CLOUDFLARE_ACCOUNT_ID", None)
        try:
            a6.provider_cfg("cloudflare")
            raise AssertionError("cloudflare wired without an account id")
        except RuntimeError as e:
            assert "CLOUDFLARE_ACCOUNT_ID" in str(e), e
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = "abc123"
        p = a6.provider_cfg("cloudflare")
        assert p["base_url"].endswith("/accounts/abc123/ai/v1"), p
        # settings always outrank the catalog: a configured base_url wins
        sb7 = make_sandbox("providers_override",
                           providers={"m": {"script": "s.json"}},
                           roles={"tester": "m"}, scripts={"s.json": []})
        P.add(sb7, "xai", base_url="https://my-proxy.example/v1",
              key_env="XAI_API_KEY")
        a7 = loop.Agent(sb7)
        assert a7.provider_cfg("xai")["base_url"] == \
            "https://my-proxy.example/v1", "the catalog overrode settings"
        # detect() reports the truth of this environment
        rows = {r["rail"]: r for r in P.detect(sb7)}
        assert rows["xai"]["key_present"] and rows["xai"]["wired"]
        assert rows["ollama"]["local"] and not rows["ollama"]["wired"]
        assert not rows["anthropic"]["key_present"] \
            or os.environ.get("ANTHROPIC_API_KEY")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("[plug] a key in the environment IS a provider: a role named a "
          "rail with no settings entry and it wired from the verified "
          "catalog at runtime; keyless rails refuse naming the exact env "
          "var; cloudflare's missing account id is a named error at wire "
          "time; an explicit settings entry always outranks the catalog")
    print("PASS test_providers")


if __name__ == "__main__":
    main()
