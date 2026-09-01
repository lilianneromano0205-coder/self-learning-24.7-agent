#!/usr/bin/env python3
"""THE CAPABILITY FRONTIER — how this fleet obtains a tool nobody anticipated.

THE DEFECT THIS FIXES, MEASURED BEFORE IT WAS WRITTEN

Everything the platform could ever do was trapped inside two hand-written
tables: `universal.CAPABILITY_HINTS` (~10 regex entries) decided what a goal
was understood to NEED, and `toolbox.ACQUIRE` (11 entries) decided what could
be OBTAINED. Run against five ordinary goals, the result was not "we are
missing a tool" — it was worse:

    explore my SaaS and produce a narrated screen recording  -> NOTHING
    generate a SPOKEN audio summary                          -> ['transcribe']
    render a 3D CAD model and export STEP                    -> NOTHING
    watch the camera feed and alert on anomalies             -> NOTHING
    SIGN the release binaries with our certificate           -> ['browser_control']

Three failures, each a different kind of lie. A goal outside the table asked
for NOTHING, so `universal.ready()` reported READY and the run failed several
milestones deep — a false green, the one verdict this codebase exists to
prevent. A goal needing speech SYNTHESIS was answered with `transcribe`, which
is speech RECOGNITION, the opposite. And "sign the binaries" matched the
sign-IN stem and was routed to a browser. That last one is hallucination at
the ROUTING layer, before a model is ever called.

So the ceiling was never the ladder. `acquire.py` is sound: it installs into
an isolated directory, runs a SANDBOXED probe, and OBSERVES the exit code
rather than accepting a verdict. What was finite was the ladder's input
vocabulary. This module makes that vocabulary open-ended without letting a
single claim through unchecked.

THE ONE IDEA

    A model may PROPOSE a capability. It may never author the test.

A proposal here is not code and not prose. It is two declared fields — an
import name plus its package, or a binary name — and the PLATFORM generates
the probe body from a closed template on every single run. There is no
`probe_python=` parameter, no `argv=`, no witness string. That is deliberate:
the first draft of this design let the agent supply probe code, and three
independent adversarial reviews returned "unsound" on exactly that, because a
tool that writes its own exam passes it. A declarative spec cannot be
state-dependent, cannot read a secret, cannot smuggle a token into a shell
string, and cannot pass by pointing at a file the agent is able to edit.

THE LADDER, AND WHY EACH RUNG REFUSES

    propose    a name, a falsifiable spec, and a QUOTE from the goal's own
               words. Runs nothing, proves nothing, costs nothing.
    falsify    seal the spec OUTSIDE the expert root, then observe the machine
               as it stands. The probe MUST FAIL FIRST. A probe that passes
               before anything is installed cannot tell having the capability
               from not having it, so it lands at `unfalsifiable` — terminal,
               never ready, never adopted.
    route      the fixed search ladder: already-trusted -> system binary ->
               MCP catalog -> PyPI -> an HTTP rail -> the owner. The owner
               rung is always present and always last, so the ladder can never
               end in silence.
    acquire    hands the sealed probe to the SHIPPED acquire.py ladder —
               request, inspect, isolated install, capability_test. Nothing
               here re-implements acquisition and nothing bypasses it.
    prove      re-run the sealed probe; record what was observed.
    adopt      the ONLY path to `owned`, and a human does it from a terminal.

WHY ADOPTION IS NOT A BUTTON IN THE PANEL

Adopting a capability publishes a command to every future agent in this fleet.
The gate therefore requires four things at once: the process must not be
inside an agent task, a granted approvals record must exist, the owner must
echo the exact command back, and where an organization exists `transfer_owner`
must pass. It deliberately does NOT use `grants._owner_check`, which returns
True unconditionally when no organization exists — the default install.

READINESS IS DECIDED OUTSIDE THE EXPERT'S REACH

`capabilities()` reports ready ONLY when the seal ledger — a file outside the
expert root — carries an adoption row whose hashes still match the spec and
the published command. Hand-writing "owned" into this expert's own ledger
buys nothing. And the seal is FIRST-seal-wins, which is this module's one
deliberate divergence from `contract.py`: under last-seal-wins an attacker
never needs to edit a seal, appending one is enough.

WHAT IT STILL WILL NOT DO

An API key, an account, a payment, a Terms of Service acceptance: those are
authority, they are never self-granted, and every route carrying one ends at
the owner. `accept_terms` records that a HUMAN read a URL. It never fetches
it, never clicks anything, and never infers acceptance from a status code.

    python frontier.py propose <cap> --root R --need "..." --quote "..." ...
    python frontier.py falsify <cap> --root R
    python frontier.py acquire <cap> --root R --home H [--apply]
    python frontier.py adopt   <cap> --root R --home H --as you --confirm-how "..."
    python frontier.py status  --root R
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

# A Windows console defaults to cp1252 and this module's own docstring carries
# arrows. Same guard acquire.py, chief.py and universal.py use; without it
# `python frontier.py --help` dies before printing a word.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):        # pragma: no cover
    pass

import locks                             # noqa: E402

LEDGER = "frontier/frontier.json"
SPECS = "frontier/probes"
EVENTS = "frontier/events.jsonl"
SEAL_FILE = "frontier-seals.jsonl"

# proposed      a name and a spec; nothing observed
# unfalsifiable the probe passed BEFORE installation — terminal, never ready
# red           the probe failed as it must, inside a containment boundary
# routing       a route was computed
# acquiring     the shipped ladder is running
# proven        installed, and the SEALED probe now passes
# owned         a human adopted it; only now is it published to agents
# refused       an attempt failed; carries a reason and a retry date
# impossible    no route exists, or a human must act first
# retired       withdrawn by the owner; stops contributing to derivation
STAGES = ("proposed", "unfalsifiable", "red", "routing", "acquiring",
          "proven", "owned", "refused", "impossible", "retired")
RUNGS = ("trusted", "binary", "mcp", "pypi", "http_rail", "owner")

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}(\.[A-Za-z_][A-Za-z0-9_]{0,63}){0,3}$")
PKG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
BIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,63}$")
HOW_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.,:@+=/\\-]{1,120}$")

# acquire.capability_test composes its probe argv into a shell string and
# quotes an element ONLY when it contains a space (acquire.py:614-618). An
# element carrying '&' or '|' and no space is therefore interpolated raw.
# Every path and token this module lets reach that string is checked here.
SHELL_META = set("&|;<>^()\"'`$\n\r\t*?[]{}!")
# `~` is NOT in that set, and the omission is deliberate. A tilde expands
# only at the START of a word in a POSIX shell; mid-word it is an ordinary
# character. Windows 8.3 short paths contain one by construction — every
# GitHub Actions Windows runner has its temp under C:\Users\RUNNER~1 — so
# banning it outright refused a legitimate expert root and failed the suite
# on three runners while passing on every machine whose paths are long.
# A LEADING tilde is still refused, below, because that one really does
# expand.

MAX_OPEN = 8
MAX_PROPOSALS_PER_DAY = 12
# acquire.capability_test hard-codes timeout=180 on its outer hop. A spec
# above that is killed with rc 124 and recorded as a RED that never ran —
# a false observation, so it is refused at intake instead.
MAX_TIMEOUT = 120
MIN_QUOTE_CHARS = 12

STOPWORDS = frozenset("""
about above after again against all also any and are because been before
being below between both but came can come could did does doing down during
each few for from further had has have having her here hers him his how
into its itself just like made make many may might more most must need
new now off once only other our out over own please same should since some
such take than that the their them then there these they thing this those
through too under until using very want was way well were what when where
which while who why will with would you your
""".split())


class Refused(Exception):
    """The sentence the owner and the agent both read."""


# --------------------------------------------------------------- ledger I/O

def _cfg(root):
    """This expert's settings. A private copy rather than a dependency on
    another module's underscore API."""
    try:
        import tomllib
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig")) or {}
    except (OSError, ValueError, ImportError):
        return {}


