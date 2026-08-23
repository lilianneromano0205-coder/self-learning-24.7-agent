#!/usr/bin/env python3
"""THE DESIGN GATE — mechanical checks a produced interface must survive.

"Make it beautiful, not AI slop" cannot be a prompt. A model that has been
asked nicely for taste produces the same purple gradient, the same three
centred feature cards, the same 9999px pills and the same emoji headings as
every other model, because that is the mode of its training data. Taste is
not enforceable; SPECIFICS are.

So this is a gate, wired as a task's done_check: finish_task is REFUSED
until the artifact passes. It checks the things that can be checked without
an opinion —

  contrast      every text/background pair declared together, against WCAG
  scale         type sizes and spacing values drawn from a system, not ad hoc
  tokens        colours referenced through custom properties once any exist
  responsive    a real breakpoint, and no fixed pixel width that overflows
  semantics     landmarks, alt text, labelled controls, focusable controls,
                a lang attribute -- the accessibility floor
  tells         the specific fingerprints of generated filler: default
                gradient palettes, emoji as iconography, lorem ipsum,
                everything centred, identical triplet cards, stock copy

Every finding names the line and what to do. Severity `blocker` fails the
gate; `warn` is reported and does not. The owner's own standards
(standards.py) can add or raise thresholds per course, so "our bar" is a
file, not a mood.

    python designcheck.py out/index.html
    python designcheck.py out/index.html --root <expert> --course design
    python designcheck.py out/ --json
"""

import json
import os
import re
import sys

TEXT_EXT = (".html", ".htm", ".css", ".jsx", ".tsx", ".vue", ".svelte")
HEX_RE = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
RGB_RE = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([0-9.]+)(px|rem|em|pt)", re.I)
SPACE_RE = re.compile(r"(?:margin|padding|gap)(?:-[a-z]+)?\s*:\s*([^;{}]+)", re.I)
PX_RE = re.compile(r"(-?[0-9.]+)px")
MEDIA_RE = re.compile(r"@media|@container", re.I)
WIDTH_RE = re.compile(r"(?:^|[;{\s])width\s*:\s*([0-9.]+)px", re.I)
IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
ALT_RE = re.compile(r"\balt\s*=", re.I)
BUTTON_RE = re.compile(r"<button\b[^>]*>(.*?)</button>", re.I | re.S)
INPUT_RE = re.compile(r"<input\b[^>]*>", re.I)
LABEL_RE = re.compile(r"<label\b[^>]*>", re.I)
ARIA_LABEL_RE = re.compile(r"aria-label\s*=|aria-labelledby\s*=", re.I)
HTML_LANG_RE = re.compile(r"<html\b[^>]*\blang\s*=", re.I)
LANDMARK_RE = re.compile(r"<(main|nav|header|footer|section|article)\b", re.I)
DIV_CLICK_RE = re.compile(r"<div\b[^>]*\bonclick\s*=", re.I)
EMOJI_HEAD_RE = re.compile(
    r"<h[1-6][^>]*>\s*[\U0001F300-\U0001FAFF←-⇿☀-➿]", re.U)
CENTER_RE = re.compile(r"text-align\s*:\s*center", re.I)
PILL_RE = re.compile(r"border-radius\s*:\s*(9999px|999px|50rem|100vmax)", re.I)
LOREM_RE = re.compile(r"\blorem ipsum\b|\bdolor sit amet\b", re.I)
VAR_RE = re.compile(r"var\(\s*--")
CUSTOM_PROP_RE = re.compile(r"--[a-z0-9-]+\s*:", re.I)
# the default palettes that generated pages reach for again and again
SLOP_COLORS = ("#6366f1", "#8b5cf6", "#a855f7", "#7c3aed", "#4f46e5",
               "#ec4899", "#f472b6", "#818cf8", "#c084fc")
SLOP_PHRASES = ("unlock the power", "take your", "to the next level",
                "seamlessly", "game-changing", "revolutionize", "elevate your",
                "supercharge", "in today's fast-paced", "look no further",
                "the ultimate guide", "delve into")
SCALE_PX = {0, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 56, 64, 72, 80, 96, 128}
DEFAULTS = {"min_contrast": 4.5, "max_type_sizes": 7, "max_offscale": 4,
            "max_center": 6, "require_responsive": True}


