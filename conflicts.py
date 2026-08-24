#!/usr/bin/env python3
"""CONTRADICTION CONTROL — what to believe when the material disagrees.

Ten hour-long videos, forty 500-page PDFs and a browser full of courses will
contradict each other. Some of it is age (a 2019 tutorial against the 2026
spec), some is authority (a forum post against the standard), some is not a
contradiction at all (two rules that hold in different situations), and some
is a genuine open dispute between equals.

An agent that flattens all four into "the material says..." produces the
confident nonsense this platform exists to prevent. So contradictions are
detected mechanically, classified into those four kinds, and either RESOLVED
with a stated reason or marked CONTESTED — and a contested point may not be
asserted as settled. No model is asked to adjudicate: the verdict comes from
the source ledger's authority tiers (sources.py) and the dates.

  superseded   the newer source supersedes the older, and the older is named
  authority    a higher tier outranks a lower one, and the loser is named
  context      both hold, under different stated conditions
  contested    same tier, same era, no qualifier -> BOTH must be presented

Detection is deterministic and conservative: polarity flips (always/never,
use/avoid, a negation on one side only) and numeric disagreements on the same
metric, between atoms that are demonstrably about the same subject. It would
rather miss a subtle conflict than invent one.

    python conflicts.py --root <expert> --course design           # scan
    python conflicts.py --root <expert> --course design --write   # + files
    python conflicts.py --root <expert> --check answer.md --course design
"""

import hashlib
import json
import os
import re
import time

try:
    import sources as _sources
except ImportError:                                  # pragma: no cover
    _sources = None

ATOM_RE = re.compile(r"^\s*-\s*([CPU]-\d{2,}[\w.]*)\s+(.*)$")
SRC_RE = re.compile(r"\[src:\s*([^\]]+)\]")
DATE_RE = re.compile(r"\b(19|20)\d{2}\b")
NUM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(px|rem|em|%|:\s*\d|s\b|ms\b|pt|dp|"
                    r"seconds?|minutes?|hours?|days?|x\b)?", re.I)
QUALIFIER_RE = re.compile(r"\b(when|if|for|on|unless|except|during|while|"
                          r"in|with)\s+([a-z0-9][a-z0-9 \-/]{2,40})", re.I)

NEGATIONS = {"not", "never", "no", "avoid", "avoids", "don't", "dont",
             "doesn't", "doesnt", "cannot", "can't", "cant", "without",
             "stop", "deprecated", "obsolete", "unsafe", "harmful", "worse",
             "discouraged", "forbidden", "disallowed", "wrong"}
ANTONYMS = [
    ("always", "never"), ("use", "avoid"), ("required", "optional"),
    ("enable", "disable"), ("include", "exclude"), ("increase", "decrease"),
    ("faster", "slower"), ("more", "less"), ("recommended", "deprecated"),
    ("safe", "unsafe"), ("allowed", "forbidden"), ("must", "may"),
    ("show", "hide"), ("add", "remove"), ("start", "stop"), ("on", "off"),
    ("before", "after"), ("larger", "smaller"), ("higher", "lower"),
    ("prefer", "avoid"), ("do", "don't"), ("supported", "unsupported"),
]
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "on",
        "at", "by", "from", "into", "that", "this", "it", "is", "are", "be",
        "was", "were", "do", "does", "did", "as", "if", "then", "than",
        "when", "while", "should", "must", "can", "will", "would", "you",
        "your", "its", "their", "there", "here", "all", "any", "one", "two",
        "use", "using", "used", "make", "makes", "made", "get", "gets"}
COMMON_WORD_SHARE = 0.15          # a word in >15% of atoms is too common
MIN_SHARED = 2
# Two claims must be about the SAME THING, not merely share a modifier.
# "buttons should never use pure black borders" and "dark mode should always
# use pure black backgrounds" overlap on 'pure black' and nothing else; at
# 0.22 that was called a contradiction, which is the confusion this module
# exists to remove. Conservative on purpose: miss a subtle conflict rather
# than invent one.
MIN_JACCARD = 0.30
MAX_PAIRS = 40_000                # a hard ceiling: scanning must always end
CONFLICTS_MD = "conflicts.md"
CONFLICTS_JSON = "conflicts.json"
# what the last scan was computed from, so "has it changed?"
# is answered by content rather than by a filesystem clock
SCAN_STAMP = "conflicts-scan.json"


