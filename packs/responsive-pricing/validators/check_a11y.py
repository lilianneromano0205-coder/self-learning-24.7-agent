#!/usr/bin/env python3
"""Accessibility floor. Exit 0 iff it holds. A FLOOR, not an audit: WCAG
conformance needs a browser and human judgment; this catches the mechanical
failures that make those impossible."""
import re
import sys
from html.parser import HTMLParser


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.problems = []
        self.stack = []
        self.text_in = {}
        self.interactive = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.stack.append((tag, a))
        ti = a.get("tabindex")
        if ti and ti.strip().lstrip("+").isdigit() and int(ti) > 0:
            self.problems.append(f"positive tabindex={ti} hijacks focus order")
        if tag == "div" and "onclick" in a:
            self.problems.append("clickable <div> — use a <button>")
        if tag in ("button", "a"):
            self.interactive.append((tag, a, len(self.text_in)))
            self.text_in[len(self.text_in)] = ""

    def handle_data(self, data):
        for k in self.text_in:
            self.text_in[k] += data

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()


def main():
    path = sys.argv[1]
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    s = Scan()
    s.feed(raw)
    for tag, a, key in s.interactive:
        label = (a.get("aria-label") or "").strip()
        text = (s.text_in.get(key) or "").strip()
        if not label and not text:
            s.problems.append(f"<{tag}> with no text and no aria-label")
        if tag == "a" and not (a.get("href") or "").strip():
            s.problems.append("<a> without href is not keyboard-reachable")
    if not re.search(r"<html[^>]*\blang=", raw, re.I):
        s.problems.append("no lang attribute")
    if s.problems:
        print("A11Y: " + "; ".join(sorted(set(s.problems))))
        sys.exit(1)
    print("a11y floor holds")


if __name__ == "__main__":
    main()