def _path(root, rel=LEDGER):
    return os.path.join(root, *rel.split("/"))


def load(root):
    try:
        with open(_path(root), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(root, rows):
    os.makedirs(os.path.dirname(_path(root)), exist_ok=True)
    tmp = f"{_path(root)}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    os.replace(tmp, _path(root))
    return rows


def get(root, capability):
    return next((r for r in load(root)
                 if r.get("capability") == capability), None)


def _put(root, row):
    """Read-modify-write UNDER THE LOCK. universal.resolve, repair, the panel
    and the CLI all write this ledger; the lost-update hazard acquire.py
    documents for its own is real here too."""
    # The lock file lives beside the ledger, so its directory must exist
    # before locks.holding opens it with O_CREAT|O_EXCL.
    os.makedirs(os.path.dirname(_path(root)), exist_ok=True)
    with locks.holding(_path(root), timeout=5.0):
        rows = load(root)
        for i, r in enumerate(rows):
            if r.get("capability") == row["capability"]:
                rows[i] = row
                break
        else:
            rows.append(row)
        _save(root, rows)
    return row


def _event(root, capability, event, **detail):
    line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "capability": capability, "event": event}
    line.update(detail)
    p = _path(root, EVENTS)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with locks.holding(p, timeout=5.0):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------- the seal

def seal_path(root):
    """The seal ledger lives OUTSIDE the expert's working root when the expert
    lives in a fleet home, so a worker editing files under its own root cannot
    also edit the record that decides whether it is ready. A bare root seals
    beside itself and every row records which kind it got, because a
    protection that silently degrades is a protection that lies."""
    parent = os.path.dirname(os.path.abspath(root))
    if os.path.basename(parent).lower() == "experts":
        home = os.path.dirname(parent)
        return os.path.join(home, "org", SEAL_FILE), "home"
    return os.path.join(root, "org", SEAL_FILE), "root"


def _seal_rows(root, capability=None):
    p, _kind = seal_path(root)
    out = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if capability is None or row.get("capability") == capability:
                    out.append(row)
    except OSError:
        return []
    return out


def _seal_append(root, row):
    p, _kind = seal_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with locks.holding(p, timeout=5.0):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def sealed_probe_hash(root, capability, gen):
    """-> (hash|None, conflict). THE FIRST SEAL WINS.

    This is the one deliberate divergence from contract.py, whose own comment
    says "The LAST seal wins". Under that rule an attacker never needs to EDIT
    a seal — appending one is enough, and appending is exactly what an
    append-only ledger permits. Here the first row for (capability, gen) is
    authoritative and any later row carrying a different hash is a CONFLICT,
    which every caller treats as TAMPER. Re-sealing legitimately is `reseal`,
    which bumps gen and is owner-gated.
    """
    first, conflict = None, False
    for row in _seal_rows(root, capability):
        if row.get("kind") != "probe" or int(row.get("gen", 0)) != int(gen):
            continue
        h = row.get("probe_hash")
        if first is None:
            first = h
        elif h != first:
            conflict = True
    return first, conflict


def sealed_adoption(root, capability, gen):
    for row in _seal_rows(root, capability):
        if row.get("kind") == "adoption" and int(row.get("gen", 0)) == int(gen):
            return row
    return None


