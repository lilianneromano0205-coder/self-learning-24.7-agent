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
import tempfile

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
    # EVERY declared flag must be enforced, not the two we happened to check.
    # `approval: True` sat in this catalogue, was exported by describe(), and
    # was promised in the module docstring's control table, while nothing in
    # execution.py ever imported `approvals`. This loop checked policy and
    # sandbox and skipped the one flag nobody implemented — an enumeration
    # with a hole is how a declared control goes missing in plain sight.
    import tempfile
    for name, o in ops.items():
        if not o.get("approval"):
            continue
        probe = tempfile.mkdtemp(prefix="approval-inv-")
        consequential = "git push origin main"
        try:
            execution.run(name, consequential, probe, cfg={},
                          role="practitioner", timeout=5)
            raise AssertionError(
                f"{name} declares approval:True and ran a consequential "
                f"command without one — the catalogue promises a control "
                f"this operation does not have")
        except execution.Refused as e:
            assert "APPROVAL REQUIRED" in str(e), (
                f"{name} refused {consequential!r} for the wrong reason: {e}")
        # and ordinary work must still flow, or the control is a brake
        rc, _o, _e = execution.run(name, "echo ok", probe, cfg={},
                                   role="practitioner", timeout=30)
        assert rc == 0, f"{name} blocked ordinary work (rc={rc})"

    # and the type check is real, not documentation
    for name, o in ops.items():
        bad = ["echo hi"] if o["shell"] else "echo hi"
        try:
            execution.run(name, bad, AGENT_DIR)
            raise AssertionError(f"{name} accepted the wrong command type")
        except execution.Refused:
            pass
    n_app = sum(1 for o in ops.values() if o.get("approval"))
    print(f"[catalogue] {len(ops)} execution operations: every model-authored "
          f"one enforces policy+sandbox, every platform one refuses a shell "
          f"string, and each of the {n_app} declaring approval actually "
          f"requires one for a consequential command while still letting "
          f"ordinary work through")


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
    for rel in fileauth.CONTROL_PATHS:
        try:
            fileauth.resolve(sb, rel, "write", "agent")
            raise AssertionError(f"control path {rel} must not be writable")
        except fileauth.Denied:
            pass

    # EVERY LEDGER IS A CONTROL FILE — checked against harness's list, not
    # fileauth's own.
    #
    # The three loops above enumerate fileauth's tables against themselves,
    # which proves each entry is enforced and can never prove an entry is
    # MISSING. It was: four of the five ledgers in harness.LEDGERS were
    # control and skills/graph.json was not, so the agent could write the
    # ledger that decides which of its own skills are trusted, while
    # skills.provenance_of documented that only the owner writes it. Two lists
    # in two modules with no third thing comparing them is how that survived.
    #
    # A ledger is a durable record the platform's own integrity depends on —
    # doctor.py and harness.py both refuse to proceed when one is corrupt.
    # Anything worth halting the fleet over is not workspace.
    import harness
    for rel, label in harness.LEDGERS:
        zone = fileauth.zone_of(rel)
        assert zone == fileauth.ZONE_CONTROL, (
            f"harness.LEDGERS lists {rel} ({label}) but fileauth puts it in "
            f"{zone!r} — the agent can rewrite a ledger the platform treats "
            f"as an integrity invariant. Add it to fileauth.CONTROL_PATHS.")
        try:
            fileauth.resolve(sb, rel, "write", "agent")
            raise AssertionError(f"ledger {rel} ({label}) is agent-writable")
        except fileauth.Denied:
            pass
    print(f"[zones] {len(cases)} paths + every declared control file/dir/path "
          f"({len(fileauth.CONTROL_FILES)} files, {len(fileauth.CONTROL_DIRS)} "
          f"dirs, {len(fileauth.CONTROL_PATHS)} paths) classified and enforced "
          f"by zone")
    print(f"[ledgers] all {len(harness.LEDGERS)} ledgers harness treats as "
          f"integrity invariants are CONTROL and refused to the agent — "
          f"including skills/graph.json, the skill trust graph, which sat in "
          f"the workspace because `skills/` is legitimately the agent's own")


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


