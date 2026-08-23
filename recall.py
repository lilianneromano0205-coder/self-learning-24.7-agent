#!/usr/bin/env python3
"""Recall — search an expert's ENTIRE mind, including what compaction paged
out of the working window.

The three-tier memory pattern (MemGPT/Letta, the 2026 production consensus):
  tier 1  in-context working memory      the live task context
  tier 2  session-compressed memory      compaction summaries in the context
  tier 3  archival memory, searchable    <- THIS TOOL

Tier 3 here is every file the expert ever wrote — notes, specs, skills,
lessons-learned, retractions, transcripts — plus the verbatim archives of
every turn compaction ever removed (contexts/*.archive.jsonl). Nothing the
agent has seen or thought is ever unreachable.

Agents with run_command use it themselves:
    python recall.py "exponential backoff attempts"
Ranked hits come back as  path:line | snippet  — then read_file the winner.

Usage:  python recall.py "query terms" [--root DIR] [--limit 12]
"""

import argparse
import json
import os
import re
import sys

SEARCH_ROOTS = ["courses", "skills", "teamwork"]
SEARCH_FILES = ["identity.md", "lessons-learned.md", "retractions.md",
                "reputation.md", "blocked.md"]
EXTS = (".md", ".txt")
MAX_FILE_BYTES = 2_000_000


def tokenize(text):
    return re.findall(r"[a-zà-ÿ0-9][a-zà-ÿ0-9_-]{1,}", text.lower())


def score_line(line_tokens, terms):
    if not line_tokens:
        return 0
    hits = sum(1 for t in terms if t in line_tokens)
    if hits == 0:
        return 0
    # all terms present beats partial matches; frequency breaks ties
    freq = sum(line_tokens.count(t) for t in terms)
    return hits * 100 + (50 if hits == len(terms) else 0) + freq


def iter_text_files(root):
    for base in SEARCH_ROOTS:
        d = os.path.join(root, base)
        for dirpath, dirnames, filenames in os.walk(d):
            dirnames.sort()
            for fn in sorted(filenames):
                if fn.endswith(EXTS):
                    yield os.path.join(dirpath, fn)
    for fn in SEARCH_FILES:
        p = os.path.join(root, fn)
        if os.path.exists(p):
            yield p


def search(root, query, limit=12):
    terms = tokenize(query)
    if not terms:
        return []
    hits = []

    for path in iter_text_files(root):
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    s = score_line(tokenize(line), terms)
                    if s:
                        rel = os.path.relpath(path, root).replace(os.sep, "/")
                        hits.append((s, f"{rel}:{i}", line.strip()[:200]))
        except OSError:
            continue

    # tier-3 archives: turns compaction removed from working memory
    ctx_dir = os.path.join(root, "contexts")
    if os.path.isdir(ctx_dir):
        for fn in sorted(os.listdir(ctx_dir)):
            if not fn.endswith(".archive.jsonl"):
                continue
            path = os.path.join(ctx_dir, fn)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        try:
                            m = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        content = m.get("content") or ""
                        s = score_line(tokenize(content), terms)
                        if s:
                            hits.append((s, f"contexts/{fn}:{i}",
                                         content.strip()[:200]))
            except OSError:
                continue

    hits.sort(key=lambda h: -h[0])
    top = hits[:limit]
    return top + _associative(root, top, limit)


ATOM_RE = re.compile(r"\b([CPU]-\d{3,4})\b")
WIKILINK_RE = re.compile(r"\[\[([\w-]+)\]\]")


def _associative(root, top, limit):
    """Associative expansion (RippleMem/CABLE, 2026-08): an answer often
    depends on memories the query never names. The initial hits become
    anchors: every atom ID they cite is chased to its DEFINITION line, and
    every [[link]] to its file — one hop, deterministic — so evidence comes
    back as a chain instead of a fragment."""
    if not top:
        return []
    seen_locs = {loc for _, loc, _ in top}
    want_atoms, want_links = [], []
    for _, _, snippet in top:
        for a in ATOM_RE.findall(snippet):
            if a not in want_atoms:
                want_atoms.append(a)
        for w in WIKILINK_RE.findall(snippet):
            if w.lower() not in want_links:
                want_links.append(w.lower())
    floor = min(sc for sc, _, _ in top)
    extra, cap = [], max(3, limit // 2)
    if want_atoms:
        defline = re.compile(
            r"^\s*-\s*(" + "|".join(map(re.escape, want_atoms)) + r")\b")
        for path in iter_text_files(root):
            if len(extra) >= cap:
                break
            try:
                if os.path.getsize(path) > MAX_FILE_BYTES:
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if not defline.match(line):
                            continue
                        rel = os.path.relpath(path, root).replace(os.sep, "/")
                        loc = f"{rel}:{i}"
                        if loc in seen_locs:
                            continue
                        seen_locs.add(loc)
                        extra.append((max(0.1, floor - 0.1),
                                      f"linked:{loc}", line.strip()[:200]))
                        if len(extra) >= cap:
                            break
            except OSError:
                continue
    for name in want_links:
        if len(extra) >= cap:
            break
        for cand in (os.path.join("skills", f"{name}.md"), f"{name}.md"):
            full = os.path.join(root, cand)
            if os.path.isfile(full):
                try:
                    with open(full, "r", encoding="utf-8",
                              errors="replace") as f:
                        first = f.readline().strip()[:200]
                    loc = f"{cand.replace(os.sep, '/')}:1"
                    if loc not in seen_locs:
                        seen_locs.add(loc)
                        extra.append((max(0.1, floor - 0.1),
                                      f"linked:{loc}", first))
                except OSError:
                    pass
                break
    return extra


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query")
    ap.add_argument("--root", default=".")
    ap.add_argument("--limit", type=int, default=12)
    args = ap.parse_args()
    hits = search(os.path.abspath(args.root), args.query, args.limit)
    if not hits:
        print("no matches — try fewer or different terms")
        sys.exit(1)
    for s, loc, snippet in hits:
        print(f"{loc} | {snippet}")


if __name__ == "__main__":
    main()
