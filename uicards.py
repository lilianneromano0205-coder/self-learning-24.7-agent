#!/usr/bin/env python3
"""GENERATIVE UI, SAFELY — agents return structured cards, not markup.

Google's A2UI takes the only defensible position on agents drawing screens:
the agent emits a DECLARATIVE description, and the client renders it from a
catalogue of components it already trusts. Nothing the model writes is ever
executed or injected as markup. AG-UI's generative-UI events work the same
way. That is exactly right for a platform whose agents read untrusted web
pages all day: an agent that can emit HTML is an agent that can be told by a
web page to emit HTML.

So an agent may write, in its message or its finish summary:

    <<<UI-CARD {"type": "table", "title": "Margin by SKU",
                "columns": ["sku", "margin"],
                "rows": [["A1", "12%"], ["B2", "31%"]]}>>>

and the panel draws a table. Four component types exist:

    table      columns + rows
    checklist  items with a done flag
    diff       before / after of one file
    metric     labelled numbers with optional deltas

Everything else is refused and logged (`ui_card_invalid`) — an unknown type
is not rendered "as best we can", it is dropped. Cards are capped in size
(8 KB) and count (10 per task), every string is escaped by the client, and
a card can carry no links, scripts or styles because the schema has nowhere
to put them.
"""

import json
import re

MARKER = "<<<UI-CARD"
CARD_RE = re.compile(r"<<<UI-CARD\s*(\{.*?\})\s*>>>", re.S)
MAX_CARD_BYTES = 8192
MAX_CARDS = 10
CATALOG = ("table", "checklist", "diff", "metric")
MAX_ROWS = 50
MAX_COLS = 12
MAX_CELL = 300


def _s(v, limit=MAX_CELL):
    return str(v)[:limit]


def validate(card):
    """-> (clean_card, problem). Exactly one of the two is None."""
    if not isinstance(card, dict):
        return None, "a card must be a JSON object"
    t = str(card.get("type") or "").lower()
    if t not in CATALOG:
        return None, (f"unknown card type '{t}' — the catalogue is: "
                      f"{', '.join(CATALOG)}")
    out = {"type": t, "title": _s(card.get("title") or "", 120)}
    if t == "table":
        cols = card.get("columns")
        rows = card.get("rows")
        if not isinstance(cols, list) or not cols:
            return None, "a table needs a non-empty 'columns' list"
        if not isinstance(rows, list):
            return None, "a table needs a 'rows' list"
        out["columns"] = [_s(c, 60) for c in cols[:MAX_COLS]]
        out["rows"] = [[_s(c) for c in (r if isinstance(r, list) else [r])
                        ][:MAX_COLS] for r in rows[:MAX_ROWS]]
    elif t == "checklist":
        items = card.get("items")
        if not isinstance(items, list) or not items:
            return None, "a checklist needs a non-empty 'items' list"
        clean = []
        for it in items[:MAX_ROWS]:
            if isinstance(it, dict):
                clean.append({"text": _s(it.get("text") or ""),
                              "done": bool(it.get("done"))})
            else:
                clean.append({"text": _s(it), "done": False})
        out["items"] = clean
    elif t == "diff":
        if card.get("before") is None or card.get("after") is None:
            return None, "a diff needs 'before' and 'after'"
        out["path"] = _s(card.get("path") or "", 200)
        out["before"] = _s(card.get("before"), 4000)
        out["after"] = _s(card.get("after"), 4000)
    elif t == "metric":
        ms = card.get("metrics")
        if not isinstance(ms, list) or not ms:
            return None, "a metric card needs a non-empty 'metrics' list"
        clean = []
        for m in ms[:12]:
            if not isinstance(m, dict):
                return None, "each metric must be an object"
            clean.append({"label": _s(m.get("label") or "", 60),
                          "value": _s(m.get("value"), 40),
                          "unit": _s(m.get("unit") or "", 16),
                          "delta": _s(m.get("delta") or "", 24)})
        out["metrics"] = clean
    return out, None


def parse(text, cap=MAX_CARDS):
    """-> (cards, problems) from any agent-authored text."""
    cards, problems = [], []
    if not text or MARKER not in str(text):
        return cards, problems
    for raw in CARD_RE.findall(str(text)):
        if len(cards) >= cap:
            problems.append(f"more than {cap} cards in one message — dropped")
            break
        if len(raw.encode("utf-8")) > MAX_CARD_BYTES:
            problems.append(f"a card exceeded {MAX_CARD_BYTES} bytes — dropped")
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            problems.append(f"a card was not valid JSON ({e.msg}) — dropped")
            continue
        clean, why = validate(obj)
        if why:
            problems.append(why + " — dropped")
            continue
        cards.append(clean)
    return cards, problems


def strip(text):
    """The text without its card blocks (for summaries shown as prose)."""
    return CARD_RE.sub("", str(text or "")).strip()


def render_text(card):
    """A terminal rendering, so the CLI shows what the panel shows."""
    t = card["type"]
    head = f"[{t}] {card.get('title') or ''}".rstrip()
    if t == "table":
        cols = card["columns"]
        w = [max(len(str(c)), *(len(str(r[i])) if i < len(r) else 0
                                for r in card["rows"] or [[]]))
             for i, c in enumerate(cols)]
        lines = ["  ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)),
                 "  ".join("-" * x for x in w)]
        for r in card["rows"]:
            lines.append("  ".join(
                str(r[i] if i < len(r) else "").ljust(w[i])
                for i in range(len(cols))))
        return head + "\n" + "\n".join(lines)
    if t == "checklist":
        return head + "\n" + "\n".join(
            f"  [{'x' if i['done'] else ' '}] {i['text']}" for i in card["items"])
    if t == "diff":
        return (head + f"\n  {card.get('path') or ''}\n  - "
                + card["before"][:200].replace("\n", "\n  - ")
                + "\n  + " + card["after"][:200].replace("\n", "\n  + "))
    return head + "\n" + "\n".join(
        f"  {m['label']}: {m['value']}{m['unit']}"
        f"{'  (' + m['delta'] + ')' if m['delta'] else ''}"
        for m in card["metrics"])


def main():
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="parse agent UI cards from text")
    ap.add_argument("file", nargs="?", help="file to scan (default: stdin)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    text = (open(a.file, encoding="utf-8").read() if a.file
            else sys.stdin.read())
    cards, problems = parse(text)
    if a.json:
        print(json.dumps({"cards": cards, "problems": problems}, indent=1))
        return
    for c in cards:
        print(render_text(c))
        print()
    for p in problems:
        print(f"REFUSED: {p}")
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