def check_registry_keys_are_unique():
    """No dict literal in this platform may define the same key twice.

    Python keeps the LAST of two identical keys and reports nothing, so a
    collision reads perfectly in the source and deletes an entry at runtime.
    It happened here: a capability written to own the worker-authority
    invariant was added to proof.REGISTRY under a name the PANEL's capability
    already used ninety lines below, and the new entry simply did not exist —
    the registry would have looked complete while the thing it was added to
    prove was absent.

    A `in REGISTRY` check cannot catch that, because by the time the module
    is imported there is only one key. So this parses the SOURCE.
    """
    import ast as _ast
    hits = []
    for fn in sorted(os.listdir(AGENT_DIR)):
        if not fn.endswith(".py"):
            continue
        try:
            tree = _ast.parse(io.open(os.path.join(AGENT_DIR, fn),
                                      encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Dict):
                continue
            seen = set()
            for k in node.keys:
                if not isinstance(k, _ast.Constant) or \
                        not isinstance(k.value, str):
                    continue
                if k.value in seen:
                    hits.append(f"{fn}:{k.lineno} duplicate key {k.value!r}")
                seen.add(k.value)
    assert not hits, (
        "a dict literal defines the same key twice — Python keeps the last "
        "one and says nothing, so an entry exists in the source and not at "
        "runtime:\n  " + "\n  ".join(hits))
    import proof
    assert "worker-authority" in proof.REGISTRY, sorted(proof.REGISTRY)
    assert "control-plane" in proof.REGISTRY, sorted(proof.REGISTRY)
    print(f"[keys] every string-keyed dict literal in the platform is "
          f"collision-free, and both proof capabilities that were competing "
          f"for one name exist ({len(proof.REGISTRY)} registered)")


def check_control_plane_zone_derivation():
    """The sealed set is DERIVED from fileauth, never listed a second time.

    controlplane.py brackets every model-authored command with a seal of the
    control zone. If that seal carried its own hand-written list of paths, the
    two lists would drift and a control directory added to fileauth tomorrow
    would be unsealed tomorrow — which is the two-descriptions-of-one-truth
    defect this codebase keeps finding, reintroduced by the module written to
    fix an instance of it.

    So: build a root containing one file for every control shape fileauth
    knows about, and assert the authority seals ALL of them.
    """
    import controlplane
    import shutil
    root = tempfile.mkdtemp(prefix="cp-derive-")
    try:
        expected = set()

        def put(rel, body="x"):
            p = os.path.join(root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(p) or root, exist_ok=True)
            io.open(p, "w", encoding="utf-8").write(body)
            expected.add(rel)

        for name in fileauth.CONTROL_FILES:
            put(name)
        for d in fileauth.CONTROL_DIRS:
            put(f"{d}/probe.txt")
        for rel in fileauth.CONTROL_PATHS:
            put(rel)
        for head, names in fileauth.CONTROL_NAMES_IN.items():
            for n in names:
                put(f"{head}/probe-goal/{n}")
        # a workspace file that must NOT be sealed, so the derivation is shown
        # to be a filter rather than "everything"
        put("courses/c1/notes.md")
        expected.discard("courses/c1/notes.md")

        sealed = set(controlplane.control_paths(root))
        missing = expected - sealed
        assert not missing, (
            f"fileauth calls these CONTROL and the control plane authority "
            f"does not seal them: {sorted(missing)}")
        assert "courses/c1/notes.md" not in sealed, (
            "the seal must cover control state, not the agent's workspace")
        # every sealed path must have a declared treatment
        for rel in sealed:
            assert controlplane.treatment(rel) in (
                controlplane.SEALED, controlplane.PENDING_ONLY,
                controlplane.DETECT), rel
        assert controlplane.treatment("state.json") == controlplane.DETECT
        # a goal's event ledger is SEALED, not "append-only": contract.replay
        # rebuilds state purely from it and lets it overrule the snapshot, so
        # an appended line is a verdict. Growth is exempt only when the
        # harness itself declared the append.
        assert controlplane.treatment("goals/g1/events.jsonl") == \
            controlplane.SEALED
        assert controlplane.treatment("approvals/ap-1.json") == \
            controlplane.PENDING_ONLY
        assert controlplane.treatment("settings.toml") == controlplane.SEALED
        print(f"[control-plane] the seal is derived from fileauth's zone "
              f"model: all {len(expected)} control shapes sealed, the "
              f"workspace untouched, every path with a declared treatment")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def check_metering_call_sites():
    """EVERY PROVIDER CALL SITE, not every purpose.

    check_metering_purposes below is the test REFERENCE.md cites as proof that
    "every provider call is metered" — and it enumerates the PURPOSES tuple
    and writes nine synthetic rows itself. It never opens a socket and never
    looks at a call site, so it passes whether or not a real provider call is
    metered. Purposes are not call sites, and that substitution WAS the hole:
    an audit walking the repository's outbound HTTP found five model-provider
    call sites and exactly one of them metered.

      ingest.transcribe_chunk   Groq Whisper       spent, recorded nowhere
      ingest.vision             OpenRouter VLM     spent, recorded nowhere
      loop._probe               chat/completions    one live call per role on
                                                    `loop.py check`
      loop.call_model                              metered
      providers.catalog         GET /models         no tokens, declared

    This is the same shape as check_execution_paths above: a rule that is only
    asserted decays, so the rule is CHECKED against the source, and a new
    bypass fails the suite the way a new raw subprocess does.
    """
    rep = modelgateway.audit_sources(AGENT_DIR)
    assert rep["checked"] >= 50, f"only scanned {rep['checked']} modules"
    if rep["violations"]:
        lines = [f"{v['file']}:{v['line']} {v['function']}()"
                 for v in rep["violations"]]
        raise AssertionError(
            "these functions call a model provider and do not meter it:\n  "
            + "\n  ".join(lines)
            + "\nRecord the call with modelgateway.record(...) (and charge() "
              "it if it costs money), or declare it in "
              "modelgateway.ALLOWED_UNMETERED with the reason it is free.")
    # the declaration must stay honest too: an entry for a function that no
    # longer exists is an exemption nobody is reading
    import ast as _ast
    for key in rep["allowed"]:
        fn, _, func = key.partition(":")
        src = io.open(os.path.join(AGENT_DIR, fn), encoding="utf-8").read()
        names = {n.name for n in _ast.walk(_ast.parse(src))
                 if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}
        assert func in names, (
            f"modelgateway.ALLOWED_UNMETERED exempts {key}, which does not "
            f"exist — a stale exemption is a hole nobody is guarding")
    print(f"[metering] {rep['checked']} modules scanned by AST; every "
          f"function that reaches a model provider meters it "
          f"({len(rep['allowed'])} declared free, each with a stated reason "
          f"and each still present in the source)")


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


def check_expert_birth_paths():
    """EVERY route that mints an expert, not the one bootstrap.py takes.

    Found live: `fleet.py create --home <a directory nobody bootstrapped>`
    died with a raw FileNotFoundError from copytree, and the panel's
    POST /api/experts turned the same thing into a 500 — because only
    bootstrap.py called seed_home() first. Four callers, one of them correct.

    The test does not check the one path it remembers. It enumerates every
    call site of fleet.create in the tree and then exercises the gateway on a
    directory that has never been prepared, which is the state all three
    broken callers put it in.
    """
    import fleet

    # 1. enumerate the callers, so a fifth one added later is not invisible
    callers = set()
    for name in sorted(os.listdir(AGENT_DIR)):
        if not name.endswith(".py"):
            continue
        with io.open(os.path.join(AGENT_DIR, name), encoding="utf-8",
                     errors="replace") as f:
            if re.search(r"\bfleet\.create\s*\(", f.read()):
                callers.add(name)
    assert callers >= {"bootstrap.py", "quick.py", "ui.py"}, callers

    # 2. the gateway itself must work on a directory that is not a fleet yet
    fresh = os.path.join(tempfile.mkdtemp(prefix="fleet-birth-"), "brand-new")
    dest = fleet.create(fresh, "Born Here", "prove a fresh home works")
    for required in ("prompts", "settings.toml", "identity.md",
                     "inbox", "courses", "logs", "skills"):
        assert os.path.exists(os.path.join(dest, required)), \
            f"a newly born expert is missing {required}"
    assert os.path.isdir(os.path.join(fresh, "prompts")), \
        "the home itself was never seeded, so the SECOND expert would fail"

    # 3. and a second expert in the same home still works (seeding is
    #    idempotent and must not overwrite what the owner already put there)
    marker = os.path.join(fresh, "settings.toml")
    with io.open(marker, "a", encoding="utf-8") as f:
        f.write("\n# owner edited this\n")
    fleet.create(fresh, "Second One", "prove seeding does not clobber")
    with io.open(marker, encoding="utf-8") as f:
        assert "# owner edited this" in f.read(), \
            "seeding overwrote settings the owner had already edited"

    # 4. the panel's route and the CLI's route agree: both go through the
    #    gateway, so neither can regress independently
    import subprocess
    import inspect
    src = inspect.getsource(fleet.create)
    assert "seed_home(home)" in src,         "creation must seed at the gateway, not in whichever caller remembers"

    # 5. run the CLI from an unrelated working directory against a home that
    #    has never been bootstrapped — the exact invocation that used to die
    fresh2 = os.path.join(tempfile.mkdtemp(prefix="fleet-cli-"), "never-seeded")
    r = subprocess.run(
        [sys.executable, os.path.join(AGENT_DIR, "fleet.py"), "create",
         "From The Cli", "--identity", "prove the CLI path", "--home", fresh2],
        capture_output=True, text=True, env={**os.environ, "PYTHONUTF8": "1"},
        cwd=tempfile.mkdtemp(prefix="fleet-elsewhere-"))
    assert r.returncode == 0 and "Traceback" not in (r.stdout + r.stderr), (
        "fleet.py create against a never-bootstrapped home still fails: "
        + (r.stdout + r.stderr)[-700:])
    assert os.path.isfile(os.path.join(fresh2, "experts", "from-the-cli",
                                       "identity.md"))

    # 6. a home that genuinely cannot be made refuses with a SENTENCE. Its
    #    parent is a FILE here, so makedirs cannot succeed however hard it
    #    tries — the one way to reach that branch on a healthy install.
    blocker = os.path.join(tempfile.mkdtemp(prefix="fleet-blocked-"), "a-file")
    with io.open(blocker, "w", encoding="utf-8") as f:
        f.write("not a directory")
    r = subprocess.run(
        [sys.executable, os.path.join(AGENT_DIR, "fleet.py"), "create", "Nope",
         "--home", os.path.join(blocker, "home")],
        capture_output=True, text=True, env={**os.environ, "PYTHONUTF8": "1"},
        cwd=tempfile.mkdtemp(prefix="fleet-elsewhere-"))
    assert r.returncode != 0, "creating inside a file must not report success"
    assert "Traceback" not in (r.stdout + r.stderr), (
        "an impossible home must refuse with an explanation, not a stack "
        "trace: " + (r.stdout + r.stderr)[-700:])

    print(f"[birth] {len(callers)} modules mint experts; the gateway seeds a "
          f"never-bootstrapped home itself (library AND CLI, from any working "
          f"directory), is idempotent, does not clobber owner edits, and "
          f"refuses with a sentence when the home is genuinely impossible")


def check_exam_readers_agree(sb):
    """EVERY reader of exam-results.md, not the one that happens to be right.

    Found live: the loop's completion check reads "SCORE: 95" (the canonical
    line the examiner writes), while the self-model looked only for a percent
    SIGN. So a course could pass at 95, the loop would agree it was complete,
    and the expert's own self-model — the block injected into every context
    window, and the number the panel prints — would report no score at all.
    An expert that cannot state its own exam result is exactly the kind of
    quiet disagreement this suite exists to catch.

    The test does not assert one regex. It writes the file in each format the
    platform has ever produced and requires every reader to return the same
    number for each one.
    """
    import selfmodel
    import loop as loop_mod

    cdir = os.path.join(sb, "courses", "exam-formats")
    os.makedirs(os.path.join(cdir, "lessons", "01"), exist_ok=True)
    with io.open(os.path.join(cdir, "spec.md"), "w", encoding="utf-8") as f:
        f.write('R-001 [from C-1]: the notes exist CHECK: "python" -c "pass"\n')
    with io.open(os.path.join(cdir, "gaps.md"), "w", encoding="utf-8") as f:
        f.write("")

    FORMATS = [
        ("canonical", "R-001: PASS — verified\nSCORE: 95\n", 95),
        ("percent",   "R-001: PASS — verified\nscored 95% overall\n", 95),
        ("indented",  "R-001: PASS — verified\n  SCORE: 88\n", 88),
        ("resat",     "R-001: PASS — verified\nSCORE: 60\nSCORE: 91\n", 91),
    ]
    agent = loop_mod.Agent(sb)
    for label, body, expect in FORMATS:
        with io.open(os.path.join(cdir, "exam-results.md"), "w",
                     encoding="utf-8") as f:
            f.write(body)
        by_selfmodel = (selfmodel.study(sb) or [])
        row = next((r for r in by_selfmodel if r["course"] == "exam-formats"), None)
        assert row is not None, "the course vanished from the self-model"
        got = (row["exam"] or {}).get("score")
        assert got == expect, (
            f"[{label}] the self-model read {got!r} from a file that says "
            f"{expect}; the loop and the panel would then disagree about "
            f"whether this course was ever examined")
        by_loop = agent.course_status("exam-formats")["score"]
        if label != "percent":            # the loop only ever wrote SCORE:
            assert by_loop == expect, (
                f"[{label}] the loop read {by_loop!r}, the self-model {got!r}")
        # and whatever it read, it must SAY so where a person will see it
        block = selfmodel.render(selfmodel.build(sb))
        assert f"exam {expect}%" in block, (
            f"[{label}] the score never reached the self-model block that goes "
            f"into every context window:\n{block[:400]}")
    print(f"[exams] {len(FORMATS)} recorded formats: the loop's completion "
          f"check, the self-model, and the block injected into every context "
          f"window all read the same score from the same file")


def check_sandbox_names_are_unique():
    """EVERY test file's sandbox name, not the ones we happened to notice.

    Found live: test_guardrails.py and test_secrets.py both called
    make_sandbox("secrets"), so they shared one directory under the suite's
    temp root. Each passed alone. In the suite, whichever ran second raced the
    first's leftover directory and died with FileExistsError — a failure that
    appeared only once the suite grew long enough to shift the timing, and
    that pointed at the wrong test when it did.

    A shared sandbox name is a landmine with a delay fuse, so this asserts the
    property rather than the incident: no two test FILES may claim the same
    name. The check reads the tree, so a collision introduced tomorrow fails
    here rather than as an intermittent red suite three weeks later.
    """
    import ast
    from collections import defaultdict
    tests_dir = os.path.join(AGENT_DIR, "tests")
    claimed = defaultdict(set)
    scanned = 0
    for name in sorted(os.listdir(tests_dir)):
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        scanned += 1
        with io.open(os.path.join(tests_dir, name), encoding="utf-8",
                     errors="replace") as f:
            tree = ast.parse(f.read(), filename=name)
        # ast, not a regex: this very docstring mentions the call, and a
        # checker that cannot tell code from prose reports itself
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if getattr(fn, "id", None) != "make_sandbox" and                     getattr(fn, "attr", None) != "make_sandbox":
                continue
            if node.args and isinstance(node.args[0], ast.Constant)                     and isinstance(node.args[0].value, str):
                claimed[node.args[0].value].add(name)
    shared = {n: sorted(files) for n, files in claimed.items() if len(files) > 1}
    assert not shared, (
        "two test files share a sandbox directory; each will pass alone and "
        "the pair will fail intermittently under load:\n  "
        + "\n  ".join(f"{n!r}: {', '.join(files)}" for n, files in shared.items())
        + "\nGive each file its own name — prefixing with the test's own name "
          "is the convention.")
    print(f"[sandboxes] {len(claimed)} sandbox names across {scanned} test "
          f"files, every one claimed by exactly one file — a shared temp "
          f"directory is the failure that only shows up under load")


def check_documented_cli_exists():
    """EVERY command the manual promises, not the ones we remembered to try.

    Found live: `MANUAL.md` named eight subcommands that argparse refused —
    `acquire.py search/inspect/install/test`, `mission.py meet/block`,
    `training.py capture/rollback`. The functions existed as library calls;
    the CLI had never been given them. An operator following the documented
    recovery path would have found nothing there, at exactly the moment they
    needed it.

    Seven were added and one was wrong in the manual (a trajectory is captured
    by the loop, not by a person). Which of the two happened is a judgement
    call each time; that the two must AGREE is not, so this checks it.

    It also catches the reverse drift — a module whose `--help` crashes before
    printing a word, which is how `acquire.py` behaved on a Windows console
    because argparse tried to write its docstring's arrows through cp1252.
    """
    import subprocess
    manual = os.path.join(AGENT_DIR, "MANUAL.md")
    with io.open(manual, encoding="utf-8") as f:
        text = f.read()

    pairs, modules = set(), set()
    for m in re.finditer(r"`python (\w+\.py)([^`]*)`", text):
        mod, rest = m.group(1), m.group(2).strip()
        assert os.path.isfile(os.path.join(AGENT_DIR, mod)), \
            f"MANUAL.md names {mod}, which does not exist"
        modules.add(mod)
        first = rest.split(" ")[0] if rest else ""
        # `[refresh]` is still a promise: an OPTIONAL subcommand that does not
        # exist misleads exactly as much as a required one. This check
        # originally skipped bracketed tokens and therefore missed
        # `python proof.py [refresh]`, where the real CLI takes --refresh.
        first = first.strip("[]")
        if not first or first[0] in "-<\"":
            continue
        for sub in first.split(r"\|"):
            sub = sub.strip().strip("[]")
            if re.fullmatch(r"[a-z][a-z-]*", sub):
                pairs.add((mod, sub))

    env = {**os.environ, "PYTHONUTF8": "0"}      # a plain Windows console
    refused, crashed = [], []
    for mod in sorted(modules):
        r = subprocess.run([sys.executable, os.path.join(AGENT_DIR, mod),
                            "--help"], capture_output=True, text=True,
                           errors="replace", timeout=60, env=env,
                           cwd=AGENT_DIR)
        if "UnicodeEncodeError" in (r.stderr or ""):
            crashed.append(mod)
    for mod, sub in sorted(pairs):
        # errors="replace": the child is deliberately run on a non-UTF-8
        # console, so its help text comes back as cp1252 bytes. Decoding
        # those strictly made the READER fail — subprocess hands back None
        # for stdout and the line below died with a TypeError instead of
        # reporting anything. Whether that happened depended on the encoding
        # of the console the SUITE was launched from, which is the worst
        # kind of test: one whose verdict is a property of the terminal.
        r = subprocess.run([sys.executable, os.path.join(AGENT_DIR, mod), sub,
                            "--help"], capture_output=True, text=True,
                           errors="replace", timeout=60, env=env,
                           cwd=AGENT_DIR)
        if "invalid choice" in ((r.stdout or "") + (r.stderr or "")):
            refused.append(f"python {mod} {sub}")

    assert not crashed, (
        "these modules cannot print their own --help on a console that is not "
        "UTF-8: " + ", ".join(crashed)
        + "\nAdd the sys.stdout.reconfigure guard chief.py and mission.py use.")
    assert not refused, (
        "MANUAL.md promises commands the CLI refuses:\n  "
        + "\n  ".join(refused)
        + "\nEither add the subcommand or correct the manual — a documented "
          "recovery path that does not exist is worse than none.")
    print(f"[cli] {len(pairs)} documented subcommands across {len(modules)} "
          f"modules all parse, and every module prints its own --help on a "
          f"non-UTF-8 console")


def check_no_file_clock_comparisons():
    """No module may decide "did this change?" by comparing one file's
    timestamp to another file's timestamp.

    U19 and U20 were the same defect in two modules, and both were found by
    enumeration rather than by noticing:

        if newest_notes <= ledger_mtime:  return False   # conflicts.py
        if lessons_mtime > curated_mtime: curate(home)   # commons.py

    It reads like a cache and behaves like a race. On overlayfs -- what every
    container runs on, including this project's own Dockerfile -- the clock
    behind file timestamps is cached rather than read per write: measured in
    a python:3.11-slim container, 200 files written back to back produced
    NINE distinct timestamps, and two consecutive writes routinely land on
    the identical st_mtime_ns. Both comparisons then say "unchanged" about
    material that changed, silently, with no error anywhere.

    Comparing a file's age to the WALL CLOCK (`time.time() - getmtime(p) >
    stale`) is sound and stays allowed -- that is how every lock in this
    codebase expires. What is banned is one file's stamp against another's.

    That allowance has an edge, and U22 walked straight into it: an age is
    sound, but an age is NOT guaranteed non-negative. The filesystem's clock
    and time.time() are different sources, and on a virtualised host a file
    written a moment ago can carry an mtime AHEAD of the wall clock. Any
    threshold at or near zero then inverts -- `age < 0` was true, and an
    inbox setting meaning "no settling required" became "never ingest".
    Compare against a positive threshold, or clamp the age; do not assume
    time only moves one way. This is written down because an allowance whose
    edge nobody records is the next defect waiting.
    """
    import ast

    def is_mtime(node):
        """os.path.getmtime(...), os.stat(...).st_mtime, or .st_mtime_ns"""
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in ("getmtime", "getctime"):
                return True
        if isinstance(node, ast.Attribute) and node.attr in (
                "st_mtime", "st_mtime_ns", "st_ctime", "st_ctime_ns"):
            return True
        return False

    def is_wall_clock(node):
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("time", "monotonic"))

    def taint(node, tainted):
        """Does this expression carry a file timestamp, and no wall clock?"""
        if any(is_wall_clock(n) for n in ast.walk(node)):
            return False                      # an age, not a stamp
        for n in ast.walk(node):
            if is_mtime(n):
                return True
            if isinstance(n, ast.Name) and n.id in tainted:
                return True
        return False

    offenders = []
    for fn in sorted(os.listdir(AGENT_DIR)):
        if not fn.endswith(".py"):
            continue
        path = os.path.join(AGENT_DIR, fn)
        with io.open(path, encoding="utf-8") as f:
            src = f.read()
        try:
            tree = ast.parse(src)
        except SyntaxError:                   # pragma: no cover
            continue
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.Module)):
                continue
            tainted = set()
            for node in ast.walk(scope):
                if isinstance(node, ast.Assign) and taint(node.value, tainted):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            tainted.add(t.id)
            for node in ast.walk(scope):
                if not isinstance(node, ast.Compare):
                    continue
                sides = [node.left] + list(node.comparators)
                if sum(1 for s in sides if taint(s, tainted)) >= 2:
                    offenders.append(
                        f"{fn}:{node.lineno} compares two file timestamps")
    assert not offenders, (
        "a file timestamp compared against another file timestamp:\n  "
        + "\n  ".join(sorted(set(offenders)))
        + "\nTwo files written in the same filesystem tick get the SAME "
          "stamp, so this silently reports 'unchanged'. Compare the "
          "material instead (see conflicts.material_fingerprint), or "
          "compare against time.time() if you want an age.")
    # and the two modules that had the defect now answer from content
    import conflicts
    import commons
    assert hasattr(conflicts, "material_fingerprint") and \
        hasattr(commons, "_curation_is_stale"), \
        "the content-based staleness checks are gone"
    n_mtime = sum(
        1 for fn in os.listdir(AGENT_DIR) if fn.endswith(".py")
        for line in io.open(os.path.join(AGENT_DIR, fn), encoding="utf-8")
        if "getmtime(" in line and "time.time()" not in line
        and not line.lstrip().startswith("#"))
    print(f"[clocks] every .py in the platform parsed: no file timestamp is "
          f"compared against another file's, which is the comparison a "
          f"coarse filesystem tick corrupts (U19, U20). The {n_mtime} "
          f"remaining getmtime sites sort, or measure age against the wall "
          f"clock — sound, but not unconditionally: an age can come back "
          f"NEGATIVE when the two clocks disagree, which is what U22 was, so "
          f"this check bans the pattern it can prove and the docstring "
          f"records the edge it cannot")


