#!/usr/bin/env python3
"""STANDARDS — the bar, extracted from the material and made checkable.

Feeding an expert the references, the guides and the studies is only half
the trick. The other half is turning what they DEMAND into a short list the
work must clear, in front of the agent while it works, and — wherever
possible — into a number a gate can test.

    - R-01 [tier 1] Body text contrast is at least 4.5:1  [atom: C-0202]
      [src: https://www.w3.org/TR/WCAG22/] [check: min_contrast=4.5]

Rules come from normative atoms: the ones that say must, never, at least,
required. Three properties keep the list honest:

  * a CONTESTED claim can never become a standard — if the expert's own
    material disagrees with itself on a point, that point is not the bar
    (conflicts.py rules on it first)
  * every rule carries the tier of the source it came from, so a rule from a
    spec outranks one from a video, visibly
  * the file is append-only and owner-editable: extraction never rewrites a
    line a human wrote, and the owner can add rules the material never
    stated, or delete ones they disagree with

Rules whose statement contains a threshold the design gate understands get a
[check: key=value] tag, which raises designcheck.py's bar for that course.

    python standards.py --root <expert> --course design --extract
    python standards.py --root <expert> --course design
    python standards.py --root <expert> --course design --add "Never ship a
        page without a skip link" --tier 2
"""

import os
import re
import time

FILE = "standards.md"
HEADER = ("# STANDARDS — the bar work in this course must clear.\n"
          "# Extracted from verified atoms; append-only. Your own lines are "
          "never rewritten.\n\n")
RULE_RE = re.compile(
    r"^- (?P<id>R-\d+)\s*\[tier (?P<tier>\d)\]\s*(?P<text>.*?)\s*"
    r"(?:\[atom:\s*(?P<atom>[^\]]+)\])?\s*"
    r"(?:\[src:\s*(?P<src>[^\]]+)\])?\s*"
    r"(?:\[check:\s*(?P<check>[^\]]+)\])?\s*$")
NORMATIVE = re.compile(
    r"\b(must|must not|never|always|shall|required|至少|at least|at most|"
    r"minimum|maximum|no less than|no more than|should not|should)\b", re.I)
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
        "at", "by", "from", "is", "are", "be", "should", "must", "never",
        "always", "least", "most"}
# statement pattern -> the designcheck threshold it sets
CHECKS = (
    (re.compile(r"contrast\D{0,30}?(\d+(?:\.\d+)?)\s*:\s*1", re.I),
     "min_contrast", float),
    (re.compile(r"(?:no more than|at most|maximum of)\s*(\d+)\s*(?:distinct\s*)?"
                r"(?:font|type)\s*sizes", re.I), "max_type_sizes", int),
)


def path(root, course):
    d = os.path.join(root, "courses", str(course))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, FILE)


def load(root, course):
    out = []
    try:
        with open(path(root, course), "r", encoding="utf-8") as f:
            body = f.read()
    except OSError:
        return out
    for line in body.splitlines():
        m = RULE_RE.match(line.strip())
        if not m:
            continue
        d = m.groupdict()
        rule = {"id": d["id"], "tier": int(d["tier"]), "text": d["text"].strip(),
                "atom": (d["atom"] or "").strip(), "src": (d["src"] or "").strip(),
                "check": None}
        if d["check"] and "=" in d["check"]:
            k, _, v = d["check"].partition("=")
            try:
                rule["check"] = {"key": k.strip(),
                                 "value": float(v) if "." in v else int(v)}
            except ValueError:
                rule["check"] = None
        out.append(rule)
    return out


def _shape(text):
    return frozenset(w for w in re.findall(r"[a-z0-9]+", text.lower())
                     if len(w) > 2 and w not in STOP)


def _next_id(rules):
    n = max((int(r["id"].split("-")[1]) for r in rules), default=0)
    return f"R-{n + 1:02d}"


def _check_for(text):
    for pattern, key, cast in CHECKS:
        m = pattern.search(text)
        if m:
            try:
                return f"{key}={cast(m.group(1))}"
            except (TypeError, ValueError):
                continue
    return ""


def _append(root, course, lines):
    p = path(root, course)
    exists = os.path.exists(p)
    with open(p, "a", encoding="utf-8") as f:
        if not exists:
            f.write(HEADER)
        for line in lines:
            f.write(line + "\n")
    return p


def add(root, course, text, tier=2, atom="", src="", check=""):
    """Owner-authored rule. Same shape as an extracted one."""
    rules = load(root, course)
    text = " ".join(str(text).split())
    if any(_shape(r["text"]) == _shape(text) for r in rules):
        return None
    rid = _next_id(rules)
    line = f"- {rid} [tier {int(tier)}] {text}"
    if atom:
        line += f" [atom: {atom}]"
    if src:
        line += f" [src: {src}]"
    check = check or _check_for(text)
    if check:
        line += f" [check: {check}]"
    _append(root, course, [line])
    return rid


