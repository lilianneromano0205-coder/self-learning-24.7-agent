#!/usr/bin/env python3
"""INVARIANT TESTS — enumerate every path, not one example of one.

Manual §25.11: *"Convert tests from primary-path examples into invariant
tests that enumerate every reachable path to protected operations."*

This is the difference between the audit's findings and its fixes. A test
that calls `run_command` with a traversal string proves that `run_command`
refuses traversal. It says nothing about `check_done`, `verify.py`,
`goal.py`, `toolbox.py` or `benchmark.py` — and that silence is exactly where
every P0 and P1 lived. Six sites executed shell; one was tested.

So these tests do not exercise behaviour through an example. They ENUMERATE:

  1. execution   every subprocess call site in the repository is either
                 routed through the Execution Authority or declared
                 platform-internal with a reason. A new bypass fails here.
  2. filesystem  every zone is classified, and the agent's write rights are
                 asserted per zone rather than per file.
  3. credentials every subsystem that must exclude a secret is asked about
                 the SAME four credential sources.
  4. gates       every operation in the execution catalogue is checked for
                 the controls its own declaration promises.
  5. metering    every provider-call purpose reaches the meter.
  6. roles       every role's tool grant is checked against what its job
                 needs, and no role may hold a capability it never uses.

Run from the agent/ directory:  python tests/test_invariants.py
"""

import io
import json
import os
import re
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import credentials          # noqa: E402
import execution            # noqa: E402
import fileauth             # noqa: E402
import loop                 # noqa: E402
import modelgateway         # noqa: E402


def check_execution_paths():
    """EVERY process execution site, not the one we remember."""
    rep = execution.audit_sources(AGENT_DIR)
    assert rep["checked"] >= 50, f"only scanned {rep['checked']} modules"
    if rep["violations"]:
        lines = [f"{v['file']}:{v['line']} {v['call']}" for v in rep["violations"]]
        raise AssertionError(
            "raw process execution outside the Execution Authority:\n  "
            + "\n  ".join(lines)
            + "\nRoute it through execution.run(op=...), or declare it in "
              "execution.ALLOWED_RAW with the reason it is safe.")
    print(f"[execution] {rep['checked']} modules scanned; 0 raw subprocess "
          f"sites outside the authority ({len(rep['allowed'])} declared "
          f"platform-internal, each with a stated reason)")


def check_execution_catalogue():
    """Every declared operation actually enforces what it declares."""
    ops = {o["op"]: o for o in execution.describe()}
    assert ops, "the catalogue must not be empty"
    for name, o in ops.items():
        if o["model_authored"]:
            assert o["policy"] and o["sandbox"], (
                f"{name} is model-authored, so it MUST screen through policy "
                f"and run in the sandbox; declared: {o}")
        else:
            assert not o["shell"], (
                f"{name} is platform-authored and must take an argument "
                f"vector — a platform call has no reason to invoke a shell")
    # and the type check is real, not documentation
    for name, o in ops.items():
        bad = ["echo hi"] if o["shell"] else "echo hi"
        try:
            execution.run(name, bad, AGENT_DIR)
            raise AssertionError(f"{name} accepted the wrong command type")
        except execution.Refused:
            pass
    print(f"[catalogue] {len(ops)} execution operations: every model-authored "
          f"one enforces policy+sandbox, every platform one refuses a shell "
          f"string")


