#!/usr/bin/env python3
"""The Commons — shared memory for the whole fleet, plus peer consultation.

Every expert keeps its own private mind (courses, notes, skills). The
commons is what they know TOGETHER:

  commons/knowledge/<topic>.md   facts contributed by any expert, each line
                                 attributed and citing its origin
  commons/lessons.md             what the fleet learned from its MISTAKES —
                                 every failure that cost work, written once so
                                 no expert repeats it
  commons/directory.md           who knows what: the live roster of experts
                                 and their specialties, so an agent knows whom
                                 to ask

Rules that keep shared memory from rotting into a rumor mill:
  * append-only and attributed — every entry names the expert and the date
  * claims carry their origin (a course atom, a file, or a verified run)
  * anything contradicted later is struck through, never silently deleted
  * agents READ the commons in context; they WRITE via this module's API,
    which stamps attribution automatically

Peer consultation: an expert can ask another expert a question — the answer
comes back through the peer's own citation-gated consultation flow, so a
borrowed answer is as grounded as a first-hand one.

Usage:
  python commons.py show [--home DIR]
  python commons.py learn "lesson text" --from <expert> [--tag t]
  python commons.py note <topic> "fact" --from <expert> [--src "..."]
  python commons.py ask <expert> "question" --from <asker> [--home DIR] [--wait]
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

MAX_INJECT_CHARS = 6000


def commons_dir(home):
    d = os.path.join(home, "commons")
    os.makedirs(os.path.join(d, "knowledge"), exist_ok=True)
    return d


def _append(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def learn(home, lesson, from_expert="unknown", tag=""):
    """Record a lesson from a MISTAKE. Deduplicated: the same lesson text is
    never written twice, it just gains a repeat marker — so the file stays
    readable and a recurring failure becomes visibly recurring."""
    path = os.path.join(commons_dir(home), "lessons.md")
    stamp = time.strftime("%Y-%m-%d")
    lesson = " ".join(lesson.split())
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = f.read()
    except OSError:
        existing = "# FLEET LESSONS — learned from real failures, never repeat these\n\n"
        _append(path, existing)
    if lesson.lower() in existing.lower():
        _append(path, f"  ↑ hit again {stamp} by {from_expert}\n")
        return False
    _append(path, f"- [{stamp}] ({from_expert}){f' #{tag}' if tag else ''} {lesson}\n")
    return True


def note(home, topic, fact, from_expert="unknown", src="", corroborate=True):
    """Contribute a fact to shared knowledge — but broader scope demands
    stronger evidence. One expert's claim is a CANDIDATE; it is promoted to
    shared knowledge only when a second, DIFFERENT expert reports the same
    thing, or when it arrives with a source citation. Without that, a single
    agent's one bad episode could poison the whole fleet's memory.

    Returns (status, path): status is 'promoted', 'candidate', or 'known'.
    """
    safe = "".join(c for c in topic.lower().replace(" ", "-")
                   if c.isalnum() or c in "-_")[:40] or "general"
    kpath = os.path.join(commons_dir(home), "knowledge", f"{safe}.md")
    cpath = os.path.join(commons_dir(home), "knowledge", f"{safe}.candidates.md")
    stamp = time.strftime("%Y-%m-%d")
    fact = " ".join(fact.split())
    key = fact.lower()

    def _has(path, needle):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return needle in f.read().lower()
        except OSError:
            return False

    if _has(kpath, key):
        _append(kpath, f"  ↑ corroborated {stamp} by {from_expert}\n")
        return "known", kpath

    # a cited claim carries its own evidence; promote it directly
    if src:
        if not os.path.exists(kpath):
            _append(kpath, f"# {topic}\n\n")
        _append(kpath, f"- [{stamp}] ({from_expert}) {fact} [origin: {src}]\n")
        return "promoted", kpath

    # uncited: park it, and promote only on independent corroboration
    prior = ""
    try:
        with open(cpath, "r", encoding="utf-8") as f:
            prior = f.read()
    except OSError:
        _append(cpath, f"# {topic} — CANDIDATES (uncorroborated, do not cite)\n\n")
    if corroborate and key in prior.lower():
        others = [ln for ln in prior.splitlines()
                  if key in ln.lower() and f"({from_expert})" not in ln]
        if others:
            if not os.path.exists(kpath):
                _append(kpath, f"# {topic}\n\n")
            _append(kpath, f"- [{stamp}] {fact} [corroborated independently by "
                           f"{from_expert} and another expert]\n")
            return "promoted", kpath
    _append(cpath, f"- [{stamp}] ({from_expert}) {fact}\n")
    return "candidate", cpath


def quarantine(home, fact, why, by="owner"):
    """Withdraw something the fleet believed. Struck, never silently deleted —
    the record of having been wrong is itself worth keeping."""
    path = os.path.join(commons_dir(home), "quarantine.md")
    if not os.path.exists(path):
        _append(path, "# QUARANTINED — believed once, withdrawn since. "
                      "Never cite these.\n\n")
    _append(path, f"- [{time.strftime('%Y-%m-%d')}] ({by}) ~~{' '.join(fact.split())}~~ "
                  f"— withdrawn: {why}\n")
    return path


def refresh_directory(home):
    """Rebuild the who-knows-what roster, so agents know whom to ask."""
    import fleet
    lines = ["# FLEET DIRECTORY — who knows what (ask them with peer.ask)", ""]
    for e in fleet.list_experts(home):
        courses = ", ".join(e["courses"][:8]) or "no courses yet"
        lines.append(f"- {e['name']}: {e['identity'] or 'unstated specialty'} "
                     f"— studied: {courses}")
    path = os.path.join(commons_dir(home), "directory.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


CURATED = "lessons.curated.md"
EDITS = "edits.jsonl"
_CURATE_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with",
                "on", "at", "by", "from", "into", "that", "this", "it", "is",
                "are", "be", "was", "were", "do", "does", "did", "as", "if",
                "then", "than", "never", "always", "when", "before", "after"}


def _lesson_entries(path):
    """Parse the append-only ledger into entries, carrying their repeats."""
    import re
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return entries
    for line in lines:
        m = re.match(r"^- \[(?P<date>[\d-]+)\] \((?P<who>[^)]*)\)"
                     r"(?P<tag> #\S+)? (?P<text>.*)$", line)
        if m:
            entries.append({"date": m.group("date"), "who": [m.group("who")],
                            "tag": (m.group("tag") or "").strip(),
                            "text": m.group("text").strip(), "seen": 1,
                            "raw": line})
        elif line.strip().startswith("↑ hit again") and entries:
            entries[-1]["seen"] += 1
            who = line.strip().split(" by ")[-1].strip()
            if who and who not in entries[-1]["who"]:
                entries[-1]["who"].append(who)
    return entries


def _shape(text):
    import re
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) > 2 and w not in _CURATE_STOP}


CURATED_STAMP = CURATED + ".stamp"


def _lessons_digest(d):
    """A hash of the material the curated view is built from. Returns "" when
    there is nothing to curate."""
    try:
        with open(os.path.join(d, "lessons.md"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _curation_is_stale(d):
    """Does the curated view need rebuilding? Answered from CONTENT, never
    from a comparison between two files' timestamps — see the note in
    digest(), and U19/U20 in GAPS_RISKS_AND_UNFINISHED.md."""
    fp = _lessons_digest(d)
    if not fp:
        return False                       # no lessons: nothing to curate
    if not os.path.exists(os.path.join(d, CURATED)):
        return True
    try:
        with open(os.path.join(d, CURATED_STAMP), encoding="utf-8") as f:
            return json.load(f).get("lessons") != fp
    except (OSError, ValueError):
        return True                        # no record of what was curated


def curate(home, write=True):
    """ACE-style grow-and-refine (arXiv 2510.04618).

    The failure mode ACE names is CONTEXT COLLAPSE: a memory that is
    repeatedly rewritten by a model loses its specifics and drifts into
    bland advice, which is worse than no memory. Their answer is to keep the
    context as an append-only ledger of DELTA entries and to curate a view
    from it — merging duplicates and superseding stale items — instead of
    rewriting the whole document.

    So `lessons.md` stays the ledger (nothing is ever edited or deleted
    there), and this pass derives `lessons.curated.md`: near-duplicate
    lessons merged into one line carrying every contributor and a hit count,
    newest first. Each operation is journalled to `commons/edits.jsonl`, so
    the curation itself is auditable and reversible — delete the view and it
    rebuilds from the ledger, unchanged.
    """
    d = commons_dir(home)
    entries = _lesson_entries(os.path.join(d, "lessons.md"))
    groups, ops = [], []
    for e in entries:
        shape = _shape(e["text"])
        merged_into = None
        for g in groups:
            other = g["shape"]
            if not shape or not other:
                continue
            inter = len(shape & other)
            union = len(shape | other)
            if shape <= other or other <= shape or (union and inter / union >= 0.8):
                merged_into = g
                break
        if merged_into:
            merged_into["seen"] += e["seen"]
            for w in e["who"]:
                if w not in merged_into["who"]:
                    merged_into["who"].append(w)
            if e["date"] > merged_into["date"]:
                merged_into["date"] = e["date"]
            if len(e["text"]) > len(merged_into["text"]):
                # keep the MORE SPECIFIC wording: brevity bias is the enemy
                merged_into["text"] = e["text"]
                merged_into["shape"] = _shape(e["text"])
            ops.append({"op": "merge", "into": merged_into["id"],
                        "text": e["text"][:120]})
        else:
            gid = "L-" + hashlib.sha1(
                e["text"].lower().encode("utf-8")).hexdigest()[:8]
            groups.append({"id": gid, "shape": shape, "seen": e["seen"],
                           "who": list(e["who"]), "date": e["date"],
                           "tag": e["tag"], "text": e["text"]})
            ops.append({"op": "grow", "id": gid, "text": e["text"][:120]})
    if not write:
        return {"entries": len(entries), "curated": len(groups),
                "merged": len(entries) - len(groups), "path": None}
    groups.sort(key=lambda g: (g["date"], g["seen"]), reverse=True)
    lines = ["# FLEET LESSONS — curated view (grow-and-refine).",
             "# The append-only ledger is lessons.md; nothing here was invented,",
             "# only merged. Delete this file and it rebuilds identically.", ""]
    for g in groups:
        hits = f" x{g['seen']}" if g["seen"] > 1 else ""
        who = ", ".join(g["who"][:4])
        lines.append(f"- [{g['date']}] ({who}){hits}"
                     f"{' ' + g['tag'] if g['tag'] else ''} {g['text']}  [{g['id']}]")
    path = os.path.join(d, CURATED)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    # record WHICH ledger this view was built from, so staleness is decided
    # by content and never by two files' timestamps
    try:
        with open(os.path.join(d, CURATED_STAMP), "w", encoding="utf-8") as f:
            json.dump({"lessons": _lessons_digest(d),
                       "at": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
    except OSError:                        # pragma: no cover — read-only dir
        pass
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(os.path.join(d, EDITS), "a", encoding="utf-8") as f:
        for op in ops:
            op["at"] = stamp
            f.write(json.dumps(op, ensure_ascii=False) + "\n")
    return {"entries": len(entries), "curated": len(groups),
            "merged": len(entries) - len(groups), "path": path}


def digest(home, limit=MAX_INJECT_CHARS):
    """The compact commons block injected into agents' context: the owner's
    pins first (they outrank everything), then the fleet's hard-won lessons
    in their curated form, then the withdrawals, then the directory."""
    d = commons_dir(home)
    # Keep the curated view fresh before injecting it. This used to ask
    # whether lessons.md was modified after lessons.curated.md, which is the
    # same unsound test that hid U19: on overlayfs — every container,
    # including this project's own Dockerfile — two files written back to
    # back get the IDENTICAL mtime, so `led > cur` was false and the curated
    # view was never rebuilt. Silently, and in the block injected into EVERY
    # agent's context across the whole fleet. Compare the material instead.
    try:
        if _curation_is_stale(d):
            curate(home)
    except Exception:                      # pragma: no cover — never block
        pass                               # the digest on a curation problem
    lessons = CURATED if os.path.exists(os.path.join(d, CURATED)) else "lessons.md"
    parts = []
    for name in ("pins.md", lessons, "quarantine.md", "directory.md"):
        p = os.path.join(d, name)
        try:
            with open(p, "r", encoding="utf-8") as f:
                body = f.read().strip()
            if body:
                parts.append(body)
        except OSError:
            continue
    if not parts:
        return ""
    # The parts are ordered by AUTHORITY — the owner's pins first — but the
    # old overflow rule kept the LAST `limit` characters, so the pins that
    # this very docstring calls outranking everything were the first thing
    # discarded. Keep the pins whole and trim the least authoritative end.
    pins = parts[0] if (parts and "pin" in parts[0][:80].lower()) else ""
    rest = "\n\n".join(parts[1:] if pins else parts)
    text = "\n\n".join(p for p in (pins, rest) if p)
    if len(text) > limit:
        head = pins + ("\n\n" if pins else "")
        room = max(0, limit - len(head) - 32)
        text = head + rest[:room] + "\n…(older entries omitted)…"
    return ("# COMMONS — what the whole fleet knows and has learned\n"
            "Treat lessons as binding: they were paid for with real failures.\n\n"
            + text + "\n")


def write_digest(home, root):
    """Materialize the commons digest inside an expert's world so the loop can
    load it like any other memory file. Returns the relative path or None."""
    text = digest(home)
    if not text.strip():
        return None
    rel = "commons-digest.md"
    with open(os.path.join(root, rel), "w", encoding="utf-8") as f:
        f.write(text)
    return rel


# ------------------------------------------------------------- peer asking

def ask(home, to_expert, question, from_expert="a peer", wait=0, drive=False):
    """Ask another expert a question through ITS OWN citation-gated
    consultation flow — a borrowed answer is as grounded as a first-hand one.
    Returns (consult_id, answer_relpath, answer_text_or_None)."""
    import consult
    root = os.path.join(home, "experts", to_expert)
    if not os.path.isdir(root):
        raise KeyError(to_expert)
    framed = (f"[Question from {from_expert}, another expert in this fleet]\n"
              f"{question}\n\n"
              f"Answer from your training only, citing your atoms; anything "
              f"outside it must say NOT IN MY TRAINING so the asker knows the "
              f"boundary of what you actually know.")
    tid, answer_rel = consult.start_consult(root, framed)
    if drive:
        subprocess.run([sys.executable, os.path.join(HOME, "loop.py"),
                        "run", "--drain", "--root", root],
                       env={**os.environ, "PYTHONUTF8": "1"},
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    deadline = time.time() + wait
    path = os.path.join(root, answer_rel)
    while wait and time.time() < deadline and not os.path.exists(path):
        time.sleep(1)
    text = None
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    return tid, answer_rel, text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show")
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("learn")
    p.add_argument("lesson")
    p.add_argument("--from", dest="frm", default="unknown")
    p.add_argument("--tag", default="")
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("note")
    p.add_argument("topic")
    p.add_argument("fact")
    p.add_argument("--from", dest="frm", default="unknown")
    p.add_argument("--src", default="")
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("ask")
    p.add_argument("expert")
    p.add_argument("question")
    p.add_argument("--from", dest="frm", default="a peer")
    p.add_argument("--wait", type=int, default=0)
    p.add_argument("--drive", action="store_true")
    p.add_argument("--home", default=HOME)
    args = ap.parse_args()

    if args.cmd == "show":
        refresh_directory(args.home)
        print(digest(args.home) or "(commons empty)")
    elif args.cmd == "learn":
        fresh = learn(args.home, args.lesson, args.frm, args.tag)
        print("recorded" if fresh else "already known — marked as recurring")
    elif args.cmd == "note":
        status, path = note(args.home, args.topic, args.fact, args.frm, args.src)
        print(f"{status}: {path}"
              + ("" if status != "candidate" else
                 "  (uncited — needs a second expert to corroborate before it "
                 "becomes shared knowledge)"))
    elif args.cmd == "ask":
        tid, rel, text = ask(args.home, args.expert, args.question,
                             args.frm, args.wait, args.drive)
        print(f"asked {args.expert}: task {tid} -> {rel}")
        if text:
            print("\n" + text)


if __name__ == "__main__":
    main()
