#!/usr/bin/env python3
"""SOURCE DISCOVERY — finding real material to learn from, without a search engine.

THE GAP THIS CLOSES. Until this module existed there was no way for an expert
to FIND anything. `ingest.py add-url` could fetch a URL and `sources.py` could
rate one, but every URL in the system arrived because a human typed it.
`goal.py`'s study plan literally reads "gather real sources (ingest.py add-url
/ --crawl / search results the …)" — the plan assumed a search that was never
built. So "learn this subject by yourself" bottomed out at a person pasting
links, and an expert that hit an unknown tool had no route to the manual.

WHY THIS IS NOT A WEB SEARCH, WHICH IS THE POINT.

The obvious implementation is to call a search engine and read the top ten
results. That is precisely the thing to avoid: a general search index is
ranked for engagement, is personalised, changes hourly, and its top results
for any technical question are content farms, SEO reposts and AI-generated
summaries of the real document. Citing a search engine cites nothing, because
the result set that produced the citation no longer exists. `sources.py` now
pins every search-engine host to tier 4 for exactly this reason.

What this module does instead is query the CATALOGUES the real material is
registered in. Every rail below is a public, keyless API run by a non-profit,
a library, a public research body or a standards organisation, and each one
indexes a curated corpus rather than the open web:

    openalex     250M scholarly works, with DOIs and open-access links
    crossref     the DOI registry itself
    pubmed       NIH/NLM biomedical literature
    doaj         peer-reviewed open-access journals, and ONLY those
    zenodo       CERN's research-data repository
    swh          Software Heritage: archived source code
    github       real code and real READMEs
    europa       the EU open-data portal
    loc          the Library of Congress
    wikidata     entity grounding — what a term even refers to
    arxiv        preprints (see BLIND SPOTS: TLS-sensitive)

The effect is that "only learn from reputable sources" stops being an
instruction in a prompt — which a model may ignore — and becomes a property
of where the candidates came from. A content farm cannot appear in these
results because it is not in these catalogues.

EVERY RESULT IS RATED, AND THE RATING IS THE PLATFORM'S OWN. Each candidate
goes through `sources.classify`, so a result carries the same tier a human
paste would, decided from the HOST rather than from anything the result says
about itself. `--min-tier` filters, and the count of what was filtered is
always reported: a discovery run that found nothing learnable must not look
like a discovery run that found nothing.

NOTHING IS INGESTED HERE. This finds and rates candidates; `ingest.py add-url`
fetches them, and that separation is deliberate — discovery is safe and
read-only, ingestion writes to the expert and costs a fetch. `--commands`
prints the exact add-url lines so the step stays explicit and auditable.

    python discover.py "b-tree index concurrency"
    python discover.py "postgres vacuum" --rails openalex,crossref --limit 5
    python discover.py "CRISPR off-target" --rails pubmed --min-tier 1
    python discover.py "raft consensus" --commands --root experts/dbexpert
    python discover.py "kubernetes operator" --json

BLIND SPOTS, stated because a discovery tool that hides them is worse than
none:
  * COVERAGE IS THE CATALOGUE'S. If a vendor never registered their manual
    with anyone, no rail here will find it. That is the trade for excluding
    content farms, and it is the right trade for this platform, but it is a
    real hole: some of the best engineering documentation on earth is a
    company's own site and appears in no index.
  * RELEVANCE IS THE RAIL'S. These are keyword APIs, not semantic search.
    Measured: OpenAlex's default `search` returned a phylogenetics paper for
    "b-tree index", so this module uses `title_and_abstract.search`, which
    did not. Other rails have no such control and will return chaff.
  * arXiv is queried over TLS and fails on machines whose certificate store
    is incomplete (reproduced on the development machine, 2026-08-25). It is
    therefore NOT in the default rail set. OpenAlex and Crossref both index
    arXiv preprints, so the coverage loss is small.
  * NO RANKING BY QUALITY WITHIN A TIER. Order is tier, then rail order, then
    the rail's own ranking. Citation counts are reported where a rail gives
    them but are not used to sort: citation count measures age and fashion at
    least as much as merit.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# A real, identifying User-Agent. Several of these APIs ask for one in their
# terms (Crossref's "polite pool" gives faster service to requests that
# identify themselves), and an anonymous scraper-shaped request is the kind
# that gets a whole platform blocked.
UA = ("expert-fleet/1.0 (+https://github.com/lilianneromano0205-coder/"
      "self-learning-24.7-agent)")
TIMEOUT = 25
MAX_PER_RAIL = 25


class RailError(Exception):
    """One rail failed. The others continue — a discovery run must not be
    all-or-nothing, because the rails have independent outages."""


def _get(url, timeout=TIMEOUT, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(4_000_000)
    except urllib.error.HTTPError as e:
        raise RailError(f"HTTP {e.code} {e.reason}") from e
    except Exception as e:
        raise RailError(f"{type(e).__name__}: {str(e)[:120]}") from e


def _json(url, timeout=TIMEOUT):
    raw = _get(url, timeout)
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as e:
        raise RailError(f"the rail did not return JSON: {e}") from e


def _q(s):
    return urllib.parse.quote(str(s or "").strip())


def _hit(url, title, rail, **extra):
    """One candidate. `url` is what would actually be ingested."""
    h = {"url": str(url or "").strip(), "title": " ".join(
        str(title or "").split())[:300], "rail": rail}
    h.update({k: v for k, v in extra.items() if v not in (None, "", [])})
    return h


# ------------------------------------------------------------------- rails

def rail_openalex(query, limit):
    # `filter=title_and_abstract.search:` rather than the bare `search=`.
    # MEASURED, not preferred: for "b-tree index" the bare search returned
    # "The neighbor-joining method: …phylogenetic trees" as its top result
    # and title_and_abstract.search did not. The default searches full text,
    # so a passing mention outranks a paper about the subject.
    url = (f"https://api.openalex.org/works?filter=title_and_abstract.search:"
           f"{_q(query)}&per-page={limit}")
    out = []
    for w in (_json(url).get("results") or [])[:limit]:
        oa = (w.get("best_oa_location") or w.get("open_access") or {})
        link = w.get("doi") or oa.get("oa_url") or w.get("id")
        if not link:
            continue
        out.append(_hit(link, w.get("title"), "openalex",
                        year=w.get("publication_year"),
                        cited_by=w.get("cited_by_count"),
                        open_access=(w.get("open_access") or {}).get("is_oa"),
                        pdf=oa.get("pdf_url")))
    return out


def rail_crossref(query, limit):
    url = (f"https://api.crossref.org/works?query={_q(query)}&rows={limit}"
           f"&select=DOI,URL,title,issued,type,container-title")
    out = []
    for it in ((_json(url).get("message") or {}).get("items") or [])[:limit]:
        link = it.get("URL") or (f"https://doi.org/{it['DOI']}"
                                 if it.get("DOI") else "")
        if not link:
            continue
        issued = ((it.get("issued") or {}).get("date-parts") or [[None]])[0]
        out.append(_hit(link, (it.get("title") or [""])[0], "crossref",
                        year=issued[0] if issued else None,
                        kind_hint=it.get("type"),
                        venue=(it.get("container-title") or [""])[0] or None))
    return out


def rail_pubmed(query, limit):
    ids = (((_json(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        f"db=pubmed&term={_q(query)}&retmax={limit}&retmode=json")
        .get("esearchresult") or {}).get("idlist")) or [])[:limit]
    if not ids:
        return []
    summ = (_json(
        f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?"
        f"db=pubmed&id={','.join(ids)}&retmode=json").get("result") or {})
    out = []
    for pid in ids:
        rec = summ.get(pid) or {}
        out.append(_hit(f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
                        rec.get("title") or f"PMID {pid}", "pubmed",
                        year=(rec.get("pubdate") or "")[:4] or None,
                        venue=rec.get("source")))
    return out


def rail_doaj(query, limit):
    url = f"https://doaj.org/api/search/articles/{_q(query)}?pageSize={limit}"
    out = []
    for r in (_json(url).get("results") or [])[:limit]:
        bib = r.get("bibjson") or {}
        links = [l.get("url") for l in (bib.get("link") or []) if l.get("url")]
        doi = next((i.get("id") for i in (bib.get("identifier") or [])
                    if (i.get("type") or "").lower() == "doi"), None)
        link = (f"https://doi.org/{doi}" if doi else
                (links[0] if links else ""))
        if not link:
            continue
        out.append(_hit(link, bib.get("title"), "doaj",
                        year=bib.get("year"),
                        venue=((bib.get("journal") or {}).get("title"))))
    return out


def rail_zenodo(query, limit):
    url = f"https://zenodo.org/api/records?q={_q(query)}&size={limit}"
    out = []
    hits = ((_json(url).get("hits") or {}).get("hits")) or []
    for r in hits[:limit]:
        meta = r.get("metadata") or {}
        link = r.get("doi_url") or r.get("links", {}).get("self_html") or ""
        if not link:
            continue
        out.append(_hit(link, meta.get("title"), "zenodo",
                        year=(meta.get("publication_date") or "")[:4] or None,
                        kind_hint=(meta.get("resource_type") or {}).get("type")))
    return out


def rail_swh(query, limit):
    url = (f"https://archive.softwareheritage.org/api/1/origin/search/"
           f"{_q(query)}/?limit={limit}")
    out = []
    for r in (_json(url) or [])[:limit]:
        if r.get("url"):
            out.append(_hit(r["url"], r["url"], "swh"))
    return out


def rail_github(query, limit):
    url = (f"https://api.github.com/search/repositories?q={_q(query)}"
           f"&per_page={limit}&sort=stars")
    out = []
    for r in (_json(url).get("items") or [])[:limit]:
        out.append(_hit(r.get("html_url"), r.get("full_name"), "github",
                        stars=r.get("stargazers_count"),
                        summary=r.get("description"),
                        language=r.get("language")))
    return out


def rail_europa(query, limit):
    url = (f"https://data.europa.eu/api/hub/search/search?q={_q(query)}"
           f"&limit={limit}")
    d = _json(url)
    results = ((d.get("result") or {}).get("results")
               if isinstance(d.get("result"), dict) else d.get("results")) or []
    out = []
    for r in results[:limit]:
        rid = r.get("id") or ""
        title = r.get("title")
        if isinstance(title, dict):
            title = title.get("en") or next(iter(title.values()), rid)
        if rid:
            out.append(_hit(f"https://data.europa.eu/data/datasets/{rid}",
                            title or rid, "europa"))
    return out


def rail_loc(query, limit):
    url = f"https://www.loc.gov/search/?q={_q(query)}&fo=json&c={limit}"
    out = []
    for r in (_json(url, timeout=45).get("results") or [])[:limit]:
        link = r.get("id") or r.get("url")
        if isinstance(link, str) and link.startswith("http"):
            out.append(_hit(link, r.get("title"), "loc"))
    return out


def rail_wikidata(query, limit):
    url = (f"https://www.wikidata.org/w/api.php?action=wbsearchentities"
           f"&search={_q(query)}&language=en&format=json&limit={limit}")
    out = []
    for r in (_json(url).get("search") or [])[:limit]:
        if r.get("concepturi"):
            out.append(_hit(r["concepturi"], r.get("label"), "wikidata",
                            summary=r.get("description")))
    return out


def rail_arxiv(query, limit):
    raw = _get(f"https://export.arxiv.org/api/query?search_query=all:"
               f"{_q(query)}&max_results={limit}", accept="application/atom+xml")
    text = raw.decode("utf-8", errors="replace")
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, re.S)[:limit]:
        idm = re.search(r"<id>([^<]+)</id>", entry)
        tim = re.search(r"<title>(.*?)</title>", entry, re.S)
        pub = re.search(r"<published>(\d{4})", entry)
        if idm:
            out.append(_hit(idm.group(1), tim.group(1) if tim else "", "arxiv",
                            year=pub.group(1) if pub else None))
    return out


RAILS = {
    "openalex": (rail_openalex, "250M scholarly works, DOIs and OA links"),
    "crossref": (rail_crossref, "the DOI registry"),
    "pubmed":   (rail_pubmed,   "NIH/NLM biomedical literature"),
    "doaj":     (rail_doaj,     "peer-reviewed open-access journals only"),
    "zenodo":   (rail_zenodo,   "CERN's research-data repository"),
    "swh":      (rail_swh,      "Software Heritage archived source code"),
    "github":   (rail_github,   "real code and READMEs"),
    "europa":   (rail_europa,   "EU open-data portal"),
    "loc":      (rail_loc,      "Library of Congress"),
    "wikidata": (rail_wikidata, "entity grounding: what a term refers to"),
    "arxiv":    (rail_arxiv,    "preprints (TLS-sensitive; not a default)"),
}

# arXiv is excluded by default: it failed TLS verification on the development
# machine while every other rail succeeded, and OpenAlex and Crossref both
# index arXiv preprints, so the coverage cost is small and the false-failure
# cost is not. loc is excluded because it needs a 45s timeout.
DEFAULT_RAILS = ("openalex", "crossref", "doaj", "pubmed", "github",
                 "zenodo", "swh")


# ------------------------------------------------------------------ search

# Words that describe WANTING something rather than the thing. A goal is
# phrased for a person ("understand b-tree index concurrency control"); a
# catalogue API is a keyword index, and handing it the whole sentence makes
# "understand" and "control" carry the same weight as "b-tree".
_INTENT = {
    "understand", "learn", "study", "research", "explain", "explore", "find",
    "know", "master", "review", "read", "summarise", "summarize", "how", "to",
    "what", "why", "when", "where", "which", "who", "is", "are", "the", "a",
    "an", "of", "for", "in", "on", "with", "about", "and", "or", "into",
    "from", "using", "use", "get", "make", "do", "does", "best", "practice",
    "practices", "guide", "tutorial", "introduction", "overview", "basics",
    "please", "help", "me", "my", "our", "we", "i", "it", "its", "this",
    "that", "these", "those", "can", "should", "would", "could", "need",
    "want", "then", "than", "so", "as", "at", "by", "be", "will",
}
_MIN_OVERLAP_LEN = 4       # a shared word must be substantive, not "data"


def terms(text):
    """The substantive words of a goal: what it is ABOUT."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+.#_-]*", str(text or "").lower())
    return [w for w in words if len(w) > 2 and w not in _INTENT]


