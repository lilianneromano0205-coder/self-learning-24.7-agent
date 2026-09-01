#!/usr/bin/env python3
"""CONTROL PLANE AUTHORITY — the worker cannot change its own authority.

The File Authority (fileauth.py) put containment in a typed ZONE rather than
a per-caller check, and the `write_file` tool has refused to touch CONTROL
state ever since. An external audit then asked the obvious next question and
got the wrong answer:

    write_file("settings.toml", ...)                 -> REFUSED by fileauth
    run_command('python -c "open(\\'settings.toml\\',\\'w\\')..."')  -> WROTE IT

Measured, on the shipped default (`[agent] sandbox = "host"`), through a real
practitioner task: settings.toml, prompts/constitution.md and approvals/*.json
were all rewritten by a model-written command while the file tool was being
refused three lines earlier in the same transcript. Roles without an explicit
`tools` list — practitioner, examiner, ripper, default — hold run_command, so
this was not a corner case; it was the shipping configuration.

policy.py could not have caught it and says so in its own docstring: it reads
a STRING, and a program that string starts can go anywhere once it is running.
Adding control-path regexes there would have repeated the mistake the module
already warns about. And `sandbox = "docker"` did not fix it either, because
the container bind-mounted the whole expert root READ-WRITE at /work.

So containment for the control plane is enforced at the two places where it
can actually be enforced, and this module owns both:

  PREVENTION, where a kernel is available.  sandbox.py asks this module for
      `readonly_mounts(root)` and layers a read-only bind over every control
      path inside the container. Under `sandbox = "docker"` (and the hosted
      backends' equivalent) the worker cannot write its authority at all —
      the boundary is the kernel's, which is the standard the sandbox module
      already sets for itself.

  DETECT-AND-REVERT, on the host backend.  There is no filesystem boundary on
      `host` — REFERENCE.md §20 has always said so — so the invariant this
      module enforces there is deliberately weaker and stated exactly:

          a model-authored command cannot DURABLY change control state.

      Every model-authored execution is bracketed by a seal: the control zone
      is digested before the command and verified after. A mutation is
      reverted from the seal, the command's exit code is replaced with a
      failing one so no gate can pass on a tampered run, the model is told
      what it touched, and the event lands in logs/controlplane.jsonl.

      That is not prevention and this module does not call it prevention. It
      is the same standard the frontier already applies to its sealed probes
      ("even a shell edit that gets past this zone check produces a TAMPER
      verdict, not a pass") applied to the whole control plane.

WHAT IS SEALED, AND WHY IT IS NOT A SECOND LIST

The set is DERIVED from fileauth's zone model, not maintained here. A control
directory added to fileauth tomorrow is sealed tomorrow, with no edit in this
file — because the defect this codebase keeps finding is two descriptions of
one truth with nothing comparing them. `test_controlplane.py` asserts the
derivation, so the two cannot drift.

Three treatments, because three kinds of control state behave differently
under a fleet that legitimately runs several loops at once:

  SEALED       bytes must be identical. Creations are removed, deletions and
               edits are restored. settings.toml, prompts/, variants/,
               frontier/, org/, capability/, skills/graph.json, identity.md,
               runbooks/trust.json, goals/*/contract.json, goal event ledgers
               and the owner's steering channel all live here.
  PENDING_ONLY approvals/. A governed call may CREATE a pending request while
               a command runs (execution.run does exactly that). It may not
               create a decided one — self-granting is the escalation this
               guards — and it may not touch an existing decision.
  DETECT       state.json. Reported, never reverted, and the reason is worth
               reading: another loop on the same expert writes this file
               constantly, and reverting it would erase that loop's committed
               work — reintroducing the lost-update race locks.py exists to
               end. The compensating control is already in the loop: the very
               next `commit_task` merges the running task from memory over
               whatever is on disk, so a task cannot mark itself done by
               editing the queue. What remains — editing a SIBLING's record —
               fails the command loudly instead of silently succeeding.

THE HARNESS'S OWN APPENDS, and why they are not a hole

A goal's event ledger grows while a command runs: swarm.py fans workers out
as THREADS, so worker B appends `swarm_worker` to goals/<id>/events.jsonl
while worker A's command is still mid-flight. Sealing that file byte-for-byte
would report the platform tampering with itself.

The obvious fix — "a ledger may grow; its existing bytes may not change" —
was written here first and it is WRONG, which is worth stating because it
reads as right: `contract.replay` reconstructs a contract's state PURELY from
this ledger and says in as many words that when the ledger and the snapshot
disagree, THE LEDGER WINS. So an appended line is not a note, it is a state
transition, and a rule that lets anything append lets a worker append
`{"kind": "state", "to": "verified"}` and grade itself.

So growth is exempt only when THE HARNESS DID IT. `harness_wrote()` counts
the platform's own ledger appends in this process, the seal remembers the
count per path, and verify allows growth on a path whose count went up. A
shell command cannot reach that counter, and a command that runs
`python goal.py …` to append events is a different PROCESS with its own empty
counter — so it is tampering, which is the right answer.

Usage:
    python controlplane.py --root . --list       what is sealed, and how
    python controlplane.py --root . --verify     compare against a fresh seal
"""