def _probe_hash(capability, gen, spec):
    """Canonical JSON so key order and whitespace cannot make one spec hash
    two ways. NOTE what is sealed: the SPEC, not a file of code. There is no
    model-authored probe body anywhere in this design."""
    payload = {"capability": capability, "gen": int(gen),
               "kind": spec["kind"], "module": spec.get("module"),
               "binary": spec.get("binary"), "package": spec.get("package"),
               "source": spec.get("source"),
               "target_rel": spec.get("target_rel"),
               "timeout": int(spec["timeout"])}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _how_hash(how_argv):
    """Sealed into the adoption row, so editing `how` in the in-root ledger
    after adoption makes the capability report NOT ready rather than
    publishing an edited command to every agent."""
    blob = json.dumps(list(how_argv), separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _no_meta(*strings):
    for s in strings:
        text = str(s or "")
        if text.startswith("~"):
            raise Refused(
                f"{text!r} begins with '~', which a POSIX shell expands to a "
                f"home directory; the acquisition ladder composes a shell "
                f"command string, so the path it runs would not be the path "
                f"that was checked.")
        for ch in text:
            if ch in SHELL_META:
                raise Refused(
                    f"{s!r} contains {ch!r}; the acquisition ladder composes a "
                    f"shell command string and quotes only around spaces, so "
                    f"this design will not let that character through.")


# ------------------------------------------------------- the generated probe

def probe_body(root, spec):
    """THE PROBE IS PLATFORM-AUTHORED. Generated from the sealed spec on every
    run, so an edited body on disk is overwritten rather than trusted. The only
    interpolated values are an already-regex-validated name and an absolute
    path this module computed."""
    if spec["kind"] == "import":
        # THE TARGET IS DERIVED FROM THE PROBE'S OWN LOCATION, NOT EMBEDDED.
        #
        # This used to interpolate the host's absolute path. The probe runs
        # inside the sandbox, where the expert root is mounted at /work — so
        # the embedded path did not exist, sys.path pointed at nothing, and
        # a package that HAD been installed correctly reported
        # "ModuleNotFoundError". The ladder completed, the digest was taken,
        # and the probe then said the capability was absent.
        #
        # The script always lives at <root>/frontier/probes/<cap>.py, so
        # three dirnames reach the root wherever it is mounted. What is
        # sealed is target_rel, not an absolute path, so this changes no
        # hash — it makes the same sealed spec resolve correctly on both
        # sides of the mount.
        rel = spec["target_rel"]
        return (
            "import os, sys\n"
            "_here = os.path.dirname(os.path.abspath(__file__))\n"
            "_root = os.path.dirname(os.path.dirname(_here))\n"
            f"target = os.path.join(_root, *{rel.split('/')!r})\n"
            "sys.path = [target] + [p for p in sys.path if p and "
            "'site-packages' not in p and "
            "p != os.path.dirname(os.path.abspath(__file__))]\n"
            f"import {spec['module']} as m\n"
            "f = getattr(m, '__file__', None)\n"
            "if not f:\n"
            "    raise SystemExit('NOT INSTALLED: %s resolved with no "
            "__file__ (a namespace package is not an installation)' "
            "% m.__name__)\n"
            "if not os.path.abspath(f).startswith(os.path.abspath(target)):\n"
            "    raise SystemExit('WRONG COPY: %s came from %s, not from the "
            "install target %s' % (m.__name__, f, target))\n"
            "print('imported', m.__name__, getattr(m, '__version__', ''), "
            "'from', f)\n")
    if spec["kind"] == "binary":
        # shutil.which searches the CURRENT DIRECTORY on Windows, and a
        # sandboxed command's current directory IS the expert root. Without
        # the realpath check an agent could satisfy a binary probe with a
        # file it wrote into its own workspace.
        # Same fix, and here it is a SECURITY one rather than a correctness
        # one: with the host path embedded, the "is this binary inside the
        # workspace" check compared against a directory that does not exist
        # in the sandbox, so it could never be true and a binary the worker
        # had written into its own root would have PASSED.
        return (
            "import os, shutil\n"
            "_here = os.path.dirname(os.path.abspath(__file__))\n"
            "root = os.path.dirname(os.path.dirname(_here))\n"
            f"p = shutil.which({spec['binary']!r}, "
            "path=os.environ.get('PATH', ''))\n"
            "if p is None:\n"
            f"    raise SystemExit('NOT PRESENT: {spec['binary']} is not on "
            "PATH')\n"
            "if os.path.realpath(p).startswith(os.path.realpath(root)):\n"
            "    raise SystemExit('INSIDE THE WORKSPACE: %s resolves to %s, "
            "which is under the expert root; a tool the worker could have "
            "written is not evidence the tool exists' % "
            f"({spec['binary']!r}, p))\n"
            "print('found', p)\n")
    raise Refused(f"unknown probe kind {spec['kind']!r}")


# -------------------------------------------------------------- 1. proposing

def _builtin_names(root):
    try:
        import toolbox
        return set((toolbox.scan(root).get("capabilities") or {}))
    except Exception:
        return set()


def _trigger_terms(quote):
    """The platform's own reading of the quote — never the model's keywords.
    At most three, each >= 5 characters and not a stopword, so the derivation
    vocabulary a proposal can add is bounded by construction."""
    toks = sorted({t for t in re.findall(r"[a-z0-9]{5,}", quote.casefold())
                   if t not in STOPWORDS})
    return toks[:3]


def propose(root, capability, need, quote, goal, criteria="", kind="import",
            module="", package="", source="pypi", binary="", how_argv=None,
            timeout=60, proposed_by="practitioner"):
    """The only intake, and it RUNS NOTHING. Proposing is cheap and proves
    nothing; every refusal below happens before a single byte is written."""
    how_argv = list(how_argv or [])
    if not NAME_RE.match(capability or ""):
        raise Refused(f"{capability!r} is not a capability name "
                      f"(lower case, 3-32 chars, letters/digits/underscore)")
    _no_meta(root, HOME, sys.executable, capability, package, binary,
             *how_argv)

    mine = {r["capability"] for r in load(root)}
    builtins = _builtin_names(root) - mine
    if capability in builtins:
        raise Refused(f"{capability!r} is already a capability this machine "
                      f"reports; the frontier does not shadow built-ins")
    # toolbox.capability_note() is the text injected into an agent's context,
    # and tests/test_invariants.py classifies a line by SUBSTRING (`elif
    # "video_download" in l`), taking the first match in the whole note. So a
    # frontier NAME carrying a built-in name inside it would be read as that
    # built-in's line and could report a capability the runtime disagrees with.
    # The name rule is therefore absolute.
    for b in builtins:
        if b and b in capability:
            raise Refused(f"{capability!r} contains the built-in capability "
                          f"name {b!r}; that substring changes how the "
                          f"capability report is parsed")
    # The published command is held to a WORD-BOUNDARY rule, not a substring
    # one. The first version refused any how token merely CONTAINING a
    # built-in name of 8+ chars — which outlawed acquiring
    # `sortedcontainers`, a major real library, because "containers" sits
    # inside it. A fragment inside a longer alphanumeric word cannot be
    # picked out by the note's line classifier as a standalone name; a token
    # that IS the built-in name (or carries it delimiter-bounded, like
    # `run-containers`) still can, and is still refused.
    for b in builtins:
        if b and len(b) >= 8 and any(
                re.search(rf"(?<![a-z0-9]){re.escape(b)}(?![a-z0-9])",
                          t.lower()) for t in how_argv):
            raise Refused(f"the published command contains the built-in "
                          f"capability name {b!r} as a standalone word; "
                          f"that changes how the capability report is parsed")
    if kind not in ("import", "binary"):
        raise Refused(f"probe kind {kind!r} is not one this platform can "
                      f"generate; it is 'import' or 'binary'")
    if kind == "import":
        if not MODULE_RE.match(module or ""):
            raise Refused(f"{module!r} is not an importable module name")
        if not PKG_RE.match(package or ""):
            raise Refused(f"{package!r} is not a package name")
        if source != "pypi":
            raise Refused(
                f"the frontier installs from pypi only; for {source!r} run "
                f"`python acquire.py request {package} --source {source}` "
                f"yourself and adopt the result")
    else:
        if not BIN_RE.match(binary or ""):
            raise Refused(f"{binary!r} is not a binary name")
    if not (5 <= int(timeout) <= MAX_TIMEOUT):
        raise Refused(f"timeout must be 5..{MAX_TIMEOUT} seconds; the "
                      f"acquisition ladder kills its own hop at 180 and a "
                      f"killed probe would be recorded as a failure that "
                      f"never ran")
    if not how_argv or len(how_argv) > 24:
        raise Refused("a proposal must publish the command agents would run, "
                      "as 1-24 argv tokens")
    for t in how_argv:
        if not HOW_TOKEN_RE.match(t):
            raise Refused(f"{t!r} is not a reviewable command token")

    # THE ANCHOR. A capability with no span of the goal behind it is a
    # capability somebody imagined.
    hay = f"{goal} {criteria}".casefold()
    q = (quote or "").strip()
    if len(q) < MIN_QUOTE_CHARS:
        raise Refused(f"the quote {q!r} is too short to be an anchor "
                      f"(>= {MIN_QUOTE_CHARS} characters)")
    if len([t for t in re.findall(r"\w+", q) if len(t) >= 4]) < 2:
        raise Refused(f"the quote {q!r} carries fewer than two real words")
    if q.casefold() not in hay:
        raise Refused(f"the quote {q!r} does not appear in the goal; a "
                      f"capability must be anchored in what was actually asked")

    rows = load(root)
    existing = next((r for r in rows if r["capability"] == capability), None)
    if existing is not None:
        ok, why = attemptable(root, capability)
        if not ok:
            raise Refused(why)
    else:
        open_rows = [r for r in rows if r["stage"] not in
                     ("owned", "retired", "impossible", "unfalsifiable")]
        if len(open_rows) >= MAX_OPEN:
            raise Refused(f"{len(open_rows)} capabilities are already open on "
                          f"this expert; finish or retire one first")
        today = time.strftime("%Y-%m-%d")
        n = sum(1 for r in rows if str(r.get("created", "")).startswith(today))
        if n >= MAX_PROPOSALS_PER_DAY:
            raise Refused(f"{n} capabilities were already proposed today")

    try:
        import acquire
        safe = acquire._safe_name(package) if kind == "import" else ""
    except Exception:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", package or "")
    row = {
        "capability": capability,
        "gen": int((existing or {}).get("gen", 1)),
        "stage": "proposed",
        "need": need,
        "quote": q,
        "goal": goal,
        "kind": kind,
        "module": module,
        "package": package,
        "source": source if kind == "import" else "",
        "binary": binary,
        "target_rel": f"capabilities/{safe}" if kind == "import" else None,
        "timeout": int(timeout),
        "how_argv": how_argv,
        "trigger_terms": _trigger_terms(q),
        "proposed_by": proposed_by,
        "created": (existing or {}).get(
            "created", time.strftime("%Y-%m-%dT%H:%M:%S")),
        "attempts": (existing or {}).get("attempts", []),
        "owner_actions": (existing or {}).get("owner_actions", []),
    }
    _put(root, row)
    _event(root, capability, "proposed", kind=kind, by=proposed_by)
    return row


def _spec_of(row):
    return {"kind": row["kind"], "module": row.get("module"),
            "binary": row.get("binary"), "package": row.get("package"),
            "source": row.get("source"), "target_rel": row.get("target_rel"),
            "timeout": int(row["timeout"])}


# ------------------------------------------------------------- 2. falsifying

def falsify(root, capability):
    """Seal the spec, then observe the machine AS IT STANDS.

    The probe must FAIL here. A probe that passes before anything is installed
    cannot distinguish having the capability from not having it, so it is not
    evidence of anything and the row goes to `unfalsifiable` — terminal.
    """
    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    if row["stage"] != "proposed":
        raise Refused(f"{capability} is at stage {row['stage']!r}; falsifying "
                      f"runs against a fresh proposal (see `reseal`)")
    import sandbox

    spec = _spec_of(row)
    h = _probe_hash(capability, row["gen"], spec)
    sealed, conflict = sealed_probe_hash(root, capability, row["gen"])
    _p, where = seal_path(root)
    if conflict:
        raise Refused(f"the seal ledger carries conflicting probe seals for "
                      f"{capability} at generation {row['gen']}")
    if sealed is None:
        _seal_append(root, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "kind": "probe", "capability": capability,
                            "gen": row["gen"], "probe_hash": h,
                            "where": where})
    elif sealed != h:
        raise Refused(
            f"a different probe is already sealed for {capability} at "
            f"generation {row['gen']}; re-sealing is "
            f"`python frontier.py reseal {capability}` and it is owner-gated")

    sp = _path(root, f"{SPECS}/{capability}.json")
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1, ensure_ascii=False)

    backend = sandbox.backend_name(_cfg(root))
    contained = backend != "host"
    rc, out = _run_probe_here(root, capability)
    obs = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rc": rc,
           "output": out[-400:], "contained": contained, "backend": backend}
    if rc == 2:
        row["stage"] = "impossible"
        row["why"] = ("the sealed probe spec does not match what is on disk; "
                      "nothing was run")
    elif rc == 0:
        row["stage"] = "unfalsifiable"
        row["why"] = ("the probe passed before anything was installed, so it "
                      "cannot distinguish having this capability from not "
                      "having it")
        # A corroborating trusted row is an OWNER ACTION, never a stage change:
        # "it may already be here" is not "the fleet owns it".
        try:
            import acquire
            hits = [h2["name"] for h2 in
                    acquire.search_known(root, row["need"])][:4]
        except Exception:
            hits = []
        if row["kind"] == "binary" and shutil.which(row["binary"]):
            hits.append(row["binary"])
        if hits:
            row["owner_actions"] = list(row.get("owner_actions", [])) + [
                f"this may already exist here: {', '.join(hits)}; "
                f"nothing was installed"]
    else:
        row["stage"] = "red"
    row["red" if rc == 1 else "observation"] = obs
    row["probe_hash"] = h
    _put(root, row)
    _event(root, capability, "falsified", rc=rc, contained=contained)
    return row


