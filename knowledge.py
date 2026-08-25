#!/usr/bin/env python3
"""THE KNOWLEDGE GRAPH — what the fleet knows, and how the pieces connect.

The platform stores what it learns as ATOMS: one claim per line, with an id
and a source.

    - C-0104 a cache revalidates with If-None-Match [src: https://.../rfc9111]

That is a good unit of knowledge and a poor structure for it. A flat list
answers "do we have a note about X" and cannot answer the questions that
make a body of knowledge worth having:

    what does this fleet actually know ABOUT a thing?
    which things keep appearing together — what are the real topics, as
        opposed to the folder names somebody chose?
    which claims rest on nothing but a blog?
    which sources carry the most of what we believe, so that one retraction
        would take a whole area with it?

So this builds a graph over the atoms the fleet has already earned. It adds
no new knowledge and asks no model anything: every node and edge is derived
mechanically from files already on disk, and every claim keeps its citation.

    ATOM      one claim, with its id, its course, its source and its tier
    ENTITY    a term the atoms actually use, extracted by rule
    SOURCE    where a claim came from, rated by sources.classify

    atom -> source     provenance, tier-weighted
    atom -> entity     this claim is about that thing
    entity -> entity   these two are discussed together (co-occurrence)

WHY EXTRACTION IS A RULE AND NOT A MODEL

Asking a model to name the entities in a corpus produces a plausible list
nobody can check, and this platform does not accept plausible. The rules are
boring on purpose and printed with every result: multi-word Capitalised
phrases, ALL-CAPS acronyms, `code identifiers`, and hyphenated technical
terms. A rule under-extracts in a way you can SEE and fix; a model
over-extracts in a way that reads beautifully and cannot be audited.

WHAT THE CLUSTERS ARE, AND ARE NOT

`clusters()` groups entities by co-occurrence — a connected-components pass
over "these two appear in the same atom". That finds the topics the material
actually has, which is frequently not the courses somebody filed it under.
It is not semantic similarity and does not pretend to be: two words that mean
the same thing but never co-occur will land in different clusters, and the
output says so rather than implying an understanding it does not have.

    python knowledge.py --root <expert>                  # the shape of it
    python knowledge.py --root <expert> --about caching  # what we know
    python knowledge.py --root <expert> --clusters
    python knowledge.py --root <expert> --weak           # thin evidence
    python knowledge.py --root <expert> --load-bearing   # source risk
"""

import argparse
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):        # pragma: no cover
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ATOM_RE = re.compile(r"^\s*-\s*([CPU]-\d{2,}[\w.]*)\s+(.*)$", re.M)
SRC_RE = re.compile(r"\[src:\s*([^\]]+)\]")

# Entity spellings this platform can extract by RULE. Each pattern is one
# way real technical prose names a thing, and each is auditable by eye.
ENTITY_PATTERNS = (
    (re.compile(r"`([A-Za-z_][\w.\-/]{2,40})`"), "code identifier"),
    (re.compile(r"\b([A-Z][A-Za-z0-9]*(?:[- ][A-Z][A-Za-z0-9]*)+)\b"),
     "capitalised phrase"),
    (re.compile(r"\b([A-Z]{2,8})\b"), "acronym"),
    # WAS: r"\b([a-z]+(?:-[a-z]+){1,3})\b" - lowercase only, so "B-tree",
    # "Cache-Control" and "Q-learning" all fell through every pattern here
    # and the claims about them produced NO entity at all. Measured on the
    # repro corpus: "A B-tree keeps its leaves at the same depth" yielded {}.
    # A graph whose nodes are missing is not a sparse graph, it is no graph.
    (re.compile(r"\b([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+){1,3})\b"),
     "hyphenated term"),
    # A single capitalised word mid-sentence is a proper noun: Postgres,
    # Kubernetes, Redis. Sentence-initial words are excluded in code below,
    # because "The index is hot" must not contribute the entity `the`.
    (re.compile(r"\b([A-Z][a-z]{2,15})\b"), "proper noun"),
)

