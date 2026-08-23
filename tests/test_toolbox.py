#!/usr/bin/env python3
"""Toolbox + pre-built specialists: agents are TOLD what tools exist, and the
gallery ships crafted identities, not generic-assistant slop.

1. The scan reports real capabilities of THIS machine (stdlib ones always
   ready; key-gated ones follow the keys) and the note tells agents exactly
   what to use and what never to attempt.
2. Every template is complete, unique, a valid kind, and carries a real
   identity (standards + refusals, not filler).
3. A quick agent launched here receives the capability note as its FIRST
   memory, and spinning from a template installs the template's identity.

Run from the agent/ directory:  python tests/test_toolbox.py
"""

import json
import os
import sys

from common import AGENT_DIR, make_sandbox, read_state

sys.path.insert(0, AGENT_DIR)
import quick
import templates
import toolbox


def main():
    # --- 1. the scan and the note
    s = toolbox.scan()
    for always in ("web_fetch", "site_crawl", "recall_memory", "verify_spec"):
        assert s["capabilities"][always]["ready"], f"{always} is stdlib — always ready"
    assert s["capabilities"]["transcribe"]["ready"] == \
        (s["binaries"]["ffmpeg"] and s["keys"]["GROQ_API_KEY"]), \
        "transcribe readiness must follow ffmpeg AND the Groq key"
    note = toolbox.capability_note()
    assert "READY:" in note and "recall.py" in note
    assert "never attempt" in note.lower() or "MISSING" not in note, \
        "missing capabilities must carry the do-not-attempt instruction"
    print("[scan] capabilities reflect this machine; the note instructs, not hints")

    # --- 2. the gallery
    tpls = templates.all_templates()
    assert len(tpls) >= 10
    slugs = [t["slug"] for t in tpls]
    assert len(set(slugs)) == len(slugs), "slugs must be unique"
    kinds = {"advisor", "maker", "operator"}
    for t in tpls:
        assert t["kind"] in kinds, t["slug"]
        assert len(t["specialty"]) > 120, \
            f"{t['slug']}: a real identity, not a one-liner"
        assert t["deliverable_hint"], t["slug"]
    assert {t["kind"] for t in tpls} == kinds, "the gallery must cover all kinds"
    # crafted, not generic: standards and refusals are present
    joined = " ".join(t["specialty"] for t in tpls).lower()
    for marker in ("never", "ask_human", "unverified"):
        assert marker in joined, f"gallery identities must carry '{marker}' discipline"
    print(f"[gallery] {len(tpls)} specialists, all kinds covered, identities "
          f"carry standards and refusals")

    # --- 3. injection into the quick lane
    home = make_sandbox("toolbox", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    t = templates.get("technical-writer")
    root = quick.create(home, "Doc Smith", t["specialty"])
    with open(os.path.join(root, "briefing", "notes.md"), "w",
              encoding="utf-8") as f:
        f.write("# API\nEndpoint /v1/ping returns pong.\n")
    kind, tid = quick.launch(root, "document the API", t["kind"],
                             t["deliverable_hint"], t["specialty"])
    assert kind == "maker"
    task = next(x for x in read_state(root)["tasks"] if x["id"] == tid)
    assert task["memory_files"][0] == "courses/briefing/capabilities.md", \
        "the capability note must be the FIRST thing in the agent's memory"
    caps = open(os.path.join(root, "courses/briefing/capabilities.md"),
                encoding="utf-8").read()
    assert "TOOLBOX" in caps and "READY:" in caps
    idn = open(os.path.join(root, "identity.md"), encoding="utf-8").read()
    assert "copy-pasteable" in idn, "the template's identity must be installed"
    print("[quick] capability note injected first; template identity installed")
    print("PASS test_toolbox")


if __name__ == "__main__":
    main()