def _run_probe_here(root, capability):
    """In-process call of the same code path the CLI exposes, so falsify and
    acquire.capability_test observe the identical thing."""
    import io
    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        rc = run_probe(root, capability)
    finally:
        sys.stdout = old
    return rc, buf.getvalue()


# ------------------------------------------------------- 3. running the probe

def run_probe(root, capability):
    """The harness-side runner, and the ONLY thing that executes a probe.

    Order matters: the seal is compared BEFORE anything is generated or run,
    so a TAMPER verdict leaves no entry in logs/execution.jsonl at all.
    """
    import execution
    import sandbox

    sp = _path(root, f"{SPECS}/{capability}.json")
    row = get(root, capability)
    try:
        with open(sp, "r", encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, ValueError):
        print(f"TAMPER: no readable probe spec for {capability}. "
              f"Nothing was run.")
        return 2
    gen = int((row or {}).get("gen", 1))
    h = _probe_hash(capability, gen, spec)
    sealed, conflict = sealed_probe_hash(root, capability, gen)
    if sealed is None or conflict or sealed != h:
        print(f"TAMPER: the sealed probe spec for {capability} does not match "
              f"what is on disk (or the seal ledger carries a conflicting "
              f"later row). Nothing was run.")
        return 2

    body = probe_body(root, spec)
    bp = _path(root, f"{SPECS}/{capability}.py")
    os.makedirs(os.path.dirname(bp), exist_ok=True)
    with open(bp, "w", encoding="utf-8") as f:
        f.write(body)

    # RELATIVE path and a backend-chosen interpreter. sandbox._docker mounts
    # the root at /work with -w /work, so a host-absolute sys.executable and a
    # host-absolute script path do not exist inside the container.
    rel = f"{SPECS}/{capability}.py"
    cfg = _cfg(root)
    backend = sandbox.backend_name(cfg)
    if backend == "host":
        cmd = f'"{sys.executable}" {rel}'
    else:
        cmd = f"python {rel}"
    if sandbox.granted_for(cmd):
        print("REFUSED: this probe command would match a scoped credential "
              "grant, which would place a live key in the probe's environment")
        return 2
    rc, out, err = execution.run(
        "capability_probe", cmd, root, cfg=cfg,
        role=os.environ.get("AGENT_ROLE", "default"),
        timeout=int(spec.get("timeout", 60)),
        reason=f"frontier probe {capability}")
    print((out or "")[-400:] or (err or "")[-400:])
    return 0 if rc == 0 else 1


def sealed_command(root, capability):
    """What acquire.capability_test is handed. Every element is
    platform-authored or NAME_RE-constrained, and _no_meta has already refused
    a root or interpreter carrying a shell metacharacter."""
    return [sys.executable, os.path.join(HOME, "frontier.py"), "run-probe",
            "--root", root, "--capability", capability]


# ---------------------------------------------------------------- 4. routing

def route(root, home, capability):
    """Pure read. Touches no network and writes nothing."""
    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    rungs, actions, chosen = [], [], None

    try:
        import acquire
        hits = [h["name"] for h in acquire.search_known(root, row["need"])][:4]
    except Exception:
        hits = []
    if hits:
        rungs.append({"rung": "trusted", "found": hits})
        actions.append(f"this fleet may already have it: {', '.join(hits)} — "
                       f"check before installing anything")

    if row["kind"] == "binary":
        if shutil.which(row["binary"]):
            rungs.append({"rung": "binary", "found": row["binary"]})
        else:
            rungs.append({"rung": "binary", "owner":
                          f"{row['binary']} is a system binary, not a Python "
                          f"package: install it and restart, or set "
                          f"[agent] sandbox = \"docker\" — the shipped image "
                          f"carries the common ones."})
            actions.append(f"install {row['binary']} on this machine")
    try:
        import mcp
        terms = set(row.get("trigger_terms") or [])
        for name, entry in (mcp.CATALOG or {}).items():
            hay = f"{name} {entry.get('desc', '')}".casefold()
            if terms and len([t for t in terms
                              if re.search(rf"\b{re.escape(t)}\b", hay)]) >= 1:
                rungs.append({"rung": "mcp", "server": name,
                              "command": f"python mcp.py enable {name}"})
                actions.append(f"python mcp.py enable {name}")
                break
    except Exception:
        pass

    if row["kind"] == "import":
        cand = {"rung": "pypi", "source": "pypi",
                "package": row["package"], "version": ""}
        rungs.append(cand)
        chosen = cand

    if row.get("http_rail"):
        scope = row.get("scope") or ""
        granted = False
        try:
            import grants
            granted = bool(grants.check(home, "credential", scope))
        except Exception:
            granted = False
        rungs.append({"rung": "http_rail", "scope": scope, "granted": granted})
        if not granted:
            actions.append(f"a credential for {scope or 'this rail'} is "
                           f"authority: only you can supply it, and its terms "
                           f"of service are yours to accept")
            chosen = None

    rungs.append({"rung": "owner", "always": True})
    actions.append(f"python frontier.py explain {capability} --root {root}")
    return {"capability": capability, "rungs": rungs, "chosen": chosen,
            "owner_actions": actions}


