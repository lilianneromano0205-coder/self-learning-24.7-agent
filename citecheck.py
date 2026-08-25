#!/usr/bin/env python3
"""Citation gate for consultations — zero room for hallucinated authority.

A consultation answer may only ship if:
  * every atom ID it cites (C-/P-/U-nnnn) is actually DEFINED in the expert's
    notes — a citation to nothing is a hallucination, and it fails here, or
  * the parts the training does not cover say exactly NOT IN MY TRAINING —
    the honest blank that outranks a confident guess.

Wired as a task's done_check: finish_task is REFUSED until this exits 0, so
an ungrounded answer cannot be delivered, whatever the model claims.

Usage:  python citecheck.py <answer-file> [--root DIR]
"""

import argparse
import os
import re
import sys

ATOM_CITE_RE = re.compile(r"\b([CPU]-\d{2,}[\w.]*)\b")
ATOM_DEF_RE = re.compile(r"^\s*-\s*([CPU]-\d{2,}[\w.]*)\b", re.M)
HONEST_BLANK = "NOT IN MY TRAINING"


def known_atoms(root):
    atoms = set()
    for _course, path in notes_files(root):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                atoms.update(ATOM_DEF_RE.findall(f.read()))
        except OSError:
            continue
    return atoms


def notes_files(root):
    """Every notes.md an expert has earned, as (course, absolute path).

    THE ONE WALKER. This was inlined here and hand-written a second time in
    knowledge.py, and the two disagreed: this one walks the whole tree, the
    other joined `courses/<course>/notes.md` flat. The platform writes
    `courses/<course>/lessons/NN/notes.md` (ingest.py, harness.py), so the
    flat version matched nothing — the knowledge graph was empty against
    every real expert while its own docstring claimed it read "the same
    notes.md files citecheck.py validates against".

    That is this codebase's recurring defect in its purest form: two
    descriptions of one truth and nothing comparing them. Now there is one
    description, and test_knowledge asserts the two agree.

    The course is the first path segment under courses/, so a lesson
    directory does not become its own course.
    """
    out = []
    courses = os.path.join(root, "courses")
    if not os.path.isdir(courses):
        return out
    for dirpath, _dirs, filenames in os.walk(courses):
        if "notes.md" not in filenames:
            continue
        rel = os.path.relpath(dirpath, courses).replace(os.sep, "/")
        course = "" if rel == "." else rel.split("/", 1)[0]
        out.append((course, os.path.join(dirpath, "notes.md")))
    return sorted(out)


def check(root, answer_path):
    with open(answer_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    cited = sorted(set(ATOM_CITE_RE.findall(text)))
    defined = known_atoms(root)
    ghosts = [a for a in cited if a not in defined]
    problems = []
    if ghosts:
        problems.append(
            f"HALLUCINATED CITATIONS — these atoms exist in no notes file: "
            f"{', '.join(ghosts)}. Cite only atoms your notes define, or mark "
            f"the claim {HONEST_BLANK}.")
    if not cited and HONEST_BLANK not in text:
        problems.append(
            f"UNGROUNDED ANSWER — no atom citations and no {HONEST_BLANK} "
            f"marker. Every claim must cite the notes it comes from; what the "
            f"training does not cover must say {HONEST_BLANK}.")
    return problems, len(cited), len(defined)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("answer")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    path = os.path.join(root, args.answer) if not os.path.isabs(args.answer) \
        else args.answer
    if not os.path.exists(path):
        print(f"FAIL: answer file {args.answer} does not exist yet")
        sys.exit(1)
    problems, n_cited, n_defined = check(root, path)
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        sys.exit(1)
    print(f"OK: {n_cited} citation(s), all resolve against {n_defined} "
          f"defined atoms")
    sys.exit(0)


if __name__ == "__main__":
    main()
