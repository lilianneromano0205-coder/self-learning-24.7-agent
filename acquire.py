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
import shutil
import sys
import time
import stat
import tempfile
import shlex

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
    value = re.sub(r"[^A-Za-z0-9._-]", "_", str(name))[:64]
    if value in ('', '.', '..'):
        raise Refused('package name has no safe directory identity')
    return value


def _contained(base, target):
    """Validate lexical and resolved containment including Windows junctions."""
    base = os.path.abspath(base)
    target = os.path.abspath(target)
    if os.path.commonpath([base, target]) != base or target == base:
        raise Refused('install path escapes its capability/arena directory')
    current = target
    while current != base:
        if os.path.lexists(current):
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
                raise Refused('links and junctions are forbidden in acquisition paths')
        current = os.path.dirname(current)
    # THE BASE MUST NOT BE A REDIRECTION — but "not canonically spelled" is
    # not a redirection. This used to demand `realpath(base) == base`, which
    # refuses any root whose path contains a WINDOWS 8.3 SHORT NAME: realpath
    # expands `RUNNER~1` to `runneradmin`, the strings differ, and a perfectly
    # contained arena was reported as escaping its authority root. Every
    # GitHub Windows runner has such a TEMP, and so does any profile name
    # longer than eight characters (`Administrator` -> `ADMINI~1`), so
    # acquisition could not run there at all. The repository has met this
    # class before — a tilde mid-path is not a metacharacter, it is every
    # Windows short name.
    #
    # What actually matters is asked directly: base itself must not be a link
    # or junction, and the RESOLVED target must sit under the RESOLVED base.
    # Intermediate components are already walked above.
    if os.path.lexists(base):
        info = os.lstat(base)
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024:
            raise Refused('the acquisition authority root is itself a link')
    real_base, real_target = os.path.realpath(base), os.path.realpath(target)
    if os.path.commonpath([real_base, real_target]) != real_base or real_target == real_base:
        raise Refused('resolved acquisition path escapes its authority root')
    return target


def validate_output(path, max_files=50000, max_bytes=512 * 1024 * 1024):
    """Bounded regular-file tree only; reject links, devices, sockets, aliases."""
    digest = hashlib.sha256()
    count = total = 0
    if not os.path.isdir(path):
        raise Refused('installer produced no output directory')
    for parent, dirs, files in os.walk(path, followlinks=False):
        for name in sorted(dirs + files):
            full = os.path.join(parent, name)
            info = os.lstat(full)
            if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 1024
                    or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise Refused('installer output contains a link or special file')
            if stat.S_ISREG(info.st_mode):
                count += 1; total += info.st_size
                if count > max_files or total > max_bytes:
                    raise Refused('installer output exceeds file/byte limits')
                rel = os.path.relpath(full, path).replace(os.sep, '/')
                digest.update(rel.encode('utf-8') + b'\0')
                with open(full, 'rb') as f:
                    for block in iter(lambda: f.read(1024 * 1024), b''):
                        digest.update(block)
                digest.update(b'\0')
    if not count:
        raise Refused('installer output is empty')
    return digest.hexdigest()


