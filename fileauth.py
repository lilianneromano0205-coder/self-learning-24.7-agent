#!/usr/bin/env python3
"""FILE AUTHORITY — one gateway for every model-influenced filesystem path.

Manual §19: *"File Authority — every caller must use it for any read/write
using an external or model-influenced path; mandatory controls: canonicalize;
containment; protected roots; symlink/junction checks; atomic write; trace."*
Manual §25.4: *"Separate agent-writable workspace from protected control
state and route all filesystem operations through File Authority."*

The audit found `_safe_path` guarding exactly two call sites while five
harness writers built `courses/<course>/…` paths from an unsanitised value —
one of which was shown writing outside the expert root entirely. The lesson
is the same one the Execution Authority answers: a control that lives at a
call site protects that call site and nothing else.

So containment is a typed ZONE, not a per-caller check:

    WORKSPACE   the agent's own work: courses, out, artifacts, answers,
                skills, teamwork, consults, goals, research, gotchas, cases
                -> agent may read and write
    CONTROL     what decides what the agent may do: settings.toml, mcp.json,
                prompts/, approvals/, variants/, state.json, prospective.json,
                effects.jsonl, the skill graph
                -> agent may READ some, may never write
    SECRET      credentials, by the one credential model
                -> never readable, never writable, never packaged
    RUNTIME     logs, contexts, checkpoints, events
                -> harness writes; agent does not

`resolve()` is the single function. It canonicalises, refuses traversal,
refuses symlinks and NTFS junctions that leave the root, classifies the zone
and enforces the zone's rule. `write_text()` adds atomic replacement so a
crash mid-write cannot leave a half-file where a whole one was.
"""

import errno
import hashlib
import json
import os
import time
import uuid

# ------------------------------------------------------------------- zones

CONTROL_FILES = {
    "settings.toml", "mcp.json", "state.json", "prospective.json",
    "routines.json", "org.json",
    # identity.md is a SYSTEM PROMPT SOURCE — loop.system_sources() puts it
    # in every window, right after the constitution — and the panel writes it
    # for the OWNER, with a backup and an identity.history.jsonl line stamped
    # `"by": "owner"`. It was nonetheless ZONE_ROOT, which this module treats
    # as workspace, so `write_file("identity.md", ...)` succeeded: an agent
    # could rewrite its own charter with the ordinary file tool, no shell
    # required — so even the Rule-of-Two roles that hold no run_command could
    # do it. Found by walking the zone model against what is actually read
    # into a prompt, rather than by reading the zone list.
    "identity.md",
    # the acquisition ledger. acquire.promote's own docstring is "the OWNER
    # grants trust. Never the agent, never the outcome" — and the file that
    # records that grant sat in the agent's writable zone.
    "acquisitions.json",
    # commons.write_digest materialises the FLEET'S shared lessons here and
    # context.compile loads it into every window as the commons block — the
    # one the compiler introduces as what the fleet learned. A worker that can
    # write it authors owner- and fleet-attributed instructions to itself.
    "commons-digest.md",
    # who changed the charter and when. The panel appends a row stamped
    # `"by": "owner"` on every identity edit; a worker that can write the file
    # can fabricate an owner edit that never happened, or erase the real ones.
    "identity.history.jsonl",
}
# `frontier` holds the sealed probe SPECS and the capability ledger. If the
# worker could write there through the ordinary write_file tool it could edit
# the test that says its own new tool works, which is the one thing the
# frontier exists to prevent.
CONTROL_DIRS = {"prompts", "approvals", "variants", "effects", "org",
                "frontier",
                # training/registry.json decides which checkpoint this fleet
                # considers promoted, and training/runs/*/manifest.json pins
                # the verifier hash that a candidate is measured against. Both
                # were ZONE_ROOT: an agent could register itself a candidate
                # and promote it by writing the file, with no CLI involved.
                "training",
                # THE ISOLATED INSTALL. acquire.py's capability probe replaces
                # sys.path with capabilities/<name> and imports from there,
                # then checks the module resolved to a real file inside that
                # directory — guards that a package the AGENT wrote passes as
                # easily as one pip installed. The probe was already moved out
                # of this directory for a related namespace-package false pass
                # (acquire.py's own comment records the measurement); the
                # install target itself stayed writable.
                "capabilities",
                # premise.quarantined reads root/commons/quarantine.md into
                # the PREMISE block as "the fleet withdrew this claim". The
                # fleet's real copy lives at HOME level (commons.py writes
                # there); nothing in the platform writes the per-root one, so
                # it existed only as an agent-forgeable alias for a
                # fleet-attributed warning the next window is told to obey.
                "commons"}