import hashlib
import json
import os
import time

# a control file is small; this only stops a pathological one from being held
# in memory. Above it, a change is reported and named as unrestorable rather
# than silently ignored.
MAX_SEAL_BYTES = 4 * 1024 * 1024

# the exit code a tampering command is reported with. Nonzero on purpose: a
# gate must not pass, and step_failed must see a failure.
TAMPER_RC = 3

LEDGER = os.path.join("logs", "controlplane.jsonl")

SEALED = "sealed"
PENDING_ONLY = "pending_only"
DETECT = "detect"

# Directories inside the control zone where a pending record may legitimately
# appear while a command runs.
PENDING_ONLY_DIRS = {"approvals"}
# Control state written by a CONCURRENT loop, which therefore cannot be
# reverted without destroying that loop's work. Reported, not restored.
DETECT_ONLY_PATHS = {"state.json"}

# The platform's OWN ledger appends, counted per absolute path for the life of
# this process. See "THE HARNESS'S OWN APPENDS" above: growth on a sealed path
# is legitimate only when this counter moved, and nothing a model writes can
# move it.
_HARNESS_WRITES = {}


def harness_wrote(path):
    """The platform is about to append to one of its own ledgers. Called by
    the writer itself (contract.event today), never by anything that handles
    model output."""
    p = os.path.abspath(path)
    _HARNESS_WRITES[p] = _HARNESS_WRITES.get(p, 0) + 1
    return _HARNESS_WRITES[p]


class Tampered(Exception):
    """Raised only by `enforce` when a caller asks for the strict form."""


# --------------------------------------------------------------- enumeration

def treatment(rel):
    """How this control-zone path is treated. Pure string work."""
    r = str(rel).replace("\\", "/").strip("/")
    parts = [p for p in r.split("/") if p]
    if not parts:
        return SEALED
    # only the ROOT state.json — the task queue a sibling loop writes. Matched
    # by basename this also caught capability/state.json, which no sibling
    # writes and which therefore should be reverted like any other control
    # file; the exception exists for the concurrency, not for the name.
    if len(parts) == 1 and parts[0].lower() in DETECT_ONLY_PATHS:
        return DETECT
    if parts[0].lower() in PENDING_ONLY_DIRS:
        return PENDING_ONLY
    return SEALED