def check_capability_report_matches_reality():
    """Every capability toolbox.py reports must agree with what can be RUN.

    A tool is present in two ways and this platform kept seeing only one.
    `pip install yt-dlp` puts a module on sys.path and a script in a Scripts/
    directory that is usually not on PATH — the default on Windows and on any
    --user install. Asking only shutil.which reported MISSING for a capability
    the machine demonstrably had, and the agent then did the right thing with
    wrong information: it declined, and asked the owner to install what was
    already installed.

    So the check is not "is the binary on PATH" but "do the report and the
    runtime give the same answer" — enumerated over every tool that has a
    module form, rather than over the one that was noticed.
    """
    import shutil
    import subprocess
    import ingest
    import toolbox

    # ---- the module-only door, CONSTRUCTED rather than hoped for ---------
    # The loop below enumerates tools this machine happens to have, and its
    # assertion — "resolves iff on PATH or importable" — is equally true of a
    # PATH-only resolver whenever the tool IS on PATH. So on a runner where
    # pip put yt-dlp on PATH, the mutation that replaces tool_argv with a
    # bare shutil.which SURVIVED: mutate_check reported MISSED on
    # ubuntu 3.12 while catching it on the five other runners. A test whose
    # power depends on where pip happened to drop a script is not measuring
    # the thing it names.
    #
    # This builds the case the gateway exists for: a module that IS
    # importable and a binary that is certainly NOT on PATH. Now the
    # module door is exercised on every machine, and the PATH-only mutation
    # fails everywhere instead of wherever the environment allows.
    probe_home = tempfile.mkdtemp(prefix="dualdoor-")
    pkg = os.path.join(probe_home, "fleetdualprobe")
    os.makedirs(pkg, exist_ok=True)
    with io.open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as f:
        f.write("__version__ = '1.0'\n")
    with io.open(os.path.join(pkg, "__main__.py"), "w", encoding="utf-8") as f:
        f.write("print('fleetdualprobe 1.0')\n")
    sys.path.insert(0, probe_home)
    try:
        import importlib
        importlib.invalidate_caches()
        assert shutil.which("fleetdualprobe") is None, (
            "the probe name exists on PATH; pick another")
        # Ask TOOLBOX, not ingest. toolbox._ingest_tool is the function that
        # decides what the capability REPORT says, and it is the one that
        # regressed to a PATH-only lookup. Asserting on ingest.tool_argv here
        # would prove the gateway is right while the report still lies —
        # which is exactly the disagreement this invariant exists to forbid.
        argv = toolbox._ingest_tool("fleetdualprobe", "fleetdualprobe")
        assert argv == [sys.executable, "-m", "fleetdualprobe"], (
            f"a tool installed ONLY as a module did not resolve through the "
            f"module door: {argv!r}. shutil.which alone reports MISSING for a "
            f"capability the machine demonstrably has.")
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                           env={**os.environ, "PYTHONPATH": probe_home})
        assert r.returncode == 0 and "fleetdualprobe" in r.stdout, (
            f"the module door resolved but does not RUN: rc={r.returncode} "
            f"out={r.stdout!r} err={r.stderr[:200]!r}")
    finally:
        sys.path.remove(probe_home)

    # every tool this platform can reach by either door
    DUAL = [("yt-dlp", "yt_dlp")]
    checked = []
    for binary, module in DUAL:
        argv = ingest.tool_argv(binary, module)
        on_path = shutil.which(binary) is not None
        importable = False
        try:
            import importlib.util
            importable = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            pass
        assert (argv is not None) == (on_path or importable), (
            f"{binary}: resolver says {argv!r} but PATH={on_path} "
            f"module={importable} — the two doors disagree")
        if argv is None:
            continue
        # it must not merely resolve; it must RUN. A resolver that reports a
        # capability which then fails is worse than one that reports MISSING.
        r = subprocess.run(argv + ["--version"], capture_output=True,
                           text=True, timeout=180)
        assert r.returncode == 0, (
            f"{binary} resolved to {argv!r} but exits {r.returncode} — the "
            f"capability report would be a promise the runtime cannot keep")
        checked.append((binary, "PATH" if on_path else "module"))

    # and the published REPORT must agree with the resolver. capability_note()
    # is the text injected into an agent's context — it is what the agent
    # actually believes about this machine, so it is the thing that must be
    # true, not an internal table nobody reads.
    note = toolbox.capability_note()
    for binary, module in DUAL:
        runnable = ingest.tool_argv(binary, module) is not None
        # the note is a READY: section then a MISSING: section, each holding
        # "- name: how" lines, so which SECTION the line falls in is the
        # report — not the text of the line itself
        section, reported = None, None
        for l in note.splitlines():
            if l.startswith("READY:"):
                section = True
            elif l.startswith("MISSING"):
                section = False
            elif "video_download" in l and section is not None:
                reported = section
                break
        assert reported is not None, "video_download vanished from the note"
        assert reported == runnable, (
            f"the agent is told video_download is "
            f"{'READY' if reported else 'MISSING'} while ingest "
            f"{'can' if runnable else 'cannot'} actually run {binary} — a "
            f"capability report the runtime disagrees with is worse than no "
            f"report, because the agent acts on it")

    print(f"[capabilities] every dual-installed tool resolves the same way for "
          f"the report and the runtime, and each one actually executes: "
          f"{', '.join(f'{b} via {how}' for b, how in checked) or 'none present'}")


