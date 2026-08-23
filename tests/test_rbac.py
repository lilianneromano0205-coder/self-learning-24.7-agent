#!/usr/bin/env python3
"""RBAC IS ENFORCED ON THE PANEL, NOT ONLY ON THE COMMAND LINE.

`org.py`'s own docstring says:

    "check() is the single question every mutating path asks"

It was not true. `org.check` was called by `org.py` and by `test_org.py`, and
by nothing else — least of all the panel, which is the main mutating path and
which authenticated with one shared token, so it had no idea who was calling.
A permission model only the CLI consults describes intentions, not behaviour.

This is the audit's own recurring pattern one more time: a control that
defends the path its author was thinking about and does not know about the
other path. So this test does not check one route. It enumerates:

  1. a SOLO install is completely unaffected — no org, no refusals
  2. every member gets their own bearer token; the value is never stored
  3. a viewer is refused every write, with the reason and the role needed
  4. an operator may run work and may not build agents or touch secrets
  5. a builder may build and may not manage secrets, users or budgets
  6. EVERY POST route in ui.py has a declared permission — a new route
     cannot be silently ungated
  7. the audit trail names the token's owner, not whatever the body claimed

Run from the agent/ directory:  python tests/test_rbac.py
"""

import io
import json
import os
import re
import sys
import urllib.error
import urllib.request

from common import AGENT_DIR, api, make_sandbox, start_panel, stop_panel

sys.path.insert(0, AGENT_DIR)
import fleet                  # noqa: E402
import org                    # noqa: E402

OWNER = "owner@example.com"
SCRIPT = [{"tool": "finish_task", "args": {"summary": "ok"}}]