def control_paths(root):
    """Every control-zone file that exists under `root`, root-relative.

    DERIVED from fileauth, never listed twice. The walk is deliberately narrow
    — the control zone is a handful of small files, and a 24/7 fleet cannot
    afford to stat a courses/ tree on every single command.
    """
    import fileauth
    out = set()
    root = os.path.abspath(root)

    def add(rel):
        rel = rel.replace(os.sep, "/").strip("/")
        if rel and fileauth.zone_of(rel) == fileauth.ZONE_CONTROL:
            out.add(rel)

    # 1. loose files in the root (settings.toml, state.json, identity.md, ...)
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.is_file():
                    add(e.name)
    except OSError:
        return sorted(out)

    # 2. whole control directories
    # 3. the workspace heads that carry control NAMES inside them
    #    (goals/<id>/contract.json, runbooks/trust.json), and CONTROL_PATHS'
    #    own heads (skills/graph.json)
    #
    # A DIRECTORY'S LISTING IS CACHED ON ITS OWN mtime. Creating or deleting a
    # file changes the mtime of the directory holding it, and creations and
    # deletions are the only thing this enumeration is FOR — modifications are
    # caught by the per-file digest below. So a fleet with three thousand
    # approvals costs a few hundred stats per command instead of a full walk:
    # measured, the walk was the larger half of the seal's remaining cost.
    heads = set(fileauth.CONTROL_DIRS) | set(fileauth.CONTROL_NAMES_IN)
    heads |= {p.split("/", 1)[0] for p in fileauth.CONTROL_PATHS}
    for head in sorted(heads):
        base = os.path.join(root, head)
        if not os.path.isdir(base):
            continue
        for dirpath, names in _listing(base, root):
            for rel in names:
                add(rel)
    return sorted(out)


# dirpath -> (mtime_ns, [root-relative file paths], [subdirectory paths])
_LISTING_CACHE = {}

# A DIRECTORY MODIFIED THIS RECENTLY IS NOT TRUSTED TO ITS mtime.
#
# Caching a listing on the directory's mtime assumes two different listings
# always carry two different timestamps. They do not: filesystem timestamp
# RESOLUTION is coarse — commonly ~10-16 ms on NTFS, and one second on some
# filesystems — so a create, a delete and another create inside a single tick
# are indistinguishable from no change at all. The cache then serves a stale
# listing, and a file that exists in a CONTROL directory is never enumerated:
# not reported as created, and therefore never reverted. The control plane
# does not detect what it cannot list.
#
# Found by a CI failure that moved between Windows Python versions — the tell
# that it was a race and not a version. A planted .pyc survived the bracket
# because the enumeration that should have seen it reused a listing taken a
# few milliseconds earlier.
#
# So a directory whose mtime is inside the uncertainty window is re-scanned
# every time and never cached. Steady-state directories — which is nearly all
# of them, nearly always — keep the whole saving; a directory being written
# to right now pays a scandir, which is what correctness costs here.
_MTIME_UNCERTAINTY_NS = 2_000_000_000        # 2s: coarser than any FS in use


def _listing(base, root):
    """Walk `base`, reusing each directory's listing while its mtime holds."""
    out, stack = [], [base]
    now_ns = time.time_ns()
    while stack:
        d = stack.pop()
        try:
            m = os.stat(d).st_mtime_ns
        except OSError:
            continue
        settled = (now_ns - m) > _MTIME_UNCERTAINTY_NS
        hit = _LISTING_CACHE.get(d)
        if hit and hit[0] == m and settled:
            _mt, files, subs = hit
        else:
            files, subs = [], []
            try:
                with os.scandir(d) as it:
                    for e in it:
                        try:
                            if e.is_dir():
                                subs.append(e.path)
                            elif e.is_file():
                                files.append(os.path.relpath(e.path, root)
                                             .replace(os.sep, "/"))
                        except OSError:
                            continue
            except OSError:
                continue
            files.sort()
            subs.sort()
            if settled:          # never cache a listing that may still move
                _LISTING_CACHE[d] = (m, files, subs)
            else:
                _LISTING_CACHE.pop(d, None)
        out.append((d, files))
        stack.extend(subs)
    return out


