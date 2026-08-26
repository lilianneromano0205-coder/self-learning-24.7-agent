#!/usr/bin/env python3
"""Pricing-UX floor: at least N priced tiers, each with a call to action.
Usage: check_pricing.py <file> [min_tiers]"""
import re
import sys
from html.parser import HTMLParser


class Scan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ctas = 0

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self.ctas += 1
        if tag == "a" and any(k == "href" for k, _ in attrs):
            self.ctas += 1


def main():
    path = sys.argv[1]
    need = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    prices = re.findall(r"[$€£]\s?\d+(?:[.,]\d{2})?|\d+\s?(?:€|USD|EUR)\b",
                        raw)
    s = Scan()
    s.feed(raw)
    problems = []
    if len(prices) < need:
        problems.append(f"{len(prices)} price(s) found, {need} tiers needed")
    if s.ctas < need:
        problems.append(f"{s.ctas} call(s) to action for {need} tiers")
    if problems:
        print("PRICING: " + "; ".join(problems))
        sys.exit(1)
    print(f"pricing floor holds ({len(prices)} price(s), {s.ctas} CTA(s))")


if __name__ == "__main__":
    main()