def resolve_version(package, root):
    """Read-only network step, called ONLY from acquire_next under apply=True.

    The registry's own sha256 is returned but stored under
    `unverified_registry_sha256` and NEVER written into acquire's
    `content_hash` field, because pip is not invoked with --require-hashes and
    a hash nothing verified, filed under a field that advertises verification,
    is evidence that misdescribes what ran.
    """
    dst = _path(root, f"tmp/frontier-{package}.json")
    try:
        import ingest
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        ingest.fetch_url(f"https://pypi.org/pypi/{package}/json", dst,
                         root=root)
        with open(dst, "r", encoding="utf-8") as f:
            text = f.read()
        # `ingest.fetch_url` is an INGESTION function: it prepends a
        # provenance header — "SOURCE-URL: <url>" and a blank line — so that
        # material can always be traced to where it came from. That is right
        # for material and fatal for JSON, and this function used to hand the
        # whole file to json.load inside a bare `except Exception`. The
        # JSONDecodeError became an empty version, `acquire.inspect` refused
        # it as "no version pinned" — a correct refusal for entirely the
        # wrong reason — and THE PYPI RUNG HAD THEREFORE NEVER COMPLETED
        # ONCE. It looked like a policy stop rather than a bug, which is
        # exactly how a swallowed exception hides.
        if not text.lstrip().startswith("{"):
            i = text.find("{")
            if i < 0:
                raise Refused(
                    f"the registry response for {package} carried no JSON "
                    f"body (first bytes: {text[:60]!r})")
            text = text[i:]
        data = json.loads(text)
        info = data.get("info") or {}
        version = str(info.get("version") or "")
        sha = ""
        for u in (data.get("urls") or []):
            sha = ((u.get("digests") or {}).get("sha256") or "")
            if sha:
                break
        # The description is fed to acquire.inspect so its RISK_SIGNALS
        # tripwire actually fires — today no caller passes it and the whole
        # supply-chain screen is dead code. It is NEVER stored and NEVER
        # rendered, so registry prose cannot become a prompt aimed at the
        # human granting the last rung.
        if not version:
            raise Refused(f"the registry named no version for {package}")
        return version, sha, str(info.get("description") or "")[:20000]
    except Refused:
        raise
    except Exception as e:
        # NARROW, AND IT SAYS WHY. Returning ('', '', '') here made a network
        # failure, a parse failure and a squatted package name all look
        # identical downstream — one empty string, refused later with a
        # message about pinning that named none of them.
        raise Refused(f"could not resolve {package} from the registry: "
                      f"{type(e).__name__}: {str(e)[:160]}")
    finally:
        try:
            os.unlink(dst)
        except OSError:
            pass


# ------------------------------------------------------------- 5. acquiring

