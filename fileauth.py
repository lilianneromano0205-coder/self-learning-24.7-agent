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
import json
import os
import time

# ------------------------------------------------------------------- zones

CONTROL_FILES = {
    "settings.toml", "mcp.json", "state.json", "prospective.json",
    "routines.json", "org.json",
}
CONTROL_DIRS = {"prompts", "approvals", "variants", "effects", "org"}
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
# fifth was not, and nothing compared the two lists. test_fileauth now walks
# harness.LEDGERS and asserts every one lands in ZONE_CONTROL, so a ledger
# added later cannot quietly land in the workspace.
CONTROL_PATHS = {"skills/graph.json"}
RUNTIME_DIRS = {"logs", "contexts", "checkpoints", "events", "archive"}
# the agent's own workspace: everything it is FOR
WORKSPACE_DIRS = {
    "courses", "out", "artifacts", "answers", "skills", "teamwork",
    "consults", "goals", "research", "gotchas", "cases", "briefing",
    "inbox", "exports", "federation", "reviews", "docs", "analysis",
    "seo", "copy", "radar", "scout", "finance", "tradeops", "ops",
    "exam", "proof", "missions",
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
    tmp = f"{p}.{os.getpid()}.{int(time.time() * 1000) % 100000}.tmp"
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