def _remove_tree(base, target):
    target = _contained(base, target)
    if os.path.lexists(target):
        validate_output(target) if os.listdir(target) else None
        shutil.rmtree(target)
    if os.path.lexists(target):
        raise Refused('installed bytes remain after removal')


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
    # The source has to be one this module can actually ACQUIRE. It used to be
    # a free-text field: `request(root, "express", "npm", ...)` was accepted,
    # and install() — which never reads rec["source"] at all — ran
    # `pip install express`, fetching an unrelated PyPI distribution that
    # happens to share the name. That is dependency confusion manufactured by
    # the platform itself, out of a branch nobody wrote.
    src = str(source or "").strip().lower()
    if src not in SOURCES:
        raise Refused(
            f"{source!r} is not a source this platform can acquire from. "
            f"Known: {', '.join(sorted(SOURCES))}. Guessing would mean "
            f"resolving the name somewhere it does not live.")
    source = src
    # REFUSING an install takes TWO shared words; listing a hit takes one.
    # _need_words already fixed the substring version of this failure ("a
    # thing" matching "everything"); the token version was one level up: the
    # need "an always-sorted container" was refused because the single word
    # "always" appears in web_fetch's help text. One common English token in
    # common is a coincidence; two distinct meaningful words is a claim.
    # search_known itself is unchanged — its single-word hits still surface
    # as notes for humans, where a false positive costs a glance, not a
    # blocked acquisition.
    nw = _need_words(need)
    strong = []
    for k in search_known(root, need):
        hay = set(re.findall(r"[a-z0-9_]+",
                             f"{k.get('name', '')} {k.get('provides', '')} "
                             f"{k.get('why', '')}".lower()))
        if len(nw & hay) >= 2:
            strong.append(k)
    if strong:
        raise Refused(
            f"we already have this capability: "
            + ", ".join(k["name"] for k in strong[:3])
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
    import sandbox
    cfg = _expert_cfg(root)
    backend = sandbox.backend_name(cfg)
    if backend != "docker":
        raise Refused(f"acquisition requires Docker workspace isolation; {backend!r} is not supported")
    avail, why = sandbox.available(cfg)
    if not avail:
        raise Refused(f"isolated acquisition unavailable: {why}; no host fallback")
    src = str(rec.get("source") or "pypi").lower()
    if src not in ("pypi", "npm"):
        routes = {'mcp': 'TRUST DECISION: use the owner-managed MCP catalog',
                  'skill': 'skills are IMPORTED using the skill registry',
                  'apt': 'apt acquisition is not implemented'}
        raise Refused(routes.get(src, f'{src!r} acquisition is not implemented'))
    os.makedirs(os.path.join(root, "tmp"), exist_ok=True)
    arena = tempfile.mkdtemp(prefix="acquire-arena-", dir=os.path.join(root, "tmp"))
    _contained(root, arena)
    stage = os.path.join(arena, "output")
    os.makedirs(stage)
    os.makedirs(os.path.join(arena, "input"))
    local = rec.get("local_path")
    try:
        if local:
            source = _contained(root, local if os.path.isabs(local) else os.path.join(root, local))
            validate_output(source)
            shutil.copytree(source, os.path.join(arena, "input", "package"))
            package_spec = "./input/package"
        elif src == "pypi":
            package_spec = f"{rec['name']}=={rec['version']}"
        else:
            package_spec = f"{rec['name']}@{rec['version']}"
        if src == "pypi":
            argv = ["python", "-m", "pip", "install", "--no-input",
                    "--disable-pip-version-check", "--no-warn-script-location",
                    "--target", "output", package_spec]
            if rec.get("index_url"):
                argv += ["--index-url", str(rec["index_url"])]
        else:
            argv = ["npm", "install", "--prefix", "output", "--no-fund", "--no-audit", package_spec]
        # Only this disposable minimal filesystem is network-enabled. No
        # expert data, fleet authority, ambient credentials or extra mounts.
        install_cfg = {"agent": {"sandbox": "docker", "sandbox_network": True,
                                 "sandbox_image": cfg.get("agent", {}).get("sandbox_image") or sandbox.DOCKER_IMAGE}}
        rc, out, err = sandbox.run(shlex.join(argv), arena, {}, 900, install_cfg)
        if rc:
            raise Refused(f"install FAILED (exit {rc}): {str(err or out)[-300:]}")
        content_hash = validate_output(stage)
        rec["worker"] = w["id"]
        rec["arena_path"] = os.path.relpath(arena, root).replace(os.sep, "/")
        rec["install_path"] = os.path.relpath(stage, root).replace(os.sep, "/")
        rec["content_hash"] = content_hash
        rec["stage"] = "installed"
        rec["install_evidence"] = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "worker": w["id"],
            "zone": w["zone"], "command": shlex.join(argv), "exit_code": rc,
            "output": str(out + err)[-1200:], "content_hash": content_hash,
            "workspace_exposed": False, "installed_names": sorted(os.listdir(stage))[:40]}
        rec["history"].append({"at": rec["install_evidence"]["at"], "stage": "installed",
                               "why": "minimal arena; bytes not promoted before capability test"})
        _save(root, rows)
        return rec
    except Exception as e:
        # The trusted host validates containment before any recursive cleanup.
        _contained(root, arena)
        shutil.rmtree(arena)
        rec["stage"] = "rejected"
        rec["install_evidence"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "exit_code": 1,
                                   "output": str(e)[:500], "workspace_exposed": False}
        _save(root, rows)
        if isinstance(e, Refused):
            raise
        raise Refused(f"acquisition failed validation: {e}") from e


