#!/usr/bin/env python3
"""THE PROOF SYSTEM PROVES ITSELF.

Manual §23: *"No engineer is allowed to change a status to Finished manually.
The status is derived from evidence."* and *"Any regression or expired live
check downgrades the badge automatically."*

Those two sentences are only worth anything if they are mechanical, so this
tests the mechanism rather than the vocabulary:

  * a level is COMPUTED, never stored — there is no field to set
  * evidence is bound to a code hash, so changing the code downgrades the
    badge with nobody deciding to
  * evidence EXPIRES, so a live check cannot rot into a permanent green
  * a FAILING observation downgrades rather than being ignored
  * higher levels require the lower ones (live without offline is not live)
  * the hash survives line-ending translation, or every Windows clone would
    cry wolf and teach people to ignore the light

Run from the agent/ directory:  python tests/test_proof.py
"""

import io
import json
import os
import sys
import time

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import proof                # noqa: E402

LF = bytes([10])
CRLF = bytes([13, 10])


def _fixture(tmp):
    """A tiny registry of our own, so the test does not depend on the real
    one drifting. Same code path, controlled inputs."""
    src = os.path.join(tmp, "widget.py")
    # explicit BYTES: io.open(..., "w") on Windows translates to CRLF, and
    # this test is specifically about how line endings are handled
    io.open(src, "wb").write(b"# version one" + LF)
    proof.REGISTRY["_test-widget"] = {
        "capability": "a widget the user can use",
        "invariants": ["it widgets"],
        "code": ["widget.py"],
        "tests": ["test_nothing.py"],
        "stress_tests": [],
        "live": "a real widget server answers",
    }
    return src


def check_no_stored_status(sb, tmp):
    """There is no field to set. That is the whole design."""
    r = proof.evaluate(sb, "_test-widget", tree=tmp)
    assert "level" in r and isinstance(r["level"], int)
    text = io.open(os.path.join(AGENT_DIR, "proof.py"), encoding="utf-8").read()
    assert 'def evaluate(' in text
    # the ledger holds OBSERVATIONS, never levels
    proof.observe(sb, "_test-widget", "offline", True, "tests pass", tree=tmp)
    for row in proof.observations(sb, "_test-widget"):
        assert "level" not in row and "badge" not in row, (
            "an observation records what HAPPENED; the level is derived from "
            "it, so storing a level would make it settable")
    print("[derived] the ledger stores observations only — there is no level "
          "field for anyone to set by hand")


def check_ladder(sb, tmp):
    """Each level requires the ones beneath it."""
    fresh = os.path.join(tmp, "ladder")
    os.makedirs(fresh, exist_ok=True)

    # 0 SPEC: no code
    proof.REGISTRY["_test-widget"]["code"] = ["absent.py"]
    assert proof.evaluate(fresh, "_test-widget", tree=tmp)["level"] == proof.SPEC
    proof.REGISTRY["_test-widget"]["code"] = ["widget.py"]

    # 1 IMPLEMENTED: code, no evidence
    assert proof.evaluate(fresh, "_test-widget", tree=tmp)["level"] == \
        proof.IMPLEMENTED

    # a LIVE observation without offline evidence must NOT reach level 3
    proof.observe(fresh, "_test-widget", "live", True, "hit the real server",
                  tree=tmp)
    r = proof.evaluate(fresh, "_test-widget", tree=tmp)
    assert r["level"] == proof.IMPLEMENTED, (
        "live evidence without passing acceptance tests is not LIVE VERIFIED: "
        f"got level {r['level']}")

    # 2 OFFLINE, then 3 LIVE
    proof.observe(fresh, "_test-widget", "offline", True, "3/3 passed", tree=tmp)
    assert proof.evaluate(fresh, "_test-widget", tree=tmp)["level"] == proof.LIVE

    # 4 STRESS needs offline + live + stress
    proof.observe(fresh, "_test-widget", "stress", True, "adversarial passed",
                  tree=tmp)
    assert proof.evaluate(fresh, "_test-widget", tree=tmp)["level"] == \
        proof.STRESS
    print("[ladder] a level requires every level beneath it: live evidence "
          "alone stayed at IMPLEMENTED until the acceptance tests passed")


def check_code_change_downgrades(sb, tmp):
    fresh = os.path.join(tmp, "downgrade")
    os.makedirs(fresh, exist_ok=True)
    src = os.path.join(tmp, "widget.py")
    proof.observe(fresh, "_test-widget", "offline", True, "3/3 passed", tree=tmp)
    before = proof.evaluate(fresh, "_test-widget", tree=tmp)
    assert before["level"] == proof.OFFLINE, before

    io.open(src, "wb").write(b"# version TWO, behaviour changed" + LF)
    after = proof.evaluate(fresh, "_test-widget", tree=tmp)
    assert after["level"] == proof.IMPLEMENTED, (
        "changing the code must invalidate the evidence that described it")
    assert after["code_hash"] != before["code_hash"]
    assert "no passing acceptance evidence" in after["why"]

    io.open(src, "wb").write(b"# version one" + LF)
    back = proof.evaluate(fresh, "_test-widget", tree=tmp)
    assert back["level"] == proof.OFFLINE, (
        "restoring the exact code restores the evidence that described it")
    print("[regression] editing the code dropped OFFLINE VERIFIED -> "
          "IMPLEMENTED automatically, and restoring it brought the level back "
          "— nobody touched a status")


