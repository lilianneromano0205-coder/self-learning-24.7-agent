#!/usr/bin/env python3
"""THE SOURCE LEDGER — every claim knows where it came from, and what that
source is worth.

Feed an expert forty 500-page PDFs, ten hour-long videos and a pile of blog
posts and one thing is guaranteed: they will not agree. An agent that treats
every sentence it ingested as equally true has not learned a subject, it has
averaged one — which is exactly how confident nonsense gets produced.

So ingestion is not just extraction: every piece of material is recorded with
an AUTHORITY TIER, and the tier is what decides who wins when two sources
contradict each other (see conflicts.py).

  tier 1  normative   the thing itself: specs, standards, official docs,
                      peer-reviewed studies, primary data
  tier 2  professional  recognised practitioner references: design-system
                      documentation, established research groups, published
                      books, vendor engineering docs
  tier 3  instructional  courses, tutorials, conference talks, videos,
                      technical blog posts -- useful, not authoritative
  tier 4  anecdotal   forums, comment threads, unattributed posts, anything
                      whose origin cannot be established

Nothing here is guessed by a model. The tier comes from the URL, the file
kind and an owner-editable table; the owner can always overrule a specific
source, and the overrule is recorded with a reason.

    python sources.py --root <expert> --course design            # the ledger
    python sources.py --root <expert> --classify https://...     # one URL
    python sources.py --root <expert> --course design --set S-3 --tier 1 \
        --why "this is the published spec"
"""

import json
import os
import re
import time
from urllib.parse import urlparse

LEDGER = "sources.json"
TIER_NAMES = {1: "normative", 2: "professional", 3: "instructional",
              4: "anecdotal"}
TIER_WEIGHT = {1: 1.0, 2: 0.8, 3: 0.55, 4: 0.3}

# Domain -> tier. Deliberately small and honest: it covers the sources this
# platform is actually pointed at, and everything else falls through to the
# kind-based default rather than pretending to know.
DOMAIN_TIERS = (
    (1, ("w3.org", "whatwg.org", "ietf.org", "rfc-editor.org", "iso.org",
         "ecma-international.org", "unicode.org", "doi.org", "arxiv.org",
         "acm.org", "ieee.org", "nature.com", "science.org", "nih.gov",
         "pubmed.ncbi.nlm.nih.gov", "python.org", "postgresql.org")),
    (2, ("developer.mozilla.org", "web.dev", "developer.chrome.com",
         "developer.apple.com", "developers.google.com", "nngroup.com",
         "a11yproject.com", "material.io", "m3.material.io",
         "carbondesignsystem.com", "polaris.shopify.com", "atlassian.design",
         "primer.style", "spectrum.adobe.com", "microsoft.com",
         "docs.microsoft.com", "learn.microsoft.com", "smashingmagazine.com",
         "css-tricks.com", "webaim.org", "deque.com")),
    (3, ("youtube.com", "youtu.be", "udemy.com", "coursera.org", "edx.org",
         "frontendmasters.com", "egghead.io", "medium.com", "dev.to",
         "substack.com", "hashnode.com", "freecodecamp.org")),
    (4, ("reddit.com", "news.ycombinator.com", "quora.com", "x.com",
         "twitter.com", "facebook.com", "discord.com", "stackexchange.com")),
)
# stackoverflow is its own case: high signal, no editorial control
KIND_TIERS = {"spec": 1, "study": 1, "docs": 2, "book": 2, "course": 3,
              "video": 3, "article": 3, "forum": 4, "unknown": 4}
VIDEO_EXT = (".mp4", ".mkv", ".mov", ".webm", ".mp3", ".wav", ".m4a")
BOOK_EXT = (".pdf", ".epub", ".mobi", ".djvu")


def _dir(root, course):
    d = os.path.join(root, "courses", str(course))
    os.makedirs(d, exist_ok=True)
    return d


def path(root, course):
    return os.path.join(_dir(root, course), LEDGER)


def load(root, course):
    try:
        with open(path(root, course), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(root, course, rows):
    p = path(root, course)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    for attempt in range(8):
        try:
            os.replace(tmp, p)
            return p
        except PermissionError:            # OneDrive holds the target briefly
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, p)
    return p


