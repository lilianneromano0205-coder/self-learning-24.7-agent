#!/usr/bin/env python3
"""CAPABILITY ACQUISITION — getting a new tool without getting new authority.

Manual §12. The pipeline it specifies, in order:

    1. detect a capability gap
    2. search the trusted Tool/Skill/MCP registry
    3. if missing, search approved external catalogues
    4. inspect provenance, permissions, package source, required secrets
    5. install ONLY in an isolated disposable worker
    6. run a generated capability test and a security check
    7. register the exact version/hash, permissions and evidence if it passes
    8. promotion to organization-wide trust requires policy-defined approval

Validation gate invariants: *"No host/control-plane installs; exact
version/provenance recorded; permissions least-privilege; capability test
mandatory; rollback/removal possible."*

The load-bearing idea is that acquisition is a LADDER, not a switch. A tool
moves candidate → tested → trusted, and each rung is earned by evidence that
is recorded. Nothing arrives trusted, and nothing becomes trusted because it
worked once in the moment somebody needed it to.

Two refusals are absolute and both are structural rather than advisory:

  * an install never runs on the host or on the control plane. If no
    disposable worker exists, acquisition FAILS — it does not fall back to
    "well, just this once".
  * a capability test is mandatory. A tool that installed cleanly has proven
    that it installs, which is not the same as proving it does the job.
"""

import hashlib
import json
import os
import re
import sys
import time

# A Windows console defaults to cp1252, which cannot encode the arrows in this
# module's own docstring — so `acquire.py --help` died before printing a word.
# Same guard chief.py, mission.py and ui.py already use.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):        # pragma: no cover
    pass

LEDGER = "acquisitions.json"

# The rungs. A tool is only as trusted as the evidence behind it.
STAGES = ("requested", "inspected", "installed", "tested", "trusted",
          "rejected", "removed")

# Package sources we will consider at all, and what each one costs to trust.
SOURCES = {
    "pypi": {"kind": "python package index", "pin": "version + hash"},
    "npm": {"kind": "node package registry", "pin": "version + integrity"},
    "apt": {"kind": "system package", "pin": "version"},
    "mcp": {"kind": "MCP server", "pin": "command + args"},
    "skill": {"kind": "an Agent Skill folder", "pin": "content hash"},
}

# Signals that a package is not what it appears to be. Deliberately blunt:
# this is a tripwire, not a malware scanner, and it says so.
RISK_SIGNALS = (
    (r"\bcurl\s+[^|]*\|\s*(ba)?sh", "pipes a download straight into a shell"),
    (r"\bwget\s+[^|]*\|\s*(ba)?sh", "pipes a download straight into a shell"),
    (r"setup\.py.*install_requires.*http", "installs from a raw URL"),
    # no \b around the keyword: the interesting names are API_KEY, AWS_SECRET,
    # GITHUB_TOKEN — where the preceding underscore is a word character, so a
    # word boundary would never match the thing we are looking for
    (r"os\.environ.{0,40}(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)",
     "reads credentials"),
    (r"(getenv|environ\.get)\s*\(\s*['\"][^'\"]*"
     r"(KEY|TOKEN|SECRET|PASSWORD)", "reads credentials"),
    (r"\bbase64\.b64decode\b.*\bexec\b", "executes decoded content"),
    (r"\beval\s*\(.*\brequests?\.get\b", "executes fetched content"),
    (r"\b(rm\s+-rf\s+/|del\s+/s\s+/q\s+c:)", "destructive filesystem command"),
    (r"\.ssh/|id_rsa|authorized_keys", "touches SSH material"),
    (r"/etc/(passwd|shadow)", "touches system credentials"),
)

# Typosquat bait: a name one edit away from something very common.
POPULAR = ("requests", "urllib3", "numpy", "pandas", "flask", "django",
           "pytest", "boto3", "pillow", "cryptography", "setuptools",
           "python-dateutil", "certifi", "click", "jinja2", "lxml")


class Refused(Exception):
    """Acquisition said no. The message is what the agent and owner see."""


def _path(root):
    return os.path.join(root, LEDGER)


