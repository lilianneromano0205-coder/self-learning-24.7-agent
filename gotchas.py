#!/usr/bin/env python3
"""ENVIRONMENT GOTCHAS — the failures this expert already paid for.

LongMemEval-V2 (arXiv 2605.12493) measured what actually separates an
"experienced operator" agent from a fresh one, and two of its five abilities
are not knowledge at all: WORKFLOW KNOWLEDGE (how work gets done here) and
ENVIRONMENT GOTCHAS (this tool lies about success; that endpoint rate-limits
at 3/s; this repo needs the venv activated first). Its winning system stored
trajectories as FILES and had the agent search them — beating vector RAG by
24 points. This module is that memory kind, made explicit.

Every structured failure record the harness files (memory.record_failure)
becomes a one-line gotcha, scoped to where it will bite again:

    courses/<course>/gotchas.md     failures while working that material
    gotchas/mcp-<server>.md         failures while calling that MCP server
    gotchas/general.md              everything else

Each entry carries a TRIGGER (the words that should summon it), WHEN (the
category plus the harness's own error text), DO (the remedy for that failure
class) and the task it came from:

  - [2026-08-21] (F-1234567890) TRIGGER: kafka, broker, lag, tool_misuse |
    WHEN tool_misuse: run_command exited 127 | DO read the tool's error text
    and fix the arguments before repeating it | src: task a1b2c3

A repeat does not duplicate the line — it appends `x2 hit again <date>`, so a
recurring gotcha becomes visibly recurring. The context compiler injects the
matching entries as a fenced, binding block: an expert that has burned itself
on a thing should never walk into it a second time.
"""

import json
import os
import re
import threading
import time

STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
        "at", "by", "from", "into", "that", "this", "it", "is", "are", "be",
        "was", "were", "do", "does", "did", "as", "if", "then", "than",
        "when", "while", "run", "task", "please", "make", "get", "use",
        "using", "your", "you", "its", "their", "there", "here", "all",
        "any", "one", "two", "new", "old"}

REMEDY = {
    "false_success": "prove it with the gate command before claiming done",
    "hallucination": "cite a defined atom or write NOT IN MY TRAINING",
    "bad_retrieval": "search the notes and the archives before answering",
    "context_loss": "re-read the task's constraints before the next step",
    "planning": "change the approach instead of repeating the failing step",
    "tool_misuse": "read the tool's error text and fix the arguments",
    "missing_evidence": "gather the proof the task requires first",
    "wrong_assumption": "verify the assumption against a source first",
    "coordination": "restate the handoff contract before delegating again",
    "budget": "narrow the scope so the work fits the ceiling",
    "security": "stay inside the agent root and the allowed commands",
    "infrastructure": "retry with backoff, then switch provider",
    "model_limitation": "emit exactly one well-formed tool call per step",
    "premature_stop": "the goal was still reachable -- keep going",
    "eval_gaming": "satisfy the work, not the check",
    "unknown": "read the error text before repeating the step",
}

ENTRY_RE = re.compile(
    r"^- \[(?P<date>[\d-]+)\] \((?P<fid>[\w-]+)\) TRIGGER: (?P<trigger>[^|]*)"
    r"\| WHEN (?P<when>[^|]*)\| DO (?P<do>[^|]*)\| src: task (?P<src>\S+)"
    r"(?P<tail>.*)$")
MCP_CALL_RE = re.compile(r"mcp\.py[\"']?\s+call\s+([a-z0-9_.-]+)", re.I)
HEADER = ("# GOTCHAS — environment failures already paid for here.\n"
          "# One line per failure: what summons it, what happened, what to do.\n\n")
MAX_INJECT = 8


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 2 and w not in STOP}


def _scopes(root, task, rec):
    """Where would this failure bite again?"""
    out = []
    course = (task or {}).get("course") or (rec or {}).get("course")
    if course:
        out.append(os.path.join("courses", str(course), "gotchas.md"))
    servers = set()
    for step in (task or {}).get("steps", []) or []:
        blob = f"{step.get('args', '')} {step.get('result', '')}"
        servers.update(m.lower() for m in MCP_CALL_RE.findall(blob))
    for s in sorted(servers):
        out.append(os.path.join("gotchas", f"mcp-{s}.md"))
    if not out:
        out.append(os.path.join("gotchas", "general.md"))
    return out


