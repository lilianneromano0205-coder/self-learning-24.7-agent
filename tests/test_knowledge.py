#!/usr/bin/env python3
"""THE KNOWLEDGE GRAPH — structure over what was actually learned.

The platform stores knowledge as atoms: one claim, one id, one source. That
is a good unit and a poor structure. A flat list answers "is there a note
about X" and cannot answer the questions that make a body of knowledge worth
keeping: what is known ABOUT a thing, which things are discussed together,
which claims rest on nothing but a blog, and which single source would take a
whole area with it if it were retracted.

What has to be true for a graph over it to be worth trusting:

  1. it adds NO knowledge — every node comes from an atom already on disk,
     and every claim keeps its citation and its tier
  2. extraction is a RULE, auditable by eye, not a model's plausible list
  3. a term used once is a word, not a topic
  4. `--weak` finds exactly the claims below the learn bar
  5. `--load-bearing` finds source concentration, which a flat notes file
     cannot show and which is a real risk nobody usually measures
  6. clusters come from co-occurrence in the MATERIAL, not from the folder
     names somebody chose

Run from the agent/ directory:  python tests/test_knowledge.py
"""

import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import fleet                   # noqa: E402
import knowledge               # noqa: E402
import sources                 # noqa: E402

RFC9111 = "https://www.rfc-editor.org/rfc/rfc9111"
RFC9110 = "https://www.rfc-editor.org/rfc/rfc9110"
PGDOCS = "https://www.postgresql.org/docs/current/indexes.html"
BLOG = "https://someseoblog.example/cdn-tips"
MEDIUM = "https://medium.com/@someone/vacuum"


def _notes(root, course, lines, lesson="01"):
    """Write notes where THE PLATFORM writes them.

    This used to write `courses/<course>/notes.md` — flat — which is exactly
    the path knowledge.py used to read, and exactly the path nothing in the
    platform ever produces. ingest.py:792 tells the watcher to write
    `courses/<c>/lessons/NN/notes.md` and harness.py:241 documents that as
    the tier. So the code and its test agreed with each other and with
    nothing else, and the knowledge graph was EMPTY against every real
    expert while this file went green.

    A test that builds its fixture the wrong way cannot fail on the bug it
    is shaped like. The fixture now uses the real layout, and
    check_the_graph_reads_what_the_platform_writes below pins the agreement
    directly rather than trusting either side.
    """
    p = os.path.join(root, "courses", course, "lessons", lesson, "notes.md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    home = make_sandbox("knowledge", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": []})
    root = fleet.create(home, "Scholar", "studies caching and storage")

    _notes(root, "http", [
        f"- C-0101 An HTTP cache revalidates with `If-None-Match` [src: {RFC9111}]",
        f"- C-0102 A shared cache must honour Cache-Control no-store [src: {RFC9111}]",
        f"- C-0103 The Cache-Control header carries no-store [src: {RFC9111}]",
        f"- C-0104 An ETag and `If-None-Match` together enable revalidation [src: {RFC9110}]",
        f"- C-0105 CDN edge nodes cache near the user [src: {BLOG}]",
    ])
    _notes(root, "db", [
        f"- C-0201 A B-Tree index speeds range queries [src: {PGDOCS}]",
        f"- C-0202 A B-Tree index is the default index type [src: {PGDOCS}]",
        f"- C-0203 VACUUM reclaims dead tuples [src: {MEDIUM}]",
    ])

    g = knowledge.build(root)

    # 1. it adds nothing — every atom is one that was written down
    assert len(g["atoms"]) == 8, [a["id"] for a in g["atoms"]]
    assert all(a["source"] for a in g["atoms"]), "an atom lost its citation"
    assert all("tier" in a for a in g["atoms"]), "an atom lost its rating"

    # 2. extraction is a rule, and it does not glue articles onto terms.
    # Measured on the first corpus this ran against: "An HTTP cache" produced
    # the entity `an http` and "A B-Tree index" produced `a b-tree`. Junk
    # terms — they can never match a query, never co-occur with the same
    # thing spelled without the article, and they quietly split one topic in
    # two.
    ents = knowledge.entities_in("An HTTP cache revalidates with `If-None-Match`")
    assert not any(e.startswith(("a ", "an ", "the ")) for e in ents), ents
    assert "if-none-match" in ents, ents
    assert "b-tree" in knowledge.entities_in("A B-Tree index speeds queries")

    # 3. a term used once is a word, not a topic
    assert "cache-control" in g["entities"], sorted(g["entities"])
    assert all(len(v["atoms"]) >= knowledge.MIN_ENTITY_ATOMS
               for v in g["entities"].values()), (
        "a term appearing in a single atom was promoted to a topic")

    # ...and the graph actually has edges, or it is a list wearing a hat
    assert g["edges"], (
        "no co-occurrence edges at all — nothing connects, so this is a flat "
        "list with extra steps")

    # 4. what is known ABOUT a thing, with citations and the best tier
    about = knowledge.about(root, "cache-control", g)
    assert about["known"] and about["best_tier"] == 1, about
    assert len(about["atoms"]) >= 2, about["atoms"]
    assert all(a["source"] for a in about["atoms"]), "a claim lost its source"
    nothing = knowledge.about(root, "kubernetes", g)
    assert not nothing["known"], (
        "the graph claimed knowledge of a subject with no atoms — an honest "
        "'no' is the whole point of asking it")

    # 5. thin evidence is named, and it is exactly the thin evidence
    thin = knowledge.weak(root, g)
    thin_ids = {a["id"] for a in thin}
    assert thin_ids == {"C-0105", "C-0203"}, (
        f"--weak found {sorted(thin_ids)}; the blog and the Medium post are "
        f"the only claims below tier {sources.LEARN_MIN_TIER}")

    # 6. source concentration — a risk a flat notes file cannot show
    lb = knowledge.load_bearing(root, g)
    top = lb[0]
    assert top["source"] == RFC9111 and top["atoms"] == 3, lb[:2]
    assert top["share"] >= 30, (
        f"RFC 9111 underpins {top['atoms']} of {len(g['atoms'])} claims and "
        f"the share reported was {top['share']}%")

    # 7. clusters come from the material, not the folder names
    cs = knowledge.clusters(root, g)
    assert cs, "co-occurrence found no topics despite edges existing"
    flat = {t for c in cs for t in c["terms"]}
    assert "cache-control" in flat, sorted(flat)
    assert not any(c["terms"] == ["http"] for c in cs), "a course name leaked in"

    s = knowledge.summary(root, g)
    assert s["atoms"] == 8 and s["weak"] == 2, s
    print(f"[graph] {s['atoms']} atoms became {s['entities']} entities and "
          f"{s['edges']} co-occurrence edge(s) across {s['clusters']} topic(s) "
          f"— derived entirely from files on disk, with every claim keeping "
          f"its citation and its source tier, and nothing asked of a model")
    print(f"[audit] --weak names exactly the 2 claims resting below the learn "
          f"bar (a content farm and a Medium post), and --load-bearing shows "
          f"one RFC underpinning {top['share']}% of everything believed here "
          f"— concentration is a real risk that a flat notes file cannot "
          f"display at all")
    check_the_graph_reads_what_the_platform_writes()
    print("PASS test_knowledge")