def acquire_next(root, home, capability, apply=False, worker_id=None):
    """Drives the SHIPPED ladder and nothing else."""
    import sandbox

    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    ok, why = attemptable(root, capability)
    if not ok:
        return {"capability": capability, "acted": False, "why": why}
    if row["stage"] != "red":
        raise Refused(
            f"{capability} is at stage {row['stage']!r}; a capability is "
            f"acquired only after its sealed probe has been observed to FAIL "
            f"(`python frontier.py falsify {capability}`)")
    red = row.get("red") or {}
    plan = route(root, home, capability)
    cfg = _cfg(root)
    # Every blocker is COMPUTED for both paths and RAISED only on the apply
    # path. A dry run is what the panel calls to render; refusing to describe
    # a plan because the plan is blocked would make the blocker invisible in
    # the one place the owner is looking.
    blockers = []
    if not red.get("contained"):
        blockers.append(
            "the RED observation was made on the host, where nothing "
            "separates the probe from the workspace; set [agent] sandbox and "
            "run falsify again")
    if sandbox.backend_name(cfg) == "host":
        blockers.append("installing third-party code requires a sandbox; set "
                        "[agent] sandbox = \"docker\" in settings.toml")
    if not apply:
        return {"capability": capability, "acted": False, "plan": plan,
                "blockers": blockers,
                "would_run": [
                    f"python frontier.py acquire {capability} --root {root} "
                    f"--home {home} --apply"]}
    if blockers:
        raise Refused(blockers[0])
    if plan["chosen"] is None:
        row["stage"] = "impossible"
        row["why"] = ("no rung of the ladder can obtain this without you: "
                      + "; ".join(plan["owner_actions"][:2]))
        _put(root, row)
        return {"capability": capability, "acted": False, "why": row["why"],
                "owner_actions": plan["owner_actions"]}

    import acquire
    row["stage"] = "acquiring"
    _put(root, row)
    try:
        version, sha, manifest = resolve_version(row["package"], root)
        rec = acquire.request(root, row["package"], "pypi", row["need"],
                              version=version, manifest_text=manifest)
        acq_id = rec["id"]
        if rec.get("local_path") or rec.get("index_url"):
            raise Refused("the acquisition row carries a local path or a "
                          "private index; the frontier never writes either")
        acquire.install(root, home, acq_id, worker_id=worker_id)
        # TWO INDEPENDENT GRADERS, EACH WHERE IT CAN ACTUALLY RUN.
        # PROMOTION is decided by acquire's own arena probe: its source is
        # hardcoded in acquire.py (outside any workspace), rewritten into a
        # disposable arena every run, hashed into probe_hash and executed
        # with no network. Passing the frontier's sealed command here was
        # worse than useless — that command is a HOST argv, executed as a
        # shell string inside a Linux container, so it could not run at all.
        # The sealed probe still decides "proven"; it now does so below,
        # against the promoted bytes, where it CAN run.
        acquire.capability_test(root, acq_id, module=row.get("module") or "")
        # acquire now stages into a disposable arena and promotes to
        # capabilities/<name> only on a passing sealed probe — install_path
        # is the ARENA until then. Checking the landing before the probe
        # therefore refused every acquisition against its own staging path.
        # The invariant stands where it can be true: after promotion, the
        # proven bytes must live exactly where the sealed probe tests.
        fresh = next((r for r in acquire.load(root) if r["id"] == acq_id), {})
        evidence = fresh.get("test_evidence") or {}
        if not evidence.get("passed"):
            # capability_test RETURNS on a failed probe (it records
            # stage="rejected"), it does not raise. Without this branch
            # control fell through to the unconditional stage="proven" write
            # below and recorded green {"rc": 0, "contained": true} — an
            # observation that was never made, about bytes that were never
            # promoted. A capability may fail its probe; the one thing it may
            # not do is be written down as proven.
            raise RuntimeError(
                "the sealed capability probe did not pass, so nothing was "
                "promoted to capabilities/: "
                + str(evidence.get("evidence", "no evidence recorded"))[:300])
        target = (fresh.get("install_path") or "").replace("\\", "/")
        if target and target != row["target_rel"]:
            raise Refused(f"the install landed at {target!r} but the "
                          f"sealed probe tests {row['target_rel']!r}")
    except Refused:
        raise
    except Exception as e:
        # Every acquire.Refused is recorded verbatim: no isolated worker, host
        # sandbox, org veto, typosquat, unpinned version, unknown source.
        row = get(root, capability) or row
        row.setdefault("attempts", []).append(
            {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": "refused",
             "why": str(e)[:400]})
        row["stage"] = "refused"
        row["refusal"] = {"why": str(e)[:400],
                          "retry_after": _retry_after(row)}
        _put(root, row)
        _event(root, capability, "refused", why=str(e)[:200])
        return {"capability": capability, "acted": False, "why": str(e)[:400]}
    finally:
        # acquire.capability_test writes an unsealed lookalike probe to
        # tmp/probe-<name>.py unconditionally, BEFORE its `if probe:` branch
        # chooses the command. It is never executed; it is removed anyway.
        try:
            os.unlink(_path(root, f"tmp/probe-{acquire._safe_name(row['package'])}.py"))
        except (OSError, UnboundLocalError, KeyError):
            pass

    # THE SEALED PROBE, AGAINST THE PROMOTED BYTES. Until now this block
    # wrote "rc": 0 as a literal — a green observation nobody had made. The
    # probe is regenerated from the sealed spec and TAMPER-checked before it
    # runs, so what is recorded below is what was actually observed.
    row = get(root, capability) or row
    green_rc, green_out = _run_probe_here(root, capability)
    if green_rc != 0:
        row.setdefault("attempts", []).append(
            {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": "refused",
             "why": f"sealed probe exit {green_rc}"})
        row["stage"] = "refused"
        row["refusal"] = {"why": (f"the capability installed, but its SEALED "
                                  f"probe still fails (exit {green_rc}): "
                                  f"{green_out.strip()[-300:]}"),
                          "retry_after": _retry_after(row)}
        _put(root, row)
        _event(root, capability, "refused", why=f"sealed probe exit {green_rc}")
        return {"capability": capability, "acted": False,
                "why": row["refusal"]["why"]}
    row["stage"] = "proven"
    row["unverified_registry_sha256"] = sha
    row["acq_id"] = acq_id
    row["green"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rc": green_rc,
                    "output": green_out.strip()[-400:],
                    "contained": True, "backend": sandbox.backend_name(cfg),
                    "install_digest": install_digest(root, row),
                    "acq_id": acq_id}
    row.setdefault("attempts", []).append(
        {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": "ok"})
    _put(root, row)
    _event(root, capability, "proven", acq_id=acq_id)
    return {"capability": capability, "acted": True, "stage": "proven",
            "acq_id": acq_id,
            "next": f"python frontier.py adopt {capability} --root {root} "
                    f"--home {home} --as <you> "
                    f"--confirm-how \"{' '.join(row['how_argv'])}\""}


def _retry_after(row):
    n = len([a for a in row.get("attempts", []) if a.get("result") != "ok"])
    days = min(90, 7 * (2 ** max(0, n - 1)))
    return time.strftime("%Y-%m-%dT%H:%M:%S",
                         time.localtime(time.time() + days * 86400))


def install_digest(root, row):
    """sha256 over (relpath, size, head+tail sha) for every installed file.

    Digesting only (relpath, size) is defeated by a same-length substitution;
    hashing the first and last 4096 bytes closes the trivial case cheaply. The
    residual — a crafted middle-of-file edit preserving length and both ends —
    is stated in the docs rather than papered over. This is DETECTION, the
    same ceiling contract.py states about its own seal.
    """
    target = row.get("target_rel")
    if not target:
        return ""
    base = os.path.join(root, *target.split("/"))
    parts = []
    for dirpath, _d, names in os.walk(base):
        for n in sorted(names):
            full = os.path.join(dirpath, n)
            try:
                size = os.path.getsize(full)
                with open(full, "rb") as f:
                    head = f.read(4096)
                    if size > 4096:
                        f.seek(max(0, size - 4096))
                        tail = f.read(4096)
                    else:
                        tail = b""
            except OSError:
                continue
            parts.append(f"{os.path.relpath(full, base)}|{size}|"
                         f"{hashlib.sha256(head + tail).hexdigest()}")
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()


def prove(root, capability):
    """Re-run the sealed probe and record what was OBSERVED."""
    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    rc, out = _run_probe_here(root, capability)
    if rc == 2:
        return {"capability": capability, "tamper": True, "green": False,
                "rc": rc, "evidence": out[-400:],
                "command": " ".join(sealed_command(root, capability)),
                "install_digest": "",
                "why": "the sealed probe spec does not match what is on disk"}
    digest = install_digest(root, row)
    return {"capability": capability, "tamper": False, "green": rc == 0,
            "rc": rc, "evidence": out[-400:],
            "command": " ".join(sealed_command(root, capability)),
            "install_digest": digest,
            "why": "observed" if rc == 0 else "the sealed probe still fails"}


# ------------------------------------------------------------- 6. the owner

def _owner_gate(root, home, capability, actor, confirm_how, action):
    """THE ADOPTION GATE. Four conditions, all required.

    It deliberately does NOT use grants._owner_check, whose first statements
    are `if org.load(home) is None: return True` — an unconditional pass on
    every fleet without an organization, which is the default install.
    """
    import approvals

    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    if os.environ.get("AGENT_TASK_ID") or os.environ.get("AGENT_ROLE"):
        raise Refused("adoption cannot be performed from inside an agent "
                      "task; run it yourself from a terminal")
    want = " ".join(row.get("how_argv") or [])
    if (confirm_how or "").strip() != want:
        raise Refused(f"echo the command that is about to be published to "
                      f"every agent in this fleet:\n"
                      f'  --confirm-how "{want}"')
    key = (f"frontier|{capability}|{row['gen']}|"
           f"{_how_hash(row.get('how_argv') or [])}|"
           f"{row.get('probe_hash', '')}")
    status = approvals.status_of(root, key)
    if status is None:
        rec = approvals.request(
            root, key, "frontier", action,
            {"capability": capability, "how": want},
            f"{action} for capability {capability}", task_id="-")
        raise Refused(f"an approval is required first: "
                      f"`python approvals.py grant {rec.get('id', key)} "
                      f"--root {root}`")
    if status != "granted":
        raise Refused(f"the approval for {capability} is {status!r}")
    try:
        import org
        if org.load(home) is not None:
            org.check(home, actor, "transfer_owner", action)
    except ImportError:
        pass
    return actor or "owner"


def adopt(root, home, capability, acq_id=None, actor="", confirm_how="",
          permissions=None):
    """The last rung, and the ONLY path to stage `owned`."""
    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    # WHO is asking is settled before WHAT is being asked. An agent must not
    # even learn whether adoption would otherwise have been possible, so this
    # precedes the stage check rather than following it.
    if os.environ.get("AGENT_TASK_ID") or os.environ.get("AGENT_ROLE"):
        raise Refused("adoption cannot be performed from inside an agent "
                      "task; run it yourself from a terminal")
    if row["stage"] != "proven":
        raise Refused(f"{capability} is at stage {row['stage']!r}; only a "
                      f"proven capability can be adopted")
    green = row.get("green") or {}
    if green.get("rc") != 0 or not green.get("contained"):
        raise Refused("the green observation was not made inside a "
                      "containment boundary")
    _sealed, conflict = sealed_probe_hash(root, capability, row["gen"])
    if conflict:
        raise Refused("the seal ledger carries conflicting probe seals")
    check = prove(root, capability)
    if check["tamper"] or not check["green"]:
        raise Refused(f"the sealed probe does not pass right now: "
                      f"{check['why']}")
    who = _owner_gate(root, home, capability, actor, confirm_how,
                      "adopt a capability into the fleet")

    import approvals
    key = (f"frontier|{capability}|{row['gen']}|"
           f"{_how_hash(row.get('how_argv') or [])}|"
           f"{row.get('probe_hash', '')}")
    aid = acq_id or row.get("acq_id")
    if aid:
        import acquire
        # `provides` is PLATFORM-AUTHORED, never the model's prose:
        # acquire.search_known word-matches name + provides + why of trusted
        # rows, so a model sentence there becomes a fleet-wide gate.
        acquire.promote(root, aid, by=who, permissions=permissions,
                        provides=f"frontier capability {capability}")
    _p, where = seal_path(root)
    _seal_append(root, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "kind": "adoption", "capability": capability,
                        "gen": row["gen"],
                        "probe_hash": row.get("probe_hash", ""),
                        "how_hash": _how_hash(row.get("how_argv") or []),
                        "by": who, "approval_id": key, "where": where})
    row["stage"] = "owned"
    row["adoption"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": who,
                       "where": where, "degraded": where == "root"}
    _put(root, row)
    _event(root, capability, "owned", by=who)
    approvals.status_of(root, key)
    return row


def retire(root, home, capability, actor="", why="", confirm_how=""):
    """Withdraw a capability: it stops being published AND stops contributing
    to derivation. The pruning mechanism for an over-broad quote."""
    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    who = _owner_gate(root, home, capability, actor, confirm_how,
                      "retire a capability")
    _seal_append(root, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "kind": "retire", "capability": capability,
                        "gen": row["gen"], "by": who, "why": why})
    row["stage"] = "retired"
    row["why"] = why or "retired by the owner"
    _put(root, row)
    _event(root, capability, "retired", by=who)
    return row