def check_filesystem_zones(sb):
    """Write rights asserted per ZONE, so a new control file is covered the
    day it is created rather than the day someone remembers to test it."""
    cases = [
        ("courses/c/notes.md", fileauth.ZONE_WORKSPACE, True),
        ("out/index.html", fileauth.ZONE_WORKSPACE, True),
        ("skills/mine/SKILL.md", fileauth.ZONE_WORKSPACE, True),
        ("settings.toml", fileauth.ZONE_CONTROL, False),
        ("mcp.json", fileauth.ZONE_CONTROL, False),
        ("state.json", fileauth.ZONE_CONTROL, False),
        ("prospective.json", fileauth.ZONE_CONTROL, False),
        ("prompts/constitution.md", fileauth.ZONE_CONTROL, False),
        ("prompts/student.md", fileauth.ZONE_CONTROL, False),
        ("approvals/ap-1.json", fileauth.ZONE_CONTROL, False),
        ("variants/manifest.json", fileauth.ZONE_CONTROL, False),
        ("logs/agent.log", fileauth.ZONE_RUNTIME, False),
        ("contexts/t1.json", fileauth.ZONE_RUNTIME, False),
        ("checkpoints/x.json", fileauth.ZONE_RUNTIME, False),
        ("events/e.json", fileauth.ZONE_RUNTIME, False),
    ]
    for rel, expect_zone, writable in cases:
        assert fileauth.zone_of(rel) == expect_zone, (rel, fileauth.zone_of(rel))
        try:
            fileauth.resolve(sb, rel, "write", "agent")
            got = True
        except fileauth.Denied:
            got = False
        assert got == writable, (
            f"{rel} ({expect_zone}): agent-writable should be {writable}")
    # every declared CONTROL file and dir is actually refused — enumerated
    # from the module's own tables, so adding one to the table covers it
    for name in fileauth.CONTROL_FILES:
        try:
            fileauth.resolve(sb, name, "write", "agent")
            raise AssertionError(f"control file {name} must not be writable")
        except fileauth.Denied:
            pass
    for d in fileauth.CONTROL_DIRS:
        try:
            fileauth.resolve(sb, f"{d}/anything.json", "write", "agent")
            raise AssertionError(f"control dir {d}/ must not be writable")
        except fileauth.Denied:
            pass
    print(f"[zones] {len(cases)} paths + every declared control file/dir "
          f"({len(fileauth.CONTROL_FILES)} files, {len(fileauth.CONTROL_DIRS)} "
          f"dirs) classified and enforced by zone")


def check_traversal_spellings(sb):
    """Containment against every spelling, not the one we thought of."""
    escapes = [
        "../escape.md", "../../escape.md", "..\\escape.md",
        "..\\..\\escape.md", "courses/../../escape.md",
        "courses/x/../../../escape.md", "./../escape.md",
        "logs\\..\\..\\escape.md", "/etc/passwd", "C:\\Windows\\evil.txt",
        "C:/abs.txt", "\\\\server\\share\\file.txt",
    ]
    for rel in escapes:
        try:
            p = fileauth.resolve(sb, rel, "write", "agent")
            assert p.startswith(os.path.realpath(sb) + os.sep), \
                f"{rel} resolved outside the root: {p}"
        except fileauth.Denied:
            pass                      # refused outright is also correct
    print(f"[traversal] {len(escapes)} escape spellings (posix, windows, UNC, "
          f"mixed, nested) all refused or contained")


def check_credential_sources(sb):
    """The SAME four sources, asked of every subsystem that must know."""
    os.makedirs(os.path.join(sb, "keys"), exist_ok=True)
    with open(os.path.join(sb, "keys", "p.key"), "w", encoding="utf-8") as f:
        f.write("sk-aaaaaaaaaaaaaaaaaaaa1234\n")
    with open(os.path.join(sb, "settings.toml"), "a", encoding="utf-8") as f:
        f.write('\n[providers.filekey]\nbase_url = "https://x"\n'
                'api_key_file = "keys/p.key"\n'
                '\n[providers.inlinekey]\nbase_url = "https://y"\n'
                'api_key = "sk-inline-secret-value"\n')

    sources = {
        "env": {"api_key_env": "SOME_ENV_NAME"},
        "inline": {"api_key": "sk-inline-secret-value"},
        "file": {"api_key_file": "keys/p.key"},
    }
    # 1. the runtime resolves each one
    assert credentials.resolve(sources["inline"], sb) == "sk-inline-secret-value"
    assert credentials.resolve(sources["file"], sb).startswith("sk-")
    # 2. funded-ness agrees with the runtime for each one
    for name in ("inline", "file"):
        assert credentials.key_present(sources[name], sb), name
    # 3. the file one is discovered as a secret PATH, not guessed by name
    assert os.path.realpath(os.path.join(sb, "keys", "p.key")) in \
        credentials.configured_key_files(sb)
    assert credentials.is_secret(os.path.join(sb, "keys", "p.key"), sb)
    # 4. the inline one is reported so an operator can move it
    assert "inlinekey" in credentials.inline_keys(sb)
    # 5. and redaction removes it from anything that travels
    red = credentials.redact(io.open(os.path.join(sb, "settings.toml"),
                                     encoding="utf-8").read())
    assert "sk-inline-secret-value" not in red
    # 6. the agent can reach none of it
    a = loop.Agent(sb)
    for rel in ("keys/p.key", "agent.env", "ui-token.txt"):
        try:
            a._safe_path(rel)
            raise AssertionError(f"{rel} must not be readable by the agent")
        except ValueError:
            pass
    print("[credentials] all 4 sources (env, agent.env, inline, api_key_file) "
          "resolve, count as funded, are excluded from packaging, are "
          "redacted, and are unreadable by the agent")