# Root-relative paths that are CONTROL wherever they sit, because the
# DIRECTORY around them is legitimately the agent's own workspace.
#
# skills/graph.json is the promotion ledger. skills.provenance_of says in as
# many words: "Trust comes from the GRAPH, which only the owner writes" — and
# the File Authority did not enforce it, because `skills` is a WORKSPACE_DIR
# (correctly: the agent must be able to write its own skill files) and zone_of
# judged only the head directory and the basename. So an agent could write
# skills/graph.json and record `provenance: own` against its own skill, which
# is the exact self-claim skills.py had already been hardened to refuse in the
# frontmatter — the module closed the front door and left the ledger writable.
# Bundled scripts run on that verdict.
#
# The general shape of the bug: four of harness.LEDGERS were control and the
# fifth was not, and nothing compared the two lists. tests/test_invariants.py
# walks harness.LEDGERS and asserts every one lands in ZONE_CONTROL, and
# tests/test_promotion_leakage.py enumerates every trust-defining path by
# name, so a ledger added later cannot quietly land in the workspace.
CONTROL_PATHS = {"skills/graph.json"}
# Files that are CONTROL wherever they appear under a workspace head. The
# goal contract is the definition of done, frozen before work begins, and
# its event ledger is the record of what happened — the two things a worker
# under pressure to finish would most profit from editing. goals/ stays a
# workspace (the worker writes plans and evidence notes there); these names
# inside it do not. The seal in org/ is the second lock: even a shell edit
# that gets past this zone check produces a TAMPER verdict, not a pass.
CONTROL_NAMES_IN = {
    # steering.jsonl / steering.md carry the OWNER'S live guidance into a
    # pursuit (steer.py). The harness writes them and injects them into the
    # worker's context; the worker itself must not — a worker that can
    # write "the owner says ship it" into its own guidance channel has
    # promoted itself to owner.
    "goals": {"contract.json", "events.jsonl", "goal.json",
              "steering.jsonl", "steering.md"},
    # A runbook is worker-authored (that is the point — the model writes
    # down what worked), but its TRUST is not: candidate/proven/quarantined
    # lives in trust.json and only the harness records outcomes there. An
    # author who could edit the ledger could promote their own procedure to
    # "proven" without the three verified wins that word means.
    "runbooks": {"trust.json"},
    # The stashed ARTIFACTS of a best-of-N attempt are the agent's own work
    # and stay writable. score.json is not: it records which attempt passed
    # its gate and what it scored, and `candidates.rank` is gate-first — so
    # an author who could write `"passed": true` could have the loop restore
    # the attempt the gate had just refused. (What closed the ESCAPE was
    # routing candidates.promote's destinations through this module; this
    # closes the grading beside it.)
    "candidates": {"score.json"},
    # The mission contract is the objective held OUTSIDE the transcript —
    # mission.py writes it as the harness and context.compile recompiles it
    # into every window "so the objective cannot drift out". A worker that
    # can rewrite it replaces the objective it was given with one it can
    # satisfy. goals/<id>/contract.json was already control for exactly this
    # reason; its older sibling was not.
    "missions": {"mission.json"},
    # mastery/<pack>/events.jsonl is what mastery.verdict computes MASTERED
    # from, and _event appends to it under the platform lock, calling it "the
    # evidence" in as many words. The sealed-pack architecture holds — the
    # transfer tasks and validators really are unreachable — but the ledger
    # the verdict is read from was not.
    "mastery": {"events.jsonl"},
    # courses/ is the agent's own workspace and stays writable; the SOURCE
    # AUTHORITY inside it is not. source-overrides.json is where an owner's
    # re-rating lives (sources.set_tier writes it), because a tier recorded
    # in the workspace ledger is now re-derived rather than trusted — see
    # sources.tier_of.
    "courses": {"source-overrides.json"},
    # proof/observations.jsonl is what proof.evaluate derives every proof
    # LEVEL from — hash-bound evidence that a subsystem earned its badge.
    # proof/ is the agent's workspace for proof packs, and the ledger inside
    # it was writable too: a worker could append observations and lift a
    # capability's badge without any test having run. Found by the
    # promotion-leakage suite (docs/DESIGN-P6.1, finding 11).
    "proof": {"observations.jsonl"},
    # memory/cases.jsonl records whether a FIX HELD — a case moves to
    # "fixed" only when a later gated task in the same subject passed, and
    # the record is injected into windows as "verified by a gate, not by
    # opinion" and read by the repeat-failure metric. memory/ was in no
    # zone table at all, so it fell to ZONE_ROOT, which the agent's file
    # tool may write: a worker could file its own fixes as verified. Found
    # by the Capability Ledger (docs/DESIGN-P7.2, finding 5).
    "memory": {"cases.jsonl"},
}
RUNTIME_DIRS = {"logs", "contexts", "checkpoints", "events", "archive"}
# the agent's own workspace: everything it is FOR
WORKSPACE_DIRS = {
    "courses", "out", "artifacts", "answers", "skills", "teamwork",
    "consults", "goals", "research", "gotchas", "cases", "briefing",
    "inbox", "exports", "federation", "reviews", "docs", "analysis",
    "seo", "copy", "radar", "scout", "finance", "tradeops", "ops",
    "exam", "proof", "missions", "runbooks",
}