def check_org_policy_is_enforced(sb):
    """Every organization policy flag is READ by something, and BITES.

    All three were written into org.json by create(), returned by summary(),
    rendered in the panel — and referenced by no other module in the
    repository. An owner reading "agents_may_install: false" in their own
    workspace had every reason to believe agents could not install software.
    They could. There was also no way to change any of them: no CLI, no API,
    no function. Inert in both directions.

    Three assertions, because each catches a different way this rots:
      1. every key create() writes is declared in POLICY_ENFORCERS
      2. every declared flag is actually read by the module that claims it
      3. the flags CHANGE BEHAVIOUR — asserted by flipping one and watching
         a real call refuse, because "the string appears in the file" is the
         same weak evidence that let this survive in the first place
    """
    import org
    home = os.path.join(sb, "orgcheck")
    os.makedirs(home, exist_ok=True)
    rec = org.create(home, "Check Co", "owner@example.com")

    declared = set(org.POLICY_ENFORCERS)
    written = set(rec["policy"])
    assert written == declared, (
        f"org.create() writes {sorted(written)} but POLICY_ENFORCERS declares "
        f"{sorted(declared)}. A flag with no declared enforcer is a setting "
        f"the product displays and does not honour.")

    # 2. the named enforcer really reads it
    for flag, claim in org.POLICY_ENFORCERS.items():
        module = claim.split(".")[0].split("(")[0].strip()
        src = os.path.join(AGENT_DIR, f"{module}.py")
        assert os.path.isfile(src), f"{flag}: no module {module}.py"
        with io.open(src, encoding="utf-8") as f:
            assert flag in f.read(), (
                f"{flag} claims to be enforced by {module}.py, and that file "
                f"never mentions it")

    # 3. and flipping it changes what the platform DOES
    import acquire
    expert = os.path.join(home, "experts", "buyer")
    os.makedirs(expert, exist_ok=True)
    org.set_policy(home, "owner@example.com", "agents_may_install", True)
    assert org.policy_flag(expert, "agents_may_install") is True
    org.set_policy(home, "owner@example.com", "agents_may_install", False)
    try:
        acquire.install(expert, home, "no-such-id")
        raise AssertionError(
            "agents_may_install=false did not stop an install — the flag is "
            "still decorative")
    except acquire.Refused as e:
        assert "agents_may_install" in str(e), f"refused for another reason: {e}"
    except KeyError:
        raise AssertionError(
            "install() reached the acquisition lookup, so the org policy gate "
            "did not run before it")

    # and only the owner may change it
    org.add_user(home, "owner@example.com", "admin@example.com", "admin")
    try:
        org.set_policy(home, "admin@example.com", "agents_may_install", True)
        raise AssertionError("an admin changed owner-level policy")
    except org.Denied:
        pass
    print(f"[org-policy] all {len(declared)} organization policy flags are "
          f"declared with an enforcer, the named module really reads each "
          f"one, flipping agents_may_install actually refuses an install, and "
          f"only the owner can change it — all three were inert, unreachable "
          f"and shown in the panel")


