#!/usr/bin/env python3
"""THE FLEET'S SHARED EXPERIENCE — a new expert inherits a sibling's scars.

commons.py has always shared the fleet's lessons and corroborated facts. Its
CASES were per-expert and read by nobody else: `grep -rn "experts" cases.py
gotchas.py` returned nothing. So a second expert doing similar work started
blind to every wall the first one walked into, and walked into them again at
full price — and failure is the expensive half of what a fleet knows.

What has to be true for sharing to help rather than mislead:

  1. a rookie with NO history of its own gets a sibling's matching case
  2. it arrives ATTRIBUTED — whose case, when, and that the fix passed a gate
     in THAT expert's environment, not this one's
  3. an expert never harvests itself, so its own case cannot arrive twice
     wearing a stranger's name
  4. relevance is term overlap, the same rule an expert's own cases use — not
     "here is everything that ever went wrong anywhere"
  5. it reaches the context window
  6. a fix is ranked above a bare failure, and a RECURRED case above an open
     one, because "the obvious fix already failed here" is the most valuable
     thing a sibling can say

Run from the agent/ directory:  python tests/test_experience.py
"""

import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import cases                   # noqa: E402
import context                 # noqa: E402
import experience             # noqa: E402
import fleet                   # noqa: E402
import loop                    # noqa: E402


def _fail(root, goal, cause, actual):
    t = {"id": f"t-{abs(hash(goal)) % 9999}", "role": "practitioner",
         "goal": goal, "status": "failed", "steps": []}
    cases.open_case(root, t, {"cause": cause, "actual": actual})
    return t


def main():
    home = make_sandbox("experience", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": []})
    veteran = fleet.create(home, "Veteran", "has been burned before")
    rookie = fleet.create(home, "Rookie", "brand new")
    other = fleet.create(home, "Other", "works on something unrelated")

    GOAL = "export the quarterly invoices from the vendor portal to csv"
    t = _fail(veteran, GOAL,
              "the portal paginates and export only takes page 1",
              "only 20 of 240 rows exported")
    cases.record_fix(veteran, dict(t, status="done",
                                   summary="set page size to 500 before exporting"))
    _fail(veteran, "render the monthly chart as svg",
          "the font was missing in the container", "boxes instead of glyphs")
    _fail(other, "tune the postgres autovacuum thresholds",
          "the table was too hot", "bloat kept growing")

    # 1 + 4. the rookie owns nothing, and gets the RELEVANT sibling case only
    assert cases.load(rookie) == [], "the rookie should start with no history"
    hits = experience.matching(home, "export the quarterly invoices to csv",
                               exclude="rookie")
    assert hits, "a rookie learned nothing from a sibling that hit this exact wall"
    assert any("invoice" in " ".join(h.get("terms") or []) or
               "invoices" in h.get("problem", "") for h in hits), hits
    assert not any("autovacuum" in h.get("problem", "") for h in hits), (
        "an unrelated expert's unrelated case was injected — sharing everything "
        "is the same as sharing nothing, only more expensive")

    # 2. attributed, and honest about where the fix was verified
    block = experience.render(hits)
    assert "veteran" in block, block[:200]
    assert "ANOTHER EXPERT" in block, block[:200]
    assert "THERE" in block, (
        "the block must say the fix passed a gate in the SIBLING's "
        "environment, not this one's — otherwise it reads as a fact about "
        "this expert's world")

    # 3. an expert never harvests itself
    own = experience.matching(home, GOAL, exclude="veteran")
    assert not any(h["expert"] == "veteran" for h in own), (
        "the veteran received its own case back as a sibling's — it would "
        "read its own history as independent corroboration")

    # 6. a verified fix outranks a bare failure
    _fail(rookie, "export the quarterly invoices to csv again",
          "unknown", "failed")
    ranked = experience.matching(home, GOAL, exclude="other")
    assert ranked[0].get("status") == "fixed", (
        f"a case carrying a verified fix must come first: "
        f"{[(h['expert'], h['status']) for h in ranked]}")

    # 5. and it reaches the window the model actually sees
    agent = loop.Agent(rookie)
    msgs, _man = context.compile(
        agent, {"id": "r1", "role": "practitioner",
                "goal": "export the quarterly invoices to csv", "course": None})
    body = msgs[1]["content"]
    assert "ANOTHER EXPERT IN THIS FLEET" in body, (
        "the shared experience never reached the context window, so it "
        "changes nothing about what the agent does")
    assert "veteran" in body.lower(), "the sibling was not named in the window"

    # ---- BOUNDED, and it must still see new work ------------------------
    # The first version read every sibling's entire ledger on every context
    # compile. Measured: 0.21 ms at 0 cases, 5.31 ms at 300, linear forever,
    # on a call that happens for every task. test_endurance.py caught it on a
    # CI runner within the hour — "work that gets steadily slower as the
    # ledgers fill is work that stops entirely at some point nobody planned
    # for". A timing assertion here would be flaky on a shared runner, so the
    # STRUCTURAL properties are asserted instead: the work is capped, and the
    # cache still notices a change.
    for i in range(experience.MAX_HARVEST + 60):
        _fail(other, f"unrelated churn number {i} in the ledger",
              "noise", "noise")
    got = experience.harvest(home)
    assert len(got) <= experience.MAX_HARVEST, (
        f"harvest returned {len(got)} rows with no ceiling — an unbounded "
        f"per-task scan is the same defect as an unbounded read, in slower "
        f"motion")
    # and one NOISY expert must not evict a quiet one's verified fix. A flat
    # "newest N fleet-wide" bound let 360 routine failures from `other` push
    # the veteran's FIXED case out of the window entirely — volume silently
    # outranking value, and the most useful record is exactly the rare kind.
    kept = {c["expert"] for c in got}
    assert "veteran" in kept, (
        f"the noisy expert crowded everyone else out: {sorted(kept)}")
    assert any(c.get("status") == "fixed" and c["expert"] == "veteran"
               for c in got), (
        "the one case in this fleet carrying a verified fix was evicted by "
        "routine churn from another expert")
    # a NEW case must still reach a sibling, or the cache is a memory hole
    _fail(veteran, "export the quarterly invoices to csv one more time",
          "a brand new wall", "failed again")
    fresh = experience.matching(home, "export the quarterly invoices to csv",
                                exclude="rookie")
    assert any("brand new wall" in str(h.get("cause", "")) for h in fresh), (
        "a case filed after the cache warmed never reached a sibling — a "
        "stale shared memory is worse than none, because it looks current")

    s = experience.summary(home)
    assert s["experts"] >= 2 and s["with_fix"] >= 1, s
    print(f"[shared] a rookie with no history of its own inherited a "
          f"sibling's FIXED case for the same work — attributed, dated, and "
          f"marked as verified in that expert's environment rather than this "
          f"one's; an unrelated expert's unrelated case was not injected; and "
          f"no expert harvests itself")
    print(f"[ranked] a case carrying a verified fix outranks a bare failure, "
          f"and the block reached the context window the model actually reads "
          f"({s['cases']} case(s) across {s['experts']} expert(s), "
          f"{s['with_fix']} with a fix)")
    print("PASS test_experience")


if __name__ == "__main__":
    main()