# -------------------------------------------------------------------- seal
#
# WHY THERE IS A CACHE HERE, AND WHAT IT COSTS
#
# The first version re-read every control file on every model-authored
# command. Measured on a synthetic fleet with a few months of history — 3000
# approvals and 400 goal ledgers — that was 3.2 s per seal warm and 27 s cold,
# against 56 ms to merely stat the same files. A runbook issues a command per
# step, so the control that stops an agent editing settings.toml would have
# been the slowest thing in the platform, and the loop.py retention comment
# already records what happens to a fleet whose per-step cost creeps up: it
# grinds to a halt after a few weeks.
#
# So content is fingerprinted through a process-local cache keyed on
# (size, mtime_ns, ctime_ns). A file whose stat is unchanged reuses its
# hash AND its bytes — which is also what makes restoration possible without
# a shadow copy on disk.
#
# TWO TIERS, because a stat gate is weaker than a hash and the difference
# should land where it costs least:
#
#   CORE  — everything that defines authority: settings.toml, prompts/,
#           identity.md, the trust ledgers, the goal contracts. Bounded in
#           number (tens), so it is RE-HASHED on every command, cache or no
#           cache. No stat trick evades it.
#   BULK  — the two things that grow without bound as a fleet runs:
#           approvals/ (one file per approval, forever) and goal event
#           ledgers. Stat-gated.
#
# Measured after both caches (the content cache above and the directory
# listing cache in control_paths), per model-authored command:
#
#     brand new expert                 10 control paths      5.5 ms
#     a month of light use             50                   11.5 ms
#     a busy quarter                  330                   44.3 ms
#     years, or a very busy fleet    3810                  373.1 ms
#
# against 27 s for the same 3810-path fleet before. The first seal in a
# process is still a full read (~4 s at that size) because the cache starts
# empty; every command after it pays the numbers above.
#
# THE RESIDUAL LIMIT, stated rather than buried: a BULK file edited in place,
# at exactly the same length, with its timestamps restored afterwards, passes
# the stat gate. `ctime_ns` is in the key because on Linux — where a 24/7
# fleet actually runs — ctime moves on any metadata change including
# os.utime(), so the evasion does not work there. On Windows ctime is the
# creation time and does not move, so the gap is real on that platform, for
# bulk paths only. Everything that decides what the agent may do is CORE.

BULK_DIRS = {"approvals", "candidates"}
BULK_NAMES = {"events.jsonl"}

# abspath -> (size, mtime_ns, ctime_ns, sha, bytes|None)
_CONTENT_CACHE = {}
MAX_CACHE_BYTES = 64 * 1024 * 1024
_cache_bytes = 0


def is_bulk(rel):
    """Grows without bound as the fleet runs -> stat-gated, not re-hashed."""
    r = str(rel).replace("\\", "/").strip("/")
    parts = [p for p in r.split("/") if p]
    if not parts:
        return False
    return parts[0].lower() in BULK_DIRS or parts[-1].lower() in BULK_NAMES


def _stat_key(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns, getattr(st, "st_ctime_ns", 0))