def words(text):
    return [w for w in re.findall(r"[a-z0-9']+", str(text).lower())
            if len(w) > 2 and w not in STOP]


def atoms(root, course):
    """Every defined atom in a course, with its citation."""
    out = []
    cdir = os.path.join(root, "courses", str(course))
    for dirpath, _, names in os.walk(cdir):
        for fn in sorted(names):
            if fn != "notes.md":
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            try:
                with open(os.path.join(dirpath, fn), "r", encoding="utf-8",
                          errors="replace") as f:
                    body = f.read()
            except OSError:
                continue
            for line in body.splitlines():
                m = ATOM_RE.match(line)
                if not m:
                    continue
                aid, text = m.group(1), m.group(2).strip()
                src = SRC_RE.search(text)
                out.append({"id": aid, "text": SRC_RE.sub("", text).strip(),
                            "src": (src.group(1).strip() if src else ""),
                            "file": rel.replace(os.sep, "/")})
    return out


def _index(rows):
    idx, n = {}, len(rows)
    for i, r in enumerate(rows):
        for w in set(r["shape"]):
            idx.setdefault(w, []).append(i)
    ceiling = max(3, int(n * COMMON_WORD_SHARE))
    return {w: ids for w, ids in idx.items() if len(ids) <= ceiling}


def _polarity(text):
    ws = set(words(text)) | {w for w in re.findall(r"[a-z']+", text.lower())}
    return bool(ws & NEGATIONS)


def _antonym_hit(a, b):
    wa, wb = set(re.findall(r"[a-z']+", a.lower())), \
        set(re.findall(r"[a-z']+", b.lower()))
    for x, y in ANTONYMS:
        if (x in wa and y in wb) or (y in wa and x in wb):
            return f"'{x}' against '{y}'"
    return None


def _numbers(text):
    out = {}
    for m in NUM_RE.finditer(text):
        val, unit = m.group(1), (m.group(2) or "").strip().lower()
        if unit:
            out.setdefault(unit, set()).add(val)
    return out


def _numeric_hit(a, b):
    na, nb = _numbers(a), _numbers(b)
    for unit in set(na) & set(nb):
        if na[unit] != nb[unit]:
            return (f"{', '.join(sorted(na[unit]))}{unit} against "
                    f"{', '.join(sorted(nb[unit]))}{unit}")
    return None


def _qualifiers(text):
    return {m.group(2).strip().lower()[:40] for m in QUALIFIER_RE.finditer(text)}


def _date_of(text, rec):
    if rec and rec.get("date"):
        return str(rec["date"])[:10]
    m = DATE_RE.search(text or "")
    if m:
        return m.group(0)
    return (rec or {}).get("added", "")


def _tier(root, course, src):
    if not _sources or not src:
        return 4, None
    rec = _sources.by_ref(root, course, src)
    return (int(rec["tier"]) if rec else 4), rec


def scan(root, course, cap=200):
    """Find and classify every contradiction in one course."""
    rows = atoms(root, course)
    for r in rows:
        r["shape"] = words(r["text"])
    idx = _index(rows)
    seen, conflicts, pairs = set(), [], 0
    for w, ids in idx.items():
        for i_pos, i in enumerate(ids):
            for j in ids[i_pos + 1:]:
                if pairs >= MAX_PAIRS or len(conflicts) >= cap:
                    return conflicts
                key = (i, j) if i < j else (j, i)
                if key in seen:
                    continue
                seen.add(key)
                pairs += 1
                a, b = rows[i], rows[j]
                sa, sb = set(a["shape"]), set(b["shape"])
                shared = sa & sb
                if len(shared) < MIN_SHARED:
                    continue
                union = sa | sb
                if not union or len(shared) / len(union) < MIN_JACCARD:
                    continue
                why = _antonym_hit(a["text"], b["text"])
                kind = "polarity"
                if not why and _polarity(a["text"]) != _polarity(b["text"]):
                    why = "one says it should NOT be done, the other says it should"
                if not why:
                    why = _numeric_hit(a["text"], b["text"])
                    kind = "numeric" if why else kind
                if not why:
                    continue
                conflicts.append(_classify(root, course, a, b, why, kind,
                                           sorted(shared)[:6]))
    return conflicts


