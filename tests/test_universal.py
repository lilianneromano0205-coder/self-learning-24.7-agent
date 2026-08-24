#!/usr/bin/env python3
"""THE UNIVERSAL AGENT — one goal in, an EARNED readiness verdict out.

`universal.py` is the layer the platform was missing: the thing that decides
which of its systems a goal needs before any work starts. Handing a goal
straight to `goal.pursue` assumes the expert already knows the domain and
already owns the tools; when it does not, the run dies several milestones
deep in a way that reads like a weak model, when the real answer was "it
needed a PDF reader" or "it had never studied this".

What is asserted here is the part that could quietly become theatre:

  1. the verdict is EARNED, not asserted — it moves only when the mechanical
     facts move (a capability appears, atoms get studied, a source improves)
  2. an AUTHORITY gap stops the run cold and never reaches goal.pursue,
     because that is the one dimension a machine must not resolve for itself
  3. knowledge learned from a WEAK source does not count as knowledge
  4. a dry run changes nothing on disk — a system that starts installing the
     moment you describe a goal is not one anybody leaves running

Run from the agent/ directory:  python tests/test_universal.py
"""

import io
import json
import os
import shutil
import sys
import tempfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import fleet          # noqa: E402
import universal      # noqa: E402


def _expert(home, slug="probe"):
    fleet.create(home, slug, "a test expert")
    return os.path.join(home, "experts", slug)


def _study(root, course, atoms):
    """Plant studied atoms with real citations, the way ingestion would."""
    d = os.path.join(root, "courses", course, "lessons", "01")
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, "notes.md"), "w", encoding="utf-8") as f:
        for i, (text, src) in enumerate(atoms, 1):
            f.write(f"- C-{i:04d} {text} [src: {src}]\n")


def check_the_verdict_is_earned(home):
    """It must move only when a mechanical fact moves."""
    root = _expert(home, "earned")
    goal = "describe the screenshot and the diagram in this image"

    r1 = universal.ready(home, "earned", goal)
    assert r1["verdict"] != "READY", "a brand-new expert cannot be ready"
    dims = {g["dimension"] for g in r1["blocking"]}
    assert "knowledge" in dims, (
        "an expert that has studied nothing must report a knowledge gap")

    # study the subject from a NORMATIVE source
    _study(root, "vision", [
        ("image diagram screenshot analysis reads figures",
         "https://www.w3.org/TR/wcag2/"),
        ("screenshot diagram figures should carry alt text",
         "https://developer.mozilla.org/en-US/docs/Web/HTML"),
    ])
    r2 = universal.ready(home, "earned", goal)
    assert r2["knowledge"]["matched"] >= 1, r2["knowledge"]
    assert r2["knowledge"]["best_tier"] is not None, "citations were not rated"
    assert r2["knowledge"]["best_tier"] <= universal.MIN_LEARN_TIER, (
        f"w3.org/MDN should rate tier <= {universal.MIN_LEARN_TIER}, "
        f"got {r2['knowledge']['best_tier']}")
    assert "knowledge" not in {g["dimension"] for g in r2["blocking"]
                               if g["what"] == "the subject itself"}, \
        "studying the subject did not close the knowledge gap"
    print(f"[earned] the verdict moved only when the facts did: a new expert "
          f"reported a knowledge gap, and {r2['knowledge']['matched']} cited "
          f"atom(s) from tier-{r2['knowledge']['best_tier']} sources closed it")


def check_a_weak_source_is_not_knowledge(home):
    """The same sentence, believed or not depending on where it came from."""
    root = _expert(home, "sourced")
    goal = "explain caching strategy for the retrieval layer"
    claim = "caching strategy for a retrieval layer should bound staleness"

    _study(root, "c", [(claim, "https://www.rfc-editor.org/rfc/rfc9111")])
    good = universal.ready(home, "sourced", goal)

    _study(root, "c", [(claim, "https://random-content-farm.example.com/top-10")])
    weak = universal.ready(home, "sourced", goal)

    assert good["knowledge"]["best_tier"] <= universal.MIN_LEARN_TIER, \
        f"an RFC should be normative, got tier {good['knowledge']['best_tier']}"
    assert weak["knowledge"]["best_tier"] > universal.MIN_LEARN_TIER, \
        f"a content farm must not rate <= {universal.MIN_LEARN_TIER}"
    weak_reasons = [g for g in weak["blocking"] if g["what"] == "source quality"]
    assert weak_reasons, (
        "identical knowledge from a junk source must be refused, or 'learn "
        "only from reputable sources' is a slogan rather than a control")
    assert not [g for g in good["blocking"] if g["what"] == "source quality"]
    print(f"[sources] the same claim was accepted at tier "
          f"{good['knowledge']['best_tier']} from an RFC and refused at tier "
          f"{weak['knowledge']['best_tier']} from a content farm — what is "
          f"believed depends on where it came from, decided by rule and never "
          f"by a model")