def classify(ref, kind_hint="", cfg=None):
    """-> (kind, tier, why). Deterministic, and it says why."""
    ref = str(ref or "")
    low = ref.lower()
    owner = ((cfg or {}).get("agent", {}) or {}).get("source_tier", {}) or {}
    host = ""
    if "://" in low:
        host = urlparse(low).hostname or ""
        if host.startswith("www."):          # NOT lstrip: it strips chars,
            host = host[4:]                  # and would turn w3.org into 3.org
    for dom, tier in owner.items():                 # owner table wins
        # matched against the HOST, exactly like DOMAIN_TIERS below. Matching
        # the whole reference let any URL inherit a trusted rule by carrying
        # the domain in its path: evil.example/?ref=w3.org became tier 1.
        d = str(dom).lower().strip()
        if host and (host == d or host.endswith("." + d)):
            try:
                return (kind_hint or _kind(_kind_subject(low, host), host),
                        int(tier),
                        f"owner's [agent.source_tier] rule for {dom}")
            except (TypeError, ValueError):
                pass
    kind = kind_hint or _kind(_kind_subject(low, host), host)
    if host:
        for tier, domains in DOMAIN_TIERS:
            for d in domains:
                if host == d or host.endswith("." + d):
                    return kind, tier, f"{d} is a tier-{tier} source " \
                                       f"({TIER_NAMES[tier]})"
        if "stackoverflow.com" in host:
            return "forum", 3, "stackoverflow: high signal, no editorial review"
        if re.search(r"\.(gov|edu)(\.|$)", host):
            return kind, 2, f"{host} is an institutional domain"
    # An UNRECOGNISED origin can never buy professional or normative rank
    # from words in its own URL. `spec`, `study` and `docs` keywords in a
    # path are chosen by whoever wrote the link, so they are a hint about
    # SHAPE, not evidence of AUTHORITY: anything a blog can name itself is
    # capped at instructional. A real spec earns tier 1 by being on a
    # recognised domain, or by the owner saying so in [agent.source_tier].
    tier = KIND_TIERS.get(kind, 4)
    if not kind_hint:
        tier = max(tier, 3)
    return kind, tier, (f"unrecognised origin; rated by kind '{kind}'"
                        + ("" if kind_hint else
                           " (capped at instructional: an unknown source "
                           "cannot rank itself)"))


def _kind_subject(low, host=""):
    """The part of a reference that may decide its KIND: the host and the
    final path segment. Middle path segments are the caller's to choose."""
    if "://" not in low:
        return low
    from urllib.parse import urlsplit
    parts = urlsplit(low)
    tail = (parts.path or "").rstrip("/").rsplit("/", 1)[-1]
    return f"{parts.netloc}/{tail}"


def _kind(low, host=""):
    """Judged on the host plus the LAST path segment. Scanning the whole
    reference meant a path keyword inflated authority: any unrecognised
    domain with `api`, `guide` or `docs` anywhere in its path was rated
    tier 2 (professional) on the strength of its URL."""
    if any(low.endswith(e) for e in VIDEO_EXT) or "youtube" in host or \
            "youtu.be" in host:
        return "video"
    if any(low.endswith(e) for e in BOOK_EXT):
        return "book"
    if re.search(r"\b(rfc|spec|standard|w3c|iso)\b", low):
        return "spec"
    if re.search(r"\b(doi|arxiv|pubmed|study|paper|journal)\b", low):
        return "study"
    if re.search(r"\b(docs?|documentation|reference|api|guide)\b", low):
        return "docs"
    if re.search(r"\b(course|tutorial|lesson|lecture|workshop)\b", low):
        return "course"
    if host:
        return "article"
    return "unknown"


def record(root, course, ref, title="", kind="", lesson="", date="",
           by="ingest", cfg=None):
    """Add (or refresh) one source. Idempotent on `ref`."""
    rows = load(root, course)
    ref = str(ref or "").strip()
    for r in rows:
        if r.get("ref") == ref:
            if lesson and lesson not in (r.get("lessons") or []):
                r.setdefault("lessons", []).append(lesson)
                save(root, course, rows)
            return r
    k, tier, why = classify(ref, kind, cfg)
    rec = {"id": f"S-{len(rows) + 1}", "ref": ref,
           "title": (title or os.path.basename(ref) or ref)[:200],
           "kind": k, "tier": tier, "tier_name": TIER_NAMES[tier],
           "weight": TIER_WEIGHT[tier], "why": why,
           "date": date or "", "added": time.strftime("%Y-%m-%d"),
           "by": by, "lessons": [lesson] if lesson else [], "override": None}
    rows.append(rec)
    save(root, course, rows)
    return rec


def set_tier(root, course, sid, tier, why="", by="owner"):
    """The owner overrules a rating. Recorded, never silent."""
    tier = int(tier)
    if tier not in TIER_NAMES:
        raise ValueError(f"tier must be 1-4, not {tier}")
    rows = load(root, course)
    for r in rows:
        if r.get("id") == sid or r.get("ref") == sid:
            r["override"] = {"from": r["tier"], "to": tier, "by": by,
                             "why": why or "no reason given",
                             "at": time.strftime("%Y-%m-%d")}
            r["tier"], r["tier_name"] = tier, TIER_NAMES[tier]
            r["weight"] = TIER_WEIGHT[tier]
            r["why"] = f"owner override: {why or 'no reason given'}"
            save(root, course, rows)
            return r
    raise KeyError(f"no source {sid} in course {course}")


