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
    courses = os.path.join(root, "courses")
    if not os.path.isdir(courses):
        return atoms
    for dirpath, _, filenames in os.walk(courses):
        for fn in filenames:
            if fn == "notes.md":
                try:
                    with open(os.path.join(dirpath, fn), "r",
                              encoding="utf-8", errors="replace") as f:
                        atoms.update(ATOM_DEF_RE.findall(f.read()))
                except OSError:
                    continue
    return atoms


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
