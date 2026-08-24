#!/usr/bin/env python3
"""THE MISSION SURVIVES EVERYTHING THAT USUALLY ERASES IT.

Manual §11 validation gate: *"A mission survives context compaction, process
restart and model/provider swap without losing objective or critical
constraints."* Invariants: *"Mission contract is persisted outside
transcript; every action references a success criterion; completed evidence
is monotonic unless explicitly invalidated."* Required tests: *"Kill/restart
tests, forced compaction tests, model-swap tests, stale-context tests,
contradictory-new-information tests."*

So this test does the erasing on purpose:

  * compaction   the transcript is compacted to nothing; the contract is
                 recompiled from disk and is byte-identical
  * restart      a fresh process with no memory of the first reads the same
                 objective, criteria and evidence
  * model swap   the provider and model change; the contract does not
  * drift        an action that names no criterion is REFUSED, and one that
                 names a satisfied criterion is refused too
  * monotonic    met evidence cannot vanish; invalidating it needs a reason
                 and keeps the prior record
  * amendment    the objective cannot be edited in place — only amended,
                 with a reason, and the fingerprint changes visibly

Run from the agent/ directory:  python tests/test_mission.py
"""

import json
import os
import subprocess
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import mission              # noqa: E402

OBJECTIVE = "Ship a pricing page that a customer could actually use"
CRITERIA = ["the page exists at out/pricing.html",
            "the page passes the design gate",
            "every price is cited to the pricing sheet"]
CONSTRAINTS = ["never invent a price", "no placeholder copy"]
NON_GOALS = ["redesigning the rest of the site"]


def check_contract_lives_outside_the_transcript(sb):
    m = mission.create(sb, OBJECTIVE, CRITERIA, CONSTRAINTS, NON_GOALS)
    mid = m["id"]
    on_disk = os.path.join(sb, "missions", mid, "mission.json")
    assert os.path.exists(on_disk), "the contract must be a file, not a prompt"
    body = json.load(open(on_disk, encoding="utf-8"))
    assert body["objective"] == OBJECTIVE
    assert len(body["criteria"]) == 3
    print("[persisted] the mission contract is a file on disk, not a passage "
          "in a transcript that compaction can summarise away")
    return mid


def check_survives_compaction_and_restart(sb, mid):
    """Compaction rewrites the WINDOW. The contract is recompiled from disk,
    so it cannot be summarised into something softer."""
    before = mission.render(mission.compile_state(sb, mid))

    # simulate the harshest possible compaction: nothing of the window is kept
    ctx = os.path.join(sb, "contexts")
    os.makedirs(ctx, exist_ok=True)
    with open(os.path.join(ctx, "wiped.json"), "w", encoding="utf-8") as f:
        json.dump([{"role": "system", "content": "(everything else compacted)"}], f)

    after = mission.render(mission.compile_state(sb, mid))
    assert after == before, "recompiling the contract must be deterministic"
    assert OBJECTIVE in after
    for c in CONSTRAINTS:
        assert c in after, f"binding constraint lost: {c}"

    # and a FRESH PROCESS, which shares no memory at all with this one
    code = (
        "import sys, json; sys.path.insert(0, %r); import mission; "
        "print(mission.render(mission.compile_state(%r, %r)))"
        % (AGENT_DIR, sb, mid))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1"})
    assert r.returncode == 0, r.stderr[-400:]
    assert OBJECTIVE in r.stdout, "a restarted process must see the objective"
    for c in CONSTRAINTS:
        assert c in r.stdout, f"a restarted process lost constraint: {c}"
    print("[compaction+restart] the window was wiped and a brand-new process "
          "recompiled the identical objective, criteria and binding "
          "constraints from disk")


def check_model_swap_changes_nothing(sb, mid):
    """Manual §11: the objective must survive a model/provider swap. The
    contract does not reference a model at all — which is the point."""
    rec = mission.load(sb, mid)
    blob = json.dumps(rec)
    for token in ("model", "provider", "openrouter", "deepseek", "gpt", "claude"):
        assert token not in blob.lower() or token in OBJECTIVE.lower(), (
            f"the mission contract must not depend on {token!r}")
    print("[model-swap] the contract names no model or provider, so swapping "
          "one cannot change what the mission is")


