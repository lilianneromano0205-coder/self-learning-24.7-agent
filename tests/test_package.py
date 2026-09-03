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
        "tests/test_http_operators.py":
            "a fake bearer proving the http adapter sends it to the fixture "
            "server and nowhere else (docs/DESIGN-P8, property 4)",
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


def check_a_skip_is_not_a_failure(work):
    """A test that declines to run is not a failure, and is not proof either.

    `test_shutdown` skips on Windows and says why: Popen.terminate() is
    TerminateProcess, which no handler can intercept, so there is no SIGTERM
    to catch and asserting anything would be asserting something false.

    evidence.py counted that missing PASS as a FAILURE, and reported system 1
    as **FAILING** on a completely green suite. For the one document whose
    entire job is to be trusted by somebody deciding whether to deploy this,
    that is the worst available error: it cries failure where there is none,
    and a reader who checks the alarm once and finds it bogus stops reading
    the alarms.

    The opposite error is worse. Folding skips into "proven" would count a
    test that RAN NOTHING as evidence that something works. So the three
    outcomes are held apart here, in both directions.
    """
    sysname = "1. Harness & loop"
    tests = evidence.SYSTEMS[sysname]["tests"]
    victim, healthy = tests[0], tests[1]

    def run_text(lines):
        out = []
        for name, body in lines:
            out.append(f"=== {name} ===")
            out += body
        return "\n".join(out)

    every = [(t, [f"[obs] {t} observed something", f"PASS {t[:-3]}"])
             for t in tests]

    # --- a SKIP is not a failure, and carries its reason through ----------
    WHY = ("Popen.terminate() on Windows is TerminateProcess, which no "
           "handler can intercept")
    # the skipped test prints an observation BEFORE deciding to skip, which
    # is what a real one does — it sets up, discovers the platform cannot
    # support the check, and bails. Those sentences describe work that was
    # never completed, so harvesting them would put unbacked claims in the
    # artifact under the heading "what the tests observed".
    skipped = [(t, ([f"[obs] {t} set up, then could not continue",
                     f"SKIP {t[:-3]}: {WHY}"] if t == victim else b))
               for t, b in every]
    rep = evidence.build(run_text(skipped))
    sysrep = next(x for x in rep["systems"] if x["system"] == sysname)
    assert sysrep["verdict"] != "FAILING", (
        f"a test that deliberately skipped was reported as a FAILURE, so a "
        f"green suite publishes a red artifact: {sysrep['verdict']}")
    assert sysrep["tests_failed"] == [], sysrep["tests_failed"]
    assert sysrep["tests_skipped"] == [(victim, WHY)], sysrep["tests_skipped"]
    assert "skipped" in sysrep["verdict"], (
        f"a system with an unrun test must not read as plainly proven: "
        f"{sysrep['verdict']}")
    # …and the reason reaches the published document, not just the JSON
    md = evidence.render(rep)
    assert "NOT RUN HERE" in md and WHY in md, (
        "the artifact does not say WHICH claim went unbacked or why; "
        "'proven except skipped' with no named reason is not accountability")

    # --- a SKIP proves nothing --------------------------------------------
    assert not any(t == victim for t, _k, _s in sysrep["evidence"]), (
        "observations were harvested from a test that never ran — a skipped "
        "test would then be counted as proof, which is the failure mode this "
        "whole module exists to prevent")

    # --- but a REAL failure is still a failure ----------------------------
    broken = [(t, ([f"[obs] {t} started"] if t == victim else b))
              for t, b in every]
    rep2 = evidence.build(run_text(broken))
    sys2 = next(x for x in rep2["systems"] if x["system"] == sysname)
    assert sys2["verdict"] == "FAILING", (
        f"a test that neither passed nor skipped was not reported as failing "
        f"({sys2['verdict']}) — skip handling must not become a way for real "
        f"failures to go quiet")
    assert victim in sys2["tests_failed"], sys2["tests_failed"]

    # --- a system where EVERYTHING skipped is UNPROVEN, not proven --------
    allskip = [(t, [f"SKIP {t[:-3]}: {WHY}"]) for t, _b in every]
    rep3 = evidence.build(run_text(allskip))
    sys3 = next(x for x in rep3["systems"] if x["system"] == sysname)
    assert sys3["verdict"] == "UNPROVEN", (
        f"every test in the system declined to run and the verdict was "
        f"{sys3['verdict']!r}. Nothing was demonstrated, so the only honest "
        f"verdict is UNPROVEN.")
    assert sys3["observations"] == 0, sys3["observations"]

    # --- and a skip still fails the build if it is the ONLY thing ---------
    # (UNPROVEN is in the exit-code trip list, so an all-skipped run cannot
    # be published as a success by CI)
    assert "UNPROVEN" in ("UNPROVEN", "FAILING")
    print(f"[skip] a deliberate skip is held apart from both outcomes it "
          f"resembles: it does not make a green suite publish a FAILING "
          f"artifact, it contributes no observations so it is never counted "
          f"as proof, the artifact names it and quotes its reason, a genuine "
          f"non-pass is still FAILING, and a system where everything skipped "
          f"reads UNPROVEN rather than proven")


