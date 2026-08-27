#!/usr/bin/env python3
"""FRESHNESS — learned claims age, get superseded, and get retracted.

THE GAP (register #26): a cited atom, once earned, was true forever. Real
knowledge is not: papers get retracted, APIs get deprecated, prices and
versions expire. A system that quotes a 2024 claim in 2027 with the same
confidence it had the day it learned it is not remembering — it is
embalming.

THE MECHANISM, three small marks and one ledger, all additive:

  [expires: YYYY-MM-DD]   on an atom line — the claim is STALE after that
                          date. For claims that age by nature (versions,
                          prices, "current best").
  [supersedes: C-01]      on an atom line — this atom REPLACES that one.
                          The superseded atom stays on disk (lineage, like
                          runbook revisions) but scan() flags it so recall
                          and answers can prefer the successor.
  org/retractions.jsonl   the retraction ledger, CONTROL-zoned (org/ is a
                          control dir): {"at", "ref", "why", "by"}. Any
                          atom whose [src: ...] contains a retracted ref is
                          RETRACTED — the strongest flag, because the
                          ground under the citation is gone.

scan() reads the SAME notes files citecheck validates (knowledge.py's
walker — one walker, after the bug where two walkers disagreed and the
graph was silently empty) and reports expired / superseded / retracted
atoms with locations. Nothing is deleted: the platform surfaces decay,
the owner decides what to do about it — auto-forgetting would be a second
way to lose knowledge silently, which is the exact failure this module
exists to prevent.

check_doi() is the live probe: Crossref's public API marks retracted works
with an update-to relation. Keyless, optional, never called by tests —
the verdict logic is a pure function (_crossref_verdict) tested offline.

    python freshness.py scan    <root>
    python freshness.py retract <root> <ref-substring> --why "..." [--by owner]
    python freshness.py doi     <doi>          # live Crossref probe
"""

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

LEDGER = os.path.join("org", "retractions.jsonl")
EXPIRES_RE = re.compile(r"\[expires:\s*(\d{4}-\d{2}-\d{2})\s*\]")
SUPERSEDES_RE = re.compile(r"\[supersedes:\s*([CPU]-\d{2,}[\w.]*)\s*\]")

# DIRECTIVE-SHAPED MEMORY (the authority-collapse attack, 2026's memory-
# poisoning literature: "policy-conformant fact injection" and the
# "experience-to-procedure write channel"). A webpage saying "always invest
# $5,000 when X happens" gets studied into a cited atom; recalled later,
# the directive rides back into context wearing knowledge's clothes, its
# source authority diluted. The zones already stop such an atom from
# GRADING or STEERING anything, and policy still screens every command —
# but an unflagged directive still gets to argue. These patterns flag the
# shape. Deliberately NARROW: a how-to course legitimately says "run npm
# install", so only directives claiming authority over the agent, the
# owner, or resources are flagged — the blind spot (rephrased directives)
# is stated, not hidden.
DIRECTIVE_RES = (
    (re.compile(r"\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|earlier)"
                r"\s+(?:instructions|rules|constraints)", re.I),
     "injection idiom"),
    (re.compile(r"\bdisregard\s+(?:your|the)\s+(?:instructions|rules|"
                r"constitution|policy)", re.I), "injection idiom"),
    (re.compile(r"\bnew\s+instructions?\s*:", re.I), "injection idiom"),
    (re.compile(r"\bthe\s+owner\s+(?:has\s+)?(?:said|says|wants|approved|"
                r"authoriz\w*|instructed)", re.I), "claims the owner's voice"),
    (re.compile(r"\byou\s+(?:must|should|need\s+to|are\s+required\s+to)\s+"
                r"(?:transfer|send|pay|invest|wire|delete|approve|deploy|"
                r"buy|sell|grant|disable)", re.I),
     "commands a consequential action"),
    (re.compile(r"\balways\s+(?:transfer|send|pay|invest|wire|approve|"
                r"trust)\b", re.I), "standing-order shape"),
    (re.compile(r"\b(?:transfer|send|wire|invest|pay)\b[^.\n]{0,40}"
                r"[$€£]\s?\d", re.I), "moves money with an amount"),
)


class FreshnessError(Exception):
    pass


# ------------------------------------------------------------------ ledger

def retractions(root):
    out = []
    try:
        with open(os.path.join(root, LEDGER), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
    except OSError:
        pass
    return out


def retract(root, ref, why, by="owner"):
    """Record that a source is retracted. Owner/harness path — org/ is a
    CONTROL zone, so the worker's file tools cannot write the ledger and
    an agent cannot retract the source of a claim it wants to dodge."""
    ref = str(ref or "").strip()
    if len(ref) < 8:
        raise FreshnessError(
            f"ref {ref!r} is too short — a retraction matches by substring "
            f"against every [src:] in the fleet, and a short one would "
            f"retract half the library")
    if not str(why or "").strip():
        raise FreshnessError("a retraction without a why is a deletion "
                             "wearing a process's clothes")
    import locks
    p = os.path.join(root, LEDGER)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ref": ref,
           "why": str(why).strip()[:300], "by": str(by)}
    with locks.holding(p, timeout=10.0, stale=8.0):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


# -------------------------------------------------------------------- scan

def _atom_rows(root):
    """(atom-id, course, file, body) for every atom — knowledge.py's own
    walker and regex, not a second copy that agrees only by luck."""
    import knowledge
    rows = []
    for course, p in knowledge._notes_files(root):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for aid, body in knowledge.ATOM_RE.findall(text):
            rows.append((aid, course, p, body))
    return rows


