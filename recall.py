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
import hashlib

import retrieval

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
            dirnames[:] = sorted(d for d in dirnames
                                 if _contained(root, os.path.join(dirpath, d)))
            for fn in sorted(filenames):
                if fn.endswith(EXTS) and _contained(root, os.path.join(dirpath, fn)):
                    yield os.path.join(dirpath, fn)
    for fn in SEARCH_FILES:
        p = os.path.join(root, fn)
        if os.path.exists(p) and _contained(root, p):
            yield p


def _contained(root, path):
    try:
        return os.path.commonpath([os.path.realpath(root), os.path.realpath(path)]) == os.path.realpath(root)
    except ValueError:
        return False


def records(root, cfg=None):
    """Read existing files and institutional ledgers without creating an index.

    A file's mtime is labelled as observation time, not source publication time.
    Source tiers are re-derived by sources.py, never accepted from note text.
    Retractions and conflict losers remain available only as labelled history.
    """
    import premise
    import sources
    import conflicts
    revoked = {(rel.split("/")[1], aid): (why, rel)
               for aid, why, rel in premise.retractions(root)}
    source_rows, conflict_rows = {}, {}
    courses = os.path.join(root, "courses")
    for course in sorted(os.listdir(courses)) if os.path.isdir(courses) else []:
        if not _contained(root, os.path.join(courses, course)):
            continue
        source_rows[course] = sources.load(root, course, cfg)
        # Recompute rules from source rather than trusting a mutable verdict row.
        conflict_rows[course] = conflicts.scan(root, course)
    paths = list(iter_text_files(root))
    ctx_dir = os.path.join(root, "contexts")
    if os.path.isdir(ctx_dir):
        for fn in sorted(os.listdir(ctx_dir)):
            path = os.path.join(ctx_dir, fn)
            if fn.endswith(".archive.jsonl") and _contained(root, path):
                paths.append(path)
    out = []
    for path in paths:
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            course = rel.split("/")[1] if rel.startswith("courses/") else None
            kind = ("course" if course else "skills" if rel.startswith("skills/") else
                    "self" if rel == "identity.md" else "gotchas" if rel == "lessons-learned.md"
                    else "premise" if rel.endswith("retractions.md") else "memory_files")
            with open(path, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if rel.endswith(".archive.jsonl"):
                        try:
                            m = json.loads(line)
                            line = m.get("content") or ""
                        except (json.JSONDecodeError, AttributeError):
                            continue
                    if not isinstance(line, str) or not line.strip():
                        continue
                    location = f"{rel}:{i}"
                    src = re.search(r"\[src:\s*([^\]]+)\]", line)
                    provenance = src.group(1).strip() if src else location
                    tier = 4
                    if src:
                        tier = sources.classify(provenance)[1]
                        for source in source_rows.get(course, []):
                            if source.get("id") and re.search(r"\b" + re.escape(source["id"]) + r"\b", provenance):
                                tier = source["tier"]
                                break
                    match = re.match(r"\s*-\s*([CPU]-\d{2,}[\w.]*)\b", line)
                    atom = match.group(1) if match else None
                    row = dict(id=location, ref=location, text=line.strip(), kind=kind,
                               course=course, atom_id=atom, source_tier=tier, provenance=provenance,
                               observed_at=os.path.getmtime(path), timestamp_basis="file_mtime",
                               content_sha256=hashlib.sha256(line.encode()).hexdigest(),
                               valid=True, retracted=False, superseded_by=None, contradiction=None)
                    # Retraction notices themselves are live safety information.
                    if atom and not rel.endswith("retractions.md") and (course, atom) in revoked:
                        why, ref = revoked[(course, atom)]
                        row.update(retracted=True, retraction_reason=why, retraction_ref=ref)
                    for conflict in conflict_rows.get(course, []):
                        if atom not in (conflict["a"]["id"], conflict["b"]["id"]):
                            continue
                        verdict, winner = conflict["verdict"], conflict.get("winner")
                        if verdict == "contested":
                            row["contradiction"] = "unresolved"
                        elif winner and winner != atom:
                            row["superseded_by"] = winner
                            row["contradiction"] = verdict
                    out.append(row)
        except OSError:
            continue
    return out


def search_records(root, query, limit=12, *, task=None, cfg=None, embedder=None,
                   mode="hybrid", include_invalid=False, **filters):
    import memrouter
    if task is not None:
        allowed = memrouter.decide(task, cfg)["kinds"]
        requested = filters.pop("kinds", allowed)
        filters["kinds"] = [k for k in requested if k in allowed]
        filters.setdefault("task_type", task.get("role"))
    if embedder is None:
        model_path = ((cfg or {}).get("agent", {}).get("memory_retrieval", {}) or {}).get("local_model_path")
        if model_path:
            try:
                embedder = retrieval.LocalEmbeddings(model_path)
            except (ImportError, OSError, ValueError):
                pass
    rows = records(root, cfg)
    hits = retrieval.rank(rows, query, limit, mode=mode, embedder=embedder,
                          include_invalid=include_invalid, **filters)
    # One-hop expansion must pass the SAME metadata gates as the initial hits.
    if hits:
        eligible = {r["ref"]: r for r in retrieval.rank(
            rows, query + " " + " ".join(r["text"] for r in rows), len(rows),
            mode="lexical", include_invalid=include_invalid, **filters)}
        tuples = [(r["score"], r["ref"], r["text"]) for r in hits]
        for score, ref, _ in _associative(root, tuples, limit):
            key = ref.removeprefix("linked:")
            if key in eligible:
                extra = dict(eligible[key], ref=ref, score=score, retrieval_mode="association")
                hits.append(extra)
    return hits


def search(root, query, limit=12, **kwargs):
    """Legacy tuple interface; use search_records to retain full metadata."""
    return [(r["score"], r["ref"], r["text"][:200])
            for r in search_records(root, query, limit, **kwargs)]


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
            if os.path.isfile(full) and _contained(root, full):
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