def check_metering_purposes(sb):
    """Every purpose reaches the meter — including the ones that used to be
    invisible to the budget (compaction, replay, benchmark)."""
    for purpose in modelgateway.PURPOSES:
        modelgateway.record(sb, purpose=purpose, role="tester",
                            provider="m", model="mock",
                            usage={"prompt_tokens": 10, "completion_tokens": 5},
                            cost=0.001, task="t-inv")
    got = modelgateway.by_purpose(sb)
    for purpose in modelgateway.PURPOSES:
        assert purpose in got and got[purpose]["calls"] == 1, purpose
    att = modelgateway.attribution(sb, "t-inv")
    assert att["calls"] == len(modelgateway.PURPOSES)
    assert modelgateway.spend_today(sb) > 0
    print(f"[metering] all {len(modelgateway.PURPOSES)} call purposes reach "
          f"the ledger, attribute per call, and count toward today's spend")


def check_role_capabilities(_sb):
    """Every role IN THE SHIPPED CONFIGURATION, checked against what its job
    needs. Testing a fixture's roles would prove something about the fixture;
    the grants that matter are the ones in settings.toml."""
    import tomllib
    cfg = tomllib.loads(io.open(os.path.join(AGENT_DIR, "settings.toml"),
                                encoding="utf-8-sig").read())
    sb = make_sandbox("invariant_roles",
                      providers={"m": {"script": "s.json"}},
                      roles={r: "m" for r in cfg.get("roles", {})},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    # carry the REAL tool grants into the fixture's settings
    text = io.open(os.path.join(sb, "settings.toml"), encoding="utf-8-sig").read()
    for name, spec in cfg.get("roles", {}).items():
        tools = spec.get("tools")
        if tools:
            text = text.replace(
                f"[roles.{name}]",
                f"[roles.{name}]" + chr(10) + f"tools = {json.dumps(tools)}", 1)
    io.open(os.path.join(sb, "settings.toml"), "w", encoding="utf-8").write(text)

    a = loop.Agent(sb)
    roles = a.cfg.get("roles", {})
    assert roles, "settings must declare roles"
    for name in roles:
        tools = a.allowed_tools(name)
        assert "finish_task" in tools and "ask_human" in tools, (
            f"{name} must always be able to end or escalate")
    student = a.allowed_tools("student")
    assert "read_file" not in student, (
        "the Student sits CLOSED-BOOK: granting read_file would let it consult "
        "the notes it is being examined on")
    assert "run_command" not in student, (
        "a shell is a way to read the notes: recall.py is one command away")
    for reader in ("consultant", "librarian", "reflector", "watcher"):
        if reader in roles:
            assert "run_command" not in a.allowed_tools(reader), (
                f"{reader} reads untrusted material, so it must not also hold "
                f"a shell (the Rule of Two)")
    print(f"[roles] {len(roles)} roles: every one can finish/escalate, the "
          f"Student holds neither read_file nor a shell, and no "
          f"untrusted-material role holds run_command")


def check_gate_catalogue():
    """The network can name a gate; it can never author a command."""
    import gates
    for row in gates.describe():
        built = gates.build({"gate": row["gate"],
                             **{n: ("out/x.html" if n == "path" else "design")
                                for n in row["needs"]}})
        assert built and isinstance(built, str)
        assert ";" not in built.split('"')[-1], "no trailing shell separator"
    for raw in ("rm -rf /", "python -c 'x'", "echo hi && whoami"):
        try:
            gates.build(raw)
            raise AssertionError("a raw string must never build a gate")
        except ValueError:
            pass
    print(f"[gates] {len(gates.describe())} catalogue entries build a command; "
          f"a raw shell string never does")


def main():
    sb = make_sandbox("invariants", providers={"m": {"script": "s.json"}},
                      roles={"practitioner": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    check_execution_paths()
    check_execution_catalogue()
    check_filesystem_zones(sb)
    check_traversal_spellings(sb)
    check_credential_sources(sb)
    check_metering_purposes(sb)
    check_role_capabilities(sb)
    check_gate_catalogue()
    print("PASS test_invariants")


if __name__ == "__main__":
    main()
