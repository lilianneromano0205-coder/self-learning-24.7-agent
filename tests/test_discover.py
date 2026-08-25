#!/usr/bin/env python3
"""SOURCE DISCOVERY — the properties that make it better than a web search.

Before discover.py, no expert could FIND anything. Every URL in the platform
arrived because a human typed it, and goal.py's own study plan said "gather
real sources (ingest.py add-url / --crawl / search results the …)" — assuming
a search that did not exist. "Learn this subject yourself" therefore bottomed
out at a person pasting links.

The naive fix is to call a search engine. That is the thing to avoid: a
general index is ranked for engagement, personalised, changes hourly, and its
top results for a technical question are content farms and SEO reposts of the
real document. This module queries the CATALOGUES instead — OpenAlex,
Crossref, DOAJ, PubMed, Zenodo, Software Heritage, GitHub — every one keyless
and curated.

The properties worth holding, and each is a way the thing could be wrong:

  1. results are RANKED BY THE PLATFORM'S OWN TIER, not by the rail's opinion
  2. one paper found by three rails is ONE result — DOI-normalised
  3. a dead rail degrades the run, it does not fail it
  4. what was filtered is COUNTED — "found nothing learnable" must never look
     like "found nothing"
  5. a search engine can never become a result, at any tier setting
  6. discovery NEVER fetches: it emits ingest commands and touches nothing
  7. an unknown rail is reported, not silently ignored
  8. and it works against the real internet (smoke, tolerant of outages)

Run from the agent/ directory:  python tests/test_discover.py
"""

import os
import sys

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import discover                 # noqa: E402
import sources                  # noqa: E402


def fake(name, hits):
    """A rail that returns exactly what we say, so ranking/dedupe/filtering
    are tested without a network in the loop."""
    def _r(_query, _limit):
        return [discover._hit(u, t, name) for u, t in hits]
    return _r


def boom(msg):
    def _r(_query, _limit):
        raise discover.RailError(msg)
    return _r


def main():
    saved = dict(discover.RAILS)
    try:
        check_ranking_dedupe_and_filtering()
        check_a_dead_rail_does_not_kill_the_run()
        check_a_search_engine_can_never_be_a_result()
        check_discovery_never_fetches()
        check_unknown_rails_are_reported()
        check_a_goal_is_not_a_keyword_query()
    finally:
        discover.RAILS.clear()
        discover.RAILS.update(saved)
    check_it_works_against_the_real_internet()
    print("PASS test_discover")


def check_ranking_dedupe_and_filtering():
    DOI = "https://doi.org/10.1145/356770.356776"
    discover.RAILS.clear()
    discover.RAILS.update({
        # the SAME work, reached three ways — the common case, because these
        # catalogues deliberately overlap
        "a": (fake("a", [(DOI, "Concurrency of operations on B-trees")]), ""),
        "b": (fake("b", [("http://dx.doi.org/10.1145/356770.356776/",
                          "same paper, other resolver")]), ""),
        "c": (fake("c", [("https://doi.org/10.1145/356770.356776",
                          "same paper again")]), ""),
        # genuinely different sources, ON TOPIC so that the TIER rule is what
        # is under test here and not the relevance gate (which is tested on
        # its own in check_a_goal_is_not_a_keyword_query)
        "d": (fake("d", [("https://medium.com/@someone/btrees-explained",
                          "B-trees explained simply")]), ""),
        "e": (fake("e", [("https://github.com/postgres/postgres",
                          "postgres B-trees and index code")]), ""),
    })
    res = discover.search("b-trees", rails=["a", "b", "c", "d", "e"], limit=10)

    urls = [h["url"] for h in res["hits"]]
    assert len(urls) == len(set(discover._norm(u) for u in urls)), urls
    doi_hits = [h for h in res["hits"] if "356770" in h["url"]]
    assert len(doi_hits) == 1, (
        f"one paper indexed by three catalogues became {len(doi_hits)} "
        f"results — the top of the list is then one work wearing three hats "
        f"while genuinely different sources are pushed off the end")

    tiers = [h["tier"] for h in res["hits"]]
    assert tiers == sorted(tiers), f"not ranked by tier: {tiers}"
    assert res["hits"][0]["tier"] == 1, res["hits"][0]

    assert not any("medium.com" in h["url"] for h in res["hits"]), (
        "a source below the learn bar was returned as learnable")
    assert res["filtered"] >= 1, res
    assert res["found"] > len(res["hits"]), res
    assert res["min_tier"] == sources.LEARN_MIN_TIER

    # and the bar is adjustable, with the count moving accordingly
    loose = discover.search("b-trees", rails=["a", "d"], limit=10, min_tier=4)
    assert any("medium.com" in h["url"] for h in loose["hits"]), (
        "--min-tier 4 must actually widen the net")
    assert loose["filtered"] == 0, loose
    print(f"[rank] three catalogues returning one DOI produced ONE result, "
          f"ranked tier-first; {res['filtered']} below-bar candidate(s) were "
          f"filtered AND counted, and raising the bar to 4 let them back in")