def _safe_name(name):
    """A package name as a directory name, with no path meaning at all."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(name))[:64] or "unnamed"


def _import_name(name):
    """The module a distribution most likely provides. Distribution names and
    import names differ often enough that this is a guess -- so a failed
    import is reported as what it is (the probe could not import it) rather
    than as proof the package is broken."""
    return re.sub(r"[^A-Za-z0-9_]", "_", str(name)).strip("_") or "sys"


def _expert_cfg(root):
    """The expert's own [agent] settings, so the sandbox backend it declares
    is the one that governs its installs."""
    try:
        import tomllib
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig"))
    except Exception:
        return {}


def load(root):
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(root, rows):
    tmp = f"{_path(root)}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    os.replace(tmp, _path(root))
    return rows


def _edit_distance(a, b):
    if abs(len(a) - len(b)) > 2:
        return 9
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# --------------------------------------------------------------- 1. search

def _need_words(need):
    """The meaningful WORDS of a need, as whole tokens.

    Substring matching is what makes a search like this useless: the need
    "a thing" matched the capability recall_memory because its description
    contains "everything", so a request for an unrelated package was refused
    as already-satisfied. Match tokens, and only tokens long enough to mean
    something.
    """
    return {w for w in re.findall(r"[a-z0-9_]+", str(need or "").lower())
            if len(w) > 3}


def _matches(need_words, haystack):
    """True when a need word appears in the haystack AS A WORD."""
    if not need_words:
        return False
    hay = set(re.findall(r"[a-z0-9_]+", str(haystack or "").lower()))
    return bool(need_words & hay)


def search_known(root, need):
    """Step 2: look in what we already trust BEFORE reaching outside.

    The cheapest capability acquisition is the one you already made.
    """
    words = _need_words(need)
    hits = []
    for row in load(root):
        if row["stage"] != "trusted":
            continue
        hay = f"{row['name']} {row.get('provides','')} {row.get('why','')}"
        if _matches(words, hay):
            hits.append(row)
    # This read scan(root)["tools"], which has never been a key that scan()
    # returns — it returns binaries/modules/keys/custom/capabilities. Dead
    # code, and silently dead, because the whole branch sat inside a bare
    # `except Exception: pass`. The cost was not a crash but the opposite:
    # step 2 of the ladder ("look in what we already trust BEFORE reaching
    # outside") never looked at this machine's own capabilities, so the
    # cheapest possible acquisition — the one already made — was invisible.
    try:
        import toolbox
        for name, cap in (toolbox.scan(root).get("capabilities") or {}).items():
            if not cap.get("ready"):
                continue
            hay = f"{name} {cap.get('how', '')}"
            if _matches(words, hay):
                hits.append({"name": name, "stage": "trusted",
                             "source": "toolbox", "provides": cap.get("how", "")})
    except Exception:
        pass
    return hits


# -------------------------------------------------------------- 2. inspect

def inspect(name, source, version="", manifest_text="", requires_secrets=None):
    """Step 4: look before installing. Returns a risk report; RAISES only for
    the things no review should ever wave through."""
    if source not in SOURCES:
        raise Refused(f"unknown package source {source!r}; approved sources "
                      f"are: {', '.join(sorted(SOURCES))}")
    findings, blocking = [], []
    nm = str(name or "").strip().lower()
    if not nm or not re.fullmatch(r"[a-z0-9][a-z0-9._@/-]{0,80}", nm):
        raise Refused(f"refusing a package name that is not a plain "
                      f"identifier: {name!r}")
    if not version:
        blocking.append(
            "no version pinned. An unpinned dependency is a different "
            "dependency tomorrow, and the evidence recorded today would "
            "describe something that no longer exists.")
    for popular in POPULAR:
        if nm != popular and _edit_distance(nm, popular) == 1:
            blocking.append(
                f"{nm!r} is one character from {popular!r} — the classic "
                f"typosquat shape. If this is genuinely the package you want, "
                f"say so explicitly.")
    for pattern, why in RISK_SIGNALS:
        if re.search(pattern, manifest_text or "", re.I):
            findings.append(why)
    secrets = list(requires_secrets or [])
    if secrets:
        findings.append(f"asks for credentials: {', '.join(secrets)}")
    return {
        "name": nm, "source": source, "version": version,
        "findings": findings, "blocking": blocking,
        "requires_secrets": secrets,
        "verdict": "blocked" if blocking else ("review" if findings else "clean"),
    }


# -------------------------------------------------------------- 3. acquire

def request(root, name, source, need, version="", manifest_text="",
            requires_secrets=None, requested_by="practitioner"):
    """Steps 1–4: record the gap, check what we already have, inspect."""
    known = search_known(root, need)
    if known:
        raise Refused(
            f"we already have this capability: "
            + ", ".join(k["name"] for k in known[:3])
            + ". Use it rather than installing something new — an unnecessary "
              "dependency is permanent and a search is free.")
    report = inspect(name, source, version, manifest_text, requires_secrets)
    rows = load(root)
    rec = {
        "id": f"acq-{hashlib.sha256((name + source + version).encode()).hexdigest()[:8]}",
        "name": report["name"], "source": source, "version": version,
        "need": str(need)[:300], "provides": "", "why": str(need)[:200],
        "stage": "rejected" if report["verdict"] == "blocked" else "inspected",
        "inspection": report, "requested_by": requested_by,
        "worker": None, "install_evidence": None, "test_evidence": None,
        "content_hash": None, "permissions": [],
        "history": [{"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "stage": "requested", "why": str(need)[:200]}],
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    rows = [r for r in rows if r["id"] != rec["id"]] + [rec]
    _save(root, rows)
    if report["verdict"] == "blocked":
        raise Refused("inspection blocked this acquisition: "
                      + " ".join(report["blocking"]))
    return rec


def install(root, home, acq_id, worker_id=None, task_text=""):
    """Step 5: install ONLY in an isolated disposable worker.

    There is no host fallback. If there is no disposable computer, this
    fails — because "just this once, on the host" is how a governed pipeline
    stops being one.
    """
    # The ORGANIZATION's answer comes first, before the worker is chosen and
    # before anything is fetched. org.json has carried
    # `agents_may_install: false` since the first workspace was created, it is
    # returned by org.summary() and rendered in the panel, and until now
    # nothing read it. An owner who saw that flag and left it alone believed
    # agents could not install software; once install() became a real pip
    # install, that belief was both load-bearing and false.
    #
    # The default applies only when there is NO organization, and it is True:
    # "nobody has formed a workspace here" is not the same statement as "the
    # workspace forbids this". Defaulting it to False looked prudent and was
    # simply wrong — it made acquisition impossible for every standalone
    # fleet, which is most of them, by reading an absent file as a refusal.
    #
    # Nothing is lost by that, because this flag is not what makes installing
    # safe: the install runs pip inside a disposable sandbox and never on the
    # host, the manifest is inspected first, a capability test must pass, and
    # only the owner grants the last rung. This flag is the ORGANIZATION's
    # separate veto, and an organization that exists starts with it False.
    try:
        import org
        may_install = org.policy_flag(root, "agents_may_install", True)
    except Exception:
        may_install = True
    if not may_install:
        raise Refused(
            "this organization does not permit agents to install software "
            "(org policy agents_may_install = false). An owner can change it "
            "with `python org.py policy --set agents_may_install=true "
            "--as <owner-email>`; it is false by default because installing "
            "a package is the one acquisition step that runs somebody else's "
            "code.")

    rows = load(root)
    rec = next((r for r in rows if r["id"] == acq_id), None)
    if rec is None:
        raise KeyError(acq_id)
    if rec["stage"] not in ("inspected", "installed"):
        raise Refused(f"{acq_id} is at stage {rec['stage']}; only an inspected "
                      f"acquisition may be installed")
    import workers
    w = workers.get(home, worker_id) if worker_id else None
    if w is None:
        w, _why = workers.choose(home, task_text or "install a package")
    if w is None:
        raise Refused(
            "no computer is available to install into. Acquisition needs a "
            "DISPOSABLE worker; add one under Resources -> Computers "
            "(Local Docker is the usual answer).")
    if w["zone"] != "isolated":
        raise Refused(
            f"refusing to install on {w['name']} ({w['zone']} zone). A new "
            f"dependency is untrusted code by definition, so it goes in a "
            f"disposable computer — never on the host and never on an "
            f"organization machine.")
    # THE LADDER NOW ACTUALLY CLIMBS.
    #
    # Until this, install() selected a worker, wrote
    #     "command": "(install <name>==<ver> in <worker>)"
    # — a sentence in parentheses describing a thing that had not happened —
    # and set stage="installed". There was no subprocess, no sandbox.run and
    # no execution.run anywhere in this module. An acquisition could reach
    # "trusted", with a full evidence trail, while nothing was ever fetched,
    # unpacked or run. Every refusal above it was real; the two steps those
    # refusals guarded were not.
    #
    # Where it installs matters as much as that it installs. --target keeps
    # the package inside the EXPERT'S OWN directory, so it is: visible to the
    # File Authority, carried by backup.py, destroyed with the expert, and
    # incapable of altering the interpreter the platform itself runs on. A
    # dependency that can rewrite the harness is not a dependency, it is a
    # new owner.
    target = os.path.join(root, "capabilities", _safe_name(rec["name"]))
    os.makedirs(target, exist_ok=True)
    # A LOCAL path is the safest install there is: nothing is resolved from a
    # registry, so the name cannot be typosquatted and the bytes cannot change
    # between the inspection and the install. It is also what makes this step
    # testable without reaching the network at all.
    local = rec.get("local_path")
    if local:
        spec = local if os.path.isabs(local) else os.path.join(root, local)
        if not os.path.exists(spec):
            raise Refused(f"local_path {spec!r} does not exist")
    else:
        spec = rec["name"] if not rec.get("version") else \
            f"{rec['name']}=={rec['version']}"
    # RELATIVE paths, because the command runs with the expert root mounted
    # somewhere else. sandbox.run bind-mounts root at /work and runs with
    # cwd=/work, so an absolute host path inside this argv would simply not
    # exist in the container — pip would report "file not found" and the
    # acquisition would be rejected for a reason that has nothing to do with
    # the package. The cwd is the expert root in every backend, so relative
    # paths are the ones that mean the same thing everywhere.
    rel_target = os.path.relpath(target, root).replace(os.sep, "/")
    rel_spec = spec
    if local:
        try:
            rel_spec = "./" + os.path.relpath(spec, root).replace(os.sep, "/")
        except ValueError:                   # a different drive on Windows
            raise Refused(
                f"local_path {spec!r} is outside the expert root, so it is "
                f"not visible inside the sandbox. Copy it under the expert "
                f"first.")
    argv = ["python", "-m", "pip", "install", "--no-input",
            "--disable-pip-version-check", "--no-warn-script-location",
            "--target", rel_target, rel_spec]
    if rec.get("index_url"):
        argv += ["--index-url", str(rec["index_url"])]

    # WHERE pip RUNS, not just where its files land.
    #
    # The first version of this ran execution.run("converter", ...), which is
    # the platform's own argv path and is NOT sandboxed. That satisfied
    # "--target keeps the package out of the host interpreter" and violated
    # the rule at the top of this module — "an install never runs on the host
    # or on the control plane" — because pip ITSELF then executed on the
    # host, and a package's build backend runs arbitrary code at install
    # time. Making a fake control real is worth nothing if it breaks a real
    # one on the way; before that change nothing ran at all, so the rule was
    # at least vacuously true.
    #
    # sandbox.py is the thing that actually isolates, and it already FAILS
    # CLOSED: a backend that is configured but unavailable returns 127 and
    # says what is missing rather than quietly running on the host. The
    # worker registry says WHICH computer; the sandbox backend is what makes
    # that mean anything.
    import sandbox
    cfg = _expert_cfg(root)
    backend = sandbox.backend_name(cfg)
    if backend == "host":
        raise Refused(
            "refusing to install: [agent] sandbox = \"host\", so there is no "
            "isolated place to run pip. A new dependency is untrusted code by "
            "definition and its build backend executes at install time, so it "
            "does not run on this machine. Set [agent] sandbox = \"docker\" "
            "(or e2b/daytona) and try again — this is the one rule this "
            "module will not bend.")
    avail, why = sandbox.available(cfg)
    if not avail:
        raise Refused(
            f"refusing to install: the {backend!r} sandbox is configured but "
            f"unavailable ({why}). Acquisition does NOT fall back to the "
            f"host.")
    # EGRESS, deliberately, and only here.
    #
    # The docker sandbox runs --network none by default, which is right for
    # model-written commands and wrong for this one: pip cannot fetch a
    # package, or even its build backend, without a network. Discovered by
    # running it — the first isolated install died on
    # "pip subprocess to install build dependencies did not run successfully
    #  ... connection broken", which is the sandbox working exactly as
    # designed and the acquisition being impossible inside it.
    #
    # So the install container gets egress while the command containers do
    # not. The trade is explicit: the container is disposable, its filesystem
    # is the expert root and nothing else, and sandbox.run has already
    # SCRUBBED every credential-shaped variable out of its environment — so
    # what egress buys an attacker here is the ability to download the
    # package we asked for. That is the job.
    install_cfg = {**cfg, "agent": {**(cfg.get("agent") or {}),
                                    "sandbox_network": True}}
    cmd = " ".join(f'"{a}"' if (" " in str(a) or "\\" in str(a)) else str(a)
                   for a in argv)
    rc, out, err = sandbox.run(cmd, root, dict(os.environ), 900, install_cfg)
    ok = (rc == 0)
    rec["worker"] = w["id"]
    rec["install_path"] = os.path.relpath(target, root).replace(os.sep, "/")
    rec["stage"] = "installed" if ok else "rejected"
    rec["install_evidence"] = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "worker": w["id"],
        "zone": w["zone"],
        "command": " ".join(argv[:4] + ["--target", rec["install_path"], spec]),
        "exit_code": rc,
        "output": ((out or "") + (err or "")).strip()[-1200:],
        "installed_names": sorted(os.listdir(target))[:40] if ok else [],
    }
    if not ok:
        rec["history"].append({
            "at": rec["install_evidence"]["at"], "stage": "rejected",
            "why": f"install exited {rc}: "
                   f"{((err or out or '').strip() or 'no output')[:160]}"})
        _save(root, rows)
        raise Refused(
            f"install FAILED (exit {rc}) and the acquisition is rejected, not "
            f"pending: {((err or out or '').strip() or 'no output')[:300]}")
    rec["history"].append({"at": rec["install_evidence"]["at"],
                           "stage": "installed", "why": f"in {w['name']}"})
    _save(root, rows)
    return rec


def capability_test(root, acq_id, passed=None, evidence="", command="",
                    probe=None):
    """Step 6: MANDATORY, and now actually a test.

    `passed` and `evidence` used to be SUPPLIED BY THE CALLER. The step the
    module calls mandatory recorded whatever verdict it was handed — a claim
    wearing the word "test", in the one place this platform swears never to
    accept one. "A tool that installed has proven it installs" was true only
    because nothing checked.

    Now the default path RUNS the thing: import the installed distribution
    from where it was installed, in a subprocess whose sys.path is exactly
    that directory, and observe the exit code. The caller may pass its own
    `probe` argv for a tool that is not importable — a binary, say — but it
    cannot pass a verdict. `passed` survives only for the explicit
    owner-override path, and when it is used the evidence records that a
    human asserted it rather than that anything was observed.
    """
    rows = load(root)
    rec = next((r for r in rows if r["id"] == acq_id), None)
    if rec is None:
        raise KeyError(acq_id)
    if rec["stage"] != "installed":
        raise Refused(f"{acq_id} is at stage {rec['stage']}; a capability test "
                      f"runs against an installed tool")

    if passed is None:
        target = os.path.join(root, rec.get("install_path")
                              or os.path.join("capabilities",
                                              _safe_name(rec["name"])))
        if not os.path.isdir(target):
            raise Refused(
                f"nothing is installed at {target!r}, so there is nothing to "
                f"test. An acquisition cannot pass a capability test by "
                f"having its paperwork in order.")
        # The probe IMPORTS code that was installed seconds ago from outside
        # this project. That is untrusted execution by definition, so it runs
        # through `capability_probe` — the operation declared model-authored,
        # policy-screened and SANDBOXED — and not through the platform's own
        # argv path, which is not sandboxed. Testing a new dependency by
        # running it unconfined would defeat the entire point of installing it
        # into an isolated directory in the first place.
        #
        # The probe is written to a FILE rather than passed with -c because
        # the operation takes a shell string, and a program embedded in a
        # shell string is a quoting bug waiting for a package name with an
        # apostrophe in it.
        # The probe must NOT live in capabilities/. Python puts a script's own
        # directory on sys.path[0], so a probe stored there makes every
        # sibling folder an implicit NAMESPACE PACKAGE — and an empty
        # capabilities/<name>/ directory then imports successfully. Measured:
        # a package that was never installed reported "imported notinstalled"
        # and the ladder marked it TESTED. That is the precise false pass this
        # step exists to prevent, manufactured by the step itself.
        probe_dir = os.path.join(root, "tmp")
        os.makedirs(probe_dir, exist_ok=True)
        probe_py = os.path.join(probe_dir, f"probe-{_safe_name(rec['name'])}.py")
        with open(probe_py, "w", encoding="utf-8") as f:
            f.write(
                "import os, sys\n"
                # REPLACE sys.path, never insert: a package that happens to
                # exist in the host interpreter must not make a failed install
                # look successful. The stdlib paths Python needs are already
                # bound before this line runs.
                f"sys.path = [{target!r}] + [p for p in sys.path\n"
                "             if p and 'site-packages' not in p "
                "and p != os.path.dirname(os.path.abspath(__file__))]\n"
                f"import {_import_name(rec['name'])} as m\n"
                # a namespace package has __file__ = None. Requiring a real
                # file inside the target is what tells an INSTALLED package
                # apart from an empty directory that merely shares its name.
                "f = getattr(m, '__file__', None)\n"
                "if not f:\n"
                "    raise SystemExit('NOT INSTALLED: %r resolved to a "
                "namespace package with no file — an empty directory, not a "
                "package' % m.__name__)\n"
                f"if not os.path.abspath(f).startswith(os.path.abspath({target!r})):\n"
                "    raise SystemExit('WRONG COPY: imported from %s, not from "
                "the isolated install' % f)\n"
                "print('imported', m.__name__, getattr(m, '__version__', ''),\n"
                "      'from', f)\n")
        import execution
        if probe:
            cmd = " ".join(f'"{a}"' if " " in str(a) else str(a) for a in probe)
        else:
            cmd = f'"{sys.executable}" "{probe_py}"'
        argv = probe or [sys.executable, probe_py]
        rc, out, err = execution.run("capability_probe", cmd, root,
                                     timeout=180,
                                     reason=f"capability test {rec['name']}")
        passed = (rc == 0)
        evidence = (f"exit {rc}: " + ((out or "") + (err or "")).strip()[-400:]) \
            or f"exit {rc} with no output"
        command = " ".join(str(a) for a in argv)[:300]
    else:
        # Check what the CALLER supplied, before decorating it. Prefixing
        # first made the emptiness check unreachable — "   " became
        # "OWNER-ASSERTED (nothing was observed):    ", which is not empty,
        # so a pass with no evidence would have been accepted. The refusal
        # was still in the file and could no longer fire.
        if not str(evidence).strip():
            raise Refused("a capability test records what it OBSERVED; a pass "
                          "with no evidence is a claim")
        evidence = f"OWNER-ASSERTED (nothing was observed): {evidence}"

    if not str(evidence).strip():
        raise Refused("a capability test records what it OBSERVED; a pass "
                      "with no evidence is a claim")
    rec["test_evidence"] = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "passed": bool(passed),
        "evidence": str(evidence)[:500], "command": str(command)[:300]}
    rec["stage"] = "tested" if passed else "rejected"
    rec["history"].append({"at": rec["test_evidence"]["at"],
                           "stage": rec["stage"],
                           "why": str(evidence)[:200]})
    _save(root, rows)
    return rec


def promote(root, acq_id, by="owner", permissions=None, provides=""):
    """Step 8: the OWNER grants trust. Never the agent, never the outcome."""
    rows = load(root)
    rec = next((r for r in rows if r["id"] == acq_id), None)
    if rec is None:
        raise KeyError(acq_id)
    if rec["stage"] != "tested":
        raise Refused(
            f"{acq_id} is at stage {rec['stage']}. Trust is granted to a tool "
            f"that passed a capability test — not to one that merely "
            f"installed, and never to one that was only requested.")
    if not (rec.get("test_evidence") or {}).get("passed"):
        raise Refused("this acquisition's capability test did not pass")
    rec["stage"] = "trusted"
    rec["permissions"] = sorted(set(permissions or []))
    rec["provides"] = provides or rec.get("need", "")[:200]
    rec["promoted_by"] = by
    rec["history"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "stage": "trusted", "why": f"promoted by {by}"})
    _save(root, rows)
    return rec


def remove(root, acq_id, why="", by="owner"):
    """Rollback is mandatory in the validation gate, so it is a first-class
    operation rather than an afterthought."""
    rows = load(root)
    rec = next((r for r in rows if r["id"] == acq_id), None)
    if rec is None:
        raise KeyError(acq_id)
    rec["stage"] = "removed"
    rec["history"].append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "stage": "removed", "why": f"{by}: {why}"[:200]})
    _save(root, rows)
    return rec


def trusted(root):
    return [r for r in load(root) if r["stage"] == "trusted"]


def summary(root):
    rows = load(root)
    by_stage = {}
    for r in rows:
        by_stage.setdefault(r["stage"], []).append(r["name"])
    return {"total": len(rows), "by_stage": by_stage,
            "trusted": [r["name"] for r in rows if r["stage"] == "trusted"]}


def main():
    try:
        _main()
    except Refused as e:
        # every rung refuses with a sentence, never a traceback: the
        # operator reading this is the person who has to act on it
        print(f"REFUSED: {e}")
        raise SystemExit(1)


def _main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("request")
    p.add_argument("name"); p.add_argument("--source", required=True,
                                           choices=sorted(SOURCES))
    p.add_argument("--version", default=""); p.add_argument("--need", required=True)
    p.add_argument("--root", default=".")
    p = sub.add_parser("list"); p.add_argument("--root", default=".")
    p = sub.add_parser("promote"); p.add_argument("id")
    p.add_argument("--root", default="."); p.add_argument("--can", action="append",
                                                          default=[])
    p = sub.add_parser("remove"); p.add_argument("id")
    p.add_argument("--why", default=""); p.add_argument("--root", default=".")
    p = sub.add_parser("stages")
    # The ladder's remaining rungs, reachable from a terminal. The library had
    # them; the CLI did not, so the manual promised commands that did not
    # exist — an operator following the documented recovery path would have
    # found nothing there.
    p = sub.add_parser("search"); p.add_argument("need")
    p.add_argument("--root", default=".")
    p = sub.add_parser("inspect"); p.add_argument("name")
    p.add_argument("--source", required=True); p.add_argument("--version", default="")
    p = sub.add_parser("install"); p.add_argument("id")
    p.add_argument("--root", default="."); p.add_argument("--home", default=".")
    p.add_argument("--worker", default=None); p.add_argument("--for", dest="task",
                                                             default="")
    # By DEFAULT this runs the probe. It used to pass `not a.failed`, which is
    # a bool on every path, and capability_test only runs the real probe when
    # `passed is None` — so the CLI, the door a human or a script actually
    # uses, took the owner-override branch every single time and recorded a
    # PASS for a tool nothing had executed. The library was fixed (U25) and
    # its only entry point kept the old hole; a control is worth what its
    # entry points enforce, not what its internals do.
    p = sub.add_parser("test"); p.add_argument("id")
    p.add_argument("--root", default=".")
    p.add_argument("--evidence", default="",
                   help="required only with --owner-asserts-pass; otherwise "
                        "the probe's own output IS the evidence")
    p.add_argument("--command", default="")
    p.add_argument("--failed", action="store_true",
                   help="record that the capability test did NOT pass")
    p.add_argument("--owner-asserts-pass", action="store_true",
                   dest="owner_asserts_pass",
                   help="record a PASS on the owner's word WITHOUT running "
                        "the probe — for a capability no probe can reach. "
                        "Requires --evidence, and the record says a human "
                        "asserted it rather than that anything was observed")
    a = ap.parse_args()
    if a.cmd == "search":
        rows = search_known(os.path.abspath(a.root), a.need)
        if not rows:
            print(f"nothing known provides {a.need!r}. That is an answer, not "
                  f"an error: acquire it deliberately with `request`.")
            return
        for r in rows:
            print(f"{r['name']:<24} {r.get('source', ''):<12} {r.get('why', '')}")
        return
    if a.cmd == "inspect":
        v = inspect(a.name, a.source, a.version)
        print(f"{a.name}: {v['verdict']}")
        for f in v["blocking"]:
            print(f"  BLOCKING: {f}")
        for f in v["findings"]:
            print(f"  review: {f}")
        if v["requires_secrets"]:
            print(f"  asks for: {', '.join(v['requires_secrets'])}")
        # the verdicts are clean / review / blocked; a blocked one must not
        # report success to a script that only reads the exit code
        raise SystemExit(1 if v["verdict"] == "blocked" else 0)
    if a.cmd == "install":
        rec = install(os.path.abspath(a.root), os.path.abspath(a.home),
                      a.id, a.worker, a.task)
        ev = rec.get("install_evidence", {})
        print(f"{rec['name']}: {rec['stage']} on {ev.get('worker', '?')} "
              f"({ev.get('zone', '?')} zone)")
        print("  a capability test must still pass before this is usable")
        return
    if a.cmd == "test":
        if a.failed and a.owner_asserts_pass:
            print("--failed and --owner-asserts-pass contradict each other")
            raise SystemExit(2)
        if a.owner_asserts_pass and not a.evidence.strip():
            print("--owner-asserts-pass records a verdict nothing observed, "
                  "so it requires --evidence saying what you checked")
            raise SystemExit(2)
        # None => RUN the probe. False => the owner asserts it failed (safe:
        # it can only ever block a promotion). True => the owner asserts a
        # pass, which is the only branch that takes a verdict on trust and is
        # now the only one you have to ask for by name.
        verdict = None
        if a.failed:
            verdict = False
        elif a.owner_asserts_pass:
            verdict = True
        rec = capability_test(os.path.abspath(a.root), a.id, verdict,
                              a.evidence, a.command)
        print(f"{rec['name']}: {rec['stage']}")
        if rec["stage"] != "tested":
            raise SystemExit(1)
        how = ("on your assertion, unverified" if a.owner_asserts_pass
               else "by running it")
        print(f"  a tool that installed has proven it installs; this proves "
              f"it does the job — {how}")
        return
    if a.cmd == "stages":
        print("requested -> inspected -> installed -> tested -> trusted")
        print("  each rung is earned by recorded evidence; nothing arrives "
              "trusted, and only the owner grants the last one")
        return
    root = os.path.abspath(a.root)
    if a.cmd == "request":
        rec = request(root, a.name, a.source, a.need, a.version)
        print(f"{rec['id']}: {rec['stage']} ({rec['inspection']['verdict']})")
        for f in rec["inspection"]["findings"]:
            print(f"  review: {f}")
        return
    if a.cmd == "promote":
        rec = promote(root, a.id, permissions=a.can)
        print(f"{rec['name']} is now trusted (permissions: "
              f"{', '.join(rec['permissions']) or 'none declared'})")
        return
    if a.cmd == "remove":
        print("removed", remove(root, a.id, a.why)["name"])
        return
    s = summary(root)
    print(f"{s['total']} acquisition(s)")
    for stage, names in sorted(s["by_stage"].items()):
        print(f"  {stage:<12} {', '.join(names)}")


if __name__ == "__main__":
    main()