def prepare(query):
    """Turn a human goal into a catalogue query.

    MEASURED, not stylistic. `universal.resolve` passed the raw goal
    "understand b-tree index concurrency control" straight through, and the
    top results were "Vascular Compliance and Cardiovascular Disease" —
    PubMed matched `compliance`/`control` and the real subject was diluted by
    four words that describe the asking rather than the topic.
    """
    keep = terms(query)
    return " ".join(keep) if keep else str(query or "").strip()


def relevant(title, wanted):
    """Does this result share a substantive term with the query?

    A deliberately blunt gate, and blunt is right here. These rails are
    keyword indexes with their own fuzzy matching, and when a query has no
    good match they return their best guess rather than nothing — which is
    how a cardiology paper arrives in answer to a database question. One
    shared substantive word is a low bar that nonetheless removes the entire
    class of confidently-irrelevant results.

    It costs recall on results whose title uses different words than the
    query. That is the right trade for this platform: a wrong source that
    gets ingested becomes a cited atom and poisons the expert's knowledge,
    while a missed source costs one more search.
    """
    if not wanted:
        return True
    have = set(terms(title))
    for w in wanted:
        if len(w) < _MIN_OVERLAP_LEN:
            continue
        if w in have:
            return True
        # a stem match, so "concurrency" finds "concurrent" and "indexing"
        # finds "index" — same word, different inflection
        for h in have:
            if len(h) >= _MIN_OVERLAP_LEN and (h.startswith(w[:_MIN_OVERLAP_LEN])
                                               and (w.startswith(h[:4]))):
                return True
    return False