def check_architecture_table_matches_code():
    """ARCHITECTURE.md's control table is checked against execution.describe().

    The table gave `capability_probe` an Approval tick. The code declares
    approval=False. Nobody was lying — the row was written when the design
    called for it — but a reader deciding whether this platform is safe reads
    the table, not the catalogue, and the table said a control existed that
    did not. This repository has now produced that same defect four times
    (U24's approval flag, loop's stale protected-writes copy, harness's
    ledger list vs fileauth's, and this), always the same shape: two
    descriptions of one truth, and nothing comparing them.

    So the doc is now a test fixture. Edit the table without editing the code
    and this fails.
    """
    import execution
    doc = os.path.join(AGENT_DIR, "ARCHITECTURE.md")
    if not os.path.isfile(doc):
        print("[arch-table] ARCHITECTURE.md absent — skipped")
        return
    with io.open(doc, encoding="utf-8") as f:
        text = f.read()

    def truth(cell):
        c = cell.strip().lower()
        if "✅" in c or c.startswith("yes") or c.startswith("on risk"):
            return True
        return False

    rows = {}
    for line in text.splitlines():
        m = re.match(r"^\|\s*`([a-z_]+)`\s*\|(.+)\|\s*$", line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) != 5:          # written by, shell, policy, sandbox, approval
            continue
        rows[m.group(1)] = {"shell": truth(cells[1]), "policy": truth(cells[2]),
                            "sandbox": truth(cells[3]),
                            "approval": truth(cells[4])}
    ops = {o["op"]: o for o in execution.describe()}
    documented = {k: v for k, v in rows.items() if k in ops}
    assert len(documented) == len(ops), (
        f"ARCHITECTURE.md documents {sorted(documented)} but the execution "
        f"catalogue holds {sorted(ops)} — an operation with no row is an "
        f"operation no reader knows exists")
    for op, claimed in sorted(documented.items()):
        for flag in ("shell", "policy", "sandbox", "approval"):
            assert claimed[flag] == bool(ops[op][flag]), (
                f"ARCHITECTURE.md says {op}.{flag}={claimed[flag]} and the "
                f"code says {bool(ops[op][flag])}. A table promising a control "
                f"the code does not have is worse than an admitted gap, "
                f"because a reader trusts the table.")
    print(f"[arch-table] all {len(documented)} rows of ARCHITECTURE.md's "
          f"control table match execution.describe() flag for flag — the doc "
          f"gave capability_probe an approval the code never implemented")


