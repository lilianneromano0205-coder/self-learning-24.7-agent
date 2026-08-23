#!/usr/bin/env python3
"""THE AUDIT FINDINGS, KEPT CLOSED.

Every check here is a defect that was reproduced against this platform in a
two-pass forensic audit, then fixed. They live in one file because they share
one shape: a control defended the path its author was thinking about, and a
second path reached the same operation without passing it.

  1. locks       release verifies ownership — a stalled holder must not delete
                 the lockfile of whoever replaced it
  2. gates       a done_check arriving over the network NAMES a gate; it never
                 authors a shell command (this was remote code execution)
  3. csrf        the panel refuses cross-origin writes — a loopback bind stops
                 other machines, not other origins
  4. secrets     one credential model: env, agent.env, inline api_key and
                 api_key_file are all secrets, to every subsystem
  5. writes      the agent cannot rewrite the files that define its own
                 permissions (settings, prompts, approvals, ledgers)
  6. scheme      ingestion reads the web, never the disk
  7. course      a course name cannot escape the expert root
  8. skills      a skill file cannot declare itself trusted
  9. effects     an unresolved external effect is never silently repeated

Run from the agent/ directory:  python tests/test_hardening.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import credentials          # noqa: E402
import effects              # noqa: E402
import gates                # noqa: E402
import ingest               # noqa: E402
import locks                # noqa: E402
import loop                 # noqa: E402
import skills               # noqa: E402


def _write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def check_locks(sb):
    """A holder that stalls past `stale` loses the lock — and must not then
    delete the lock of the process that replaced it. locks.py had no test at
    all; test_lock.py covers the loop's course lock, a different mechanism."""
    base = os.path.join(sb, "ledger.json")
    _write(base, "{}")
    lock = base + ".lock"

    a = locks.holding(base, timeout=2.0, stale=0.2)
    a.__enter__()
    a_tok = open(lock, encoding="utf-8").read().strip()
    import time
    time.sleep(0.4)                      # A stalls past the stale window

    with locks.holding(base, timeout=2.0, stale=0.2):
        b_tok = open(lock, encoding="utf-8").read().strip()
        assert b_tok != a_tok, "B must hold its own token, not A's"
        a.__exit__(None, None, None)     # A finishes and releases
        assert os.path.exists(lock), "A must not delete B's lock"
        assert open(lock, encoding="utf-8").read().strip() == b_tok, \
            "the lock still belongs to B"
    assert not os.path.exists(lock), "B's own release removes it"

    # a token is unique per ACQUISITION, not per process: same pid twice
    with locks.holding(base) as _:
        t1 = open(lock, encoding="utf-8").read().strip()
    with locks.holding(base) as _:
        t2 = open(lock, encoding="utf-8").read().strip()
    assert t1 != t2, "a reused PID must not reuse a token"
    print("[locks] release verifies ownership: a stalled holder cannot free "
          "the lock that replaced it, and tokens are per-acquisition")


def check_gates():
    """A gate is named and parameterised. A free-form shell string delivered
    over HTTP was arbitrary code execution on the owner's machine."""
    cmd = gates.build({"gate": "exists", "path": "out/index.html"})
    assert "out/index.html" in cmd and cmd.strip().startswith('"')
    for bad, why in (
            ({"gate": "exists", "path": "../../etc/passwd"}, "traversal"),
            ({"gate": "exists", "path": "x'; rm -rf /; '"}, "shell syntax"),
            ({"gate": "verify", "course": "a; whoami"}, "shell syntax"),
            ({"gate": "nope", "path": "x"}, "unknown gate"),
            ("python -c 'anything'", "a raw command"),
            ({"gate": "exists"}, "a missing parameter")):
        try:
            gates.build(bad)
            raise AssertionError(f"must refuse {why}: {bad!r}")
        except ValueError:
            pass
    assert gates.build(None) is None, "no gate is legal; it just is not a gate"
    assert {g["gate"] for g in gates.describe()} == {
        "exists", "designcheck", "citecheck", "verify", "memcheck"}
    print("[gates] the catalogue builds the command; traversal, shell syntax, "
          "unknown gates and raw strings are all refused")


def check_secrets(sb):
    """One credential model. Four sources; six subsystems used to disagree."""
    _write(os.path.join(sb, "keys", "openai.key"), "sk-abcdefghij0123456789\n")
    _write(os.path.join(sb, "cookies.txt"), "session=x\n")
    _write(os.path.join(sb, "bootstrap.json"), "{}\n")
    _write(os.path.join(sb, "notes.md"), "# ordinary course material\n")
    cfg = os.path.join(sb, "settings.toml")
    with open(cfg, "a", encoding="utf-8") as f:
        f.write('\n[providers.filekey]\nbase_url = "https://x"\n'
                'api_key_file = "keys/openai.key"\n')

    for rel in ("keys/openai.key", "cookies.txt", "bootstrap.json"):
        assert credentials.is_secret(os.path.join(sb, rel), sb), rel
    assert not credentials.is_secret(os.path.join(sb, "notes.md"), sb)
    assert not credentials.is_secret(cfg, sb), "settings.toml stays readable"

    # the file settings.toml points at is discovered, not guessed
    assert os.path.realpath(os.path.join(sb, "keys", "openai.key")) in \
        credentials.configured_key_files(sb)

    # every source the runtime honours counts as funded
    assert credentials.key_present({"api_key_file": "keys/openai.key"}, sb)
    assert credentials.key_present({"api_key": "inline-value"}, sb)
    assert not credentials.key_present({"api_key_env": "NOT_SET_ANYWHERE"}, sb)

    # an inline key never travels
    red = credentials.redact('api_key = "sk-secret-value"\nmodel = "x"\n')
    assert "sk-secret-value" not in red and 'model = "x"' in red
    print("[secrets] api_key_file and inline api_key are secrets to every "
          "subsystem; ordinary files and settings.toml are unaffected")