def _read_digest(path):
    """-> (sha256, size, bytes|None). bytes is None above MAX_SEAL_BYTES."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return None, 0, None
    h = hashlib.sha256()
    keep = size <= MAX_SEAL_BYTES
    chunks = []
    try:
        with open(path, "rb") as f:
            while True:
                b = f.read(262144)
                if not b:
                    break
                h.update(b)
                if keep:
                    chunks.append(b)
    except OSError:
        return None, 0, None
    return h.hexdigest(), size, (b"".join(chunks) if keep else None)


def _digest(path, rel=None):
    """(sha, size, bytes) — cached for BULK paths, always read for CORE."""
    global _cache_bytes
    key = os.path.abspath(path)
    stat_key = _stat_key(path)
    if stat_key is None:
        _CONTENT_CACHE.pop(key, None)
        return None, 0, None
    bulk = is_bulk(rel if rel is not None else path)
    hit = _CONTENT_CACHE.get(key)
    if bulk and hit and hit[0] == stat_key:
        return hit[1], stat_key[0], hit[2]
    sha, size, blob = _read_digest(path)
    if sha is None:
        return None, 0, None
    if hit is not None and hit[2] is not None:
        _cache_bytes -= len(hit[2])
    if blob is not None and _cache_bytes + len(blob) > MAX_CACHE_BYTES:
        blob_cached = None            # keep the hash, drop the bytes
    else:
        blob_cached = blob
        if blob is not None:
            _cache_bytes += len(blob)
    _CONTENT_CACHE[key] = (stat_key, sha, blob_cached)
    return sha, size, blob


def seal(root):
    """A snapshot of the control zone, taken before every model-authored
    command. CORE paths are hashed; BULK paths reuse a cached hash when their
    stat is unchanged — see the note above for the cost that bought and the
    limit it carries."""
    root = os.path.abspath(root)
    files = {}
    for rel in control_paths(root):
        p = os.path.join(root, rel)
        sha, size, blob = _digest(p, rel)
        if sha is None:
            continue
        files[rel] = {"sha": sha, "size": size, "bytes": blob,
                      "how": treatment(rel), "bulk": is_bulk(rel),
                      "writes": _HARNESS_WRITES.get(os.path.abspath(p), 0)}
    return {"root": root, "files": files, "at": time.time()}


def _prefix_sha(path, n):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            left = n
            while left > 0:
                b = f.read(min(262144, left))
                if not b:
                    return None
                h.update(b)
                left -= len(b)
    except OSError:
        return None
    return h.hexdigest()


def _is_pending_request(path):
    """A newly created approvals/*.json may only be an UNDECIDED request."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(rec, dict) and rec.get("status") == "pending"


def verify(root, before):
    """-> list of violations. Each names the path, what happened, and how the
    path is treated. Pure observation: nothing is written here."""
    root = os.path.abspath(root)
    now = set(control_paths(root))
    was = dict(before.get("files") or {})
    bad = []

    for rel, rec in sorted(was.items()):
        how = rec["how"]
        p = os.path.join(root, rel)
        if not os.path.exists(p):
            bad.append({"path": rel, "how": how, "what": "deleted"})
            continue
        sha, size, _blob = _digest(p, rel)
        if sha == rec["sha"]:
            continue
        # GROWTH THE HARNESS ITSELF CAUSED. Only this: the same file growing
        # with nobody in this process having appended to it is tampering, and
        # a ledger line is a state transition (contract.replay lets the ledger
        # overrule the snapshot), so "it only appended" is not a defence.
        grew = (size >= rec["size"]
                and _prefix_sha(p, rec["size"]) == rec["sha"])
        if grew and _HARNESS_WRITES.get(os.path.abspath(p), 0) >                 rec.get("writes", 0):
            continue
        bad.append({"path": rel, "how": how,
                    "what": "appended" if grew else "modified"})

    for rel in sorted(now - set(was)):
        how = treatment(rel)
        if how == PENDING_ONLY and _is_pending_request(os.path.join(root, rel)):
            continue                          # a governed call asked the owner
        bad.append({"path": rel, "how": how, "what": "created"})
    return bad


def restore(root, before, violations):
    """Put the control zone back. -> list of paths this could NOT restore.

    DETECT paths are never restored — see the module docstring. Anything whose
    bytes were too large to seal is reported here rather than pretended away.
    """
    root = os.path.abspath(root)
    files = dict(before.get("files") or {})
    unrestored = []
    for v in violations:
        rel, how, what = v["path"], v["how"], v["what"]
        p = os.path.join(root, rel)
        if how == DETECT:
            unrestored.append(rel)
            continue
        try:
            if what == "created":
                # RETRY THE DELETE. On Windows a file that was written moments
                # ago can be briefly undeletable — an antivirus scan, the
                # search indexer, or a lagging handle from the writer — and
                # os.remove raises PermissionError. A single attempt made this
                # the one revert that could quietly fail under load: a planted
                # .pyc surviving the bracket is precisely what this control
                # exists to prevent, and it was seen doing so once on a loaded
                # CI runner. Same shape as the retry loops in tests/common.py
                # and evaluation_workspace.arena, for the same reason.
                for attempt in range(5):
                    try:
                        os.remove(p)
                        break
                    except FileNotFoundError:
                        break                    # already gone: the goal
                    except OSError:
                        if attempt == 4:
                            raise
                        time.sleep(0.1 * (attempt + 1))
                continue
            blob = (files.get(rel) or {}).get("bytes")
            if blob is None:
                unrestored.append(rel)
                continue
            os.makedirs(os.path.dirname(p) or root, exist_ok=True)
            tmp = f"{p}.{os.getpid()}.cprestore"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, p)
        except OSError:
            unrestored.append(rel)
    return unrestored


def note(root, event, **fields):
    """Every verdict leaves a line. A control nobody can audit afterwards is
    a control nobody governs — the same rule execution.py's trace follows."""
    try:
        d = os.path.join(root, "logs")
        os.makedirs(d, exist_ok=True)
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event}
        rec.update(fields)
        with open(os.path.join(root, LEDGER), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def describe_violations(violations, unrestored):
    """The text the MODEL reads. It names the rule, what it touched, and what
    to do instead — the same shape as a policy refusal."""
    touched = ", ".join(f"{v['path']} ({v['what']})" for v in violations[:8])
    more = f" (+{len(violations) - 8} more)" if len(violations) > 8 else ""
    tail = ""
    if unrestored:
        tail = (f"\nNOT REVERTED (a sibling loop owns these and reverting "
                f"would destroy its work): {', '.join(unrestored[:5])}. This "
                f"is recorded as tampering and the owner will see it.")
    return (
        f"CONTROL PLANE TAMPER — this command changed state that defines what "
        f"this agent is allowed to do: {touched}{more}. The change has been "
        f"REVERTED and this command is reported as failed regardless of its "
        f"exit code.\n"
        f"Control state is not yours to edit — that is the same rule the "
        f"write_file tool enforces, and running a program does not lift it. "
        f"Use the tool that governs the thing you were trying to change "
        f"(variants.py for charters, approvals.py for decisions, the panel "
        f"for settings), or ask_human.{tail}")


def _is_bytecode(rel):
    """Interpreter cache, not control state: __pycache__/ contents and bare
    .pyc/.pyo files. These are DERIVED from the sealed .py sources by the
    import machinery itself."""
    r = str(rel).replace("\\", "/")
    return "/__pycache__/" in r or r.endswith((".pyc", ".pyo"))


def enforce(root, before, op="", command="", role="", task=None):
    """The bracket's closing half. -> (clean, message).

    `clean` is True when nothing in the control zone moved. Otherwise the
    mutation is reverted, the event is recorded, and `message` is what the
    model is told.

    One class is reverted WITHOUT convicting: interpreter bytecode. The first
    real acquisition ladder run after capabilities/ became control state
    proved why — the capability probe imported the freshly installed package,
    the import wrote __pycache__/__init__.cpython-314.pyc inside it, and a
    probe that exited 0 was reported as TAMPER (test_acquire, 2026-08-30).
    Any host-backend command that legitimately imports an adopted capability
    would fail the same way. Bytecode is derived state, so it cannot carry a
    verdict — but it IS still reverted, every time, because a planted .pyc is
    a real attack: Python loads matching cache instead of recompiling, and a
    sourceless .pyc imports outright. Reverting denies both persistence; the
    writer's own process was already the writer's to control. The cleanse is
    recorded in the ledger, so an owner can still see who keeps shedding
    bytecode where.
    """
    violations = verify(root, before)
    if not violations:
        return True, ""
    cache = [v for v in violations if _is_bytecode(v["path"])]
    real = [v for v in violations if not _is_bytecode(v["path"])]
    if not real:
        unrestored = restore(root, before, cache)
        for v in cache:
            try:                     # the emptied __pycache__ dir itself
                os.rmdir(os.path.dirname(os.path.join(root, v["path"])))
            except OSError:
                pass
        note(root, "bytecode_cleansed", op=op, role=role, task=task,
             cmd=str(command)[:400], violations=cache, unrestored=unrestored)
        return True, ""
    unrestored = restore(root, before, violations)
    note(root, "control_plane_tamper", op=op, role=role, task=task,
         cmd=str(command)[:400], violations=violations,
         unrestored=unrestored)
    return False, describe_violations(violations, unrestored)


# ------------------------------------------------------- prevention (docker)

def readonly_mounts(root):
    """-> [(host_abs_path, container_path)] to bind read-only over /work.

    Docker applies the most specific mount, so a read-only bind at
    /work/settings.toml wins over the read-write /work beneath it. Only paths
    that EXIST are returned: docker creates a missing source as a directory,
    which would turn settings.toml into a folder.

    Directories are mounted whole rather than file-by-file so a file created
    inside prompts/ during the run cannot appear either.
    """
    import fileauth
    root = os.path.abspath(root)
    out = []
    seen = set()

    def take(rel):
        rel = rel.replace(os.sep, "/").strip("/")
        if not rel or rel in seen:
            return
        p = os.path.join(root, rel.replace("/", os.sep))
        if os.path.exists(p):
            seen.add(rel)
            out.append((p.replace("\\", "/"), "/work/" + rel))

    for d in sorted(fileauth.CONTROL_DIRS):
        take(d)
    for name in sorted(fileauth.CONTROL_FILES):
        take(name)
    for rel in sorted(fileauth.CONTROL_PATHS):
        take(rel)
    # identity.md and any other loose control file the zone model recognises
    try:
        for name in sorted(os.listdir(root)):
            if os.path.isfile(os.path.join(root, name)) and \
                    fileauth.zone_of(name) == fileauth.ZONE_CONTROL:
                take(name)
    except OSError:
        pass
    # the named control files that live inside workspace heads
    for head, names in sorted(fileauth.CONTROL_NAMES_IN.items()):
        base = os.path.join(root, head)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for fn in sorted(filenames):
                if fn.lower() in names:
                    take(os.path.relpath(os.path.join(dirpath, fn), root))
    return out


# ------------------------------------------------------------- the owner gate

def inside_agent_task():
    """Is this process running underneath a model's command?

    The markers are the ones sandbox.py passes into every model-authored
    command (AGENT_TASK_ID / AGENT_ROLE), and the idiom is frontier.py's,
    which has refused adoption from inside a task since it was written.

    HONEST LIMIT, because this module refuses to promise containment it does
    not have: a command can unset an environment variable. This gate stops the
    straightforward call — `python training.py promote ...` typed by a model —
    and it is NOT the load-bearing control. The seal is: whatever these CLIs
    write lands in the control zone, and the bracket around the command
    reverts it. Two independent controls, neither relying on the other.
    """
    return bool(os.environ.get("AGENT_TASK_ID")
                or os.environ.get("AGENT_ROLE"))


def owner_only(action):
    """Refuse an owner-level action attempted from inside an agent task."""
    if inside_agent_task():
        raise SystemExit(
            f"REFUSED: {action} is an OWNER action — it changes what this "
            f"fleet's agents are allowed to do — and this process is running "
            f"inside an agent task (AGENT_TASK_ID/AGENT_ROLE are set). Run it "
            f"yourself from a terminal.")


# -------------------------------------------------------------------- CLI

def main():
    import argparse
    ap = argparse.ArgumentParser(description="the control plane authority")
    ap.add_argument("--root", default=".")
    ap.add_argument("--list", action="store_true",
                    help="what is sealed, and under which treatment")
    ap.add_argument("--verify", action="store_true",
                    help="seal, then immediately verify (a self-check)")
    ap.add_argument("--mounts", action="store_true",
                    help="the read-only binds the docker backend layers on")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.mounts:
        rows = readonly_mounts(root)
        print(json.dumps(rows, indent=1) if a.json else
              "\n".join(f"{h} -> {c}:ro" for h, c in rows) or "(nothing)")
        return
    if a.verify:
        s = seal(root)
        bad = verify(root, s)
        print(json.dumps(bad, indent=1) if a.json else
              (f"{len(s['files'])} sealed path(s); "
               f"{len(bad)} violation(s) — {bad if bad else 'clean'}"))
        raise SystemExit(1 if bad else 0)
    s = seal(root)
    if a.json:
        print(json.dumps({rel: {"how": r["how"], "size": r["size"],
                                "sha": r["sha"][:16]}
                          for rel, r in s["files"].items()}, indent=1))
        return
    print(f"CONTROL PLANE — {len(s['files'])} path(s) under {root}")
    for rel, r in s["files"].items():
        print(f"  {r['how']:<13}{r['size']:>9}  {rel}")
    if not s["files"]:
        print("  (nothing — is this an expert root?)")


if __name__ == "__main__":
    main()
