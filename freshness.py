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
    expired, superseded, retracted = [], [], []
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
    flagged = {r["atom"] for r in expired + superseded + retracted}
    return {"expired": expired, "superseded": superseded,
            "retracted": retracted, "checked": len(rows),
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
    a = ap.parse_args()
    if a.cmd == "scan":
        r = scan(a.root)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        raise SystemExit(1 if (r["expired"] or r["retracted"]) else 0)
    elif a.cmd == "retract":
        row = retract(a.root, a.ref, a.why, by=a.by)
        print(f"retracted refs containing {row['ref']!r}: {row['why']}")
    elif a.cmd == "doi":
        print(json.dumps(check_doi(a.doi), indent=1))


if __name__ == "__main__":
    main()