def check_every_action_is_bound(sb, mid):
    """Drift is refused, not warned about."""
    chain = mission.justify(sb, mid, "C1", milestone="M1",
                            task_goal="write the page",
                            expected_evidence="out/pricing.html exists")
    assert chain["criterion"]["id"] == "C1"
    assert chain["objective"] == OBJECTIVE

    for bad, why in (
            ("C99", "a criterion that does not exist"),
            (None, "no criterion at all")):
        try:
            mission.justify(sb, mid, bad, task_goal="do something",
                            expected_evidence="something happens")
            raise AssertionError(f"must refuse: {why}")
        except (ValueError, TypeError):
            pass
    # and an action with no recognisable outcome is refused
    try:
        mission.justify(sb, mid, "C1", task_goal="think about it",
                        expected_evidence="   ")
        raise AssertionError("must refuse an action with no expected evidence")
    except ValueError:
        pass
    mission.record_action(sb, mid, chain, task_id="t1")
    rec = mission.load(sb, mid)
    assert rec["actions"][-1]["criterion"] == "C1"
    print("[bound] an action must name the criterion it serves and the "
          "evidence it will produce; unbound work and unrecognisable "
          "outcomes are both refused")


def check_evidence_is_monotonic(sb, mid):
    mission.meet(sb, mid, "C1", "out/pricing.html written, 4.2 KB",
                 verified_by="exists-gate", task="t1")
    st = mission.compile_state(sb, mid)
    assert st["criteria_met"] == 1

    # a met criterion cannot be worked again — that is not progress
    try:
        mission.justify(sb, mid, "C1", task_goal="redo it",
                        expected_evidence="the file again")
        raise AssertionError("a satisfied criterion must not be re-queued")
    except ValueError:
        pass

    # meeting a criterion requires EVIDENCE, not a claim
    try:
        mission.meet(sb, mid, "C2", "   ")
        raise AssertionError("a criterion is met by evidence, not assertion")
    except ValueError:
        pass

    # invalidation is explicit, reasoned, and KEEPS the prior record
    try:
        mission.invalidate(sb, mid, "C1", "")
        raise AssertionError("invalidating met evidence requires a reason")
    except ValueError:
        pass
    mission.invalidate(sb, mid, "C1", "the file was deleted by a later step",
                       by="examiner")
    rec = mission.load(sb, mid)
    c1 = next(c for c in rec["criteria"] if c["id"] == "C1")
    assert c1["state"] == "invalidated"
    assert len(c1["evidence"]) == 2, "the original evidence must be kept"
    assert "out/pricing.html written" in c1["evidence"][0]["evidence"]
    assert c1["evidence"][1].get("invalidation") is True
    print("[monotonic] met evidence cannot silently vanish: invalidating it "
          "needed a stated reason and the original record is still there")


def check_amendment_is_visible(sb, mid):
    before = mission.load(sb, mid)["fingerprint"]
    try:
        mission.amend(sb, mid, objective="something else entirely", why="")
        raise AssertionError("an amendment must state why")
    except ValueError:
        pass
    mission.amend(sb, mid, objective="Ship a pricing page AND a FAQ",
                  why="the customer asked for the FAQ in the same release",
                  by="owner")
    rec = mission.load(sb, mid)
    assert rec["fingerprint"] != before, "an amended contract is a new contract"
    a = rec["amendments"][-1]
    assert a["why"] and a["by"] == "owner"
    assert a["from_fingerprint"] == before and a["to_fingerprint"] == rec["fingerprint"]
    assert a["changed"][0]["from"] == OBJECTIVE, "the previous objective is kept"
    print("[amendment] the objective cannot be edited in place — the change "
          "carries a reason, an author, and both fingerprints, so drift is "
          "visible instead of silent")


def check_gap_router(sb, mid):
    """Every blocker is CLASSIFIED, because the class decides the route."""
    for dim in ("knowledge", "capability", "authority", "strategy"):
        mission.blocked(sb, mid, dim, f"a {dim} problem", criterion="C2")
    try:
        mission.blocked(sb, mid, "vibes", "unclassifiable")
        raise AssertionError("an unknown gap dimension must be refused")
    except ValueError:
        pass
    st = mission.compile_state(sb, mid)
    dims = {b["dimension"] for b in st["blockers"]}
    assert {"knowledge", "capability", "authority", "strategy"} <= dims
    human = {b["dimension"] for b in st["needs_human"]}
    assert "authority" in human, (
        "an authority gap cannot be solved by the agent trying harder, so it "
        "must surface to the owner")
    assert "knowledge" not in human, (
        "a knowledge gap routes to study, not to the human")
    print(f"[gaps] {len(dims)} blocker dimensions classified and routed; only "
          f"the authority gap escalated to the owner")