ZONE_WORKSPACE = "workspace"
ZONE_CONTROL = "control"
ZONE_SECRET = "secret"
ZONE_RUNTIME = "runtime"
ZONE_ROOT = "root"          # loose files directly in the expert root


class Denied(Exception):
    """Containment said no. The message is what the agent is told."""


def zone_of(rel):
    """Classify a root-relative path. Pure string work — no disk access — so
    it is the same answer whether or not the file exists yet."""
    r = str(rel).replace("\\", "/").strip("/")
    if not r:
        return ZONE_ROOT
    parts = [p for p in r.split("/") if p]
    head = parts[0].lower()
    name = parts[-1].lower()
    if r.lower() in CONTROL_PATHS:
        return ZONE_CONTROL
    if head in CONTROL_DIRS or name in CONTROL_FILES:
        return ZONE_CONTROL
    # the panel keeps the last ten copies of a charter it replaced. They are
    # what a rollback restores FROM, so they are the charter, under another
    # name — and a name is all that kept them out of this zone.
    if name.startswith("identity.md.bak-"):
        return ZONE_CONTROL
    if name in CONTROL_NAMES_IN.get(head, ()):
        return ZONE_CONTROL
    if head in RUNTIME_DIRS:
        return ZONE_RUNTIME
    if head in WORKSPACE_DIRS:
        return ZONE_WORKSPACE
    return ZONE_ROOT


def _real(path):
    """realpath, tolerating a file that does not exist yet: resolve the
    deepest existing ancestor so a symlinked PARENT cannot smuggle a write
    outside the root just because the leaf is new."""
    p = os.path.abspath(path)
    probe = p
    tail = []
    while True:
        if os.path.exists(probe):
            return os.path.join(os.path.realpath(probe), *reversed(tail))
        parent = os.path.dirname(probe)
        if parent == probe:
            return os.path.realpath(p)
        tail.append(os.path.basename(probe))
        probe = parent


def resolve(root, rel, mode="read", actor="agent", allow_zones=None):
    """-> an absolute path inside `root`, or raise Denied.

    mode  : "read" | "write"
    actor : "agent"   — a model-influenced path; the zone rules apply
            "harness" — the platform's own write; still contained, but may
                        reach runtime/control state it owns
    """
    root_real = os.path.realpath(root)
    raw = str(rel).replace("\\", "/")
    if os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
        raise Denied(f"absolute paths are not accepted here: {rel}")
    full = _real(os.path.join(root_real, raw))
    if full != root_real and not full.startswith(root_real + os.sep):
        raise Denied(f"path escapes the expert root: {rel}")

    import credentials
    if credentials.is_secret(full, root_real):
        # wording kept verbatim: the tool contract "ERROR: ... secrets file"
        # is asserted by the guardrail tests and read by the model
        raise Denied(f"refusing access to a secrets file: {rel}")

    z = zone_of(raw)
    if allow_zones is not None and z not in allow_zones:
        raise Denied(f"{rel} is {z} state; this operation may only touch "
                     f"{', '.join(sorted(allow_zones))}")
    if actor == "agent" and mode == "write":
        if z == ZONE_CONTROL:
            raise Denied(
                f"refusing to write {rel}: control state defines what this "
                f"agent is allowed to do, so the agent does not get to edit "
                f"it. Use the tool that governs it — variants.py for "
                f"charters, approvals.py for decisions, the panel for "
                f"settings.")
        if z == ZONE_RUNTIME:
            raise Denied(
                f"refusing to write {rel}: {raw.split('/')[0]}/ is the "
                f"harness's own record of what happened. Rewriting it would "
                f"make the trace worthless as evidence.")
    return full