def _trigger_words(task, rec):
    goal = (rec or {}).get("goal") or (task or {}).get("goal") or ""
    picked = []
    for w in re.findall(r"[a-z0-9]+", goal.lower()):
        if len(w) > 2 and w not in STOP and w not in picked:
            picked.append(w)
        if len(picked) >= 6:
            break
    cat = (rec or {}).get("category") or "unknown"
    if cat not in picked:
        picked.append(cat)
    return picked


# A gotcha is BINDING and it is injected into a window with room for
# MAX_INJECT of them. That makes a STALE gotcha strictly worse than no gotcha:
# it evicts a live warning, and it forbids a step that now works. "pandoc is
# not on PATH" was true in March and false in April, and nothing in this file
# could ever notice.
#
# The tempting signal is silence — "nobody has hit this in 200 tasks, retire
# it". That signal is a lie, and it is the same lie this codebase keeps
# finding: a gotcha is silent when it is OBSOLETE and equally silent when it
# is WORKING, because everyone is obeying it. Retiring on silence retires
# exactly the fences that are load-bearing.
#
# So retirement requires DIRECT evidence: the specific thing that failed was
# tried again, by a later task, and it worked. That means a gotcha has to
# record what it was about in a form a later step can be compared against —
# a PROBE. Only two kinds of failure yield an honest probe:
#
#   cmd:<executable>   the step ran a command and the command was the problem
#   mcp:<server>       the step called an MCP server and the server was
#
# Everything else (a model_limitation, a premature_stop, a reasoning error)
# gets NO probe and is never auto-retired, because nothing a later task does
# could prove it gone. Under-retiring costs a context slot. Over-retiring
# deletes a warning that was still true, so the bias is deliberate.
_CMD_KEYS = ("cmd", "command")
# ":" is in the class so a Windows absolute path survives: without it
# `C:\tools\pandoc.exe` matched only "C" and every such gotcha probed as
# `cmd:c`, which would let ANY command retire it.
_EXE_RE = re.compile(r"[A-Za-z0-9_.:\-/\\]+")
_SKIP = ("sudo", "env", "nice", "time", "exec", "command")
# For these, the executable name says nothing about what actually failed:
# `python3 -m pytest` failing because pytest is missing must NOT be retired by
# a later `python3 --version` that works. The first non-flag argument is the
# real subject, so the probe carries it.
_GENERIC = {"python", "python3", "py", "node", "npx", "npm", "pnpm", "yarn",
            "pip", "pip3", "git", "docker", "kubectl", "apt", "apt-get",
            "brew", "dotnet", "cargo", "go", "gh", "systemctl", "sh", "bash",
            "cmd", "powershell", "pwsh", "poetry", "uv", "make"}
_RETIRED_RE = re.compile(r"\| RETIRED (?P<rdate>[\d-]+) by task (?P<rsrc>\S+)")
_PROBE_RE = re.compile(r"\| probe: (?P<probe>\S+)")


def _executable(cmd):
    r"""The subject of a command line: the program, plus its subcommand when
    the program alone does not identify the work.

    `pandoc report.docx -o out.md` and `C:\tools\pandoc.exe --version` are
    the same probe, because "is pandoc reachable" is what the gotcha was
    about. But `git push` and `git status` are NOT the same probe — a push
    that fails on credentials must not be retired by a status that works — so
    for a generic runner the first non-flag argument comes along.
    """
    toks = (cmd or "").strip().split()
    i = 0
    while i < len(toks):
        tok = toks[i]
        tail = tok.replace("\\", "/").rsplit("/", 1)[-1]
        if "=" in tail and not tok.startswith("-"):
            i += 1                        # FOO=bar prefix
            continue
        if tail.lower() in _SKIP:
            i += 1
            continue
        break
    if i >= len(toks):
        return ""
    m = _EXE_RE.match(toks[i])
    if not m:
        return ""
    base = m.group(0).replace("\\", "/").rsplit("/", 1)[-1]
    exe = (base.rsplit(".", 1)[0] if "." in base else base).lower()
    if not exe:
        return ""
    if exe in _GENERIC:
        for arg in toks[i + 1:]:
            if arg.startswith("-"):
                continue
            sub = arg.replace("\\", "/").rsplit("/", 1)[-1].lower()
            sub = sub.rsplit(".", 1)[0] if "." in sub else sub
            if sub:
                return f"{exe}:{sub}"
        return exe
    return exe


