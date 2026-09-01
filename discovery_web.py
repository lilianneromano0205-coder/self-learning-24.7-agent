"""Opt-in general-web candidate lane, independent of source evidence quality.

Uses an owner-configured SearXNG JSON endpoint through discover's guarded
transport. It never fetches result pages or imports search snippets as facts.
Unknown publishers remain visible for review without gaining source authority.
"""
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlencode, urlsplit, urlunsplit

import sources


def candidate_url(url):
    """Cheap structural gate. DNS/redirect checks still run at actual fetch."""
    import ingest
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 for c in url):
        raise ValueError("invalid candidate URL")
    ingest._check_scheme(url)
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL host/credential authority refused")
    if parsed.hostname.lower() == "localhost" or parsed.hostname.lower().endswith((".localhost", ".local")):
        raise ValueError("local candidate URL refused")
    literal = ingest._host_as_ip(parsed.hostname)
    if literal is not None and ingest._blocked_ip(str(literal)):
        raise ValueError("private candidate address refused")
    return parsed


def purpose(url):
    parsed = urlsplit(url)
    host, path = parsed.hostname or "", parsed.path.lower()
    if host.endswith(".gov") or "/legal" in path or "/regulation" in path:
        return "legal_regulatory"
    if any(s in path for s in ("/news", "/announcement", "/press", "/release")):
        return "company_announcement"
    if any(s in path for s in ("/troubleshoot", "/support", "/knowledge-base")):
        return "operational_troubleshooting"
    if host.startswith(("docs.", "developer.", "learn.")) or "/docs" in path:
        return "software_documentation"
    return "general_web"


def search(query, limit, cfg, as_of, get_json):
    config = (cfg or {}).get("agent", {}).get("discovery", {}).get("general_web", {})
    if config.get("enabled") is not True:
        raise ValueError("general-web discovery requires owner enabled=true configuration")
    endpoint = config.get("endpoint", "")
    parsed = candidate_url(endpoint)
    if parsed.scheme != "https" or parsed.query or parsed.fragment:
        raise ValueError("general-web endpoint must be a credential-free HTTPS search URL")
    max_age = config.get("max_age_days", 90)
    sources.freshness(as_of=as_of, max_age_days=max_age)
    request_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/search",
                             urlencode({"q": query[:2000], "format": "json", "safesearch": 2}), ""))
    payload = get_json(request_url)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("general-web response is not SearXNG JSON results")
    response_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    observed_at = datetime.now(timezone.utc).isoformat()
    rows, rejected = [], []
    for position, item in enumerate(payload["results"][:max(1, min(limit, 25))]):
        if not isinstance(item, dict):
            rejected.append({"position": position, "reason": "malformed result"})
            continue
        url = item.get("url", "")
        try:
            destination = candidate_url(url)
            if sources._in(destination.hostname, sources.SEARCH_ENGINE) or destination.hostname == parsed.hostname:
                raise ValueError("search index is discovery infrastructure, not evidence")
        except ValueError as exc:
            rejected.append({"position": position, "reason": str(exc)})
            continue
        title = str(item.get("title", ""))[:1000]
        snippet = str(item.get("content", ""))[:3000]
        kind, tier, why = sources.classify(url, cfg=cfg)  # never result's kind/tier/score
        published_at = item.get("publishedDate", item.get("published_at", ""))
        temporal = sources.freshness(published_at, as_of, max_age)
        cid = "D-" + hashlib.sha256((url + "|" + response_hash).encode()).hexdigest()[:16]
        rows.append({"url": url, "title": title, "rail": "general_web", "lane": "general_web",
                     "kind": kind, "tier": tier, "why": why, "purpose": purpose(url),
                     "freshness": temporal, "citation_id": cid, "evidence_state": "retrieved",
                     "established": False, "requires_primary_fetch": True,
                     "url_validation": "structural_only; DNS and redirects checked on fetch",
                     "content_fence": sources.fence_content(cid, title + "\n" + snippet),
                     "provenance": {"provider": "searxng", "endpoint": endpoint,
                                    "observed_at": observed_at, "query_sha256": query_hash,
                                    "response_sha256": response_hash, "search_position": position + 1,
                                    "position_is_quality": False,
                                    "published_date_origin": "unverified search metadata"}})
    return rows, rejected