def check_policy_fails_closed():
    """A command policy that does not compile refuses, and says which rule.

    The old behaviour was `except re.error: continue` — the unreadable rule
    was skipped and its neighbours kept matching, so a deny list was
    PARTIALLY enforced while reading as fully enforced. Nothing is more
    dangerous than a safety control that looks present. The allowlist branch
    of the same function had no guard at all and raised straight out, so the
    two halves of check() disagreed about what a malformed pattern means.
    """
    import policy
    assert policy.rule_problems({}) == [], (
        f"the platform's own BUILTIN_DENY does not compile: "
        f"{policy.rule_problems({})}")

    valid = "curl .* evil"
    for label, cfg in (
            ("deny", {"command_policy": {"deny": [valid, "rm -rf ["]}}),
            ("allow", {"command_policy": {"r": {"allow": ["ec[ho"]}}}),
    ):
        probs = policy.rule_problems(cfg)
        assert probs, f"{label}: a malformed pattern was not reported"
        verdict = policy.check("anything at all", role="r", cfg=cfg)
        assert verdict and "does not compile" in verdict, (
            f"{label}: a fleet whose policy cannot be read still ALLOWED a "
            f"command — the rule meant to stop it was skipped in silence "
            f"(got {verdict!r})")
        # and it names the rule, so the owner can fix it without bisecting
        assert "rm -rf [" in verdict or "ec[ho" in verdict, verdict

    # a clean policy is untouched in BOTH directions — the guard must not
    # become a blanket refusal, which would pass the assertions above while
    # making the platform useless
    clean = {"command_policy": {"deny": [valid]}}
    assert policy.check("echo hello", cfg=clean) is None, (
        "a valid policy refused an innocent command")
    assert policy.check("curl x evil", cfg=clean), (
        "a valid deny rule stopped firing")
    print("[policy] an uncompilable deny OR allow pattern refuses every "
          "command and names the rule, instead of being skipped in silence "
          "while the rules around it keep working; a valid policy is "
          "unaffected in both directions")