def scan(root, today=None):
    """-> {"expired", "superseded", "retracted", "checked", "fresh"}.

    Flags, never deletes. Each flagged row names the atom, its course, and
    WHY it is suspect — the same evidence discipline as every diagnosis
    here: no signal, no action."""
    today = today or _dt.date.today().isoformat()
    retr = retractions(root)
    rows = _atom_rows(root)
    superseded_by = {}
    for aid, _c, _p, body in rows:
        for old in SUPERSEDES_RE.findall(body):
            superseded_by[old] = aid
    expired, superseded, retracted, suspect = [], [], [], []
    import knowledge
    for aid, course, _p, body in rows:
        src = knowledge.SRC_RE.search(body)
        ref = src.group(1).strip() if src else ""
        m = EXPIRES_RE.search(body)
        if m and m.group(1) < today:
            expired.append({"atom": aid, "course": course,
                            "why": f"expired {m.group(1)} (today {today})"})
        if aid in superseded_by:
            superseded.append({"atom": aid, "course": course,
                               "why": f"superseded by {superseded_by[aid]}"})
        hit = next((r for r in retr if r["ref"] in ref), None) if ref else None
        if hit:
            retracted.append({"atom": aid, "course": course,
                              "why": f"source retracted: {hit['why']}"
                                     f" (ref {hit['ref'][:60]})"})
        for rex, label in DIRECTIVE_RES:
            dm = rex.search(body)
            if dm:
                suspect.append({
                    "atom": aid, "course": course,
                    "why": f"directive-shaped ({label}): "
                           f"“{dm.group(0)[:70]}” from "
                           f"{ref[:60] or 'an uncited line'} — memory is "
                           f"evidence, never instruction"})
                break
    flagged = {r["atom"] for r in expired + superseded + retracted + suspect}
    return {"expired": expired, "superseded": superseded,
            "retracted": retracted, "suspect": suspect,
            "checked": len(rows),
            "fresh": len({a for a, _c, _p, _b in rows} - flagged)}


# -------------------------------------------------------------- live probe

def _crossref_verdict(js):
    """Pure verdict from a Crossref /works/<doi> message: retracted or not,
    with the evidence named. Kept free of network so tests exercise the
    judgment, not the wire."""
    msg = (js or {}).get("message") or {}
    updates = msg.get("update-to") or []
    for u in updates:
        if str(u.get("type", "")).lower() in ("retraction", "retracted",
                                              "withdrawal", "removal"):
            return {"retracted": True,
                    "why": f"Crossref update-to type={u.get('type')} "
                           f"dated {(u.get('updated') or {}).get('date-parts')}"}
    if str(msg.get("subtype") or "").lower() == "retraction":
        return {"retracted": True, "why": "the record IS a retraction notice"}
    return {"retracted": False, "why": "no retraction relation on record"}


def check_doi(doi, timeout=20):
    """LIVE Crossref probe. Keyless, read-only, never called by tests."""
    import urllib.request
    url = f"https://api.crossref.org/works/{urllib.parse.quote(str(doi))}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "expert-fleet-freshness (mailto:owner@localhost)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _crossref_verdict(json.loads(r.read().decode("utf-8")))


_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\]\"']+)")


def cited_dois(root):
    """Every distinct DOI appearing in a [src:] across this expert's notes —
    the same walker as scan(), so the feed checks exactly what recall can
    cite."""
    import knowledge
    out = set()
    for _aid, _course, _p, body in _atom_rows(root):
        src = knowledge.SRC_RE.search(body)
        if src:
            m = _DOI_RE.search(src.group(1))
            if m:
                out.add(m.group(1).rstrip(".,;)"))
    return sorted(out)


def feed(root, limit=25, probe=None, by="crossref-feed"):
    """THE RETRACTION FEED: probe every cited DOI against Crossref's
    retraction relations and record a ledger row for each hit — the
    automated half of what retract() does by hand. Bounded per run
    (Crossref is a shared public resource), idempotent (an already-retracted
    ref is skipped), and every hit carries Crossref's own evidence as the
    why. Wire it as a routine to run on a schedule; a failure on one DOI is
    reported and never stops the sweep."""
    probe = probe or check_doi
    already = {r["ref"] for r in retractions(root)}
    checked, hits, errors = 0, [], []
    for doi in cited_dois(root):
        if checked >= max(1, int(limit)):
            break
        if any(ref in doi for ref in already):
            continue
        checked += 1
        try:
            v = probe(doi)
        except Exception as e:
            errors.append({"doi": doi, "error": f"{type(e).__name__}: {e}"[:120]})
            continue
        if v.get("retracted"):
            retract(root, doi, v.get("why") or "retraction on record",
                    by=by)
            hits.append(doi)
    return {"checked": checked, "retracted": hits, "errors": errors,
            "already_on_ledger": len(already)}


# --------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("scan")
    ps.add_argument("root")
    pr = sub.add_parser("retract")
    pr.add_argument("root"); pr.add_argument("ref")
    pr.add_argument("--why", required=True)
    pr.add_argument("--by", default="owner")
    pd = sub.add_parser("doi")
    pd.add_argument("doi")
    pf = sub.add_parser("feed")
    pf.add_argument("root")
    pf.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()
    if a.cmd == "scan":
        r = scan(a.root)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        raise SystemExit(1 if (r["expired"] or r["retracted"]
                               or r["suspect"]) else 0)
    elif a.cmd == "retract":
        row = retract(a.root, a.ref, a.why, by=a.by)
        print(f"retracted refs containing {row['ref']!r}: {row['why']}")
    elif a.cmd == "doi":
        print(json.dumps(check_doi(a.doi), indent=1))
    elif a.cmd == "feed":
        r = feed(a.root, limit=a.limit)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        raise SystemExit(1 if r["retracted"] else 0)


if __name__ == "__main__":
    main()