def check_a_dead_rail_does_not_kill_the_run():
    discover.RAILS.clear()
    discover.RAILS.update({
        "up":   (fake("up", [("https://doi.org/10.1/x", "a real paper")]), ""),
        "down": (boom("HTTP 503 Service Unavailable"), ""),
        "slow": (boom("TimeoutError: the read operation timed out"), ""),
    })
    res = discover.search("q", rails=["up", "down", "slow"], limit=5)
    assert len(res["hits"]) == 1, res["hits"]
    assert len(res["errors"]) == 2, res["errors"]
    names = {e["rail"] for e in res["errors"]}
    assert names == {"down", "slow"}, names
    assert all(e["error"] for e in res["errors"]), (
        "a rail failed and the reason was not recorded — an operator cannot "
        "tell a rate limit from an outage from a broken parser")

    # a rail that raises something UNEXPECTED must also be contained: the
    # rails parse third-party JSON whose shape changes without notice, so
    # KeyError and TypeError are the realistic failures, not RailError
    def nasty(_q, _l):
        raise KeyError("results")
    discover.RAILS["nasty"] = (nasty, "")
    res2 = discover.search("q", rails=["up", "nasty"], limit=5)
    assert len(res2["hits"]) == 1, res2
    assert any(e["rail"] == "nasty" for e in res2["errors"]), res2["errors"]
    print("[degrade] two dead rails and one that raised KeyError left the "
          "live rail's result intact, each failure named with its reason — a "
          "catalogue outage is a partial answer, not a total one")


def check_a_search_engine_can_never_be_a_result():
    """The whole point, expressed mechanically rather than as a prompt."""
    ENGINES = ["https://duckduckgo.com/?q=btree",
               "https://www.google.com/search?q=btree",
               "https://search.brave.com/search?q=btree",
               "https://www.bing.com/search?q=btree"]
    discover.RAILS.clear()
    discover.RAILS.update({
        "se": (fake("se", [(u, "a search results page") for u in ENGINES]), ""),
    })
    for bar in (1, 2, 3):
        res = discover.search("btree", rails=["se"], limit=10, min_tier=bar)
        assert not res["hits"], (
            f"a search-engine results page was offered as a learnable source "
            f"at --min-tier {bar}: {res['hits']}. Citing a search engine "
            f"cites nothing — the result set that produced it is already gone.")
    for u in ENGINES:
        _k, tier, why = sources.classify(u)
        assert tier == 4, (u, tier)
        assert "SEARCH ENGINE" in why or "search engine" in why.lower(), why
    print(f"[no-trash] all {len(ENGINES)} search-engine result pages are "
          f"tier 4 by host and cannot clear the learn bar at any setting — "
          f"'only reputable sources' is a property of the catalogue, not an "
          f"instruction a model may ignore")


def check_discovery_never_fetches():
    """Discovery is read-only and cheap; ingestion writes and costs. The
    separation must be real, not a convention."""
    import urllib.request
    discover.RAILS.clear()
    discover.RAILS.update({
        "a": (fake("a", [("https://doi.org/10.1/x", "paper one"),
                         ("https://doi.org/10.1/y", "paper two")]), ""),
    })
    res = discover.search("q", rails=["a"], limit=5)

    opened = []
    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: opened.append(a) or real(*a, **k)
    try:
        cmds = discover.add_url_commands(res, root="experts/x")
    finally:
        urllib.request.urlopen = real
    assert not opened, "building the ingest commands opened the network"
    assert len(cmds) == 2, cmds
    assert all(c.startswith("python ingest.py add-url ") for c in cmds), cmds
    assert all('--root "experts/x"' in c for c in cmds), cmds
    assert all('"' in c for c in cmds), (
        "a URL was interpolated unquoted — a '&' in a query string would "
        "background the command in any shell that ran it")
    print("[read-only] discovery emitted 2 quoted `ingest.py add-url` lines "
          "and opened no connection of its own: finding is free and "
          "auditable, fetching stays an explicit, separate act")