def check_authority_stops_the_run(home):
    """The boundary that makes every other control meaningful."""
    _expert(home, "bounded")
    for goal in ("create an account on example.com and publish the report",
                 "buy the dataset and email the summary to the team",
                 "get an api key for the vendor and deploy to production"):
        r = universal.achieve(home, "bounded", goal, learn=False)
        assert r["started"] is False, f"it started work on: {goal}"
        assert "pursuit" not in r, "goal.pursue was reached despite the block"
        assert r["needs_owner"], f"no authority gap detected in: {goal}"
        assert "NEEDS YOU" in r["verdict"] or r["needs_owner"], r["verdict"]
        for g in r["needs_owner"]:
            assert g["routes_to"].startswith("the owner"), g
    # and an ordinary goal is NOT falsely routed to the owner
    ok = universal.ready(home, "bounded", "summarise the notes into a report")
    assert not ok["needs_owner"], (
        f"an ordinary goal was sent to the owner: {ok['needs_owner']}")
    print("[authority] three goals implying an account, a payment, a "
          "credential, a deployment and an email all stopped BEFORE any work "
          "began and routed to the owner; goal.pursue was never reached; and "
          "an ordinary goal was not falsely escalated")


def check_a_dry_run_changes_nothing(home):
    """Describing a goal must not start installing things."""
    root = _expert(home, "dry")
    before = _tree(root)
    plan = universal.resolve(home, "dry",
                             "read the pdf papers and the video lecture",
                             apply=False)
    after = _tree(root)
    assert before == after, (
        f"a dry run wrote to disk: {sorted(set(after) - set(before))[:5]}")
    assert plan["applied"] is False
    assert plan["actions"], "a blocked goal must produce a plan of action"
    for a in plan["actions"]:
        assert a["why"], f"action {a['action']!r} has no stated reason"
        if a["action"] != "ask the owner":
            assert a["command"], f"{a['action']} is not reproducible by hand"
    print(f"[dry-run] describing a goal produced {len(plan['actions'])} routed "
          f"action(s), each with a reason and a command you can run yourself, "
          f"and wrote nothing to the expert")


def check_every_gap_routes_somewhere_real(home):
    """A dimension with no route is a dead end wearing a label."""
    import mission
    _expert(home, "routed")
    r = universal.resolve(home, "routed",
                          "sign up, read the pdf papers, watch the lecture "
                          "video and publish the findings", apply=False)
    seen = {g["dimension"] for g in r["blocking"]}
    assert seen, "a goal needing everything reported no gaps at all"
    for g in r["blocking"]:
        assert g["dimension"] in mission.GAPS, (
            f"{g['dimension']} is not one of the platform's own dimensions")
        assert g["routes_to"] == mission.GAPS[g["dimension"]]["routes_to"], (
            f"{g['dimension']} routes somewhere the gap router does not know "
            f"about — two answers to one question is how they drift apart")
        assert g["user_sees"], f"{g['what']} has no plain-language label"
    print(f"[routing] {len(r['blocking'])} gap(s) across {len(seen)} dimension(s), "
          f"every one classified by mission.GAPS itself rather than by a "
          f"second opinion, and every one carrying the route the platform "
          f"already declared for it")


def _tree(root):
    out = []
    for dirpath, _d, names in os.walk(root):
        for n in names:
            out.append(os.path.relpath(os.path.join(dirpath, n), root))
    return sorted(out)


def main():
    home = tempfile.mkdtemp(prefix="universal-")
    try:
        check_the_verdict_is_earned(home)
        check_a_weak_source_is_not_knowledge(home)
        check_authority_stops_the_run(home)
        check_a_dry_run_changes_nothing(home)
        check_every_gap_routes_somewhere_real(home)
        print("PASS test_universal")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
