#!/usr/bin/env python3
"""SOURCE AUTHORITY — discovery authority is not evidence quality.

The external audit's biggest finding, verified against the primary sources
before this test was written: sources.py conflated two different kinds of
authority. It rated doi.org, crossref.org and arxiv.org as TIER 1 with the
stated reason "admits only reviewed work, or is the citation identifier
itself" — and that is FALSE for those hosts:

  * Crossref's own membership page says eligibility is open to producers of
    "professional and scholarly materials" with deliberately low barriers;
    it does not assess content quality. A DOI is an identifier, not a mark
    of review. (crossref.org/membership, checked 2026-08-27)
  * arXiv is a preprint server — sources.py's OWN comment said it is not
    peer reviewed, and then the table gave it tier 1 anyway. An internal
    contradiction, in the module whose whole job is honesty about origins.
  * DOAJ is different: its application guide requires journals to operate a
    quality-control process (normally at least two independent reviewers),
    so a DOAJ-indexed article really does sit behind review.

Why this matters more than a label: tier feeds LEARN_MIN_TIER, which
decides what may become a CITED ATOM — durable knowledge the expert will
cite forever. A junk-journal article reached through its DOI would have
entered the knowledge base wearing "tier 1 (normative)". False authority in
the learning pipeline is the one contamination that compounds.

The fix this file pins is the audit's, and it is NOT "demote everything":

    DISCOVERY / PROVENANCE AUTHORITY   ≠   EVIDENCE QUALITY

  1. hosts that only admit reviewed work (DOAJ, PubMed/NLM-selected
     journals, Europe PMC) stay tier 1 — with why-texts that claim
     exactly that and nothing more;
  2. provenance infrastructure (DOI resolvers, Crossref, DataCite) and
     preprint servers (arXiv) become tier 2: REAL scholarly provenance,
     STILL LEARNABLE (tier <= LEARN_MIN_TIER), but never "normative" —
     and their why-text says a DOI is not a review mark;
  3. no why-text anywhere claims review where none exists;
  4. the discovery rails keep working: every scholarly rail's results
     remain at or under the learn bar, so nothing found through them
     stops being ingestible — only the false halo is gone;
  5. the subdomain-spoof defence is unchanged.

Run from the agent/ directory:  python tests/test_sources.py
"""

import sys

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import sources                 # noqa: E402


def main():
    check_reviewed_hosts_stay_tier1_with_honest_reasons()
    check_provenance_is_not_evidence()
    check_no_false_review_claims_anywhere()
    check_discovery_still_feeds_learning()
    check_spoofing_still_refused()
    print("PASS test_sources")


def check_reviewed_hosts_stay_tier1_with_honest_reasons():
    REVIEWED = [
        "https://doaj.org/article/abc123",
        "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "https://europepmc.org/article/MED/12345678",
    ]
    for u in REVIEWED:
        kind, tier, why = sources.classify(u)
        assert tier == 1, (
            f"{u} rated tier {tier} — this host genuinely sits behind "
            f"editorial selection or review, and demoting it would throw "
            f"away the one class of source that earns tier 1: {why}")
    _k, _t, doaj_why = sources.classify("https://doaj.org/article/x")
    assert "review" in doaj_why.lower(), doaj_why
    print("[reviewed] DOAJ, PubMed and Europe PMC keep tier 1, with reasons "
          "that name the review/selection process actually behind them")