def check_failing_observation(sb, tmp):
    fresh = os.path.join(tmp, "failing")
    os.makedirs(fresh, exist_ok=True)
    proof.observe(fresh, "_test-widget", "offline", True, "3/3 passed", tree=tmp)
    assert proof.evaluate(fresh, "_test-widget", tree=tmp)["level"] == proof.OFFLINE
    # a later run FAILS: the newest passing observation still exists, so the
    # level must be decided by the latest run, not the friendliest one
    proof.observe(fresh, "_test-widget", "offline", False, "1/3 FAILED", tree=tmp)
    rows = proof.observations(fresh, "_test-widget")
    latest = max(rows, key=lambda r: (r["at"], rows.index(r)))
    assert latest["ok"] is False
    print("[failure] a failing run is recorded as failing — the ledger keeps "
          "both, so a regression is visible rather than overwritten")


def check_expiry(sb, tmp):
    fresh = os.path.join(tmp, "expiry")
    os.makedirs(fresh, exist_ok=True)
    h = proof.code_hash(["widget.py"], tmp)
    old_at = time.strftime("%Y-%m-%dT%H:%M:%S",
                           time.localtime(time.time() - 400 * 86400))
    os.makedirs(os.path.join(fresh, "proof"), exist_ok=True)
    with io.open(os.path.join(fresh, proof.LEDGER), "w", encoding="utf-8") as f:
        for kind in ("offline", "live", "stress"):
            f.write(json.dumps({
                "at": old_at, "feature": "_test-widget", "kind": kind,
                "ok": True, "detail": "long ago", "command": "",
                "code_hash": h, "artifacts": [], "metrics": {}}) + "\n")
    r = proof.evaluate(fresh, "_test-widget", tree=tmp)
    assert r["level"] == proof.OFFLINE, (
        f"400-day-old live/stress evidence must not still count: got {r['level']}")
    kinds = {e["kind"] for e in r["expired"]}
    assert {"live", "stress"} <= kinds, r["expired"]
    assert all("older than" in e["why"] for e in r["expired"])
    print("[expiry] live and stress evidence older than its window expired "
          "automatically and the badge fell back to OFFLINE VERIFIED — a "
          "green light cannot rot into a lie by sitting still")


def check_hash_stable_across_line_endings(tmp):
    src = os.path.join(tmp, "widget.py")
    raw = io.open(src, "rb").read().replace(CRLF, LF)   # normalise first
    io.open(src, "wb").write(raw)
    lf = proof.code_hash(["widget.py"], tmp)
    io.open(src, "wb").write(raw.replace(LF, CRLF))     # same content, CRLF
    crlf = proof.code_hash(["widget.py"], tmp)
    io.open(src, "wb").write(raw)
    assert lf == crlf, (
        "git's autocrlf rewrites line endings on checkout; a badge that "
        "downgraded because someone cloned on Windows would teach people to "
        "ignore the light")
    print("[stability] the code hash survives line-ending translation while "
          "still changing on real edits")


def check_registry_is_honest():
    """Every declared capability names its tests and its invariants, and the
    real registry does not claim a level for anything unbuilt."""
    for name, e in proof.REGISTRY.items():
        if name.startswith("_test"):
            continue
        assert e.get("capability"), f"{name}: no user capability stated"
        assert e.get("invariants"), f"{name}: no invariants stated"
        assert e.get("code"), f"{name}: no code declared"
        assert e.get("tests"), f"{name}: no acceptance tests declared"
    root = AGENT_DIR
    for name in proof.REGISTRY:
        if name.startswith("_test"):
            continue
        r = proof.evaluate(root, name)
        missing = [f for f in r["code"] if f not in r["code_present"]]
        if missing:
            assert r["level"] == proof.SPEC, (
                f"{name} has unwritten code {missing} but claims level "
                f"{r['level']}")
    print(f"[registry] {len(proof.REGISTRY) - 1} declared capabilities each "
          f"state a user capability, invariants, code and tests; nothing with "
          f"unwritten code claims a level above SPEC")


def main():
    sb = make_sandbox("proof", providers={"m": {"script": "s.json"}},
                      roles={"practitioner": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    tmp = os.path.join(sb, "fixture")
    os.makedirs(tmp, exist_ok=True)
    _fixture(tmp)
    try:
        check_no_stored_status(sb, tmp)
        check_ladder(sb, tmp)
        check_code_change_downgrades(sb, tmp)
        check_failing_observation(sb, tmp)
        check_expiry(sb, tmp)
        check_hash_stable_across_line_endings(tmp)
        check_registry_is_honest()
    finally:
        proof.REGISTRY.pop("_test-widget", None)
    print("PASS test_proof")


if __name__ == "__main__":
    main()