def extract(root, course, cap=40):
    """Promote normative atoms to standards. Skips contested points."""
    try:
        import conflicts
        # A claim that LOST a ruling is not the bar either: the blog post
        # beaten by the spec, and the 2018 guidance superseded by 2026, must
        # not come back as standards -- least of all carrying a [check:] that
        # could LOWER the gate below the winner's.
        contested = set()
        for c in conflicts.load(root, course):
            if c.get("verdict") == "contested":
                contested.add(c["a"]["id"])
                contested.add(c["b"]["id"])
            elif c.get("winner"):
                for side in ("a", "b"):
                    if c[side]["id"] != c["winner"]:
                        contested.add(c[side]["id"])
        atoms = conflicts.atoms(root, course)
    except Exception:
        contested, atoms = set(), []
    try:
        import sources
    except Exception:
        sources = None
    existing = load(root, course)
    seen = {_shape(r["text"]) for r in existing}
    added, skipped = [], 0
    for a in atoms:
        if len(added) >= cap:
            break
        text = " ".join(a["text"].split())
        if not NORMATIVE.search(text):
            continue
        if a["id"] in contested:
            skipped += 1              # disputed or defeated: not the bar
            continue
        shape = _shape(text)
        if not shape or shape in seen:
            continue
        seen.add(shape)
        tier = sources.tier_of(root, course, a["src"]) if sources else 4
        rid = f"R-{len(existing) + len(added) + 1:02d}"
        line = f"- {rid} [tier {tier}] {text} [atom: {a['id']}]"
        if a["src"]:
            line += f" [src: {a['src']}]"
        chk = _check_for(text)
        if chk:
            line += f" [check: {chk}]"
        added.append(line)
    if added:
        _append(root, course, added)
    return {"course": course, "added": len(added),
            "skipped_contested": skipped, "total": len(existing) + len(added)}


def render(root, course, cap=12):
    rules = load(root, course)
    if not rules:
        return ""
    rules.sort(key=lambda r: (r["tier"], r["id"]))
    lines = ["STANDARDS — the bar this work must clear. These came from your "
             "own verified material; a lower tier number is a stronger source. "
             "Work that misses one of these is not finished, however good it "
             "looks."]
    for r in rules[:cap]:
        gate = "  (gate-checked)" if r["check"] else ""
        lines.append(f"- [{r['id']} tier {r['tier']}] {r['text']}{gate}")
    if len(rules) > cap:
        lines.append(f"- ...and {len(rules) - cap} more in "
                     f"courses/{course}/standards.md")
    return "\n".join(lines)


def summary(root):
    out = {"courses": {}, "total": 0, "checked": 0}
    cdir = os.path.join(root, "courses")
    try:
        names = sorted(n for n in os.listdir(cdir)
                       if os.path.isdir(os.path.join(cdir, n)))
    except OSError:
        names = []
    for c in names:
        rules = load(root, c)
        if not rules:
            continue
        checked = sum(1 for r in rules if r["check"])
        out["courses"][c] = {"n": len(rules), "checked": checked}
        out["total"] += len(rules)
        out["checked"] += checked
    return out


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser(description="the standards a course demands")
    ap.add_argument("--root", default=".")
    ap.add_argument("--course")
    ap.add_argument("--extract", action="store_true")
    ap.add_argument("--add")
    ap.add_argument("--tier", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.add:
        if not a.course:
            raise SystemExit("--add needs --course")
        rid = add(root, a.course, a.add, a.tier)
        print(f"{rid or 'already present'}: {a.add[:70]}")
        return
    if a.extract:
        if not a.course:
            raise SystemExit("--extract needs --course")
        rep = extract(root, a.course)
        print(json.dumps(rep, indent=1) if a.json else
              f"{rep['course']}: +{rep['added']} standard(s), "
              f"{rep['skipped_contested']} contested point(s) refused, "
              f"{rep['total']} total")
        return
    if a.course:
        rules = load(root, a.course)
        print(json.dumps(rules, indent=1) if a.json else
              (render(root, a.course) or "no standards recorded yet"))
        return
    s = summary(root)
    print(json.dumps(s, indent=1) if a.json else
          f"{s['total']} standard(s), {s['checked']} gate-checked\n" +
          "\n".join(f"  {c:<22} {i['n']:>4} ({i['checked']} checked)"
                    for c, i in sorted(s["courses"].items())))


if __name__ == "__main__":
    main()