# Words that match a pattern and mean nothing on their own. Kept short: every
# entry is a thing the graph will never be able to talk about.
STOP = {
    "THE", "AND", "FOR", "NOT", "BUT", "ALL", "ANY", "ONE", "TWO", "USE",
    "CAN", "MAY", "MUST", "SHOULD", "WHEN", "THEN", "THIS", "THAT", "WITH",
    "FROM", "INTO", "ONLY", "SUCH", "SEE", "NOTE", "SRC", "HTTP", "HTTPS",
    "well-known", "so-called", "up-to-date", "state-of-the-art",
    # Auxiliaries, determiners and bare verbs. These are capitalised at the
    # front of a claim and are never what a claim is ABOUT, so they are
    # removed by identity rather than by position — a rule that also catches
    # them mid-sentence, which a position rule cannot.
    "IT", "ITS", "THEY", "THEM", "THESE", "THOSE", "EACH", "EVERY", "SOME",
    "MOST", "BOTH", "EITHER", "NEITHER", "IF", "AS", "AT", "BY", "ON", "IN",
    "OF", "TO", "OR", "IS", "ARE", "WAS", "WERE", "BE", "BEEN", "BEING",
    "HAS", "HAVE", "HAD", "DO", "DOES", "DID", "WILL", "WOULD", "COULD",
    "SET", "GET", "ADD", "RUN", "PUT", "MAKE", "TAKE", "GIVE", "KEEP",
    "CALL", "READ", "WRITE", "AVOID", "NEVER", "ALWAYS", "AFTER", "BEFORE",
    "DURING", "WHILE", "SINCE", "UNTIL", "UNLESS", "BECAUSE", "HOWEVER",
    "THEREFORE", "OTHERWISE", "PREFER", "ENSURE", "CHECK", "CONTROL",
}
MIN_ENTITY_ATOMS = 2        # a term used once is a word, not a topic
_LEADING_ARTICLE = re.compile(r"^(?:an?|the)\s+", re.I)


