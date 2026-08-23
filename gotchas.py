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

import os
import re
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


def entry_line(rec, trigger, when, do, src):
    return (f"- [{time.strftime('%Y-%m-%d')}] ({rec.get('failure_id', 'F-0')}) "
            f"TRIGGER: {', '.join(trigger)} | WHEN {when} | DO {do} | "
            f"src: task {src}\n")


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    for attempt in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


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
    written = []
    for rel in _scopes(root, task, rec):
        path = os.path.join(root, rel)
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
            new += f" | x{n} hit again {time.strftime('%Y-%m-%d')}"
            body = body.replace(hit, new)
        else:
            if not body.endswith("\n"):
                body += "\n"
            body += entry_line(rec, trigger, when, do, src)
        _write(path, body)
        written.append(rel.replace(os.sep, "/"))
    return written


def load(root, course=None):
    """Every gotcha entry that could apply here, newest file last."""
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
            out.append(d)
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
    g = load(root)
    by_scope = {}
    for e in g:
        by_scope.setdefault(e["scope"], 0)
        by_scope[e["scope"]] += 1
    return {"total": len(g), "by_scope": by_scope,
            "repeats": sum(1 for e in g if e["repeats"] > 1)}


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
