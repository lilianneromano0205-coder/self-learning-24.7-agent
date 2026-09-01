"""Deterministic claim/evidence planning; no model verdict or truth oracle.

Support is deliberately narrow: a literal declarative proposition occurs as
a complete sentence in locally read course bytes with a source citation,
acceptable source tier and temporal validity. It is source-relative support,
not verified real-world truth. Open questions and semantic entailment remain
unresolved. The immutable execution/evaluation authorities are not touched.
"""
import hashlib
import json
from pathlib import Path
import re

import sources

MAX_CLAIMS = 24
MAX_FILE_BYTES = 2_000_000
ATOM = re.compile(r"\b([CPU]-\d{2,}[\w.]*)\b")


def make_plan(question, supplied, basic):
    raw = supplied if supplied is not None else basic
    if not isinstance(raw, list) or len(raw) > MAX_CLAIMS:
        raise ValueError("research plan must be a bounded list")
    claims, ids = [], set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("research claim must be an object")
        cid = str(item.get("id", f"c{i+1}"))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid) or cid in ids:
            raise ValueError("invalid or duplicate claim id")
        ids.add(cid)
        ask = str(item.get("ask", "")).strip()
        proposition = str(item.get("proposition", "")).strip()
        if not ask or len(ask) > 2000 or len(proposition) > 2000:
            raise ValueError("claim needs a bounded factual subquestion")
        depends = item.get("depends_on", [])
        counters = item.get("counterclaims", [])
        hypotheses = item.get("hypotheses", [])
        if (not isinstance(depends, list) or not all(isinstance(d, str) for d in depends)
                or not isinstance(counters, list) or not isinstance(hypotheses, list)
                or len(counters) + len(hypotheses) > 12):
            raise ValueError("invalid dependencies or competing hypotheses")
        alternatives = []
        for text in counters + hypotheses:
            if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                raise ValueError("hypothesis must be a bounded literal proposition")
            if text not in alternatives:
                alternatives.append(text)
        max_age = item.get("max_age_days")
        sources.freshness(as_of="2026-01-01", max_age_days=max_age)
        claims.append({"id": cid, "ask": ask, "proposition": proposition,
                       "terms": item.get("terms", []), "depends_on": list(dict.fromkeys(depends)),
                       "counterclaims": alternatives, "max_age_days": max_age})
    by_id = {c["id"]: c for c in claims}
    visiting, ordered = set(), []

    def visit(cid):
        if cid not in by_id:
            raise ValueError("unknown research dependency")
        if cid in visiting:
            raise ValueError("research dependency cycle")
        if cid in ordered:
            return
        visiting.add(cid)
        for dep in by_id[cid]["depends_on"]:
            visit(dep)
        visiting.remove(cid)
        ordered.append(cid)

    for c in claims:
        visit(c["id"])
    return claims, ordered


def _normal(text):
    return " ".join(text.casefold().split()).strip(" .!\t\r\n")


def _sentences(text):
    # Strip only explicit atom/citation annotations. Do not strip arbitrary
    # prefixes such as "it is false that" or turn negation into affirmation.
    text = re.sub(r"\[src:\s*[^\]]+\]", "", text, flags=re.I)
    text = re.sub(r"^\s*[-*]?\s*[CPU]-\d{2,}[\w.]*\s+", "", text)
    return {_normal(s) for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()}


def read_evidence(root, hit, as_of, max_age, cfg):
    """Resolve retrieval against bytes; retrieval's tier/verdict/text is not authority."""
    if isinstance(hit, dict):
        where, suggested = hit.get("where", ""), hit.get("text", "")
    elif isinstance(hit, (list, tuple)) and len(hit) >= 3:
        where, suggested = hit[1], hit[2]
    else:
        return None
    row = {"where": str(where), "text": str(suggested)[:2000], "atoms": [],
           "valid": False, "issues": [], "relation": "retrieved"}
    try:
        rel, number = str(where).rsplit(":", 1)
        path = Path(root, rel).resolve()
        corpus = Path(root, "courses").resolve()
        if (not rel.replace("\\", "/").startswith("courses/") or
                not path.is_relative_to(corpus) or not path.is_relative_to(Path(root).resolve())
                or path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES):
            raise ValueError("outside bounded course corpus")
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            raise ValueError("source exceeds evidence bound")
        text = data.decode("utf-8")
        lines = text.splitlines()
        number = int(number)
        if not 1 <= number <= len(lines):
            raise ValueError("invalid source line")
        actual = lines[number - 1].strip()
        if not str(suggested).strip() or str(suggested).strip() not in actual:
            raise ValueError("retrieval quote differs from source bytes")
        inline = re.search(r"\[src:\s*(https?://[^\s\]]+)\]", actual, re.I)
        header = re.search(r"^SOURCE-URL:\s*(https?://\S+)", text, re.M)
        source = (inline or header).group(1) if (inline or header) else ""
        dated = re.search(r"^SOURCE-DATE:[ \t]*(\S*)", text, re.M)
        date = dated.group(1) if dated else ""
        kind, tier, why = sources.classify(source, cfg=cfg)
        temporal = sources.freshness(date, as_of, max_age)
        from urllib.parse import urlsplit
        parsed = urlsplit(source)
        if not source or parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username:
            row["issues"].append("missing or invalid primary source citation")
        if tier > sources.learn_bar(cfg)[0]:
            row["issues"].append("source below required quality tier")
        if temporal["state"] not in ("fresh", "not_required"):
            row["issues"].append("temporal validity: " + temporal["state"])
        digest = hashlib.sha256(data).hexdigest()
        identity = hashlib.sha256(f"{source}|{rel}|{number}|{digest}".encode()).hexdigest()[:16]
        row.update(text=actual, atoms=ATOM.findall(actual), source=source,
                   citation_id="E-" + identity, source_sha256=digest,
                   quality={"kind": kind, "tier": tier, "why": why}, freshness=temporal,
                   content_fence=sources.fence_content(str(where), actual),
                   valid=not row["issues"])
    except (OSError, ValueError, UnicodeError) as exc:
        row["issues"].append(str(exc))
    return row


