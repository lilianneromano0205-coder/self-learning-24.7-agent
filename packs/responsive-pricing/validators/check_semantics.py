#!/usr/bin/env python3
"""Semantic-structure floor for an HTML artifact. Exit 0 iff it holds.

Deterministic and stdlib-only, per the platform's law that graders must be
runnable anywhere with nothing installed. This is a FLOOR: passing it means
the structure is not broken, not that the design is good.
"""
import sys
from html.parser import HTMLParser


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.attrs = []
        self.imgs_missing_alt = 0
        self.headings = 0
        self.lang = False
        self.viewport = False
        self.landmarks = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append(tag)
        self.attrs.append((tag, a))
        if tag in ("h1", "h2", "h3"):
            self.headings += 1
        if tag == "html" and (a.get("lang") or "").strip():
            self.lang = True
        if tag == "meta" and a.get("name") == "viewport":
            self.viewport = True
        if tag in ("main", "header", "footer", "nav", "section", "article"):
            self.landmarks += 1
        if tag == "img" and not (a.get("alt") or "").strip():
            self.imgs_missing_alt += 1


def main():
    path = sys.argv[1]
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    s = Scan()
    s.feed(raw)
    problems = []
    if not raw.lstrip().lower().startswith("<!doctype"):
        problems.append("no doctype")
    if not s.lang:
        problems.append("<html> carries no lang attribute")
    if not s.viewport:
        problems.append("no viewport meta — not responsive-ready")
    if s.landmarks < 2:
        problems.append(f"{s.landmarks} semantic landmark(s); a page built "
                        f"from divs alone is not semantic structure")
    if s.headings < 1:
        problems.append("no heading")
    if s.imgs_missing_alt:
        problems.append(f"{s.imgs_missing_alt} img(s) without alt")
    if problems:
        print("SEMANTICS: " + "; ".join(problems))
        sys.exit(1)
    print("semantics floor holds")


if __name__ == "__main__":
    main()