def probe_of(step):
    """What a single step TRIED, as a comparable name, or None.

    None means "this step cannot prove anything about any gotcha", which is
    the common case and the safe one.
    """
    if not step:
        return None
    blob = f"{step.get('args', '')} {step.get('result', '')}"
    srv = MCP_CALL_RE.search(blob)
    if srv:
        return f"mcp:{srv.group(1).lower()}"
    if step.get("tool") != "run_command":
        return None
    args = step.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, TypeError):
            args = {}
    if not isinstance(args, dict):
        return None
    for k in _CMD_KEYS:
        if args.get(k):
            exe = _executable(str(args[k]))
            return f"cmd:{exe}" if exe else None
    return None


def probes_that_passed(task, failed):
    """The probes a finished task PROVED work.

    `failed` is the caller's step-failure test — loop.step_failed — passed in
    rather than reimplemented here, so there is exactly one definition of "a
    step failed" in the platform and this module stays a leaf.
    """
    out = set()
    for step in (task or {}).get("steps", []) or []:
        if failed(step.get("result", "")):
            continue
        pr = probe_of(step)
        if pr:
            out.add(pr)
    return out


def entry_line(rec, trigger, when, do, src, probe=None):
    line = (f"- [{time.strftime('%Y-%m-%d')}] ({rec.get('failure_id', 'F-0')}) "
            f"TRIGGER: {', '.join(trigger)} | WHEN {when} | DO {do} | "
            f"src: task {src}")
    # appended AFTER src, which ENTRY_RE captures loosely as `tail` — so a
    # gotcha file written before probes existed still parses, and simply
    # never auto-retires. Old evidence keeps its meaning.
    if probe:
        line += f" | probe: {probe}"
    return line + "\n"


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _write(path, text):
    """UNIQUE temp. The shared `path + ".tmp"` is the one every other ledger
    in this platform stopped using: two writers share the scratch name, one
    os.replace lands first and the second raises FileNotFoundError — which
    the loop logs as `gotcha_failed` and the warning is simply never filed.
    Compare prospective.py, checkpoint.py and skills.py, which all key the
    temp on the process."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


# THE READ-MODIFY-WRITE IS A CRITICAL SECTION, like every other ledger here.
# gotchas.py was the one that had neither a lock nor a unique temp: two loops
# filing a warning at the same moment could each read the file, each append
# their own line, and the later write would drop the earlier warning
# outright. locks.py's own docstring names this as the platform's standing
# race; this module was simply missed.

def _hold(path):
    # the directory has to exist before the LOCKFILE can: _write makes it,
    # and _write now runs inside this lock rather than before it
    import locks
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return locks.holding(path, timeout=10.0, stale=8.0)


def from_failure(root, task, rec):
    """Turn one structured failure record into gotcha entries. Returns the
    relative paths written."""
    if not rec:
        return []
    cat = rec.get("category") or "unknown"
    cause = " ".join((rec.get("cause") or rec.get("actual") or "").split())[:160]
    when = f"{cat}: {cause or 'no error text'}"
    do = REMEDY.get(cat, REMEDY["unknown"])
    trigger = _trigger_words(task, rec)
    src = (task or {}).get("id") or rec.get("task_id") or "unknown"
    # The probe comes from the step that was in flight when the task died —
    # the last one. A failure with no runnable subject (a reasoning error, a
    # premature stop) yields None, and such a gotcha simply never auto-retires.
    steps = (task or {}).get("steps") or []
    probe = probe_of(steps[-1]) if steps else None
    written = []
    for rel in _scopes(root, task, rec):
        path = os.path.join(root, rel)
        with _hold(path):
            written += _file_failure(path, rel, rec, trigger, when, do, src,
                                     probe)
    return written


def _file_failure(path, rel, rec, trigger, when, do, src, probe):
    """One gotcha file's read-modify-write, held by the caller's lock.

    Split out of from_failure so the whole cycle — read, dedupe, rewrite —
    happens inside one critical section. It used to be an unlocked
    read-modify-write per file, so two loops filing a warning at the same
    moment each read the old body and the later write dropped the earlier
    warning outright.
    """
    written = []
    body = _read(path) or HEADER
    # dedupe on (scope, when): a repeat is a COUNT, not a new line
    hit = None
    for line in body.splitlines():
        m = ENTRY_RE.match(line)
        if m and m.group("when").strip() == when:
            hit = line
            break
    if hit:
        n = 2
        mt = re.search(r"x(\d+) hit again", hit)
        if mt:
            n = int(mt.group(1)) + 1
        new = re.sub(r"\s*\| x\d+ hit again [\d-]+$", "", hit)
        # A RESURRECTION is the most important thing this file can record.
        # The warning was withdrawn because a later task ran the same
        # thing successfully — and here it is failing again. That means
        # the environment is FLAPPING, not fixed, and an intermittent
        # failure is worth more attention than a steady one because it is
        # the kind that passes review and breaks in production. So the
        # retirement is lifted (the gotcha binds again) and the fact that
        # it came back from retirement is kept in the line forever.
        was = _RETIRED_RE.search(new)
        if was:
            new = _RETIRED_RE.sub("", new).rstrip()
            new += (f" | UNRETIRED {time.strftime('%Y-%m-%d')} "
                    f"(disproved {was.group('rdate')} by task "
                    f"{was.group('rsrc')}, then failed again)")
        new += f" | x{n} hit again {time.strftime('%Y-%m-%d')}"
        body = body.replace(hit, new)
    else:
        if not body.endswith("\n"):
            body += "\n"
        body += entry_line(rec, trigger, when, do, src, probe)
    _write(path, body)
    written.append(rel.replace(os.sep, "/"))
    return written


def _gotcha_files(root, course=None):
    """Every gotcha file that applies here, newest last. One definition,
    because load() and retire() must agree about what they are looking at —
    a retirement written to a file the loader never reads is a no-op that
    reports success."""
    rels = []
    if course:
        rels.append(os.path.join("courses", str(course), "gotchas.md"))
    gdir = os.path.join(root, "gotchas")
    try:
        for fn in sorted(os.listdir(gdir)):
            if fn.endswith(".md"):
                rels.append(os.path.join("gotchas", fn))
    except OSError:
        pass
    return rels


def load(root, course=None, include_retired=False):
    """Every gotcha entry that could apply here, newest file last.

    A RETIRED entry is not returned by default: it has been disproved by a
    later task that ran the same thing successfully, so it must stop being
    injected and stop occupying one of the MAX_INJECT slots. It is NOT
    deleted — the line stays in the file with the date and the task id that
    disproved it, because "this warning was withdrawn, here is who withdrew
    it and what they ran" is the audit trail, and a fleet that silently
    rewrites its own history cannot be checked by anyone. `include_retired`
    is how the ledger and the tests read it back.
    """
    rels = _gotcha_files(root, course)
    out = []
    for rel in rels:
        for line in _read(os.path.join(root, rel)).splitlines():
            m = ENTRY_RE.match(line)
            if not m:
                continue
            d = m.groupdict()
            d["scope"] = rel.replace(os.sep, "/")
            d["trigger_words"] = [w.strip().lower()
                                  for w in d["trigger"].split(",") if w.strip()]
            d["repeats"] = int(re.search(r"x(\d+) hit again", line).group(1)) \
                if "hit again" in line else 1
            pm = _PROBE_RE.search(line)
            d["probe"] = pm.group("probe") if pm else None
            rm = _RETIRED_RE.search(line)
            d["retired"] = (rm.group("rdate"), rm.group("rsrc")) if rm else None
            out.append(d)
    return out if include_retired else [d for d in out if not d["retired"]]


def retire(root, probes, task_id, course=None):
    """Withdraw every gotcha a later task DISPROVED. Returns what it withdrew.

    `probes` is what a finished task PROVED works — see probes_that_passed().
    A gotcha whose probe is in that set was about a thing that has now been
    run successfully, so the warning is false and must stop being injected.

    Why this is evidence and not a guess: the alternative signal is silence
    ("nobody has hit this in 200 tasks"), and silence cannot distinguish an
    obsolete gotcha from a load-bearing one that everybody is obeying.
    Retiring on silence retires exactly the fences that are still holding.
    Running the command and watching it exit 0 has no such ambiguity.

    The line is MARKED, never deleted. Anyone auditing this fleet can see
    what was withdrawn, when, and which task's successful step withdrew it —
    and if it ever fails again, from_failure() un-retires it and records the
    resurrection, because a warning that came back is worth more than one
    that never left.
    """
    probes = {p for p in (probes or []) if p}
    if not probes:
        return []
    out = []
    stamp = time.strftime("%Y-%m-%d")
    for rel in _gotcha_files(root, course):
        path = os.path.join(root, rel)
        with _hold(path):
            out += _retire_file(path, rel, probes, task_id, stamp)
    return out


def _retire_file(path, rel, probes, task_id, stamp):
    """One gotcha file's retirement pass, held by the caller's lock."""
    out = []
    body = _read(path)
    if not body:
        return out
    changed = False
    lines = body.splitlines(True)
    for i, line in enumerate(lines):
        m = ENTRY_RE.match(line.rstrip("\n"))
        if not m:
            continue
        pm = _PROBE_RE.search(line)
        if not pm or pm.group("probe") not in probes:
            continue
        if _RETIRED_RE.search(line):
            continue                        # already withdrawn
        lines[i] = (line.rstrip("\n") +
                    f" | RETIRED {stamp} by task {task_id}\n")
        changed = True
        out.append({"scope": rel.replace(os.sep, "/"),
                    "when": m.group("when").strip(),
                    "probe": pm.group("probe"),
                    "by": task_id})
    if changed:
        _write(path, "".join(lines))
    return out


def matching(root, goal, course=None, cap=MAX_INJECT):
    """Phrase-aware trigger match, exactly like the skill fetch rule: a
    trigger fires when every word of it appears in the goal."""
    gw = words(goal)
    hits = []
    for g in load(root, course):
        fired = [t for t in g["trigger_words"]
                 if set(re.findall(r"[a-z0-9]+", t)) & gw and
                 set(w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2) <= gw]
        if len(fired) >= 2 or (fired and g["repeats"] > 1):
            g["fired_on"] = fired
            hits.append(g)
    hits.sort(key=lambda g: (-g["repeats"], -len(g["fired_on"])))
    return hits[:cap]


def render(hits):
    if not hits:
        return ""
    lines = ["GOTCHAS — failures this expert already paid for. These are "
             "BINDING: do not re-run a step that is listed here as failing "
             "without changing what the DO line says to change."]
    for g in hits:
        rep = f" (hit {g['repeats']}x)" if g["repeats"] > 1 else ""
        lines.append(f"- WHEN {g['when'].strip()}{rep} -> DO {g['do'].strip()} "
                     f"[{g['scope']}, task {g['src']}]")
    return "\n".join(lines)


def summary(root):
    every = load(root, include_retired=True)
    g = [e for e in every if not e["retired"]]
    by_scope = {}
    for e in g:
        by_scope.setdefault(e["scope"], 0)
        by_scope[e["scope"]] += 1
    return {"total": len(g), "by_scope": by_scope,
            "repeats": sum(1 for e in g if e["repeats"] > 1),
            "retired": sum(1 for e in every if e["retired"]),
            "probed": sum(1 for e in g if e["probe"])}


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="environment gotchas")
    ap.add_argument("--root", default=".")
    ap.add_argument("--goal", help="show the gotchas this goal would summon")
    ap.add_argument("--course")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.goal:
        hits = matching(root, a.goal, a.course)
        print(json.dumps(hits, indent=1) if a.json else
              (render(hits) or "no gotcha matches that goal"))
        return
    if a.json:
        print(json.dumps({"summary": summary(root), "all": load(root, a.course)},
                         indent=1))
        return
    s = summary(root)
    print(f"{s['total']} gotcha(s), {s['repeats']} recurring")
    for scope, n in sorted(s["by_scope"].items()):
        print(f"  {scope:<40} {n}")


if __name__ == "__main__":
    main()