def _classify(root, course, a, b, why, kind, subject):
    ta, ra = _tier(root, course, a["src"])
    tb, rb = _tier(root, course, b["src"])
    da, db = _date_of(a["text"], ra), _date_of(b["text"], rb)
    qa, qb = _qualifiers(a["text"]), _qualifiers(b["text"])
    rec = {"subject": " ".join(subject), "why": why, "signal": kind,
           "a": {"id": a["id"], "text": a["text"][:300], "src": a["src"],
                 "tier": ta, "date": da, "file": a["file"],
                 "qualifiers": sorted(qa)[:3]},
           "b": {"id": b["id"], "text": b["text"][:300], "src": b["src"],
                 "tier": tb, "date": db, "file": b["file"],
                 "qualifiers": sorted(qb)[:3]},
           "at": time.strftime("%Y-%m-%d")}
    # 1. not a contradiction at all: each holds under its own stated condition
    if qa and qb and qa != qb:
        rec.update({"verdict": "context", "winner": None,
                    "ruling": (f"both hold: {a['id']} applies {', '.join(sorted(qa))}; "
                               f"{b['id']} applies {', '.join(sorted(qb))}. State "
                               f"the condition with the rule.")})
        return rec
    # 2. age: a newer source of at least equal standing supersedes an older
    ya, yb = (da[:4] if da[:4].isdigit() else ""), (db[:4] if db[:4].isdigit() else "")
    if ya and yb and ya != yb:
        new, old = (a, b) if ya > yb else (b, a)
        tnew, told = (ta, tb) if ya > yb else (tb, ta)
        if tnew <= told:
            rec.update({"verdict": "superseded", "winner": new["id"],
                        "ruling": (f"{new['id']} ({max(ya, yb)}) supersedes "
                                   f"{old['id']} ({min(ya, yb)}). Use the newer "
                                   f"one and say the older is out of date.")})
            return rec
    # 3. authority: a higher tier outranks a lower one
    if ta != tb:
        win, lose = (a, b) if ta < tb else (b, a)
        rec.update({"verdict": "authority", "winner": win["id"],
                    "ruling": (f"{win['id']} comes from a tier-{min(ta, tb)} "
                               f"source and outranks {lose['id']} "
                               f"(tier {max(ta, tb)}). Follow the higher tier "
                               f"and name the source you did not follow.")})
        return rec
    # 4. equals, no condition, same era: genuinely open
    rec.update({"verdict": "contested", "winner": None,
                "ruling": (f"{a['id']} and {b['id']} carry equal authority and "
                           f"neither is newer. This point is CONTESTED: present "
                           f"both positions and say the material disagrees. Do "
                           f"not assert either as settled.")})
    return rec


def write(root, course, cap=200):
    """Persist the scan: a JSON ledger and the human-readable page."""
    found = scan(root, course, cap)
    cdir = os.path.join(root, "courses", str(course))
    os.makedirs(cdir, exist_ok=True)
    with open(os.path.join(cdir, CONFLICTS_JSON), "w", encoding="utf-8") as f:
        json.dump(found, f, indent=1, ensure_ascii=False)
    counts = {}
    for c in found:
        counts[c["verdict"]] = counts.get(c["verdict"], 0) + 1
    lines = [f"# CONFLICTS — {course}", "",
             f"Scanned {time.strftime('%Y-%m-%d')}: {len(found)} contradiction(s) "
             f"— " + (", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
                      or "none"), "",
             "Resolved conflicts name their winner and their loser. CONTESTED "
             "points have no winner: an answer that asserts one side without "
             "saying the material disagrees is wrong, and the gate rejects it.",
             ""]
    for c in found:
        lines += [f"## {c['a']['id']} vs {c['b']['id']} — {c['verdict'].upper()}",
                  f"- subject: {c['subject']}",
                  f"- signal: {c['why']}",
                  f"- {c['a']['id']} (tier {c['a']['tier']}"
                  f"{', ' + c['a']['date'] if c['a']['date'] else ''}): "
                  f"{c['a']['text'][:200]}",
                  f"- {c['b']['id']} (tier {c['b']['tier']}"
                  f"{', ' + c['b']['date'] if c['b']['date'] else ''}): "
                  f"{c['b']['text'][:200]}",
                  f"- RULING: {c['ruling']}", ""]
    p = os.path.join(cdir, CONFLICTS_MD)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    # record WHAT was scanned, not WHEN: refresh() compares this and never
    # has to trust a filesystem clock (see material_fingerprint)
    fp, _n = material_fingerprint(cdir)
    try:
        with open(os.path.join(cdir, SCAN_STAMP), "w", encoding="utf-8") as f:
            json.dump({"fingerprint": fp, "at": time.time(),
                       "scanned": time.strftime("%Y-%m-%dT%H:%M:%S")}, f)
    except OSError:                        # pragma: no cover — read-only dir
        pass
    return {"course": course, "found": len(found), "by_verdict": counts,
            "path": p}