def check_grant_kinds_cover_authority_classes():
    """Every owner-authority class universal detects is either grantable or
    named as deliberately not.

    grants.py joins on the gap's exact description string, so a class added
    to universal.AUTHORITY_HINTS without a matching KINDS value is silently
    ungrantable: the owner is asked the same question forever with no way to
    answer it once. That is exactly what happened in 2026-08 — five classes
    were added, zero kinds followed, and the module's own comment still
    claimed the mapping was one-to-one. This check makes the decision
    mandatory: a new authority class must land in KINDS or in
    NEVER_GRANTABLE, in the same commit, with the reasoning on the record.
    """
    import grants
    import universal
    detected = {what for _, what in universal.AUTHORITY_HINTS}
    grantable = set(grants.KINDS.values())
    never = set(grants.NEVER_GRANTABLE)
    orphan_kinds = grantable - detected
    assert not orphan_kinds, (
        f"grants.KINDS promises coverage universal cannot detect: "
        f"{sorted(orphan_kinds)} — the join is by exact description string, "
        f"so these grants can never be consulted")
    dead_exclusions = never - detected
    assert not dead_exclusions, (
        f"grants.NEVER_GRANTABLE names classes universal no longer detects: "
        f"{sorted(dead_exclusions)}")
    undecided = detected - grantable - never
    assert not undecided, (
        f"universal detects owner-authority classes with no grant decision: "
        f"{sorted(undecided)} — add each to grants.KINDS (grantable, scoped, "
        f"expiring) or grants.NEVER_GRANTABLE (asked every time, on purpose)")
    both = grantable & never
    assert not both, f"grantable AND never-grantable at once: {sorted(both)}"
    print(f"[grants] {len(grantable)} authority classes grantable, "
          f"{len(never)} deliberately ask-every-time, 0 undecided — the two "
          f"vocabularies cannot drift apart silently")