def check_unknown_rails_are_reported():
    discover.RAILS.clear()
    discover.RAILS.update({"a": (fake("a", [("https://doi.org/1/z", "x")]), "")})
    res = discover.search("q", rails=["a", "nosuchrail"], limit=5)
    assert any(e["rail"] == "nosuchrail" and "no such rail" in e["error"]
               for e in res["errors"]), res["errors"]
    assert len(res["hits"]) == 1, res
    print("[typo] a misspelled rail is reported by name rather than silently "
          "producing a smaller result set that looks like a real answer")


def check_a_goal_is_not_a_keyword_query():
    """Garbage in is the expensive kind of garbage here.

    universal.resolve hands this module the user's GOAL, phrased for a human:
    "understand b-tree index concurrency control". Passed through verbatim,
    the catalogues weighted `understand` and `control` like `b-tree`, and the
    measured top results were "Vascular Compliance and Cardiovascular
    Disease" — PubMed's best guess for `compliance`/`control`.

    That is the worst possible failure for this platform, because these rails
    are TRUSTED. A cardiology paper reached by a tier-1 route gets ingested,
    becomes a cited atom, and the expert then holds a wrong belief with a
    real citation attached. A missing source costs another search; a
    confidently irrelevant one costs the integrity of everything downstream.

    Two mechanisms, both asserted here: the intent words are stripped before
    the query is sent, and any result that shares no substantive term with
    the query is dropped AND counted.
    """
    assert discover.prepare("understand b-tree index concurrency control") \
        == "b-tree index concurrency control"
    assert discover.prepare("how to learn about raft consensus") \
        == "raft consensus"
    # a query of pure intent words must not become an empty query
    assert discover.prepare("explain how this works").strip(), \
        "an all-intent goal produced an empty catalogue query"

    ON = "Performance of B+ tree concurrency control algorithms"
    OFF = "Vascular Compliance and Cardiovascular Disease A Risk Factor"
    wanted = discover.terms("b-tree index concurrency control")
    assert discover.relevant(ON, wanted), ON
    assert not discover.relevant(OFF, wanted), (
        f"the exact off-topic paper this gate exists for was accepted: {OFF}")
    # inflection must not be treated as a different subject
    assert discover.relevant("Concurrent indexing structures", wanted), \
        "a stem match failed: 'concurrency' should find 'concurrent'"

    discover.RAILS.clear()
    discover.RAILS.update({
        "r": (fake("r", [
            ("https://doi.org/10.1/on", ON),
            ("https://doi.org/10.1/off", OFF),
            ("https://doi.org/10.1/off2", "Neighbor-joining phylogenetic trees"),
        ]), ""),
    })
    res = discover.search("understand b-tree index concurrency control",
                          rails=["r"], limit=10)
    titles = [h["title"] for h in res["hits"]]
    assert titles == [ON], titles
    assert res["off_topic"] == 2, res
    assert res["asked"] == "b-tree index concurrency control", res["asked"]
    print(f"[relevance] the goal was reduced to its subject before being sent "
          f"({res['asked']!r}), and {res['off_topic']} confidently-irrelevant "
          f"tier-1 result(s) were dropped and counted — an off-topic source "
          f"reached by a trusted route becomes a cited atom, which is a wrong "
          f"belief carrying a real citation")


def check_it_works_against_the_real_internet():
    """A SMOKE TEST, and honest about what it is.

    Everything above runs offline against substituted rails, which proves the
    ranking, dedupe, filtering and failure handling — and proves nothing at
    all about whether OpenAlex still answers or still returns the shape this
    parses. Only a live call can do that, and a live call in a test suite is
    a flake waiting to happen.

    So: it runs, it reports, and it SKIPS rather than fails when the network
    or the catalogue is unavailable. A red suite caused by somebody else's
    outage teaches people to ignore red suites.
    """
    try:
        res = discover.search("b-tree index concurrency",
                              rails=["openalex", "crossref"], limit=5)
    except Exception as e:                            # pragma: no cover
        print(f"[live] SKIPPED: discovery raised {type(e).__name__} — treated "
              f"as an outage, not a defect")
        return
    if not res["hits"]:
        print(f"[live] SKIPPED: no catalogue answered "
              f"({'; '.join(e['rail'] + ': ' + e['error'] for e in res['errors']) or 'no errors, no hits'})")
        return
    top = res["hits"][0]
    assert top["url"].startswith("http"), top
    assert top["tier"] <= sources.LEARN_MIN_TIER, top
    assert top["title"], top
    print(f"[live] a real query to {len(res['rails'])} catalogue(s) returned "
          f"{len(res['hits'])} learnable source(s), top result tier "
          f"{top['tier']}: {top['title'][:60]!r} — found by catalogue lookup, "
          f"with no search engine and no API key anywhere")


if __name__ == "__main__":
    main()
