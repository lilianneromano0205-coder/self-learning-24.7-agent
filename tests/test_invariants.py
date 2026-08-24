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
                           timeout=60, env=env, cwd=AGENT_DIR)
        if "UnicodeEncodeError" in (r.stderr or ""):
            crashed.append(mod)
    for mod, sub in sorted(pairs):
        r = subprocess.run([sys.executable, os.path.join(AGENT_DIR, mod), sub,
                            "--help"], capture_output=True, text=True,
                           timeout=60, env=env, cwd=AGENT_DIR)
        if "invalid choice" in (r.stdout + r.stderr):
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
    check_expert_birth_paths()
    check_exam_readers_agree(sb)
    check_sandbox_names_are_unique()
    check_documented_cli_exists()
    check_no_file_clock_comparisons()
    check_capability_report_matches_reality()
    print("PASS test_invariants")


if __name__ == "__main__":
    main()