def reseal(root, home, capability, actor="", confirm_how=""):
    """The ONLY way a new probe spec can be sealed for a capability that
    already has one: bump the generation, under the owner's gate."""
    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    who = _owner_gate(root, home, capability, actor, confirm_how,
                      "re-seal a capability probe")
    row["gen"] = int(row["gen"]) + 1
    row["stage"] = "proposed"
    row.pop("red", None)
    row.pop("green", None)
    row.pop("probe_hash", None)
    _put(root, row)
    _event(root, capability, "resealed", by=who, gen=row["gen"])
    return row


def accept_terms(root, home, capability, actor="", url="", confirm_how=""):
    """Record that a HUMAN read and accepted a route's terms.

    Never fetches the URL, never clicks anything, never infers acceptance from
    a status code.
    """
    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    who = _owner_gate(root, home, capability, actor, confirm_how,
                      "accept terms of service on the fleet's behalf")
    row.setdefault("terms", []).append(
        {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": who, "url": url})
    _put(root, row)
    _event(root, capability, "terms_accepted", by=who)
    return row


# ---------------------------------------------------------------- 7. reading

def attemptable(root, capability):
    """-> (bool, why). A refused capability is not silently re-attempted."""
    row = get(root, capability)
    if row is None:
        return True, "no row yet"
    if row["stage"] in ("impossible", "retired", "owned"):
        return False, (f"{capability} is {row['stage']}: "
                       f"{row.get('why', 'no further attempt is useful')}")
    if row["stage"] == "refused":
        after = (row.get("refusal") or {}).get("retry_after", "")
        if after and after > time.strftime("%Y-%m-%dT%H:%M:%S"):
            return False, (f"{capability} was refused "
                           f"({(row.get('refusal') or {}).get('why', '')}); "
                           f"not retried before {after}")
    return True, "attemptable"


def capabilities(root):
    """What toolbox.scan merges, and THE SINGLE PLACE READINESS IS DECIDED.

    ready is True only when the seal ledger — outside the expert root — still
    vouches for both the spec and the published command. Editing this expert's
    own frontier.json, by any route including a shell write the File Authority
    never sees, cannot manufacture a ready capability.
    """
    if not root:
        # toolbox.scan(), doctor.py and /api/toolbox all call with root=None,
        # and os.path.join(None, ...) would raise inside a bare except — the
        # dead-branch-in-a-bare-except shape acquire.py documents.
        return {}
    out = {}
    for row in load(root):
        name = row.get("capability")
        if not name or row.get("stage") == "retired":
            continue
        ready, how = False, ""
        if row["stage"] == "owned":
            ad = sealed_adoption(root, name, row.get("gen", 1))
            if (ad and ad.get("probe_hash") == row.get("probe_hash")
                    and ad.get("how_hash") == _how_hash(row.get("how_argv") or [])):
                ready = True
                how = (" ".join(row.get("how_argv") or [])
                       + f" — owner-adopted {ad.get('at', '')[:10]}")
                if (row.get("adoption") or {}).get("degraded"):
                    how += (" (seal stored inside this root: this adoption is "
                            "not tamper-evident)")
            else:
                how = ("recorded as owned, but the seal outside this root does "
                       "not vouch for it — re-adopt")
        elif row["stage"] == "refused":
            r = row.get("refusal") or {}
            how = f"refused: {r.get('why', '')} (not retried before " \
                  f"{r.get('retry_after', '')})"
        elif row["stage"] == "unfalsifiable":
            how = row.get("why", "the probe could not distinguish present "
                                 "from absent")
        elif row["stage"] == "impossible":
            how = row.get("why", "no route without the owner")
        elif row["stage"] == "proven":
            how = (f"proven but not adopted — `python frontier.py adopt "
                   f"{name} --root {root}`")
        else:
            how = (f"at stage {row['stage']} — `python frontier.py "
                   f"{'falsify' if row['stage'] == 'proposed' else 'acquire'} "
                   f"{name} --root {root}`")
        out[name] = {"ready": ready, "how": how}
    return out


def recipe(capability, root=None, cfg=None):
    """toolbox.recipe's shape, computed from the ledger."""
    if not root:
        return None
    row = get(root, capability)
    if row is None:
        return None
    if row["kind"] == "import" and row["stage"] in ("red", "refused",
                                                    "routing", "acquiring"):
        return {"source": "pypi", "package": row["package"],
                "version": row.get("version", "")}
    if row["kind"] == "binary":
        return {"owner": f"{row['binary']} is a system binary, not a Python "
                         f"package: install it and restart."}
    if row["stage"] in ("impossible", "unfalsifiable", "retired"):
        return {"owner": row.get("why", "only the owner can resolve this")}
    return None


def implied(root, goal, criteria=""):
    """The LEARNED half of derivation, and it makes NO model call.

    Whole-token matching only, two distinct terms minimum — the same floor
    universal.py already applies to atoms — over at most three
    platform-derived trigger terms per row. Bounded by construction, and an
    owner removes a row from the vocabulary with `retire`.
    """
    if not root:
        return []
    hay = f"{goal} {criteria}".casefold()
    out = []
    for row in load(root):
        if row.get("stage") not in ("owned", "proven", "refused", "impossible"):
            continue
        name = row.get("capability", "")
        terms = set(row.get("trigger_terms") or []) | {
            t for t in re.split(r"[^a-z0-9]+", name) if len(t) >= 4}
        hit = {t for t in terms
               if re.search(rf"\b{re.escape(t)}\b", hay)}
        if len(hit) >= 2:
            out.append((name, f"this fleet has met {', '.join(sorted(hit))} "
                              f"before and recorded {name}"))
    return out


def summary(root):
    rows = load(root)
    by = {}
    for r in rows:
        by.setdefault(r.get("stage", "?"), []).append(r.get("capability"))
    # SHADOWED means "something else already owns this name, so the merge
    # skipped mine" — NOT "the name appears in scan()", which it always does
    # now that scan() merges this ledger. Comparing a name against a report
    # that already contains it reported every open capability as shadowed,
    # and a false alarm in the one place that exists to surface real
    # collisions is worse than no alarm.
    shadowed = []
    try:
        import toolbox
        reported = toolbox.scan(root).get("capabilities") or {}
        ours = capabilities(root)
        for name, ours_row in ours.items():
            got = reported.get(name)
            if got and got.get("how") != ours_row.get("how"):
                shadowed.append(name)
        shadowed.sort()
    except Exception:
        shadowed = []
    actions = []
    for r in rows:
        actions.extend(r.get("owner_actions") or [])
    return {"total": len(rows), "by_stage": by,
            "owned": by.get("owned", []),
            "shadowed": shadowed,
            "refused": [{"name": r["capability"],
                         "why": (r.get("refusal") or {}).get("why", ""),
                         "retry_after": (r.get("refusal") or {}).get(
                             "retry_after", "")}
                        for r in rows if r.get("stage") == "refused"],
            "owner_actions": actions[:12]}


def status(root):
    s = summary(root)
    lines = [f"frontier: {s['total']} capability row(s)"]
    for stage in STAGES:
        names = s["by_stage"].get(stage)
        if names:
            lines.append(f"  {stage:14s} {', '.join(n for n in names if n)}")
    for a in s["owner_actions"]:
        lines.append(f"  owner: {a}")
    return "\n".join(lines)


def explain(root, capability):
    row = get(root, capability)
    if row is None:
        raise Refused(f"no proposal for {capability!r}")
    ok, why = attemptable(root, capability)
    caps = capabilities(root)
    return {"row": row, "attemptable": ok, "why": why,
            "ready": caps.get(capability, {}).get("ready", False),
            "how": caps.get(capability, {}).get("how", ""),
            "seal": seal_path(root)[1]}


# -------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("propose", help="declare a capability and its probe")
    p.add_argument("capability")
    p.add_argument("--root", required=True)
    p.add_argument("--need", required=True)
    p.add_argument("--quote", required=True,
                   help="the span of the goal that asks for this")
    p.add_argument("--goal", required=True)
    p.add_argument("--criteria", default="")
    p.add_argument("--kind", default="import", choices=["import", "binary"])
    p.add_argument("--module", default="")
    p.add_argument("--package", default="")
    p.add_argument("--source", default="pypi")
    p.add_argument("--binary", default="")
    p.add_argument("--how", default="", help="the command agents would run")
    p.add_argument("--timeout", type=int, default=60)

    for name, helptext in (("falsify", "seal the spec and observe: it must FAIL"),
                           ("prove", "re-run the sealed probe"),
                           ("status", "what this fleet can do, and cannot"),
                           ("explain", "one capability, in full"),
                           ("run-probe", "harness-side probe runner")):
        q = sub.add_parser(name, help=helptext)
        if name != "status":
            q.add_argument("capability", nargs="?" if name == "run-probe" else None)
        q.add_argument("--root", required=True)
        if name == "run-probe":
            q.add_argument("--capability", dest="capability_opt", default="")

    for name, helptext in (("route", "which rung could obtain this"),
                           ("acquire", "walk the shipped ladder (needs --apply)")):
        q = sub.add_parser(name, help=helptext)
        q.add_argument("capability")
        q.add_argument("--root", required=True)
        q.add_argument("--home", default=HOME)
        if name == "acquire":
            q.add_argument("--apply", action="store_true")
            q.add_argument("--worker", default=None)

    for name, helptext in (("adopt", "publish it to the fleet (owner only)"),
                           ("retire", "withdraw it (owner only)"),
                           ("reseal", "bump the generation (owner only)"),
                           ("accept-terms", "record a human's acceptance")):
        q = sub.add_parser(name, help=helptext)
        q.add_argument("capability")
        q.add_argument("--root", required=True)
        q.add_argument("--home", default=HOME)
        q.add_argument("--as", dest="actor", default="")
        q.add_argument("--confirm-how", dest="confirm_how", default="")
        if name == "retire":
            q.add_argument("--why", default="")
        if name == "accept-terms":
            q.add_argument("--url", default="")

    a = ap.parse_args()
    try:
        if a.cmd == "propose":
            r = propose(a.root, a.capability, a.need, a.quote, a.goal,
                        a.criteria, kind=a.kind, module=a.module,
                        package=a.package, source=a.source, binary=a.binary,
                        how_argv=a.how.split(), timeout=a.timeout)
            print(f"proposed {r['capability']} at stage {r['stage']} — "
                  f"nothing has been observed yet")
            print(f"  next: python frontier.py falsify {r['capability']} "
                  f"--root {a.root}")
            return 0
        if a.cmd == "falsify":
            r = falsify(a.root, a.capability)
            print(f"{r['capability']}: {r['stage']}")
            if r["stage"] == "unfalsifiable":
                print(f"  {r['why']}")
                return 3
            return 0 if r["stage"] == "red" else 3
        if a.cmd == "run-probe":
            return run_probe(a.root, a.capability or a.capability_opt)
        if a.cmd == "route":
            r = route(a.root, a.home, a.capability)
            print(json.dumps(r, indent=1))
            return 0 if r["chosen"] else 3
        if a.cmd == "acquire":
            r = acquire_next(a.root, a.home, a.capability, apply=a.apply,
                             worker_id=a.worker)
            print(json.dumps(r, indent=1))
            return 0 if r.get("acted") else 3
        if a.cmd == "prove":
            r = prove(a.root, a.capability)
            print(json.dumps(r, indent=1))
            return 2 if r["tamper"] else (0 if r["green"] else 1)
        if a.cmd == "adopt":
            r = adopt(a.root, a.home, a.capability, actor=a.actor,
                      confirm_how=a.confirm_how)
            print(f"{r['capability']} is now owned by this fleet")
            return 0
        if a.cmd == "retire":
            retire(a.root, a.home, a.capability, actor=a.actor, why=a.why,
                   confirm_how=a.confirm_how)
            print(f"{a.capability} retired")
            return 0
        if a.cmd == "reseal":
            r = reseal(a.root, a.home, a.capability, actor=a.actor,
                       confirm_how=a.confirm_how)
            print(f"{a.capability} is back at proposed, generation {r['gen']}")
            return 0
        if a.cmd == "accept-terms":
            accept_terms(a.root, a.home, a.capability, actor=a.actor,
                         url=a.url, confirm_how=a.confirm_how)
            print(f"recorded: a human accepted the terms for {a.capability}")
            return 0
        if a.cmd == "status":
            print(status(a.root))
            return 0
        if a.cmd == "explain":
            print(json.dumps(explain(a.root, a.capability), indent=1))
            return 0
    except Refused as e:
        print(f"REFUSED: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