def _courses(root):
    d = os.path.join(root, "courses")
    try:
        return sorted(n for n in os.listdir(d)
                      if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []


def _notes_files(root):
    """Delegate to citecheck, the module that defines what an atom IS."""
    try:
        import citecheck
        return citecheck.notes_files(root)
    except Exception:                    # pragma: no cover
        return []


def atoms(root):
    """Every cited atom this expert has earned. -> [dict].

    Reads the same notes.md files citecheck.py validates against — literally
    the same function, citecheck.notes_files, rather than a second
    hand-written walker that agreed with it only by luck. It did not: this
    joined `courses/<course>/notes.md` flat while the platform writes
    `courses/<course>/lessons/NN/notes.md`, so the graph was EMPTY against
    every real expert and said so to nobody. Proven by running both against
    one tree: citecheck saw C-01 and C-02, this saw nothing.

    So an atom the graph knows about is an atom a citation can legally
    reference, and that is now true by construction instead of by assertion.
    """
    out = []
    for course, p in _notes_files(root):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for aid, body in ATOM_RE.findall(text):
            src = SRC_RE.search(body)
            ref = (src.group(1).strip() if src else "")
            claim = SRC_RE.sub("", body).strip()
            out.append({"id": aid, "course": course, "claim": claim,
                        "source": ref})
    return out


def _tier_of(ref):
    if not ref:
        return 4, "no source cited"
    try:
        import sources
        _kind, tier, why = sources.classify(ref)
        return tier, why
    except Exception:                    # pragma: no cover
        return 4, "unrated"


def entities_in(text):
    """Terms this claim is about, by rule. -> {term: how_it_was_found}."""
    found = {}
    # POSITION IS NOT EVIDENCE. The first attempt dropped every capitalised
    # word that opened a sentence, on the theory that it was capitalised for
    # grammar. Measured, it deleted `postgres` from "Postgres uses a B-tree"
    # and `kubernetes` from "Kubernetes schedules pods" — atoms are one-line
    # claims, so the SUBJECT is usually first, and the subject is usually
    # exactly the entity the claim is about. STOP already removes the
    # articles and auxiliaries that motivated the rule, and it removes them
    # wherever they appear rather than only at the front.
    for pat, how in ENTITY_PATTERNS:
        for m in pat.findall(text):
            term = m.strip()
            # A sentence-initial article is capitalised, so "An HTTP cache"
            # extracted as the entity `an http` and "A B-Tree index" as
            # `a b-tree`. Those are junk terms: they can never match a query,
            # never co-occur with the same thing spelled without the article,
            # and they quietly split one topic into two. Measured on the
            # first corpus this ran against, two of four claims produced one.
            term = _LEADING_ARTICLE.sub("", term).strip()
            if len(term) < 3 or term in STOP or term.upper() in STOP:
                continue
            found.setdefault(term.lower(), how)
    # "Cache-Control" is one entity, not three. The proper-noun rule also
    # matches `Cache` and `Control` inside it, and those halves are not
    # topics — nothing else in the corpus is about `control`. Drop any term
    # that is merely a component of a compound already found.
    compounds = [t for t in found if "-" in t]
    for t in list(found):
        if "-" in t:
            continue
        if any(t in c.split("-") for c in compounds):
            del found[t]
    return found


def build(root):
    """The whole graph, from files on disk. Nothing is asked of a model."""
    rows = atoms(root)
    by_entity, edges, by_source = {}, {}, {}
    for a in rows:
        a["tier"], a["why"] = _tier_of(a["source"])
        ents = entities_in(a["claim"])
        a["entities"] = sorted(ents)
        for e in ents:
            by_entity.setdefault(e, {"atoms": [], "how": ents[e],
                                     "courses": set(), "best_tier": 4})
            by_entity[e]["atoms"].append(a["id"])
            by_entity[e]["courses"].add(a["course"])
            by_entity[e]["best_tier"] = min(by_entity[e]["best_tier"], a["tier"])
        for i, x in enumerate(a["entities"]):
            for y in a["entities"][i + 1:]:
                edges[(x, y)] = edges.get((x, y), 0) + 1
        if a["source"]:
            by_source.setdefault(a["source"], []).append(a["id"])
    # a term used once is a word, not a topic
    thin = [e for e, v in by_entity.items() if len(v["atoms"]) < MIN_ENTITY_ATOMS]
    for e in thin:
        del by_entity[e]
    edges = {k: v for k, v in edges.items()
             if k[0] in by_entity and k[1] in by_entity}
    for v in by_entity.values():
        v["courses"] = sorted(v["courses"])
    return {"atoms": rows, "entities": by_entity, "edges": edges,
            "sources": by_source}


def about(root, term, graph=None):
    """What this fleet knows about a thing, with citations and tiers."""
    g = graph or build(root)
    t = term.lower().strip()
    hits = [a for a in g["atoms"]
            if t in a["claim"].lower() or t in [e.lower() for e in a["entities"]]]
    hits.sort(key=lambda a: a["tier"])
    node = g["entities"].get(t)
    related = sorted(
        ((b if a == t else a, n) for (a, b), n in g["edges"].items()
         if t in (a, b)), key=lambda kv: -kv[1])[:8]
    return {"term": term, "atoms": hits, "known": bool(hits),
            "best_tier": min([a["tier"] for a in hits], default=4),
            "courses": sorted({a["course"] for a in hits}),
            "related": related, "node": node}


def clusters(root, graph=None, min_shared=1):
    """Topics the material actually has, by co-occurrence.

    Connected components over "these two terms appear in the same claim".
    Not semantic similarity: two words meaning the same thing that never
    co-occur land apart, and that is a limit rather than a secret.
    """
    g = graph or build(root)
    adj = {}
    for (a, b), n in g["edges"].items():
        if n >= min_shared:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    seen, out = set(), []
    for node in sorted(adj):
        if node in seen:
            continue
        stack, comp = [node], []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(adj.get(cur, ()) - seen)
        if len(comp) > 1:
            weight = sum(len(g["entities"][c]["atoms"]) for c in comp)
            out.append({"terms": sorted(comp), "size": len(comp),
                        "atoms": weight})
    out.sort(key=lambda c: -c["atoms"])
    return out


def weak(root, graph=None, bar=None):
    """Claims resting only on sources below the learn bar."""
    g = graph or build(root)
    try:
        import sources
        bar = bar if bar is not None else sources.LEARN_MIN_TIER
    except Exception:                    # pragma: no cover
        bar = bar if bar is not None else 2
    return [a for a in g["atoms"] if a["tier"] > bar]


def load_bearing(root, graph=None, top=8):
    """Sources carrying the most of what the fleet believes.

    Concentration is a risk nobody usually measures: if one document
    underpins forty claims, one retraction takes an area of knowledge with
    it, and nothing in a flat notes file would ever say so.
    """
    g = graph or build(root)
    rows = [{"source": s, "atoms": len(ids), "tier": _tier_of(s)[0],
             "ids": ids[:6]} for s, ids in g["sources"].items()]
    rows.sort(key=lambda r: -r["atoms"])
    total = len(g["atoms"]) or 1
    for r in rows:
        r["share"] = round(100.0 * r["atoms"] / total, 1)
    return rows[:top]


def summary(root, graph=None):
    g = graph or build(root)
    tiers = {}
    for a in g["atoms"]:
        tiers[a["tier"]] = tiers.get(a["tier"], 0) + 1
    return {"atoms": len(g["atoms"]), "entities": len(g["entities"]),
            "edges": len(g["edges"]), "courses": len(_courses(root)),
            "by_tier": tiers, "weak": len(weak(root, g)),
            "clusters": len(clusters(root, g))}


def main():
    ap = argparse.ArgumentParser(
        description="the knowledge graph — what the fleet knows, and how it "
                    "connects")
    ap.add_argument("--root", default=".")
    ap.add_argument("--about", default="")
    ap.add_argument("--clusters", action="store_true")
    ap.add_argument("--weak", action="store_true")
    ap.add_argument("--load-bearing", dest="lb", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    g = build(root)

    if a.about:
        r = about(root, a.about, g)
        if a.json:
            print(json.dumps(r, indent=1, ensure_ascii=False, default=list))
            return
        if not r["known"]:
            print(f"nothing studied mentions {a.about!r}. That is an honest "
                  f"'no', not an absence of opinion — the fleet has "
                  f"{len(g['atoms'])} atom(s) and none of them is about this.")
            return
        print(f"{a.about}: {len(r['atoms'])} atom(s), best tier "
              f"{r['best_tier']}, across {', '.join(r['courses'])}")
        for at in r["atoms"][:10]:
            print(f"  [{at['id']} tier {at['tier']}] {at['claim'][:96]}")
            print(f"      {at['source'][:88] or 'NO SOURCE'}")
        if r["related"]:
            print("  discussed together with: "
                  + ", ".join(f"{t} ({n})" for t, n in r["related"]))
        return
    if a.clusters:
        cs = clusters(root, g)
        if not cs:
            print("no topic has two terms that co-occur yet — a graph needs "
                  "material before it can find structure in it")
            return
        for c in cs[:12]:
            print(f"  {c['atoms']:>4} atom(s)  {', '.join(c['terms'][:9])}"
                  + (" ..." if c["size"] > 9 else ""))
        print(f"\n{len(cs)} topic(s) found by co-occurrence — these are what "
              f"the MATERIAL groups into, which is not always what the "
              f"courses were named")
        return
    if a.weak:
        rows = weak(root, g)
        if not rows:
            print("every claim rests on a source at or above the learn bar")
            return
        for at in rows[:20]:
            print(f"  [{at['id']} tier {at['tier']}] {at['claim'][:80]}")
            print(f"      {at['why'][:96]}")
        print(f"\n{len(rows)} claim(s) rest on sources below the bar. They are "
              f"not wrong; they are unsupported, which is a different problem "
              f"with a different fix: find the primary source or drop them.")
        return
    if a.lb:
        rows = load_bearing(root, g)
        if not rows:
            print("no sources recorded yet")
            return
        for r in rows:
            print(f"  {r['share']:>5.1f}%  {r['atoms']:>3} atom(s)  "
                  f"tier {r['tier']}  {r['source'][:70]}")
        top = rows[0]
        if top["share"] >= 30:
            print(f"\n  CONCENTRATION: {top['share']}% of everything believed "
                  f"here rests on one document. If it is retracted or was "
                  f"misread, an entire area goes with it.")
        return

    s = summary(root, g)
    if a.json:
        print(json.dumps(s, indent=1))
        return
    print(f"{s['atoms']} atom(s) across {s['courses']} course(s)")
    print(f"{s['entities']} entity(ies), {s['edges']} co-occurrence edge(s), "
          f"{s['clusters']} topic(s)")
    print(f"by source tier: " + ", ".join(
        f"tier {t}: {n}" for t, n in sorted(s["by_tier"].items())))
    if s["weak"]:
        print(f"{s['weak']} claim(s) rest on sources below the learn bar "
              f"(`--weak` to see them)")
    print("\n  --about <term>   --clusters   --weak   --load-bearing")


if __name__ == "__main__":
    main()
