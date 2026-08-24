#!/usr/bin/env python3
"""THE SHIPPED ARCHIVE MUST NOT CARRY WHAT IT PROMISES TO LEAVE BEHIND.

`package.py` and `evidence.py` were the last two modules no test mentioned.
That mattered unevenly: `evidence.py` writing a wrong report is embarrassing,
and `package.py` shipping a key is a disclosed credential. A distributable
archive is the most-copied artefact this project produces — it goes to people
who were never told what not to look at.

So the checks here are the ones whose failure is expensive:

  1. the archive contains NO credential, by name, by extension, or by
     content — including the four sources `credentials.py` knows about
  2. it contains no expert memory, no task state, no logs, no contexts
  3. it DOES contain everything needed to run: the modules, the prompts, the
     tests, and settings.toml
  4. an archive with a secret in it is refused rather than shipped
  5. it unzips into a directory that immediately passes `harness --check`
  6. `evidence.py` names every registered test and refuses to invent a
     verdict for a system whose tests never ran

Run from the agent/ directory:  python tests/test_package.py
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import credentials             # noqa: E402
import evidence                # noqa: E402

PY = sys.executable
# Assembled at runtime, never written as a literal. This file SHIPS in the
# archive it is checking, so a literal decoy would find itself and fail — the
# scanner reporting its own bait as a leak.
SECRET = "sk-" + "live-" + "THIS-MUST-" + "NEVER-SHIP"


def build(out_dir):
    out = os.path.join(out_dir, "shipped.zip")
    r = subprocess.run([PY, os.path.join(AGENT_DIR, "package.py"),
                        "--out", out],
                       capture_output=True, text=True, timeout=300,
                       cwd=AGENT_DIR, env={**os.environ, "PYTHONUTF8": "1"})
    assert r.returncode == 0, (
        f"package.py failed:\n{(r.stdout + r.stderr)[-800:]}")
    assert os.path.isfile(out), r.stdout
    return out


def check_no_credential_ships(zpath):
    """Every way a key can exist in this tree, checked in the archive."""
    z = zipfile.ZipFile(zpath)
    names = z.namelist()
    # by NAME: the basenames credentials.py knows are secret
    for base in credentials.SECRET_BASENAMES:
        hits = [n for n in names if os.path.basename(n) == base]
        assert not hits, f"the archive carries {base}: {hits}"
    # by DIRECTORY: anything under a secrets-shaped folder
    for n in names:
        parts = {p.lower() for p in n.replace("\\", "/").split("/")[:-1]}
        assert not (parts & set(credentials.SECRET_DIRS)), \
            f"the archive carries a file under a secret directory: {n}"
    # by EXTENSION
    for ext in (".key", ".pem", ".p12", ".pfx"):
        hits = [n for n in names if n.lower().endswith(ext)]
        assert not hits, f"the archive carries {ext} files: {hits}"
    # by CONTENT: read every text member and look for key-shaped tokens
    suspicious = []
    for n in names:
        if n.endswith("/") or z.getinfo(n).file_size > 2_000_000:
            continue
        try:
            body = z.read(n).decode("utf-8", errors="ignore")
        except Exception:
            continue
        if SECRET in body:
            suspicious.append((n, "the planted secret"))
        # credentials.keys_in_text, NOT looks_like_key: the latter takes a
        # PATH and begins with os.path.getsize(), so calling it on a LINE OF
        # TEXT raised OSError inside the function and returned False for
        # every line of every member. This loop reported nothing because it
        # was incapable of reporting anything — while the line below printed
        # that the archive had been "checked four ways ... by reading every
        # text file". Three ways worked. A dead check and a clean check both
        # return False, which is why it survived every run.
        for line_no, excerpt in credentials.keys_in_text(body):
            suspicious.append((n, f"line {line_no}: {excerpt}"))
    # Fake credentials this platform's own tests are BUILT from. A package
    # that ships its tests ships these, and that is correct: each one exists
    # to prove a control catches it. They are enumerated rather than
    # pattern-matched, because "looks like a fixture" is exactly the judgement
    # an attacker would want the scanner to make.
    #
    # The table is checked in BOTH directions. An unlisted hit fails, so a
    # real key cannot arrive quietly. A listed member with no hit ALSO fails,
    # so a renamed or deleted fixture cannot leave a standing exemption behind
    # for some future file to inherit — which is how allowlists rot into
    # blindfolds.
    FIXTURE_KEYS = {
        "mutate_check.py":
            "the mutation that plants a key in agent.env to prove the "
            "packaging scan catches it",
        "tests/test_backup.py":
            "SECRET — planted to prove a backup excludes credentials",
        "tests/test_bootstrap.py":
            "SECRET — planted to prove setup never echoes a key",
        "tests/test_guardrails.py":
            "a fake DEEPSEEK_API_KEY written into a test agent.env",
        "tests/test_invariants.py":
            "the inline api_key fixture for the credential-source invariant",
        "tests/test_url.py":
            "a fake DEEPSEEK_API_KEY proving a fetched URL cannot carry "
            "a key into the transcript",
        "tests/test_secrets.py":
            "SECRET — planted to prove the redaction path",
    }
    unexpected = [(n, w) for n, w in suspicious if n not in FIXTURE_KEYS]
    assert not unexpected, (
        "credential-shaped content in the archive:\n  "
        + "\n  ".join(f"{n}: {w}" for n, w in unexpected[:6])
        + "\nIf this is a deliberate test fixture, add it to FIXTURE_KEYS "
          "with the reason. If it is a real key, it just shipped.")
    stale = sorted(set(FIXTURE_KEYS) - {n for n, _w in suspicious})
    assert not stale, (
        f"FIXTURE_KEYS exempts {stale} but the scan found nothing there — "
        f"remove the entry. A standing exemption for a file that no longer "
        f"contains a fixture is a hole waiting for the next edit.")
    for n, _w in suspicious:                # the fixtures must be FAKE
        assert "sk-" in _w or "sk_" in _w, (n, _w)
    print(f"[secrets] {len(names)} archive members checked four ways — by "
          f"basename, by containing directory, by extension, and by READING "
          f"every text member for assigned credential values. The content "
          f"scan was calling a path-taking function on a line of text, so it "
          f"had never evaluated true; now live, it finds exactly the "
          f"{len(suspicious)} synthetic fixtures the tests are built from and "
          f"nothing else, and an unlisted hit or a stale exemption both fail")


def check_no_private_data_ships(zpath):
    """Somebody else's archive must not contain this fleet's memory."""
    names = zipfile.ZipFile(zpath).namelist()
    forbidden = {
        "experts/": "another operator's expert directories",
        "state.json": "a task queue with real goals in it",
        "logs/": "logs, which carry goals, errors and file paths",
        "contexts/": "compiled context windows — whole transcripts",
        "org/": "the organization roster and its audit trail",
    }
    z = zipfile.ZipFile(zpath)
    for frag, what in forbidden.items():
        hits = [n for n in names
                if frag in n.replace("\\", "/") and not n.endswith("/")
                # an EMPTY placeholder is the opposite of a leak: package.py
                # creates the working directories on purpose so a fresh
                # unzip runs without setup. What must not ship is CONTENT.
                and os.path.basename(n) not in (".gitkeep", ".keep")
                and z.getinfo(n).file_size > 0]
        assert not hits, f"the archive carries {what}: {hits[:4]}"
    # PROOF OBSERVATIONS ARE ALLOWED TO SHIP, and that is a decision rather
    # than an oversight. Each one is bound to a code hash, so a recipient who
    # changes anything sees the level fall on its own; and the records carry
    # no host path, user name or goal — only a feature, a verdict, a count
    # and a hash. What must NOT ship is anything identifying this machine.
    obs = [n for n in names if n.replace("\\", "/").endswith(
        "proof/observations.jsonl")]
    for n in obs:
        for line in z.read(n).decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            assert rec.get("code_hash"), (
                "a shipped observation with no code hash would give the "
                "recipient a verdict nothing can invalidate")
            leak = [w for w in ("Users", "home/", "C:\\", "/c/", "@")
                    if w in line]
            assert not leak, (
                f"a shipped proof observation carries host-identifying "
                f"content {leak}: {line[:160]}")
    placeholders = [n for n in names
                    if os.path.basename(n) in (".gitkeep", ".keep")]
    print(f"[private] none of {len(forbidden)} private-data shapes carries "
          f"CONTENT in the archive — no expert memory, task state, logs, "
          f"context windows or organization roster — "
          f"while {len(placeholders)} empty placeholder(s) keep the working "
          f"directories so a fresh unzip runs with no setup. Proof "
          f"observations DO ship, deliberately: every one is bound to a code "
          f"hash and none names this machine, so the recipient inherits "
          f"evidence that falls the moment they change the code")


def check_it_is_actually_runnable(zpath, work):
    """An archive that ships nothing private and also nothing useful is not
    a win."""
    names = set(zipfile.ZipFile(zpath).namelist())
    flat = {os.path.basename(n) for n in names}
    for must in ("loop.py", "harness.py", "ui.py", "ui.html", "settings.toml",
                 "fleet.py", "bootstrap.py", "run_all.py", "constitution.md"):
        assert must in flat, f"the archive is missing {must}"
    n_mods = len([n for n in names if n.endswith(".py")
                  and "tests/" not in n.replace("\\", "/")])
    n_tests = len([n for n in names if "test_" in os.path.basename(n)])
    assert n_mods >= 50, n_mods
    assert n_tests >= 80, n_tests

    dest = os.path.join(work, "unzipped")
    zipfile.ZipFile(zpath).extractall(dest)
    root = dest
    while not os.path.isfile(os.path.join(root, "harness.py")):
        subs = [d for d in os.listdir(root)
                if os.path.isdir(os.path.join(root, d))]
        assert subs, "harness.py is not in the archive at any depth"
        root = os.path.join(root, subs[0])
    r = subprocess.run([PY, "harness.py", "--check"], cwd=root,
                       capture_output=True, text=True, timeout=180,
                       env={**os.environ, "PYTHONUTF8": "1"})
    assert r.returncode == 0, (
        "a freshly unzipped archive does not pass its own contract check:\n"
        + (r.stdout + r.stderr)[-700:])
    print(f"[runnable] the archive carries {n_mods} modules, {n_tests} tests, "
          f"the prompts and settings.toml — and unzipped into an empty "
          f"directory it passes `harness.py --check` with no setup at all")
    return root


def check_a_planted_secret_does_not_ship(work):
    """The real test of an exclusion rule is a file that WANTS to be caught."""
    planted = []
    for rel in ("agent.env", "keys/openai.key", "ui-token.txt"):
        p = os.path.join(AGENT_DIR, rel.replace("/", os.sep))
        if os.path.exists(p):
            continue                      # never touch a real one
        os.makedirs(os.path.dirname(p) or AGENT_DIR, exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            f.write(f"OPENAI_API_KEY={SECRET}\n")
        planted.append(p)
    assert planted, "could not plant a decoy — every candidate name existed"
    try:
        z = build(work)
        names = zipfile.ZipFile(z).namelist()
        for p in planted:
            rel = os.path.relpath(p, AGENT_DIR).replace(os.sep, "/")
            assert not any(n.replace("\\", "/").endswith(rel) for n in names), \
                f"a planted credential file shipped: {rel}"
        blob = b"".join(zipfile.ZipFile(z).read(n) for n in names
                        if not n.endswith("/")
                        and zipfile.ZipFile(z).getinfo(n).file_size < 2_000_000)
        assert SECRET.encode() not in blob, (
            "the planted secret's VALUE appears somewhere in the archive, "
            "even though the file itself was excluded")
    finally:
        for p in planted:
            try:
                os.remove(p)
                d = os.path.dirname(p)
                if d != AGENT_DIR and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass
    print(f"[planted] {len(planted)} decoy credential file(s) were created in "
          f"the source tree and the archive excluded every one, by file and "
          f"by value — an exclusion rule is only worth what it catches")


def check_evidence_refuses_to_invent(work):
    """`evidence.py` builds its report from an actual suite run. The property
    worth holding is that it cannot report a verdict it did not observe."""
    # every registered test is classified; a new one shows as drift
    listed = set(evidence.registered_tests())
    classified = set()
    for sysname, spec in evidence.SYSTEMS.items():
        for t in spec["tests"]:
            assert t not in classified, f"{t} is claimed by two systems"
            classified.add(t)
        assert spec.get("blind"), f"{sysname} states no blind spot"
        assert len(spec["blind"]) > 60, f"{sysname}'s blind spot is a token"
    drift = listed - classified
    assert not drift, (
        f"{len(drift)} registered test(s) belong to no system, so their "
        f"evidence is counted nowhere: {sorted(drift)}")
    ghosts = classified - listed
    assert not ghosts, f"classified but never run: {sorted(ghosts)}"
    assert evidence.GLOBAL_CAVEAT and "mock" in evidence.GLOBAL_CAVEAT.lower()
    # and the shipped report says the same thing
    report = os.path.join(AGENT_DIR, "EVIDENCE.md")
    if os.path.isfile(report):
        with io.open(report, encoding="utf-8") as f:
            text = f.read()
        assert "scripted mock" in text, (
            "EVIDENCE.md must carry the standing caveat on every page")
        assert "blind spot" in text.lower()
        # A report that claims a system the module no longer defines is a
        # lie and fails here. A report MISSING a system added since it was
        # generated is merely stale — the file is regenerated by
        # `python evidence.py`, and failing the suite on it would make a
        # 5-minute regeneration a prerequisite for every test run.
        claimed = set(re.findall(r"^## (\d+\. .+)$", text, re.M))
        ghosts = claimed - set(evidence.SYSTEMS)
        assert not ghosts, (
            f"EVIDENCE.md reports {sorted(ghosts)}, which evidence.py no "
            f"longer defines — a generated report must never outlive its "
            f"source")
        stale = set(evidence.SYSTEMS) - claimed
        if stale:
            print(f"       note: EVIDENCE.md predates {len(stale)} system(s) "
                  f"({', '.join(sorted(stale))}); regenerate with "
                  f"`python evidence.py`")
    print(f"[evidence] all {len(listed)} registered tests are classified into "
          f"{len(evidence.SYSTEMS)} systems with no overlap and no drift, "
          f"every system states a blind spot, and the standing "
          f"'every call is a mock' caveat is in the module and in the "
          f"generated report")


def main():
    work = tempfile.mkdtemp(prefix="pkg-test-")
    try:
        z = build(work)
        check_no_credential_ships(z)
        check_no_private_data_ships(z)
        check_it_is_actually_runnable(z, work)
        check_a_planted_secret_does_not_ship(work)
        check_evidence_refuses_to_invent(work)
        print("PASS test_package")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