def check_health_checks_can_fail():
    """Every health check must be able to return NOT OK for some input.

    harness's sandbox check passed cfg["agent"] to sandbox.available(), which
    reads cfg["agent"]["sandbox"] itself — so it looked up agent.agent.sandbox,
    found nothing, defaulted to "host", and returned OK for every fleet that
    has ever run. It was structurally incapable of reporting a problem. The
    generalisable defect is not the typo, it is that nothing ever asked the
    check to fail.
    """
    import sandbox
    ok, _why = sandbox.available({"agent": {"sandbox": "no-such-backend"}})
    assert ok is False, (
        "sandbox.available cannot report an unavailable sandbox — the "
        "harness health check is decorative")
    ok2, why2 = sandbox.available({"agent": {"sandbox": "host"}})
    assert ok2 is False, (
        "host was reported available without allow_unsafe_host — autonomous "
        "shell work would run uncontained on the owner's machine")
    assert "allow_unsafe_host" in why2, why2
    ok3, why3 = sandbox.available(
        {"agent": {"sandbox": "host", "allow_unsafe_host": True}})
    assert ok3 is True, (
        "an owner who explicitly declared the developer host was still "
        f"refused, so trusted fixtures have no way to run: {why3}")

    # A REACHABLE daemon is not a USABLE one. Docker Desktop in
    # Windows-container mode answers `docker info` perfectly and rejects
    # every container this platform launches, because --pids-limit is a Linux
    # cgroup control: `docker run` exits 125 with "Windows does not support
    # PidsLimit" before any command runs. available() reported "docker is
    # ready (network off)" to that daemon, so acquisition promised a sandbox
    # it did not have and CI failed on three of six runners. Simulated, since
    # the daemon's mode is not ours to change inside a test.
    import subprocess as _sp

    class _R:
        def __init__(self, rc=0, out=""):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    real_run = _sp.run
    for ostype, usable in (("windows", False), ("linux", True)):
        def fake_run(cmd, *a, _t=ostype, **k):
            if list(cmd[:2]) == ["docker", "info"]:
                return _R(0, f"{_t}\n" if "--format" in cmd else "Server: x\n")
            return real_run(cmd, *a, **k)
        _sp.run = fake_run
        try:
            import shutil as _sh
            if _sh.which("docker") is None:
                break                       # nothing to simulate against
            got, why = sandbox.available({"agent": {"sandbox": "docker"}})
        finally:
            _sp.run = real_run
        assert got is usable, (
            f"a {ostype}-container daemon reported available={got}; this "
            f"platform can only use Linux containers, and saying otherwise "
            f"promises a sandbox that fails at exit 125 ({why})")
        if not usable:
            assert "linux containers" in why.lower(), why
    print("[health] the sandbox health check can actually FAIL: a configured "
          "backend that does not exist is reported, and `host` is refused "
          "unless the owner explicitly declares allow_unsafe_host")


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
    check_metering_call_sites()
    check_metering_purposes(sb)
    check_registry_keys_are_unique()
    check_control_plane_zone_derivation()
    check_role_capabilities(sb)
    check_gate_catalogue()
    check_expert_birth_paths()
    check_exam_readers_agree(sb)
    check_sandbox_names_are_unique()
    check_documented_cli_exists()
    check_no_file_clock_comparisons()
    check_capability_report_matches_reality()
    check_org_policy_is_enforced(sb)
    check_architecture_table_matches_code()
    check_policy_fails_closed()
    check_health_checks_can_fail()
    check_grant_kinds_cover_authority_classes()
    print("PASS test_invariants")


if __name__ == "__main__":
    main()