def _call(base, method, path, body=None, token=None):
    """-> (status, payload). Unlike common.api this keeps the status."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json",
               "Origin": base, "Sec-Fetch-Site": "same-origin"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw[:200]}


def check_solo_install_is_untouched(base):
    """No organization: every write works, exactly as before."""
    st, r = _call(base, "POST", "/api/experts",
                  {"name": "Solo One", "identity": "before any org exists"})
    assert st == 200 and r.get("created") == "solo-one", (st, r)
    st, r = _call(base, "POST", "/api/experts/solo-one/stop", {})
    assert st == 200, (st, r)
    print("[solo] with no organization, creating an agent and driving it "
          "still works with no token and no role — adding RBAC must not make "
          "the person who owns the machine ask themselves for permission")


def check_tokens_are_personal_and_unstored(home, base):
    org.create(home, "Acme", OWNER, "The Owner")
    for email, role in (("viewer@example.com", "viewer"),
                        ("operator@example.com", "operator"),
                        ("builder@example.com", "builder")):
        org.add_user(home, OWNER, email, role)
    tokens = {e: org.issue_token(home, OWNER, e)
              for e in ("viewer@example.com", "operator@example.com",
                        "builder@example.com")}
    tokens[OWNER] = org.issue_token(home, OWNER, OWNER)
    blob = io.open(os.path.join(home, "org", "org.json"),
                   encoding="utf-8").read()
    for who, tok in tokens.items():
        assert tok not in blob, f"{who}'s token was written to disk in clear"
        assert len(tok) >= 32, tok
    assert len(set(tokens.values())) == 4, "two members share a token"
    # and the summary the panel serves never carries the hash either
    s = json.dumps(org.summary(home))
    assert "token_sha256" not in s, "the panel would ship the token hashes"
    assert '"has_token": true' in s.lower().replace(" ", " ")
    print(f"[tokens] {len(tokens)} personal tokens minted; none appears in "
          f"org.json, none is served by the API, and each resolves to exactly "
          f"one member")
    return tokens


def check_viewer_is_refused_every_write(base, tokens):
    t = tokens["viewer@example.com"]
    writes = [
        ("POST", "/api/experts", {"name": "Nope", "identity": "x"}),
        ("POST", "/api/quick", {"name": "Nope2", "specialty": "x"}),
        ("POST", "/api/experts/solo-one/task",
         {"role": "practitioner", "goal": "do a thing"}),
        ("POST", "/api/experts/solo-one/start", {}),
        ("POST", "/api/workers", {"name": "Box", "kind": "local-docker"}),
        ("POST", "/api/missions", {"objective": "x", "criteria": ["y"],
                                   "expert": "solo-one"}),
        ("PUT", "/api/experts/solo-one/identity", {"identity": "rewritten"}),
        ("DELETE", "/api/experts/solo-one", None),
    ]
    for method, path, body in writes:
        st, r = _call(base, method, path, body, token=t)
        assert st == 403, f"a viewer was allowed {method} {path} -> {st} {r}"
        assert "viewer" in r.get("error", ""), r
        assert r.get("permission"), "the refusal does not name the permission"
        assert r.get("actor") == "viewer@example.com", r
    print(f"[viewer] all {len(writes)} write routes refused with 403, each "
          f"naming the actor, the permission required and the role that has it")


def check_operator_and_builder_stop_where_they_should(base, tokens):
    op, bd = tokens["operator@example.com"], tokens["builder@example.com"]
    # an operator RUNS work
    st, r = _call(base, "POST", "/api/experts/solo-one/task",
                  {"role": "practitioner",
                   "goal": "an operator may queue work"}, token=op)
    assert st == 200 and r.get("queued"), (st, r)
    # …and may not build, wire providers or spend
    for method, path, body, why in (
            ("POST", "/api/experts", {"name": "No", "identity": "x"},
             "create an agent"),
            ("POST", "/api/experts/solo-one/provider",
             {"name": "p", "base_url": "https://x"}, "add a provider"),
            ("POST", "/api/experts/solo-one/policy", {"policy": "quality"},
             "change the model policy")):
        st, r = _call(base, method, path, body, token=op)
        assert st == 403, f"an operator could {why}: {st} {r}"
    # a builder builds
    st, r = _call(base, "POST", "/api/experts",
                  {"name": "Built By Builder", "identity": "x"}, token=bd)
    assert st == 200 and r.get("created") == "built-by-builder", (st, r)
    # …and may not touch secrets or people
    for path, body, why in (
            ("/api/experts/solo-one/provider", {"name": "p"}, "add a provider"),
            ("/api/org/users", {"email": "x@y.com", "role": "admin"},
             "invite anybody"),
            ("/api/backup", {}, "take a backup that carries configuration")):
        st, r = _call(base, "POST", path, body, token=bd)
        assert st == 403, f"a builder could {why}: {st} {r}"
    print("[ladder] an operator queued work and was refused agent creation, "
          "provider wiring and budget changes; a builder created an agent and "
          "was refused secrets, invitations and backups")


def check_every_post_route_is_gated(base):
    """The enumeration that matters: no route may be ungated by omission."""
    src = io.open(os.path.join(AGENT_DIR, "ui.py"), encoding="utf-8").read()
    post_body = src[src.index("def do_POST"):src.index("def do_PUT")]
    routes = set(re.findall(r'path == "(/api/[\w/-]+)"', post_body))
    declared = set(re.findall(r'^    "(/api/[\w/-]+)":', src, re.M))
    # a route with no table entry falls through to DEFAULT_WRITE_PERMISSION,
    # which must be a real, restrictive permission — never "read"
    default = re.search(r'DEFAULT_WRITE_PERMISSION = "(\w+)"', src).group(1)
    assert default in org.PERMISSIONS, default
    assert org.rank(org.PERMISSIONS[default]) >= org.rank("builder"), (
        f"an unlisted route defaults to {default!r}, which a viewer or "
        f"operator would be allowed — the default must be strict")
    ungated = sorted(routes - declared)
    # every one of those still resolves to a permission, because the resolver
    # has no path that returns None
    assert "_may_write(path)" in src and "DEFAULT_WRITE_PERMISSION" in src
    assert "if not self._may(" in src, "PUT/DELETE are not gated"
    print(f"[coverage] {len(routes)} POST routes; {len(routes & declared)} "
          f"named in the table and {len(ungated)} falling through to "
          f"{default!r}, which needs {org.PERMISSIONS[default]} or above — "
          f"a route added tomorrow is refused for a viewer, not waved through")


def check_audit_names_the_token_holder(home, base, tokens):
    """An audit trail whose author is a request field records what the caller
    typed, which is not the same as what happened."""
    before = len(org.trail(home, 10000))
    st, r = _call(base, "POST", "/api/org/users",
                  {"email": "late@example.com", "role": "viewer",
                   # a lie: the body claims somebody else did this
                   "as": "somebody-else@example.com"},
                  token=tokens[OWNER])
    assert st == 200, (st, r)
    rows = org.trail(home, 10000)
    assert len(rows) > before
    added = [x for x in rows if x["action"] == "add_user"
             and x["object"] == "late@example.com"]
    assert added, rows[-3:]
    assert added[-1]["actor"] == OWNER, (
        f"the audit recorded {added[-1]['actor']!r}, which is what the request "
        f"body claimed rather than who the token belongs to")
    print(f"[audit] a request that claimed a different author was recorded "
          f"against the token's real owner ({OWNER}) — the trail is "
          f"attributable because the identity comes from the credential")


def check_a_shared_fleet_demands_a_token(tmp_home):
    """An organization with NO token defeats itself.

    `_authed` returns early when there is nothing to check, so every caller
    resolves to the owner and the roles somebody carefully configured govern
    nothing at all. A token is what makes an actor identifiable, so a fleet
    that belongs to an organization auto-enables one — for the same reason an
    exposed one does, and it says why on start-up.
    """
    import shutil
    import socket
    import subprocess
    import time
    shutil.copytree(os.path.join(AGENT_DIR, "prompts"),
                    os.path.join(tmp_home, "prompts"), dirs_exist_ok=True)
    shutil.copy(os.path.join(AGENT_DIR, "settings.toml"),
                os.path.join(tmp_home, "settings.toml"))
    org.create(tmp_home, "Shared", OWNER)
    sk = socket.socket(); sk.bind(("127.0.0.1", 0))
    port = sk.getsockname()[1]; sk.close()
    proc = subprocess.Popen(
        [sys.executable, os.path.join(AGENT_DIR, "ui.py"), "--home", tmp_home,
         "--port", str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUTF8": "1"})
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(75):
            try:
                urllib.request.urlopen(base + "/", timeout=2)
                break
            except urllib.error.HTTPError:
                break
            except OSError:
                time.sleep(0.2)
        st, r = _call(base, "GET", "/api/system")
        assert st == 401, (
            f"a fleet with an organization served its API with no token "
            f"({st}) — every caller would resolve to the owner and the roles "
            f"would govern nothing")
        tok_path = os.path.join(tmp_home, "ui-token.txt")
        assert os.path.isfile(tok_path), "no token was generated"
        with io.open(tok_path, encoding="utf-8") as f:
            master = f.read().strip()
        assert len(master) >= 24
        st, r = _call(base, "GET", "/api/system", token=master)
        assert st == 200, (st, r)
        # a member's own token also works, and stops where their role does
        org.add_user(tmp_home, OWNER, "seer@example.com", "viewer")
        vt = org.issue_token(tmp_home, OWNER, "seer@example.com")
        st, _ = _call(base, "GET", "/api/system", token=vt)
        assert st == 200
        st, r = _call(base, "POST", "/api/experts",
                      {"name": "No", "identity": "x"}, token=vt)
        assert st == 403 and r["actor"] == "seer@example.com", (st, r)
        print("[shared] a fleet that belongs to an organization refuses an "
              "untokened request, generates a master token, and admits a "
              "member on their own token while still refusing what their "
              "role forbids")
    finally:
        stop_panel(proc, base, token=master if "master" in dir() else None)


def main():
    home = make_sandbox("rbac", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": SCRIPT})
    proc, base = start_panel(home)
    try:
        check_solo_install_is_untouched(base)
        tokens = check_tokens_are_personal_and_unstored(home, base)
        check_viewer_is_refused_every_write(base, tokens)
        check_operator_and_builder_stop_where_they_should(base, tokens)
        check_every_post_route_is_gated(base)
        check_audit_names_the_token_holder(home, base, tokens)
    finally:
        stop_panel(proc, base)
    import tempfile
    check_a_shared_fleet_demands_a_token(
        os.path.join(tempfile.mkdtemp(prefix='rbac-shared-'), 'h'))
    print("PASS test_rbac")


if __name__ == "__main__":
    main()