def capability_test(root, acq_id, passed=None, evidence="", command="",
                    probe=None, module=""):
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

    if passed is True:
        raise Refused("a real sealed capability probe is mandatory; an owner assertion cannot replace execution")
    if passed is None:
        if not rec.get("arena_path"):
            raise Refused("nothing is installed in a validated acquisition arena; reinstall before testing")
        arena = _contained(os.path.join(root, "tmp"), os.path.join(root, rec["arena_path"]))
        target = _contained(arena, os.path.join(root, rec["install_path"]))
        before = validate_output(target)
        if before != rec.get("content_hash"):
            raise Refused("TAMPER: installed output differs from recorded hash")
        cfg = _expert_cfg(root)
        import sandbox
        if sandbox.backend_name(cfg) != "docker":
            raise Refused("capability probes require Docker isolation; no host import")
        # Move within the arena to the ordinary read-only CONTROL directory.
        readonly_target = os.path.join(arena, "capabilities", "package")
        os.makedirs(os.path.dirname(readonly_target), exist_ok=True)
        if target != readonly_target:
            os.replace(target, readonly_target)
        rec["install_path"] = os.path.relpath(readonly_target, root).replace(os.sep, "/")
        _save(root, rows)  # interrupted probes retain their actual staging path
        os.makedirs(os.path.join(arena, "prompts"), exist_ok=True)
        probe_py = os.path.join(arena, "prompts", "capability-probe.py")
        # A CALLER THAT KNOWS THE IMPORT NAME MAY SAY SO. _import_name only
        # transliterates the DISTRIBUTION name, so `ulid-py` became `ulid_py`
        # while the module it actually installs is `ulid` — the arena probe
        # then failed to import a package that was installed perfectly well,
        # and the capability was rejected for the guess rather than for the
        # bytes. The frontier seals the real module name in its row; anything
        # else keeps the guess.
        module = str(module or "").strip() or _import_name(rec["name"])
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*",
                            module):
            raise Refused(f"{module!r} is not a python module name")
        source = (
            "import os,sys,importlib\n"
            "target='/work/capabilities/package'\n"
            "sys.path=[target]+[p for p in sys.path if p and 'site-packages' not in p and p != '/work/prompts']\n"
            f"m=importlib.import_module({module!r})\n"
            "f=getattr(m,'__file__',None)\n"
            "if not f or os.path.commonpath([target,os.path.realpath(f)]) != target: raise SystemExit('NOT INSTALLED: wrong or empty package')\n"
            "print('imported',m.__name__,'from',f)\n")
        Path = __import__('pathlib').Path
        Path(probe_py).write_text(source, encoding="utf-8")
        if probe:
            import controlplane
            controlplane.owner_only("provide acquisition probe")
            argv = list(probe)
        elif rec.get("source") == "npm":
            argv = ["node", "-e", f"console.log(require.resolve({('./capabilities/package/node_modules/' + rec['name'])!r}))"]
        else:
            argv = ["python", "prompts/capability-probe.py"]
        probe_hash = hashlib.sha256(json.dumps([argv,source], sort_keys=True).encode()).hexdigest()
        probe_cfg = {"agent": {"sandbox":"docker", "sandbox_network":False,
                               "sandbox_image":cfg.get("agent",{}).get("sandbox_image") or sandbox.DOCKER_IMAGE}}
        import execution
        rc, out, err = execution.run("capability_probe", shlex.join(argv), arena,
                                     cfg=probe_cfg, timeout=180,
                                     reason=f"sealed capability test {rec['name']}")
        passed = rc == 0 and validate_output(readonly_target) == before
        evidence = f"exit {rc}: " + str(out + err)[-400:]
        command = shlex.join(argv)
        rec["probe_hash"] = probe_hash
        if passed:
            final = _contained(os.path.join(root, "capabilities"),
                               os.path.join(root, "capabilities", _safe_name(rec["name"])))
            os.makedirs(os.path.dirname(final), exist_ok=True)
            # First promotion is an atomic rename. Replacing an active install
            # needs explicit removal; never expose half a previous/new tree.
            if os.path.lexists(final):
                raise Refused("capability already exists; remove it explicitly before replacement")
            os.replace(readonly_target, final)
            rec["install_path"] = os.path.relpath(final, root).replace(os.sep, "/")
            rec.pop("arena_path", None)
            _contained(root, arena)
            shutil.rmtree(arena)
    else:
        evidence = "OWNER-REPORTED FAILURE: " + str(evidence)

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
    install_path = rec.get('install_path')
    if install_path:
        target = os.path.join(root, install_path)
        if rec.get('arena_path'):
            arena = _contained(os.path.join(root, 'tmp'), os.path.join(root, rec['arena_path']))
            _contained(arena, target)
            _remove_tree(os.path.join(root, 'tmp'), arena)
        else:
            _remove_tree(os.path.join(root, 'capabilities'), target)
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
        # OWNER ACTION. `promote` writes acquisitions.json, the ledger that
        # grants a tool the fleet's trust — "the OWNER grants trust. Never
        # the agent, never the outcome", as promote()'s own docstring puts
        # it — so it may not run from inside an agent task. The seal around
        # every model-authored command would revert the write anyway; this
        # refuses FIRST, with a sentence, instead of letting the work happen
        # model-authored command would revert the write anyway; this refuses
        # first, with a sentence, instead of letting the work happen and
        # then undoing it. (controlplane.py explains why the two controls
        # are independent and neither relies on the other.)
        import controlplane
        controlplane.owner_only(
            f"granting acquisition {a.id!r} the fleet's trust")
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