def read_text(root, rel, actor="agent", limit=None, encoding="utf-8"):
    p = resolve(root, rel, "read", actor)
    with open(p, "r", encoding=encoding, errors="replace") as f:
        return f.read() if limit is None else f.read(limit)


def write_text(root, rel, text, actor="agent", encoding="utf-8"):
    """Contained, then ATOMIC: write a unique temp beside the target and
    replace. A crash mid-write leaves the previous file whole rather than a
    truncated one, and two writers cannot share a scratch name."""
    p = resolve(root, rel, "write", actor)
    os.makedirs(os.path.dirname(p) or root, exist_ok=True)
    # a UUID, not PID + milliseconds: two writers in one process aiming at
    # one target inside the same millisecond must never share a scratch
    # name (docs/DESIGN-P6.1, finding 6)
    tmp = f"{p}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding=encoding) as f:
        f.write(text)
    for attempt in range(8):
        try:
            os.replace(tmp, p)
            return p
        except PermissionError:            # OneDrive briefly holds the target
            time.sleep(0.05 * (attempt + 1))
        except OSError as e:
            if e.errno != errno.EACCES:
                raise
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, p)
    return p


def read_bytes(root, rel, actor="agent"):
    p = resolve(root, rel, "read", actor)
    with open(p, "rb") as f:
        return f.read()


def sha256_bytes(root, rel, actor="agent"):
    """The digest of a file AS BYTES — the only honest evidence for a
    binary artifact. A text decode with replacement lets different files
    share one hash (docs/DESIGN-P6.1, finding 4). Streamed in 1 MiB chunks
    so a multi-gigabyte database or archive is never loaded whole
    (docs/DESIGN-P7.1, P1-B)."""
    p = resolve(root, rel, "read", actor)
    digest = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_bytes(root, rel, data, actor="agent"):
    """The binary twin of write_text — same containment, same atomic
    temp-beside-target-then-replace — for artifacts that are not text (a
    workbook). One mutation semantic, whatever the payload."""
    p = resolve(root, rel, "write", actor)
    os.makedirs(os.path.dirname(p) or root, exist_ok=True)
    # a UUID, not PID + milliseconds: two writers in one process aiming at
    # one target inside the same millisecond must never share a scratch
    # name (docs/DESIGN-P6.1, finding 6)
    tmp = f"{p}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    for attempt in range(8):
        try:
            os.replace(tmp, p)
            return p
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
        except OSError as e:
            if e.errno != errno.EACCES:
                raise
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, p)
    return p


def write_json(root, rel, obj, actor="agent", indent=1):
    return write_text(root, rel,
                      json.dumps(obj, indent=indent, ensure_ascii=False) + "\n",
                      actor=actor)


def describe():
    return {
        "workspace": {"dirs": sorted(WORKSPACE_DIRS),
                      "agent": "read + write", "why": "the agent's own work"},
        "control": {"dirs": sorted(CONTROL_DIRS), "files": sorted(CONTROL_FILES),
                    "agent": "read only",
                    "why": "defines what the agent is permitted to do"},
        "runtime": {"dirs": sorted(RUNTIME_DIRS), "agent": "read only",
                    "why": "the harness's own evidence of what happened"},
        "secret": {"agent": "no access",
                   "why": "resolved by credentials.py, never model-visible"},
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="the file authority")
    ap.add_argument("--root", default=".")
    ap.add_argument("--classify", help="show the zone of a relative path")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.classify:
        z = zone_of(a.classify)
        try:
            resolve(os.path.abspath(a.root), a.classify, "write", "agent")
            verdict = "agent MAY write"
        except Denied as e:
            verdict = f"agent may NOT write — {e}"
        print(f"{a.classify}\n  zone: {z}\n  {verdict}")
        return
    d = describe()
    if a.json:
        print(json.dumps(d, indent=1))
        return
    for zone, info in d.items():
        print(f"{zone.upper():<10} agent: {info['agent']:<12} {info['why']}")
        if info.get("dirs"):
            print(f"           {', '.join(info['dirs'])}")


if __name__ == "__main__":
    main()