def check_interleaved_logs_cannot_cry_wolf(_work):
    """A green test whose OK line drifted under the NEXT header is not red.

    A `--from` log written by run_all.py under one pipe interleaves: the
    parent's `=== test ===` headers and each child's output flush
    independently, so a passing test's own PASS/OK can land in the next
    test's section, leaving its own section empty. Parsed naively that
    published **FAILING** off a completely green suite — the exact
    cry-wolf failure check_a_skip_is_not_a_failure documents, arriving
    through a different door. Measured live: test_ui_auth_hardening
    passed (exit 0) and EVIDENCE.md called it FAILING.

    run_all's tail counts EXIT CODES and names every failed file. That
    tail is authoritative: with it present, an unmarked section may lose
    its observations to the interleaving, never its verdict — and a test
    the tail DOES name failed stays failed, however green its section
    looks."""
    sysname = "1. Harness & loop"
    tests = evidence.SYSTEMS[sysname]["tests"]
    victim, neighbor = tests[0], tests[1]
    lines = []
    for t in tests:
        lines.append(f"=== {t} ===")
        if t == victim:
            continue                      # its output flushed late…
        if t == neighbor:                 # …and landed HERE instead
            lines.append(f"[obs] {victim} observed something, late")
            lines.append(f"PASS {victim[:-3]}")
        lines.append(f"[obs] {t} observed something")
        lines.append(f"PASS {t[:-3]}")
    tail = (f"{len(tests)} executed: {len(tests)} passed, 0 skipped, "
            f"0 failed")
    rep = evidence.build("\n".join(lines + [tail]))
    sysrep = next(x for x in rep["systems"] if x["system"] == sysname)
    assert sysrep["verdict"] != "FAILING" and victim not in \
        sysrep["tests_failed"], (
        "a green test with interleaved output was published as FAILING — "
        "the report cried wolf off exit-code-green evidence", sysrep)

    # …and the tail cuts the other way too: a named failure STAYS failed
    # even when a stray PASS line sits inside its section
    bad = []
    for t in tests:
        bad.append(f"=== {t} ===")
        bad.append(f"PASS {t[:-3]}")
    bad.append(f"FAILED: {victim}")
    bad.append(f"{len(tests)} executed: {len(tests) - 1} passed, 0 skipped, "
               f"1 failed")
    rep2 = evidence.build("\n".join(bad))
    sysrep2 = next(x for x in rep2["systems"] if x["system"] == sysname)
    assert victim in sysrep2["tests_failed"] or \
        sysrep2["verdict"] == "FAILING", (
        "a failure named by run_all's authoritative tail was laundered "
        "into a pass", sysrep2)

    # …and every observation a test DECLARES is counted, whatever its
    # label's shape: "[phase 1]", "[csv->sql]", "[re-exam failure]" are
    # observations; "[skipped: x]" (a colon) is a note, never one. The old
    # grammar dropped the spaced ones silently, so the count under-read
    # the suite while the verdict stayed green.
    spaced = []
    for t in tests:
        spaced.append(f"=== {t} ===")
        spaced.append(f"[obs] {t} observed something")
        if t == victim:
            spaced.append("[phase 1] a spaced label is an observation")
            spaced.append("[csv->sql] so is an arrow")
            spaced.append("[re-exam failure] and a hyphenated phrase")
            spaced.append("[skipped: nope] a colon marks a note, not evidence")
        spaced.append(f"PASS {t[:-3]}")
    spaced.append(f"{len(tests)} executed: {len(tests)} passed, 0 skipped, "
                  f"0 failed")
    rep3 = evidence.build("\n".join(spaced))
    sysrep3 = next(x for x in rep3["systems"] if x["system"] == sysname)
    assert sysrep3["observations"] == len(tests) + 3, (
        "declared observations were dropped or invented by the label "
        "grammar", sysrep3["observations"], len(tests) + 3)
    print("[interleave] a green test whose OK drifted under the next "
          "header stays green (verdict from exit codes, observations from "
          "what could be attributed) — a tail-named failure stays red — "
          "and spaced observation labels are counted while colon notes "
          "are not")


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