def check_contract_reaches_every_role(sb):
    """The contract is the ASSIGNMENT, not memory. A role that may see less
    memory (the Student sits closed-book) must still see what it was asked to
    do — otherwise the strictest role is the one most free to drift."""
    import context
    import loop as L
    sb2 = make_sandbox("mission_roles",
                       providers={"m": {"script": "s.json"}},
                       roles={"practitioner": "m", "student": "m",
                              "consultant": "m"},
                       scripts={"s.json": [{"tool": "finish_task",
                                            "args": {"summary": "ok"}}]})
    m = mission.create(sb2, OBJECTIVE, CRITERIA, CONSTRAINTS, NON_GOALS)
    a = L.Agent(sb2)
    for role in ("practitioner", "student", "consultant"):
        tid = a.add_task(role, "do the next thing", mission=m["id"],
                         criterion="C1")
        msgs, man = context.compile(a, a.find_task(tid))
        window = msgs[1]["content"]
        assert OBJECTIVE in window, f"{role} cannot see the objective"
        for c in CONSTRAINTS:
            assert c in window, f"{role} cannot see constraint: {c}"
        assert "serves criterion C1" in window, f"{role} lost the binding"
        assert window.index("MISSION CONTRACT") < 250, (
            f"{role}: the contract must lead the window, not trail it")
        entry = next(s for s in man["sources"] if s["name"] == "mission")
        assert entry["excluded_by_router"] is None, (
            f"{role}: the memory router must never route the contract away")
    print("[every-role] practitioner, student and consultant all receive the "
          "objective, the binding constraints and their criterion — the "
          "memory router cannot route the assignment away")


def check_close_requires_evidence(sb):
    m = mission.create(sb, "A small mission", ["the artifact exists"])
    mid = m["id"]
    try:
        mission.close(sb, mid, "I think it is done")
        raise AssertionError("a mission must not close on an opinion")
    except ValueError as e:
        assert "still open" in str(e)
    mission.meet(sb, mid, "C1", "artifact.md written", verified_by="gate")
    mission.close(sb, mid)
    assert mission.load(sb, mid)["status"] == "complete"
    # and a mission with no criteria cannot exist at all
    try:
        mission.create(sb, "vague ambition", [])
        raise AssertionError("a mission needs at least one success criterion")
    except ValueError:
        pass
    print("[closure] a mission closes on met criteria, never on a decision to "
          "stop; and a mission with no criteria cannot be created")


def main():
    sb = make_sandbox("mission", providers={"m": {"script": "s.json"}},
                      roles={"practitioner": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    mid = check_contract_lives_outside_the_transcript(sb)
    check_survives_compaction_and_restart(sb, mid)
    check_model_swap_changes_nothing(sb, mid)
    check_every_action_is_bound(sb, mid)
    check_evidence_is_monotonic(sb, mid)
    check_amendment_is_visible(sb, mid)
    check_gap_router(sb, mid)
    check_contract_reaches_every_role(sb)
    check_close_requires_evidence(sb)
    # ---- a raised blocker can be lowered again --------------------------
    # mission.resolve_blocker existed, fully written, and no CLI, panel route
    # or other module in the repository ever called it. So `mission.py block`
    # could raise a blocker and nothing on any surface could clear it: a
    # mission that hit a gap stayed blocked for the life of the fleet, and
    # the gap router's promise ("this routes to X") had no closing move.
    # Driven through the CLI, because the CLI is what was missing.
    ub = mission.create(sb, "prove a blocker can be cleared",
                        ["the blocker is resolved with a reason"])["id"]
    mission.blocked(sb, ub, "authority", "needs a login nobody granted")
    assert [b.get("resolved") for b in mission.load(sb, ub)["blockers"]] == [False]
    r = subprocess.run([sys.executable, os.path.join(AGENT_DIR, "mission.py"),
                        "unblock", ub, "0", "--how", "the owner granted it",
                        "--root", sb], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"unblock failed: {r.stdout}{r.stderr}"
    b0 = mission.load(sb, ub)["blockers"][0]
    assert b0.get("resolved") is True and "owner granted" in b0.get("how", ""), b0
    # and an index that does not exist fails loudly rather than silently
    r2 = subprocess.run([sys.executable, os.path.join(AGENT_DIR, "mission.py"),
                         "unblock", ub, "9", "--root", sb],
                        capture_output=True, text=True, timeout=120)
    assert r2.returncode != 0, "unblocking a blocker that does not exist succeeded"
    print("[unblock] a raised blocker can be resolved through the CLI with "
          "the reason recorded, and a bad index fails loudly — resolve_blocker "
          "was written but unreachable from every surface")

    print("PASS test_mission")


if __name__ == "__main__":
    main()