def check_provenance_is_not_evidence():
    """The heart of the fix: a DOI is an identifier, not an endorsement."""
    PROVENANCE = [
        "https://doi.org/10.1234/junk-journal-2026-001",
        "https://dx.doi.org/10.1234/anything",
        "https://api.crossref.org/works/10.1/x",
        "https://www.crossref.org/members/x",
        "https://arxiv.org/abs/2608.99999",
        "https://export.arxiv.org/abs/2608.99999",
        "https://api.datacite.org/dois/10.5/x",
    ]
    for u in PROVENANCE:
        kind, tier, why = sources.classify(u)
        assert tier == 2, (
            f"{u} rated tier {tier}. Crossref's own membership page says it "
            f"does not assess content quality and keeps barriers "
            f"deliberately low; arXiv is a preprint server. Tier 1 here is "
            f"FALSE AUTHORITY — anything with a DOI, junk journals "
            f"included, would enter the knowledge base as 'normative'. "
            f"Tier 2 keeps it learnable without the halo: {why}")
    # and the why-text must carry the distinction, because the tier is read
    # by humans deciding whether to trust an atom's citation
    _k, _t, why = sources.classify("https://doi.org/10.1234/x")
    assert "not" in why.lower() and (
        "review" in why.lower() or "quality" in why.lower()), (
        f"the reason must SAY that provenance is not review/quality: {why}")
    print("[provenance] DOI resolvers, Crossref, DataCite and arXiv rate "
          "tier 2 — real scholarly provenance, still learnable, and the "
          "reason states outright that an identifier is not a review mark")


def check_no_false_review_claims_anywhere():
    """No classification may claim review where none exists — swept across
    every host the scholarly tables know, not just the ones above."""
    UNREVIEWED = ("doi.org", "dx.doi.org", "crossref.org",
                  "api.crossref.org", "datacite.org", "api.datacite.org",
                  "arxiv.org", "export.arxiv.org", "zenodo.org", "osf.io",
                  "biorxiv.org", "medrxiv.org")
    for host in UNREVIEWED:
        _k, _t, why = sources.classify(f"https://{host}/thing/123")
        low = why.lower()
        assert "admits only reviewed" not in low, (
            f"{host}: the why-text still claims it 'admits only reviewed' "
            f"work — the exact false statement the audit caught, surviving "
            f"in the explanation a human reads: {why}")
        assert "peer-reviewed only" not in low, (host, why)
    print(f"[honest] none of the {len(UNREVIEWED)} unreviewed scholarly "
          f"hosts carries a why-text claiming review — the words a human "
          f"reads now match what the host actually promises")


def check_discovery_still_feeds_learning():
    """The audit's warning: don't let this fix break the discovery and
    learning machinery. Every scholarly rail discover.py queries must keep
    producing results at or under the learn bar."""
    import discover
    RAIL_HOSTS = {
        "openalex": "https://api.openalex.org/works/W1",
        "crossref": "https://doi.org/10.1145/356770.356776",
        "pubmed": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        "doaj": "https://doaj.org/article/abc",
        "zenodo": "https://zenodo.org/records/123",
        "swh": "https://archive.softwareheritage.org/api/1/origin/x",
        "github": "https://github.com/postgres/postgres",
        "arxiv": "https://arxiv.org/abs/2301.00001",
    }
    for rail, url in RAIL_HOSTS.items():
        _k, tier, why = sources.classify(url)
        assert tier <= sources.LEARN_MIN_TIER, (
            f"rail '{rail}' now produces tier-{tier} results, above the "
            f"learn bar ({sources.LEARN_MIN_TIER}) — the evidence fix "
            f"must remove the false halo WITHOUT making the catalogue "
            f"rails unable to feed learning: {why}")
    assert set(RAIL_HOSTS) <= set(discover.RAILS), (
        "this test's rail list has drifted from discover.RAILS")
    print(f"[fed] all {len(RAIL_HOSTS)} scholarly discovery rails still "
          f"produce results at or under the learn bar — the halo is gone, "
          f"the pipeline is not")


def check_spoofing_still_refused():
    for u in ("https://evildoaj.org.attacker.com/x",
              "https://doi.org.phish.example/x",
              "https://notpubmed.ncbi.nlm.nih.gov.evil.io/x"):
        _k, tier, _w = sources.classify(u)
        assert tier >= 3, (u, tier)
    print("[spoof] lookalike subdomains still buy nothing")


if __name__ == "__main__":
    main()