def by_ref(root, course, ref):
    """EXACT match only. Substring matching returned another source's tier
    whenever one reference contained another ("a.md" matched "data.md"),
    which silently mis-rated the authority a conflict ruling depends on."""
    ref = str(ref or "")
    for r in load(root, course):
        if r.get("ref") == ref or r.get("id") == ref:
            return r
    return None


def tier_of(root, course, ref, default=4):
    r = by_ref(root, course, ref)
    return int(r["tier"]) if r else default


def courses(root):
    d = os.path.join(root, "courses")
    try:
        return sorted(n for n in os.listdir(d)
                      if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []


def summary(root, course=None):
    out = {"courses": {}, "total": 0, "by_tier": {1: 0, 2: 0, 3: 0, 4: 0}}
    for c in ([course] if course else courses(root)):
        rows = load(root, c)
        if not rows:
            continue
        counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for r in rows:
            counts[int(r.get("tier", 4))] += 1
            out["by_tier"][int(r.get("tier", 4))] += 1
        out["courses"][c] = {"n": len(rows), "by_tier": counts,
                             "overridden": sum(1 for r in rows if r.get("override"))}
        out["total"] += len(rows)
    return out


def render(root, course, cap=12):
    """The context block: what this course actually rests on."""
    rows = load(root, course)
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: (r.get("tier", 4), r.get("title", "")))
    lines = ["SOURCE AUTHORITY — what this course rests on. When two sources "
             "disagree, the lower tier number wins; when they are the SAME "
             "tier, say so instead of picking one."]
    for r in rows[:cap]:
        lines.append(f"- [tier {r['tier']} {r['tier_name']}] {r['title'][:80]} "
                     f"({r['kind']}{', ' + r['date'] if r.get('date') else ''})")
    if len(rows) > cap:
        by_tier = {}
        for r in rows[cap:]:
            by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
        lines.append("- ...and " + ", ".join(
            f"{n} more tier-{t}" for t, n in sorted(by_tier.items())))
    return "\n".join(lines)


def main():
    import argparse
    import tomllib
    ap = argparse.ArgumentParser(description="the source authority ledger")
    ap.add_argument("--root", default=".")
    ap.add_argument("--course")
    ap.add_argument("--classify", help="rate one URL or path and explain why")
    ap.add_argument("--add", help="record a source (needs --course)")
    ap.add_argument("--title", default="")
    ap.add_argument("--kind", default="")
    ap.add_argument("--set", dest="sid", help="source id to overrule")
    ap.add_argument("--tier", type=int)
    ap.add_argument("--why", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    cfg = {}
    try:
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            cfg = tomllib.loads(f.read().decode("utf-8-sig"))
    except OSError:
        pass
    if a.classify:
        k, t, why = classify(a.classify, a.kind, cfg)
        print(json.dumps({"kind": k, "tier": t, "tier_name": TIER_NAMES[t],
                          "weight": TIER_WEIGHT[t], "why": why}, indent=1)
              if a.json else
              f"{a.classify}\n  kind {k} · tier {t} ({TIER_NAMES[t]}, "
              f"weight {TIER_WEIGHT[t]})\n  {why}")
        return
    if a.add:
        if not a.course:
            raise SystemExit("--add needs --course")
        r = record(root, a.course, a.add, a.title, a.kind, cfg=cfg)
        print(json.dumps(r, indent=1) if a.json else
              f"{r['id']} {r['title']} -> tier {r['tier']} ({r['why']})")
        return
    if a.sid:
        if not (a.course and a.tier):
            raise SystemExit("--set needs --course and --tier")
        r = set_tier(root, a.course, a.sid, a.tier, a.why)
        print(f"{r['id']} -> tier {r['tier']} ({r['tier_name']}); "
              f"was tier {r['override']['from']}")
        return
    if a.json:
        print(json.dumps({"summary": summary(root, a.course),
                          "rows": load(root, a.course) if a.course else None},
                         indent=1))
        return
    s = summary(root, a.course)
    print(f"{s['total']} source(s) across {len(s['courses'])} course(s)")
    for t in (1, 2, 3, 4):
        print(f"  tier {t} {TIER_NAMES[t]:<14} {s['by_tier'][t]}")
    for c, info in sorted(s["courses"].items()):
        print(f"  {c:<22} {info['n']:>4} sources, "
              f"{info['overridden']} owner-rated")


if __name__ == "__main__":
    main()