def _norm(url):
    """A comparison key, so one paper found by three rails is one result.

    DOIs are the strong case: OpenAlex, Crossref and DOAJ routinely return
    the same work, and without this the top of the list is one paper wearing
    three hats while genuinely different sources are pushed off the end.
    """
    u = str(url or "").strip().lower().rstrip("/")
    u = re.sub(r"^https?://(dx\.)?doi\.org/", "doi:", u)
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u


def search(query, rails=None, limit=8, min_tier=None, cfg=None,
           per_rail=None):
    """Find candidate sources. -> {"hits", "errors", "filtered", "rails"}

    Never raises for a rail failure: a discovery run with one dead rail is a
    partial result, and reporting it as a total failure would be a lie in the
    unhelpful direction.
    """
    import sources
    names = [r for r in (rails or DEFAULT_RAILS) if r in RAILS]
    unknown = [r for r in (rails or []) if r not in RAILS]
    n = max(1, min(int(per_rail or limit), MAX_PER_RAIL))
    asked = prepare(query)
    wanted = terms(asked)
    hits, errors, seen, off_topic = [], [], set(), 0
    for name in names:
        fn = RAILS[name][0]
        try:
            got = fn(asked, n) or []
        except RailError as e:
            errors.append({"rail": name, "error": str(e)})
            continue
        except Exception as e:                       # pragma: no cover
            errors.append({"rail": name,
                           "error": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        for h in got:
            key = _norm(h.get("url"))
            if not key or key in seen:
                continue
            seen.add(key)
            if not relevant(h.get("title") or "", wanted):
                # These rails answer every query with SOMETHING. Their idea
                # of "closest match" for a term they do not cover is a
                # confidently irrelevant paper, and an irrelevant source that
                # gets ingested becomes a cited atom — a wrong belief with a
                # real citation attached, which is worse than no belief.
                off_topic += 1
                continue
            kind, tier, why = sources.classify(h["url"],
                                               kind_hint=h.pop("kind_hint", ""),
                                               cfg=cfg)
            h.update({"kind": kind, "tier": tier, "why": why})
            hits.append(h)
    for u in unknown:
        errors.append({"rail": u, "error": "no such rail"})

    bar = sources.LEARN_MIN_TIER if min_tier is None else int(min_tier)
    kept = [h for h in hits if h["tier"] <= bar]
    filtered = len(hits) - len(kept)
    order = {r: i for i, r in enumerate(names)}
    kept.sort(key=lambda h: (h["tier"], order.get(h["rail"], 99)))
    return {"query": query, "asked": asked, "rails": names,
            "hits": kept[:limit], "errors": errors, "filtered": filtered,
            "off_topic": off_topic, "found": len(hits), "min_tier": bar}


def add_url_commands(res, root=None):
    """The exact ingest lines for these hits. Discovery never fetches."""
    out = []
    for h in res.get("hits", []):
        cmd = f'python ingest.py add-url "{h["url"]}"'
        if root:
            cmd += f' --root "{root}"'
        out.append(cmd)
    return out


# --------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", help="what to look for")
    ap.add_argument("--rails", help=f"comma-separated; default "
                                    f"{','.join(DEFAULT_RAILS)}")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--per-rail", type=int, default=None)
    ap.add_argument("--min-tier", type=int, default=None,
                    help="1 normative … 4 anecdotal; default is the platform's "
                         "LEARN_MIN_TIER")
    ap.add_argument("--commands", action="store_true",
                    help="print ingest.py add-url lines instead of a table")
    ap.add_argument("--root", help="expert root, for --commands")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-rails", action="store_true")
    a = ap.parse_args()

    if a.list_rails:
        import sources
        print("RAILS — every one keyless, public, and a curated catalogue "
              "rather than a web index\n")
        for name, (_fn, what) in RAILS.items():
            mark = "*" if name in DEFAULT_RAILS else " "
            print(f" {mark} {name:10} {what}")
        print(f"\n * = on by default. LEARN_MIN_TIER = {sources.LEARN_MIN_TIER}")
        return 0
    if not a.query:
        ap.error("a query is required (or --list-rails)")

    rails = [r.strip() for r in a.rails.split(",")] if a.rails else None
    res = search(a.query, rails=rails, limit=a.limit, min_tier=a.min_tier,
                 per_rail=a.per_rail)

    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    if a.commands:
        for c in add_url_commands(res, a.root):
            print(c)
        if not res["hits"]:
            print("# nothing cleared the tier bar — no commands to run",
                  file=sys.stderr)
        return 0

    print(f"QUERY   {res['query']}")
    print(f"RAILS   {', '.join(res['rails'])}")
    print(f"FOUND   {res['found']} candidate(s); {res['filtered']} below "
          f"tier {res['min_tier']} were filtered out")
    if res["errors"]:
        for e in res["errors"]:
            print(f"  rail '{e['rail']}' failed: {e['error']}")
    print()
    if not res["hits"]:
        print("Nothing cleared the bar. That is a RESULT, not an error: these "
              "catalogues do not index everything, and the alternative — "
              "falling back to a web search — is what this module exists to "
              "avoid.")
        return 0
    for h in res["hits"]:
        extra = []
        for k in ("year", "venue", "cited_by", "stars", "language"):
            if h.get(k) is not None:
                extra.append(f"{k}={h[k]}")
        print(f"[tier {h['tier']}] {h['title'][:88]}")
        print(f"           {h['url']}")
        print(f"           {h['rail']}"
              + (f" — {'; '.join(extra)}" if extra else ""))
    print(f"\nIngest any of them with:  python ingest.py add-url <url>"
          + (f" --root {a.root}" if a.root else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
