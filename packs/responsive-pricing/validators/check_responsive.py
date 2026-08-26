#!/usr/bin/env python3
"""Responsive floor. Exit 0 iff the page carries real breakpoint logic and
no hard-fixed page width. Rendering across viewports needs a browser; this
is the mechanical precondition for it."""
import re
import sys


def main():
    path = sys.argv[1]
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    problems = []
    if not re.search(r"@media[^{]*\((?:max|min)-width", raw, re.I):
        problems.append("no @media breakpoint anywhere")
    if not re.search(r'<meta[^>]+name=["\']viewport', raw, re.I):
        problems.append("no viewport meta")
    for m in re.finditer(r"(?:body|\.container|main)\s*{[^}]*}", raw, re.I):
        if re.search(r"width\s*:\s*\d{3,}px", m.group(0)):
            problems.append("a layout container is fixed at a pixel width")
            break
    if problems:
        print("RESPONSIVE: " + "; ".join(problems))
        sys.exit(1)
    print("responsive floor holds")


if __name__ == "__main__":
    main()