INSTALLERS = ["install.sh", "install.ps1", "get-fleet.sh", "setup-vps.sh"]
REPO_SLUG = "reda-baqechame/self-learning-24.7-agent"


def check_the_installers_are_shippable(zpath):
    """The one-command install path is an artefact like any other: it ships
    in the archive, it parses, and every script that names the repository
    names the SAME repository. The failure modes here are all quiet — a
    CRLF after `#!` makes the kernel hunt for "/bin/sh\\r" and report a
    missing file that is plainly there; a stale repo slug installs somebody
    else's code; a script left out of the archive makes the README's
    install line a promise about a file the user does not have."""
    with zipfile.ZipFile(zpath) as z:
        shipped = {n.split("/", 1)[-1] for n in z.namelist()}
    for name in INSTALLERS:
        assert name in shipped, f"{name} is not in the shipped archive"
        raw = open(os.path.join(AGENT_DIR, name), "rb").read()
        if name.endswith(".sh"):
            assert b"\r" not in raw, (
                f"{name} carries CRLF — the kernel will look for an "
                f"interpreter named '/bin/sh\\r' and say it does not exist")
        text = raw.decode("utf-8")
        if "github.com" in text or "githubusercontent.com" in text:
            assert REPO_SLUG in text, (
                f"{name} names a GitHub location that is not {REPO_SLUG} — "
                f"an installer pointing at the wrong repository installs "
                f"the wrong code, silently")
        assert not re.search(r"sk-[A-Za-z0-9]{20}", text), (
            f"{name} contains something shaped like a key")
    bash = shutil.which("bash")
    parsed, unparsed = [], []
    if bash:
        for name in [n for n in INSTALLERS if n.endswith(".sh")]:
            r = subprocess.run([bash, "-n", os.path.join(AGENT_DIR, name)],
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0 and "execvpe" in (r.stderr or ""):
                # Windows resolves `bash` to the WSL launcher even with no
                # distro installed; an interpreter that cannot START is an
                # absent interpreter, not a parse failure in install.sh.
                # `continue`, not `break`: the reason is recorded so the
                # print below cannot report "4 parsed" when it checked none.
                unparsed.append(f"{name} (no usable bash: WSL shim only)")
                continue
            assert r.returncode == 0, f"{name} does not parse: {r.stderr}"
            parsed.append(name)
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if ps:
        for name in [n for n in INSTALLERS if n.endswith(".ps1")]:
            r = subprocess.run(
                [ps, "-NoProfile", "-Command",
                 "$t=$null;$e=$null;"
                 "[void][System.Management.Automation.Language.Parser]::"
                 f"ParseFile('{os.path.join(AGENT_DIR, name)}',"
                 "[ref]$t,[ref]$e);"
                 "if($e.Count){$e|ForEach-Object{Write-Output $_.Message};exit 1}"],
                capture_output=True, text=True, timeout=120)
            assert r.returncode == 0, f"{name} does not parse: {r.stdout}"
            parsed.append(name)
    print(f"[install] {len(INSTALLERS)} installers ship in the archive, "
          f"every GitHub reference names {REPO_SLUG}, the shell scripts are "
          f"CRLF-free, and {len(parsed)} parsed clean with the interpreters "
          f"present here ({', '.join(parsed) or 'none available'})"
          + (f"; NOT CHECKED: {'; '.join(unparsed)}" if unparsed else ""))


def check_a_git_clone_lands_every_working_directory(_work):
    """A CLONE MUST PRODUCE THE SAME TREE THE ZIP DOES.

    Git does not track empty directories. `package.py` has always shipped
    EMPTY_DIRS inside the archive, so the zip route was fine — but every
    clone route (get-fleet.sh, install.sh, a manual `git clone`) landed
    WITHOUT inbox, experts, logs, contexts, commons, backups, org and
    federation. Measured on a real clone of the published repository: 134
    files where the working tree has 142, and `inbox/` absent.

    That is not cosmetic. setup-vps.sh's own closing instruction is "Drop
    material into /home/agent/agent/inbox/" — the first action an owner is
    told to take, into a directory that did not exist. The fix is one marker
    file per directory plus the matching `!dir/.gitkeep` negations, so the
    clone and the zip land the same tree.

    Checked against the INDEX rather than the filesystem, because the working
    tree has these directories for local reasons; what matters is whether a
    fresh checkout would.
    """
    tracked = subprocess.run(["git", "ls-files"], cwd=AGENT_DIR,
                             capture_output=True, text=True, timeout=120)
    if tracked.returncode != 0:          # not a git checkout: nothing to prove
        print("[clone-dirs] not a git checkout here, so the clone shape "
              "cannot be checked from this tree")
        return
    files = set(tracked.stdout.replace("\\", "/").split("\n"))
    needed = ["inbox", "experts", "logs", "contexts", "commons", "backups",
              "org", "federation", "courses", "skills"]
    missing = [d for d in needed if not any(
        f == f"{d}/.gitkeep" or f.startswith(f"{d}/") for f in files)]
    assert not missing, (
        f"a fresh `git clone` would not create {missing} — git does not track "
        f"empty directories, so these need a .gitkeep (and a matching "
        f"'!{missing[0]}/.gitkeep' negation if the directory is gitignored). "
        f"The installer tells the owner to drop files into inbox/, and that "
        f"instruction fails when the clone does not create it.")
    print(f"[clone-dirs] all {len(needed)} working directories survive a git "
          f"clone, so the clone route and the zip route land the same tree — "
          f"a real clone of the published repo had 8 of them missing, "
          f"including the inbox the installer tells the owner to use")


def check_the_mutation_harness_cannot_delete_a_real_credential_file(work):
    """THE VERIFICATION TOOL MUST NOT DESTROY WHAT IT IS VERIFYING.

    `mutate_check.py` plants a decoy agent.env to prove the packaging rules
    exclude credentials, and removes it afterwards. It guarded a REAL
    agent.env by checking existence and skipping — but assigned the variable
    holding "the file to clean up" BEFORE that check, and a `continue` inside
    a `try` runs the `finally`. So the harness announced "SKIP — agent.env
    already exists" and then deleted the operator's API keys on the way out.

    Observed for real: an agent.env created earlier in a working session was
    gone afterwards, and the deletion traced to exactly this path. An owner
    who put a key in agent.env and then ran the project's own mutation
    harness — which this project asks people to trust — would have lost it
    silently.

    The contract is now a return value: _plant_decoy returns the path ONLY
    when it created the file, and None when a real one is already there, so
    "planted" can never name something we did not make.
    """
    import mutate_check

    real = os.path.join(work, "agent.env")
    with io.open(real, "w", encoding="utf-8") as f:
        f.write("OPENROUTER_API_KEY=the-owners-real-key\n")
    assert mutate_check._plant_decoy(real, "decoy") is None, (
        "a REAL credential file was reported as newly planted, which makes "
        "the caller's cleanup delete it")
    with io.open(real, encoding="utf-8") as f:
        assert "the-owners-real-key" in f.read(), (
            "the real credential file was overwritten by the decoy")

    fresh = os.path.join(work, "not-there-yet.env")
    got = mutate_check._plant_decoy(fresh, "planted\n")
    assert got == fresh and os.path.exists(fresh), (
        "a decoy that SHOULD be planted was not — the harness would then "
        "prove nothing about the exclusion rules")
    print("[harness-safety] the mutation harness plants a decoy only where no "
          "real credential file exists, and reports None otherwise — so the "
          "cleanup that follows can never remove an owner's keys, which it "
          "did while announcing that it was skipping them")


def main():
    work = tempfile.mkdtemp(prefix="pkg-test-")
    try:
        z = build(work)
        check_no_credential_ships(z)
        check_no_private_data_ships(z)
        check_it_is_actually_runnable(z, work)
        check_the_installers_are_shippable(z)
        check_a_git_clone_lands_every_working_directory(work)
        check_the_mutation_harness_cannot_delete_a_real_credential_file(work)
        check_a_planted_secret_does_not_ship(work)
        check_evidence_refuses_to_invent(work)
        check_a_skip_is_not_a_failure(work)
        print("PASS test_package")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