def collect(root, question, plan, as_of, per_sub, cfg, search):
    from research import facts_needed, terms
    claims, order = make_plan(question, plan, facts_needed(question))
    subs, all_atoms = [], set()
    cap = max(1, min(int(per_sub), 30))
    for claim in claims:
        queries = [claim["ask"], claim["proposition"]] + claim["counterclaims"]
        hits, seen, errors = [], set(), []
        for query in dict.fromkeys(q for q in queries if q):
            try:
                retrieved = search(root, " ".join(terms(query)), limit=cap)
            except Exception as exc:
                errors.append(type(exc).__name__)
                continue
            for raw in (retrieved or [])[:cap]:
                row = read_evidence(root, raw, as_of, claim["max_age_days"], cfg)
                if row is None or row["where"] in seen:
                    continue
                seen.add(row["where"])
                if row["valid"]:
                    sentences = _sentences(row["text"])
                    if claim["proposition"] and _normal(claim["proposition"]) in sentences:
                        row["relation"] = "supports"
                    if any(_normal(c) in sentences for c in claim["counterclaims"]):
                        row["relation"] = "contradicts"
                hits.append(row)
                all_atoms.update(row["atoms"])
        support = [h["citation_id"] for h in hits if h["relation"] == "supports"]
        counter = [h["citation_id"] for h in hits if h["relation"] == "contradicts"]
        hypotheses = [{"proposition": h, "state": "supported" if any(
            e["valid"] and _normal(h) in _sentences(e["text"]) for e in hits) else "unresolved"}
                      for h in claim["counterclaims"]]
        gaps = []
        if not claim["proposition"]:
            gaps.append("factual proposition not specified; retrieved text is not an answer")
        if not hits:
            gaps.append("no source evidence retrieved")
        if not support:
            gaps.append("no literal source support meeting quality and temporal requirements")
        if counter:
            gaps.append("counterevidence requires reconciliation")
        if errors:
            gaps.append("retrieval incomplete: " + ", ".join(errors))
        gaps += list(dict.fromkeys(issue for row in hits for issue in row["issues"]))
        state = "contradicted" if counter else "supported" if support and not errors else "unresolved"
        subs.append(dict(claim, hits=hits, atoms=sorted({a for h in hits for a in h["atoms"]}),
                         support=support, counterevidence=counter, hypotheses=hypotheses,
                         missing_evidence=gaps, state=state, retrieved=bool(hits),
                         established=state == "supported", blocked_by=[]))
    by_id = {s["id"]: s for s in subs}
    for cid in order:
        sub = by_id[cid]
        blocked = [d for d in sub["depends_on"] if by_id[d]["state"] != "supported"]
        if blocked:
            sub["blocked_by"] = blocked
            sub["missing_evidence"].append("unresolved dependencies: " + ", ".join(blocked))
            if sub["state"] == "supported":
                sub["state"] = "unresolved"
            sub["established"] = False
    counts = {"retrieved": sum(s["retrieved"] for s in subs),
              "supported": sum(s["state"] == "supported" for s in subs),
              "contradicted": sum(s["state"] == "contradicted" for s in subs),
              "unresolved": sum(s["state"] != "supported" for s in subs)}
    report = {"question": question, "mode": "deep" if plan is not None else "decomposition",
              "subs": subs, "atoms": sorted(all_atoms), "coverage_states": counts,
              "coverage": round(counts["supported"] / len(subs), 2) if subs else 0.0,
              "unestablished": [s["ask"] for s in subs if not s["established"]],
              "limitation": "Literal source-relative support only; no semantic entailment or real-world truth proof."}
    report["gap_assessment"] = assess_gaps(report)
    return report


def _digest(report):
    return hashlib.sha256(json.dumps({k: report[k] for k in ("question", "subs")},
                                     sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def assess_gaps(report):
    unresolved = [s["id"] for s in report["subs"] if not s["established"]]
    return {"performed": True, "unresolved_claims": unresolved,
            "answer_ready": bool(report["subs"]) and not unresolved,
            "evidence_digest": _digest(report),
            "scope": "Assessment covers retrieved evidence only; search completeness is unproven."}


def answer(report):
    assessment = report.get("gap_assessment", {})
    if not assessment.get("performed") or assessment.get("evidence_digest") != _digest(report):
        raise ValueError("missing or stale gap assessment")
    if not assessment.get("answer_ready") or any(not s["established"] for s in report["subs"]):
        raise ValueError("unresolved evidence gaps prohibit a complete answer")
    lines = ["Source-supported statements (literal evidence; not independent truth verification):"]
    for sub in report["subs"]:
        citations = [f"[{h['citation_id']}]({h['source']})" for h in sub["hits"]
                     if h["relation"] == "supports"]
        lines.append(sub["proposition"] + " " + " ".join(citations))
    return "\n".join(lines)