def _srgb(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb):
    r, g, b = (_srgb(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def parse_color(text):
    m = HEX_RE.search(text)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = RGB_RE.search(text)
    if m:
        return tuple(int(m.group(i)) for i in (1, 2, 3))
    return None


def _finding(sev, rule, line, msg, fix):
    return {"severity": sev, "rule": rule, "line": line, "message": msg,
            "fix": fix}


def _blocks(css):
    """(selector, body, line) for each rule block -- enough to pair colours."""
    out, line = [], 1
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        line += css.count("\n", 0, m.start()) if not out else 0
        out.append((m.group(1).strip()[-120:], m.group(2),
                    css.count("\n", 0, m.start()) + 1))
    return out


def check_text(text, name="artifact", thresholds=None):
    """Run every check over one file's text. Returns a list of findings."""
    t = dict(DEFAULTS)
    t.update(thresholds or {})
    f = []
    lines = text.splitlines()

    def line_of(idx):
        return text.count("\n", 0, idx) + 1

    # --- contrast on pairs declared in the same rule
    for sel, body, ln in _blocks(text):
        fg = re.search(r"(?:^|[;\s])color\s*:\s*([^;]+)", body, re.I)
        bg = re.search(r"background(?:-color)?\s*:\s*([^;]+)", body, re.I)
        if not (fg and bg):
            continue
        c1, c2 = parse_color(fg.group(1)), parse_color(bg.group(1))
        if not (c1 and c2):
            continue
        ratio = contrast(c1, c2)
        if ratio < t["min_contrast"]:
            f.append(_finding(
                "blocker", "contrast", ln,
                f"{sel}: text on its background is {ratio}:1, below the "
                f"{t['min_contrast']}:1 floor",
                "darken the text or lighten the surface until it clears the "
                "floor -- this is unreadable for real people, not a style note"))

    # --- type scale
    sizes = {f"{m.group(1)}{m.group(2).lower()}" for m in FONT_SIZE_RE.finditer(text)}
    if len(sizes) > t["max_type_sizes"]:
        f.append(_finding(
            "warn", "type-scale", 0,
            f"{len(sizes)} distinct font sizes ({', '.join(sorted(sizes)[:8])}...)",
            "pick a scale (e.g. 12/14/16/20/24/32/48) and use only its steps"))

    # --- spacing scale
    offscale = []
    for m in SPACE_RE.finditer(text):
        for px in PX_RE.findall(m.group(1)):
            try:
                v = abs(float(px))
            except ValueError:
                continue
            if v and v not in SCALE_PX:
                offscale.append((line_of(m.start()), f"{px}px"))
    if len(offscale) > t["max_offscale"]:
        f.append(_finding(
            "warn", "spacing-scale", offscale[0][0],
            f"{len(offscale)} spacing values are off any 4px scale "
            f"({', '.join(v for _, v in offscale[:6])})",
            "snap spacing to a 4 or 8px rhythm; arbitrary gaps are what makes "
            "a layout feel assembled rather than designed"))

    # --- tokens: once custom properties exist, raw hex is a leak
    props = len(CUSTOM_PROP_RE.findall(text))
    raw_hex = [m for m in HEX_RE.finditer(text)]
    if props >= 3 and len(raw_hex) > props:
        f.append(_finding(
            "warn", "tokens", line_of(raw_hex[0].start()),
            f"{len(raw_hex)} raw colour literals beside {props} defined custom "
            f"properties",
            "reference the tokens with var(--name) so a theme change is one edit"))

    # --- responsive
    if t["require_responsive"] and "<html" in text.lower() and \
            not MEDIA_RE.search(text):
        f.append(_finding(
            "blocker", "responsive", 0,
            "no @media or @container rule anywhere in the page",
            "add real breakpoints; a page that only works at one width is not "
            "finished"))
    for m in WIDTH_RE.finditer(text):
        try:
            w = float(m.group(1))
        except ValueError:
            continue
        if w > 600:
            f.append(_finding(
                "blocker", "fixed-width", line_of(m.start()),
                f"a fixed width of {int(w)}px will overflow a phone",
                "use max-width with a percentage or a fluid unit"))
            break

    # --- accessibility floor
    if "<html" in text.lower() and not HTML_LANG_RE.search(text):
        f.append(_finding("blocker", "a11y-lang", 1,
                          "<html> has no lang attribute",
                          'add lang="en" (or the real language)'))
    for m in IMG_RE.finditer(text):
        if not ALT_RE.search(m.group(0)):
            f.append(_finding("blocker", "a11y-alt", line_of(m.start()),
                              "an <img> has no alt attribute",
                              'add alt="..." describing it, or alt="" if it is '
                              'decorative'))
            break
    for m in BUTTON_RE.finditer(text):
        inner = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if not inner and not ARIA_LABEL_RE.search(m.group(0)):
            f.append(_finding("blocker", "a11y-button", line_of(m.start()),
                              "a <button> has no text and no aria-label",
                              "give it a name a screen reader can announce"))
            break
    n_inputs = len(INPUT_RE.findall(text))
    if n_inputs and not LABEL_RE.search(text) and not ARIA_LABEL_RE.search(text):
        f.append(_finding("blocker", "a11y-label", 0,
                          f"{n_inputs} input(s) and not one <label>",
                          "label every control; a placeholder is not a label"))
    m = DIV_CLICK_RE.search(text)
    if m:
        f.append(_finding("blocker", "a11y-interactive", line_of(m.start()),
                          "a <div> carries onclick",
                          "use a <button>: a div cannot be focused or "
                          "activated from a keyboard"))
    if "<html" in text.lower() and not LANDMARK_RE.search(text):
        f.append(_finding("warn", "a11y-landmarks", 0,
                          "no landmark elements (main/nav/header/footer)",
                          "wrap the regions so assistive tech can skip around"))

    # --- the generated-filler tells
    low = text.lower()
    hits = [c for c in SLOP_COLORS if c in low]
    if len(hits) >= 2:
        f.append(_finding(
            "warn", "tell-palette", 0,
            f"the default generated palette again ({', '.join(hits[:4])})",
            "choose colours from the brief or the reference material; this "
            "exact indigo/violet set is the fingerprint of unconsidered output"))
    m = EMOJI_HEAD_RE.search(text)
    if m:
        f.append(_finding("warn", "tell-emoji", line_of(m.start()),
                          "emoji used as iconography in a heading",
                          "use a real icon or nothing; emoji headings read as "
                          "filler and render differently on every platform"))
    if LOREM_RE.search(text):
        f.append(_finding("blocker", "tell-lorem", 0,
                          "lorem ipsum shipped in the artifact",
                          "write the real copy, or ask_human for it"))
    centers = len(CENTER_RE.findall(text))
    if centers > t["max_center"]:
        f.append(_finding("warn", "tell-centered", 0,
                          f"text-align:center used {centers} times",
                          "centre headlines, not paragraphs; everything centred "
                          "is the default look, not a decision"))
    if len(PILL_RE.findall(text)) >= 3 and len(hits) >= 1:
        f.append(_finding("warn", "tell-pills", 0,
                          "fully-rounded pills plus the default palette",
                          "vary the radius with the element's role"))
    phrases = [p for p in SLOP_PHRASES if p in low]
    if phrases:
        f.append(_finding("warn", "tell-copy", 0,
                          f"stock marketing copy: {', '.join(phrases[:3])}",
                          "say what the thing actually does, in the owner's "
                          "words"))
    return f


def check_file(path, thresholds=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return [_finding("blocker", "unreadable", 0, str(e),
                         "the gate must be able to read what you built")]
    out = check_text(text, os.path.basename(path), thresholds)
    for x in out:
        x["file"] = path.replace("\\", "/")
    return out


def check_path(target, thresholds=None):
    if os.path.isdir(target):
        out = []
        for dirpath, _, names in os.walk(target):
            for n in sorted(names):
                if n.lower().endswith(TEXT_EXT):
                    out += check_file(os.path.join(dirpath, n), thresholds)
        return out
    return check_file(target, thresholds)


STRICTER = {"min_contrast": max, "max_type_sizes": min, "max_offscale": min,
            "max_center": min}


def thresholds_for(root, course):
    """A course's standards can RAISE the bar, never lower it.

    Defence in depth: standards.py already refuses to promote a claim that
    lost a ruling, but a threshold must not depend on that -- nor on the
    order of lines in a file. Two rules touching one key resolve to the
    stricter value, so no source can ever loosen a stricter one.
    """
    t = dict(DEFAULTS)
    try:
        import standards
        for r in standards.load(root, course):
            chk = r.get("check") or {}
            key, val = chk.get("key"), chk.get("value")
            if key not in t or val is None:
                continue
            pick = STRICTER.get(key)
            t[key] = pick(t[key], val) if pick else val
    except Exception:
        pass
    return t


def report(findings):
    if not findings:
        return "design gate: PASS -- nothing to fix"
    lines = []
    for sev in ("blocker", "warn"):
        rows = [x for x in findings if x["severity"] == sev]
        if not rows:
            continue
        lines.append(f"{sev.upper()} ({len(rows)}):")
        for x in rows:
            where = f"{x.get('file', '')}:{x['line']}" if x.get("line") else \
                x.get("file", "")
            lines.append(f"  [{x['rule']}] {where}")
            lines.append(f"      {x['message']}")
            lines.append(f"      FIX: {x['fix']}")
    n_block = sum(1 for x in findings if x["severity"] == "blocker")
    lines.append(f"design gate: {'FAIL' if n_block else 'PASS'} "
                 f"({n_block} blocker(s), "
                 f"{len(findings) - n_block} warning(s))")
    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="the mechanical design gate")
    ap.add_argument("target", help="an HTML/CSS file or a directory")
    ap.add_argument("--root", default=".")
    ap.add_argument("--course")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="warnings fail the gate too")
    a = ap.parse_args()
    thresholds = thresholds_for(os.path.abspath(a.root), a.course) \
        if a.course else None
    findings = check_path(a.target, thresholds)
    if a.json:
        print(json.dumps(findings, indent=1))
    else:
        print(report(findings))
    bad = [x for x in findings
           if x["severity"] == "blocker" or (a.strict and x["severity"] == "warn")]
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
