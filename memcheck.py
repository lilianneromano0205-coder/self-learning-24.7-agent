#!/usr/bin/env python3
"""Memory integrity checker — makes the grounding rule mechanically checkable.

The house memory format promises: every atom has a unique ID, every claim a
[src:] citation that resolves, every spec item cites real atoms, every lesson
a line in index.md. Promises are hints; this enforces them:

  1. ID uniqueness   — no C-/P-/U- ID defined twice across the course's notes,
                       no R- ID defined twice in spec.md
  2. Citations       — every [src: <file> ...] resolves to a real file
                       (tried relative to the lesson dir, the course dir, and
                       the agent root; bare names also tried with .txt/.md)
  3. Spec grounding  — every ID in an R-item's [from ...] is a defined atom
  4. Index coverage  — every lessons/NN/notes.md has a matching index.md line

Exit 0 = memory is internally sound; exit 1 = violations (all printed).
The Examiner runs this alongside verify.py; a failing memcheck means the
notes cannot be trusted, whatever they claim.

Usage:  python memcheck.py <course> [--root DIR]
"""

import argparse
import os
import re
import sys

ATOM_DEF_RE = re.compile(r"^\s*-\s*([CPU]-[\w.]+)\b", re.M)
SPEC_DEF_RE = re.compile(r"^\s*(R-[\w.]+)\s*[:\[]", re.M)
SPEC_FROM_RE = re.compile(r"^\s*(R-[\w.]+)\s*\[from\s+([^\]]+)\]", re.M)
CITE_RE = re.compile(r"\[src:\s*([^\s\]]+)[^\]]*\]")


def read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def resolve_citation(name, lesson_dir, course_dir, root):
    candidates = [name] + ([name + ".txt", name + ".md"] if "." not in os.path.basename(name) else [])
    for base in (lesson_dir, course_dir, root):
        for c in candidates:
            if os.path.exists(os.path.join(base, c)):
                return True
    return False


def check(course, root):
    course_dir = os.path.join(root, "courses", course)
    lessons_dir = os.path.join(course_dir, "lessons")
    errors = []

    notes = []  # (lesson_nn, path, text)
    if os.path.isdir(lessons_dir):
        for nn in sorted(os.listdir(lessons_dir)):
            p = os.path.join(lessons_dir, nn, "notes.md")
            if os.path.isdir(os.path.join(lessons_dir, nn)) and os.path.exists(p):
                notes.append((nn, p, read(p)))

    # 1. ID uniqueness
    seen = {}
    for nn, path, text in notes:
        for aid in ATOM_DEF_RE.findall(text):
            if aid in seen and seen[aid] != nn:
                errors.append(f"DUPLICATE ID: {aid} defined in lesson {seen[aid]} and lesson {nn}")
            seen.setdefault(aid, nn)
    spec_text = read(os.path.join(course_dir, "spec.md"))
    spec_ids = SPEC_DEF_RE.findall(spec_text)
    for rid in {r for r in spec_ids if spec_ids.count(r) > 1}:
        errors.append(f"DUPLICATE ID: {rid} defined {spec_ids.count(rid)} times in spec.md")

    # 2. citations resolve
    for nn, path, text in notes:
        lesson_dir = os.path.dirname(path)
        for name in CITE_RE.findall(text):
            if not resolve_citation(name, lesson_dir, course_dir, root):
                errors.append(f"BROKEN CITATION: lesson {nn} cites [src: {name}] "
                              f"but no such file exists")

    # 3. spec items cite defined atoms
    for rid, from_ids in SPEC_FROM_RE.findall(spec_text):
        for aid in (x.strip() for x in from_ids.split(",")):
            if aid and aid not in seen:
                errors.append(f"UNGROUNDED SPEC: {rid} cites {aid}, "
                              f"which is defined in no notes file")

    # 4. index coverage
    index_text = read(os.path.join(course_dir, "index.md"))
    for nn, path, text in notes:
        try:
            n = int(nn)
        except ValueError:
            continue
        if not re.search(rf"^\s*0*{n}\s*[|:\-]", index_text, re.M):
            errors.append(f"INDEX GAP: lesson {nn} has notes.md but no line in index.md")

    return errors, len(notes), len(seen), len(set(spec_ids))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("course")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    errors, n_notes, n_atoms, n_spec = check(args.course, os.path.abspath(args.root))
    for e in errors:
        print(e)
    print(f"\n{n_notes} notes files, {n_atoms} atoms, {n_spec} spec items — "
          + (f"{len(errors)} VIOLATION(S)" if errors else "memory is internally sound"))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