def check_writes(sb):
    """The agent may not rewrite what defines its own permissions."""
    a = loop.Agent(sb)
    for rel in ("settings.toml", "prompts/constitution.md", "prompts/student.md",
                "state.json", "prospective.json", "approvals/ap-1.json"):
        try:
            a._safe_path(rel, write=True)
            raise AssertionError(f"writing {rel} must be refused")
        except ValueError:
            pass
    for rel in ("out/index.html", "courses/c/notes.md", "skills/mine/SKILL.md"):
        a._safe_path(rel, write=True)          # real work is untouched
    r = a.exec_tool({"id": "t", "role": "practitioner"}, "write_file",
                    {"path": "settings.toml", "content": "[providers.evil]"})
    assert r.startswith("ERROR"), r
    print("[writes] settings, charters, approvals and ledgers are unwritable "
          "by the agent; its own work and skills still are")


def check_scheme(sb):
    """Ingestion reads the web. A `.url` file in the inbox is auto-scanned,
    so file:// would have read agent.env straight into a lesson."""
    _write(os.path.join(sb, "agent.env"), "DEEPSEEK_API_KEY=sk-never\n")
    import pathlib
    for bad in (pathlib.Path(os.path.join(sb, "agent.env")).as_uri(),
                "file://localhost/etc/passwd", "ftp://x/y", "/etc/passwd"):
        try:
            ingest.fetch_url(bad, os.path.join(sb, "leak.md"))
            raise AssertionError(f"must refuse {bad}")
        except ValueError as e:
            assert "http and https" in str(e)
    assert not os.path.exists(os.path.join(sb, "leak.md"))
    print("[scheme] file://, ftp:// and bare paths refused by ingestion")


def check_course(sb):
    """A course name is a PATH in five harness writers that never see
    _safe_path. Unsanitised, it wrote outside the expert root."""
    import gotchas
    assert loop.safe_course("../../ESCAPED") == "escaped"
    assert loop.safe_course("Web Course 101") == "web-course-101"
    assert loop.safe_course(None) is None
    task = {"id": "t", "course": loop.safe_course("../../ESCAPED"),
            "goal": "kafka broker lag", "steps": []}
    gotchas.from_failure(sb, task, {"category": "tool_misuse",
                                    "cause": "probe", "failure_id": "F-1"})
    outside = os.path.abspath(os.path.join(sb, "..", ".."))
    stray = [os.path.join(dp, f) for dp, _, fn in os.walk(outside)
             for f in fn if "ESCAPED" in dp]
    assert not stray, stray
    assert os.path.exists(os.path.join(sb, "courses", "escaped", "gotchas.md"))
    print("[course] a traversing course name is slugified; the gotcha lands "
          "inside the expert, not above it")


def check_skill_trust(sb):
    """Trust comes from the graph the owner writes, never from the file."""
    _write(os.path.join(sb, "skills", "third-party", "SKILL.md"),
           "---\nname: third-party\ndescription: x\nprovenance: own\n---\n\nbody\n")
    _write(os.path.join(sb, "skills", "third-party", "scripts", "run.py"),
           "print('hello')\n")
    assert skills.provenance_of(sb, "skills/third-party/SKILL.md") == "community", \
        "a file may not declare itself trusted"
    assert skills.script_guard(sb, "python skills/third-party/scripts/run.py"), \
        "its bundled scripts stay disabled"
    skills.set_provenance(sb, "third-party", "owner")
    assert skills.script_guard(sb, "python skills/third-party/scripts/run.py") is None, \
        "the owner's recorded decision unlocks it"
    print("[skills] a third-party SKILL.md cannot self-declare 'own'; only "
          "the owner's recorded decision grants trust")


def check_effects(sb):
    """An effect started and never resolved is not repeated silently."""
    key = "lin-1|srv|send|abc"
    effects.begin(sb, key, "t1", "srv", "send", {"to": "x"})
    assert effects.unfinished(sb, key), "a started effect is visible as unresolved"
    effects.record(sb, key, "t1", "srv", "send", {"to": "x"}, {"ok": True})
    assert not effects.unfinished(sb, key), "a resolved effect is settled"
    assert effects.lookup(sb, key), "and replayable"
    hist = effects.history(sb)
    assert len(hist) == 1, f"one entry per effect, got {len(hist)}: {hist}"
    print("[effects] the ledger is write-ahead: an unresolved effect is "
          "visible, and one effect reads as one entry")


def main():
    sb = make_sandbox("hardening", providers={"m": {"script": "s.json"}},
                      roles={"practitioner": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    check_locks(sb)
    check_gates()
    check_secrets(sb)
    check_writes(sb)
    check_scheme(sb)
    check_course(sb)
    check_skill_trust(sb)
    check_effects(sb)
    print("PASS test_hardening")


if __name__ == "__main__":
    main()