def material_fingerprint(cdir):
    """What a scan was computed FROM, as a hash. -> (digest, file count)

    This used to be a timestamp comparison: rescan if the newest notes.md is
    modified after conflicts.json. That is a race dressed as a cache, and it
    fails on the filesystem this platform is most often deployed on. On
    overlayfs — what every container runs on, including this project's own
    Dockerfile — the clock behind file timestamps is cached, not read per
    write: 200 files written back to back produced NINE distinct values, and
    two consecutive writes routinely land on the identical st_mtime_ns. The
    ledger and the notes written just after it therefore looked simultaneous,
    `newest <= stamp` was true, and new material was silently un-scanned —
    the one thing the docstring promised could not happen.

    A hash of the material cannot be fooled by a clock. It costs more than the
    stat it replaced, and the price is worth stating rather than waving away:
    measured at 29 ms on a 40-lesson, 844 KB course — over four times larger
    than the 50,000-token context budget that would have to load it — against
    roughly 1 ms for the timestamps. `refresh()` runs once per context
    compile, beside a model call measured in seconds, so this is under a
    percent of a step. Exact and slightly slower beats fast and wrong about
    whether the material changed.
    """
    h, n = hashlib.sha256(), 0
    for dirpath, _dirs, names in sorted(os.walk(cdir)):
        for fn in sorted(names):
            if fn != "notes.md":
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "rb") as f:
                    body = f.read()
            except OSError:
                continue
            rel = os.path.relpath(p, cdir).replace("\\", "/")
            h.update(rel.encode("utf-8") + b"\0")
            h.update(body)
            h.update(b"\0")
            n += 1
    return h.hexdigest(), n