def check_the_graph_reads_what_the_platform_writes():
    """The graph and the citation checker must see THE SAME atoms.

    knowledge.atoms() claimed in its own docstring to read "the same
    notes.md files citecheck.py validates against". It did not. citecheck
    walks the whole course tree; knowledge joined one flat path. The
    platform writes `courses/<c>/lessons/NN/notes.md`, so citecheck saw the
    atoms and knowledge saw nothing — the knowledge graph was empty for
    every expert that had ever actually been taught, and no test noticed
    because the tests wrote the flat layout too.

    Two independent descriptions of one truth is this codebase's most
    frequent defect. The repair is not a corrected second copy — it is one
    function, citecheck.notes_files, called by both. This asserts that they
    agree on a tree laid out the way the platform lays it out, at several
    depths, so a future edit that reintroduces a private walker fails here.
    """
    import tempfile
    import citecheck

    root = tempfile.mkdtemp(prefix="kg-agree-")
    LAYOUTS = [
        ("databases", ["lessons", "01"], "C-01"),
        ("databases", ["lessons", "02"], "C-02"),
        ("http", ["lessons", "01"], "P-10"),
        ("deep", ["lessons", "01", "part", "b"], "U-77"),
    ]
    for course, parts, aid in LAYOUTS:
        d = os.path.join(root, "courses", course, *parts)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "notes.md"), "w", encoding="utf-8") as f:
            f.write(f"- {aid} Postgres uses a B-tree index. [src: {PGDOCS}]\n")

    want = {a for _c, _p, a in LAYOUTS}
    seen_by_cite = set(citecheck.known_atoms(root))
    seen_by_graph = {a["id"] for a in knowledge.atoms(root)}
    assert seen_by_cite == want, (
        f"citecheck missed atoms: expected {sorted(want)}, "
        f"got {sorted(seen_by_cite)}")
    assert seen_by_graph == want, (
        f"the knowledge graph is blind to atoms the platform actually "
        f"wrote: expected {sorted(want)}, got {sorted(seen_by_graph)}. "
        f"A graph with no nodes answers every question with silence, and "
        f"silence is indistinguishable from 'nothing is known'.")
    assert seen_by_graph == seen_by_cite, (
        f"the graph and the citation checker disagree about what this "
        f"expert knows: graph {sorted(seen_by_graph)} vs citecheck "
        f"{sorted(seen_by_cite)}. An atom the graph cannot see is an atom "
        f"a citation can still legally reference, so the two must not drift.")

    # the course must be the COURSE, not the deepest directory
    courses = {a["course"] for a in knowledge.atoms(root)}
    assert courses == {"databases", "http", "deep"}, (
        f"lesson directories leaked into the course names: {sorted(courses)}")

    # and the graph must actually be non-empty end to end
    g = knowledge.build(root)
    assert len(g["atoms"]) == 4, g["atoms"]
    assert "b-tree" in g["entities"] and "postgres" in g["entities"], (
        f"the two terms every claim is about produced no entity: "
        f"{sorted(g['entities'])}")
    print(f"[agree] the knowledge graph and the citation checker see the "
          f"identical {len(want)} atoms across 4 course layouts up to 4 "
          f"levels deep, because they call one walker rather than two — the "
          f"flat path this used to join matched nothing the platform writes, "
          f"and both this test and the code were wrong the same way")


if __name__ == "__main__":
    main()