def _read_scan_stamp(cdir):
    try:
        with open(os.path.join(cdir, SCAN_STAMP), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def refresh(root, course, max_age_s=0):
    """Rescan when the material actually changed, and only then.

    `max_age_s` is a debounce: with it set, a course scanned more recently
    than that is left alone even if it changed.
    """
    cdir = os.path.join(root, "courses", str(course))
    if not os.path.isdir(cdir):
        return False
    fp, n = material_fingerprint(cdir)
    if not n:
        return False                       # no material to scan
    prev = _read_scan_stamp(cdir)
    if prev.get("fingerprint") == fp and \
            os.path.exists(os.path.join(cdir, CONFLICTS_JSON)):
        return False
    if max_age_s and prev.get("at"):
        try:
            if time.time() - float(prev["at"]) < max_age_s:
                return False
        except (TypeError, ValueError):
            pass
    try:
        write(root, course)
        return True
    except Exception:
        return False


def load(root, course):
    try:
        with open(os.path.join(root, "courses", str(course), CONFLICTS_JSON),
                  "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def matching(root, goal, course, cap=6):
    """The conflicts this goal is about to walk into."""
    gw = set(words(goal))
    hits = []
    for c in load(root, course):
        subj = set(words(c.get("subject", "")))
        if subj and len(subj & gw) >= min(2, len(subj)):
            hits.append(c)
    hits.sort(key=lambda c: 0 if c["verdict"] == "contested" else 1)
    return hits[:cap]


def render(hits):
    if not hits:
        return ""
    lines = ["CONFLICTING MATERIAL — your own sources disagree on this. These "
             "rulings are BINDING:"]
    for c in hits:
        lines.append(f"- [{c['verdict']}] {c['subject']}: {c['ruling']}")
        if c["verdict"] == "contested":
            lines.append(f"    {c['a']['id']}: {c['a']['text'][:120]}")
            lines.append(f"    {c['b']['id']}: {c['b']['text'][:120]}")
    return "\n".join(lines)


HEDGES = ("contested", "disagree", "disputed", "both", "however", "whereas",
          "on the other hand", "some sources", "others", "no consensus",
          "conflicting", "depends")


def check(root, answer_path, course):
    """Gate: an answer may not assert one side of a CONTESTED point without
    saying the material disagrees. Returns (problems, n_contested_touched)."""
    try:
        with open(answer_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return [f"cannot read the answer: {e}"], 0
    low = text.lower()
    cited = set(re.findall(r"\b([CPU]-\d{2,}[\w.]*)\b", text))
    problems, touched = [], 0
    for c in load(root, course):
        if c.get("verdict") != "contested":
            continue
        ids = {c["a"]["id"], c["b"]["id"]}
        used = ids & cited
        subj = set(words(c.get("subject", "")))
        about = subj and len(subj & set(words(text))) >= min(2, len(subj))
        if not used and not about:
            continue
        touched += 1
        if len(used) >= 2:
            continue                       # both sides cited: honest by construction
        if any(h in low for h in HEDGES):
            continue                       # the disagreement is acknowledged
        problems.append(
            f"CONTESTED POINT ASSERTED AS SETTLED: {c['subject']} — "
            f"{c['a']['id']} and {c['b']['id']} disagree and neither outranks "
            f"the other. Present both, or say the material is divided.")
    return problems, touched


def summary(root):
    out = {"courses": {}, "total": 0, "contested": 0}
    cdir = os.path.join(root, "courses")
    try:
        names = sorted(n for n in os.listdir(cdir)
                       if os.path.isdir(os.path.join(cdir, n)))
    except OSError:
        names = []
    for c in names:
        rows = load(root, c)
        if not rows:
            continue
        contested = sum(1 for r in rows if r["verdict"] == "contested")
        out["courses"][c] = {"n": len(rows), "contested": contested}
        out["total"] += len(rows)
        out["contested"] += contested
    return out


def main():
    import argparse
    ap = argparse.ArgumentParser(description="contradiction control")
    ap.add_argument("--root", default=".")
    ap.add_argument("--course")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", help="gate an answer file")
    ap.add_argument("--goal", help="show the conflicts this goal would hit")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.check:
        if not a.course:
            raise SystemExit("--check needs --course")
        problems, n = check(root, a.check, a.course)
        for p in problems:
            print(p)
        print(f"[conflictcheck] {n} contested point(s) touched, "
              f"{len(problems)} problem(s)")
        raise SystemExit(1 if problems else 0)
    if a.goal:
        hits = matching(root, a.goal, a.course)
        print(json.dumps(hits, indent=1) if a.json else
              (render(hits) or "no conflicting material for that goal"))
        return
    if not a.course:
        s = summary(root)
        print(json.dumps(s, indent=1) if a.json else
              f"{s['total']} conflict(s), {s['contested']} contested\n" +
              "\n".join(f"  {c:<22} {i['n']:>4} ({i['contested']} contested)"
                        for c, i in sorted(s["courses"].items())))
        return
    rep = write(root, a.course) if a.write else \
        {"found": len(scan(root, a.course)), "course": a.course}
    if a.json:
        print(json.dumps(rep, indent=1))
        return
    print(f"{rep['course']}: {rep['found']} contradiction(s)"
          + (f" -> {rep['path']}" if a.write else " (use --write to record)"))
    for c in scan(root, a.course)[:10]:
        print(f"  [{c['verdict']:<10}] {c['subject'][:40]:<42} {c['why'][:50]}")


if __name__ == "__main__":
    main()
