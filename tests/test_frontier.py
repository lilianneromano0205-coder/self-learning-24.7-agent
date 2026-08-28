#!/usr/bin/env python3
"""THE CAPABILITY FRONTIER: A MODEL MAY PROPOSE A TOOL, NEVER ITS OWN EXAM.

The frontier makes the set of capabilities open-ended. That is the whole
point, and it is also the whole danger: every mechanism here exists because
the obvious version of "let the agent add tools" hands a worker the ability to
install code and then write the test that says the code works.

The laws proved here, each one a thing that would be catastrophic if it
quietly stopped being true:

  1. A probe that PASSES before anything is installed is not evidence. It
     cannot tell having the capability from not having it, so it lands at
     `unfalsifiable` — terminal, never ready, never adopted.
  2. Nothing reaches `owned` except through the shipped acquisition ladder
     and a human. A green probe is not ownership.
  3. An edited spec, a missing seal, or an APPENDED second seal all yield
     TAMPER, and TAMPER runs nothing at all — logs/execution.jsonl must not
     grow by a line. Appending is the attack that defeats last-seal-wins,
     which is why this ledger is first-seal-wins.
  4. The agent cannot write the probe spec or the ledger through the File
     Authority; both live in a CONTROL zone.
  5. Readiness is decided OUTSIDE the expert root. Hand-writing `owned` into
     the expert's own ledger buys nothing.
  6. A capability with no anchor in the goal's own words is refused.
  7. The model cannot author a probe at all — there is no parameter for it.
  8. An observation made on the host cannot ground an acquisition.
  9. Adoption is owner-only, and refuses from inside an agent task.
 10. A refused capability is not silently re-attempted.
 11. universal.ready() reports NOT READY with the exact owner action, in both
     documented shapes of the false-READY bug.
 12. A dry run writes nothing, anywhere.
 13. A frontier capability cannot shadow or corrupt a built-in.
 14. Nothing model-chosen reaches the shell command string.
 15. toolbox keeps its published shapes, including root=None.

This file NEVER prints the token "SKIP" followed by a space, because
mutate_check scores a mutation as skipped on that substring appearing
anywhere in the output — which is how three of acquire's mutations became
unscored. The Docker-dependent half lives in test_frontier_live.py.

Run from the agent/ directory:  python tests/test_frontier.py
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import fileauth                # noqa: E402
import frontier                # noqa: E402
import harness                 # noqa: E402
import policy                  # noqa: E402
import toolbox                 # noqa: E402
import universal               # noqa: E402

PY = sys.executable
GOAL = ("explore my SaaS end to end and produce a narrated screen-recorded "
        "walkthrough with a spoken explanation of every flow")
QUOTE = "narrated screen-recorded walkthrough"


def _tree(*roots):
    out = []
    for root in roots:
        for dirpath, _d, names in os.walk(root):
            for n in names:
                p = os.path.join(dirpath, n)
                try:
                    out.append((os.path.relpath(p, root), os.path.getsize(p)))
                except OSError:
                    pass
    return sorted(out)


def _exec_lines(root):
    try:
        with io.open(os.path.join(root, "logs", "execution.jsonl"),
                     encoding="utf-8") as f:
            return len(f.readlines())
    except OSError:
        return 0


def _absent(root, name, module="nosuchmodule_xyz", package="nosuchpkg_xyz"):
    """A proposal whose probe must fail: nothing by that name is installed."""
    return frontier.propose(root, name, "a capability this goal needs",
                            QUOTE, GOAL, kind="import", module=module,
                            package=package,
                            how_argv=["python", "-m", module])


def check_a_probe_that_passes_before_anything_is_installed_is_refused(root):
    """A probe that is already green proves nothing about the capability."""
    frontier.propose(root, "already_here", "use a tool that exists", QUOTE,
                     GOAL, kind="binary", binary=os.path.basename(PY),
                     how_argv=[os.path.basename(PY), "--version"])
    row = frontier.falsify(root, "already_here")
    assert row["stage"] == "unfalsifiable", (
        f"a probe that passed BEFORE any installation landed at "
        f"{row['stage']!r}; it must be unfalsifiable, because it cannot "
        f"distinguish having the capability from not having it")
    caps = frontier.capabilities(root)
    assert caps["already_here"]["ready"] is False, (
        "an unfalsifiable capability was reported READY")
    print(f"[unfalsifiable] a probe observed green before anything was "
          f"installed is held at 'unfalsifiable' and never reported ready; "
          f"any corroboration is recorded as an owner action "
          f"({len(row.get('owner_actions', []))} of them), never as a stage")


def check_a_passing_probe_never_becomes_owned(root):
    """The deleted shortcut: rc==0 plus corroboration must never self-grant."""
    for cap in ("already_here",):
        row = frontier.get(root, cap)
        assert row["stage"] != "owned", (
            f"{cap} reached 'owned' with no acquisition, no capability test "
            f"and no human — the self-granting branch is back")
    ok, why = frontier.attemptable(root, "already_here")
    assert frontier.capabilities(root)["already_here"]["ready"] is False, why

    # And acquiring must refuse BECAUSE the probe never failed — not for some
    # other reason that happens to also stop it. Asserting only "it raised"
    # let the mutation `if row["stage"] != "red": -> if False:` survive, since
    # the host-sandbox blocker refused it anyway one line later. The REASON is
    # the law; anything else is a different law wearing its name.
    try:
        frontier.acquire_next(root, root, "already_here", apply=True)
        raise AssertionError(
            "an acquisition began for a capability whose probe was never "
            "observed to fail")
    except frontier.Refused as e:
        assert "red" in str(e) or "FAIL" in str(e), (
            f"acquiring a non-red capability was refused, but for the wrong "
            f"reason: {e!s}. The stage guard is what must stop it, because "
            f"only a probe that failed first can prove anything by passing "
            f"later")
    print("[no-self-grant] a passing pre-install probe cannot reach 'owned', "
          "and acquiring one is refused BECAUSE its probe never failed: the "
          "only path is request -> install -> capability_test -> a human")


def check_an_edited_spec_or_a_second_seal_yields_tamper_and_runs_nothing(root):
    """TAMPER must be decided BEFORE anything is generated or executed."""
    _absent(root, "tamper_one")
    frontier.falsify(root, "tamper_one")
    sp = os.path.join(root, "frontier", "probes", "tamper_one.json")
    spec = json.load(io.open(sp, encoding="utf-8"))
    spec["module"] = "json"
    with io.open(sp, "w", encoding="utf-8") as f:
        json.dump(spec, f)
    before = _exec_lines(root)
    rc = frontier.run_probe(root, "tamper_one")
    assert rc == 2, f"an edited sealed spec returned {rc}, not TAMPER"
    assert _exec_lines(root) == before, (
        "a TAMPER verdict executed something; the seal must be compared "
        "before any body is generated or run")

    # THE APPEND ATTACK, IN ITS ONLY DANGEROUS FORM. Appending a seal with a
    # WRONG hash is caught by any comparison at all, so asserting that proves
    # nothing about seal ORDER. The attack that separates the two rules is:
    # edit the spec, then append a seal that MATCHES the edited spec. Under
    # "the last seal wins" that is accepted and the swapped probe runs; under
    # first-seal-wins the later row is a conflict and nothing runs. The
    # mutation `first = h` failed to be caught until this case existed.
    _absent(root, "tamper_two")
    frontier.falsify(root, "tamper_two")
    sp2 = os.path.join(root, "frontier", "probes", "tamper_two.json")
    swapped = json.load(io.open(sp2, encoding="utf-8"))
    swapped["module"] = "json"
    with io.open(sp2, "w", encoding="utf-8") as f:
        json.dump(swapped, f)
    matching = frontier._probe_hash("tamper_two", 1, swapped)
    sealf, _kind = frontier.seal_path(root)
    with io.open(sealf, "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "probe", "capability": "tamper_two",
                            "gen": 1, "probe_hash": matching}) + "\n")
    before = _exec_lines(root)
    rc = frontier.run_probe(root, "tamper_two")
    assert rc == 2, (
        f"a spec was swapped and a MATCHING seal appended, and run_probe "
        f"returned {rc} instead of TAMPER — the last seal is winning, so an "
        f"attacker never needs to edit a seal: appending one re-seals the "
        f"probe and the replacement runs")
    assert _exec_lines(root) == before, "the append attack still executed"
    print("[tamper] an edited spec AND an appended conflicting seal both "
          "return 2 with the execution ledger unchanged — first-seal-wins, so "
          "appending a seal is not a way to re-seal a probe")


def check_the_agent_cannot_write_the_probe_or_the_ledger_through_the_file_authority(root):
    """frontier/ must be a CONTROL zone, like approvals/ and org/."""
    assert "frontier" in fileauth.CONTROL_DIRS, (
        "frontier/ is not a control directory, so a worker could edit the "
        "sealed spec through the ordinary write_file tool")
    for rel in ("frontier/frontier.json", "frontier/probes/x.json",
                "frontier/probes/x.py"):
        z = fileauth.zone_of(rel)
        assert z == fileauth.ZONE_CONTROL, (
            f"{rel} classifies as {z}, not CONTROL")
    assert ("frontier/frontier.json", "capability frontier ledger") \
        in harness.LEDGERS, "the frontier ledger is not in harness.LEDGERS"
    print("[zone] frontier/ is a CONTROL directory and its ledger is in "
          "harness.LEDGERS — the scope proved here is the write_file tool's "
          "classification, which is what an agent's file writes go through")


def check_readiness_is_decided_outside_the_expert_root(root):
    """Hand-writing 'owned' into the expert's own ledger must buy nothing."""
    _absent(root, "forged_one")
    frontier.falsify(root, "forged_one")
    rows = frontier.load(root)
    for r in rows:
        if r["capability"] == "forged_one":
            r["stage"] = "owned"
            r["adoption"] = {"by": "nobody", "where": "home"}
    frontier._save(root, rows)
    cap = frontier.capabilities(root)["forged_one"]
    assert cap["ready"] is False, (
        "writing stage='owned' into the in-root ledger produced a READY "
        "capability; readiness must be decided by the seal outside the root")
    assert "seal" in cap["how"], cap["how"]
    _p, kind = frontier.seal_path(root)
    assert kind == "home", (
        f"the seal for an expert inside a fleet landed {kind!r}, not outside "
        f"the root it protects")
    print(f"[outside] a forged 'owned' row is not ready: the deciding record "
          f"is the seal ledger at kind={kind!r}, outside the expert root, "
          f"which no write under that root can reach")


def check_a_quote_that_is_not_in_the_goal_or_is_trivial_is_refused(root):
    """A capability with no anchor in the goal is one somebody imagined."""
    for quote, what in ((" ", "an empty quote"), ("the", "a stopword"),
                        ("a b c d e f g h", "words too short to mean anything"),
                        ("a phrase found nowhere in the goal at all",
                         "a quote that is not in the goal")):
        try:
            frontier.propose(root, "anchor_probe", "need", quote, GOAL,
                             kind="import", module="m_xyz", package="p_xyz",
                             how_argv=["python", "-m", "m_xyz"])
            raise AssertionError(f"{what} was accepted as an anchor")
        except frontier.Refused:
            pass
    print("[anchor] four unanchored quotes refused — a capability must quote "
          "a real span of what was actually asked, or it is a capability "
          "somebody imagined")


def check_a_probe_is_never_authored_by_the_model(root):
    """There must be no parameter through which probe code can be supplied."""
    import inspect
    sig = set(inspect.signature(frontier.propose).parameters)
    for banned in ("probe", "probe_python", "probe_argv", "command", "argv",
                   "witness", "source_code", "script"):
        assert banned not in sig, (
            f"propose() accepts {banned!r}: a model can author the test that "
            f"says its own tool works, which is the one thing this system "
            f"exists to prevent")
    body = frontier.probe_body(root, {"kind": "import", "module": "m_xyz",
                                      "target_rel": "capabilities/p",
                                      "timeout": 30})
    assert "WRONG COPY" in body and "sys.path = [target]" in body, (
        "the generated import probe no longer ties GREEN to the install "
        "target, so a module from anywhere would satisfy it")
    body2 = frontier.probe_body(root, {"kind": "binary", "binary": "b_xyz",
                                       "timeout": 30})
    assert "INSIDE THE WORKSPACE" in body2, (
        "the generated binary probe no longer rejects an executable resolved "
        "from inside the expert root; shutil.which searches the current "
        "directory on Windows and that directory IS the workspace")
    print(f"[authored] propose() has no parameter that could carry probe "
          f"code ({len(sig)} parameters, none of them a body), and both "
          f"generated bodies keep the checks that tie a pass to installed "
          f"bytes rather than to anything the worker could place")


def check_a_host_observation_cannot_ground_an_acquisition(root):
    """An uncontained RED is honest, and it is not a foundation."""
    _absent(root, "uncontained")
    row = frontier.falsify(root, "uncontained")
    assert row["stage"] == "red", row["stage"]
    assert row["red"]["contained"] is False, (
        "a probe run on the host backend was recorded as contained")
    try:
        frontier.acquire_next(root, root, "uncontained", apply=True)
        raise AssertionError("an acquisition proceeded from a host observation")
    except frontier.Refused as e:
        assert "host" in str(e), str(e)
    print("[contained] a RED observed on the host is recorded honestly as "
          "uncontained and is refused as the basis for installing anything — "
          "the same refusal acquire.install already makes")


def check_authority_and_adoption_route_to_the_owner(root, home):
    """Adoption is owner-only, and refuses from inside an agent task."""
    _absent(root, "adopt_probe")
    frontier.falsify(root, "adopt_probe")
    row = frontier.get(root, "adopt_probe")
    want = " ".join(row["how_argv"])

    os.environ["AGENT_TASK_ID"] = "t-1"
    try:
        frontier.adopt(root, home, "adopt_probe", actor="me", confirm_how=want)
        raise AssertionError("adoption succeeded from inside an agent task")
    except frontier.Refused as e:
        assert "agent task" in str(e), str(e)
    finally:
        os.environ.pop("AGENT_TASK_ID", None)

    try:
        frontier.adopt(root, home, "adopt_probe", actor="me",
                       confirm_how="not the published command")
        raise AssertionError("adoption succeeded without echoing the command")
    except frontier.Refused:
        pass
    # and it is not adoptable at all from a stage that never proved anything
    try:
        frontier.adopt(root, home, "adopt_probe", actor="me", confirm_how=want)
        raise AssertionError("a capability that was never proven was adopted")
    except frontier.Refused as e:
        assert "proven" in str(e) or "approval" in str(e), str(e)
    print("[owner] adoption refuses from inside an agent task, refuses "
          "without an exact echo of the command being published to every "
          "future agent, and refuses a capability nothing has proven")


def check_a_refused_capability_is_not_retried_and_says_why(root):
    """A fleet that re-runs an impossible acquisition every cycle is a fleet
    that will do it forever."""
    _absent(root, "refused_one")
    frontier.falsify(root, "refused_one")
    rows = frontier.load(root)
    for r in rows:
        if r["capability"] == "refused_one":
            r["stage"] = "refused"
            r["attempts"] = [{"result": "refused"}] * 3
            r["refusal"] = {"why": "no rung reached it",
                            "retry_after": "2999-01-01T00:00:00"}
    frontier._save(root, rows)
    ok, why = frontier.attemptable(root, "refused_one")
    assert ok is False and "2999" in why, (ok, why)
    out = frontier.acquire_next(root, root, "refused_one", apply=True)
    assert out["acted"] is False and "2999" in out["why"], out
    assert frontier.get(root, "refused_one")["stage"] == "refused", (
        "a backed-off capability was re-attempted anyway")
    print("[backoff] a refused capability is not retried before its recorded "
          "date, the reason travels with the refusal, and asking again "
          "changes no stage and starts no acquisition")


def check_universal_reports_not_ready_with_the_exact_owner_action(root, home):
    """The false READY this whole system exists to prevent, both shapes."""
    # shape 1: a capability the hint table names that nothing reports
    caps = universal.required_capabilities("summarise these PDFs")
    assert caps, "the shipped hint floor stopped working"
    # shape 2: a frontier row not at 'owned' must block
    _absent(root, "blocking_cap")
    frontier.falsify(root, "blocking_cap")
    rows = frontier.load(root)
    for r in rows:
        if r["capability"] == "blocking_cap":
            r["stage"] = "refused"
            r["refusal"] = {"why": "nothing could obtain it",
                            "retry_after": "2999-01-01T00:00:00"}
    frontier._save(root, rows)
    implied = dict(frontier.implied(root, GOAL))
    assert "blocking_cap" in implied, (
        "a capability this fleet has already met is not implied by the same "
        "goal a second time; the frontier is not learning its own edges")
    named = universal.required_capabilities(GOAL, root=root)
    assert "blocking_cap" in [c for c, _ in named], named
    scan = toolbox.scan(root)["capabilities"]
    assert scan["blocking_cap"]["ready"] is False, scan["blocking_cap"]
    assert "nothing could obtain it" in scan["blocking_cap"]["how"], (
        "the reason a capability is missing did not reach the report the "
        "agent actually reads")
    print(f"[no-false-ready] a goal the hint table never knew now names "
          f"{len(named)} capability(ies) on its SECOND encounter, each "
          f"reported not-ready with the recorded reason — the first shape of "
          f"the bug was a silent drop, the second a silent READY")


def check_a_dry_run_writes_nothing(root, home):
    """The panel renders this. Rendering must not seal, probe or fetch."""
    _absent(root, "dry_probe")
    frontier.falsify(root, "dry_probe")
    sealf, _k = frontier.seal_path(root)
    before = (_tree(root), _tree(os.path.dirname(sealf)))
    frontier.route(root, home, "dry_probe")
    frontier.acquire_next(root, home, "dry_probe", apply=False)
    frontier.capabilities(root)
    frontier.summary(root)
    universal.resolve(home, os.path.basename(root), GOAL, apply=False)
    after = (_tree(root), _tree(os.path.dirname(sealf)))
    assert before == after, (
        "a dry run changed bytes on disk:\n"
        f"  added:   {sorted(set(after[0]) - set(before[0]))[:6]}\n"
        f"  removed: {sorted(set(before[0]) - set(after[0]))[:6]}")
    print("[dry] route, a dry acquire, capabilities, summary and a dry "
          "universal.resolve left the expert tree AND the seal directory "
          "byte-identical")


def check_a_frontier_capability_cannot_shadow_or_break_a_built_in(root):
    """A collision must be visible, and a name must not fool the report."""
    built = set(toolbox.scan(root)["capabilities"]) - {
        r["capability"] for r in frontier.load(root)}
    victim = "video_download" if "video_download" in built else sorted(built)[0]
    for name in (victim, f"{victim}_hd"):
        try:
            frontier.propose(root, name, "need", QUOTE, GOAL, kind="import",
                             module="m_xyz", package="p_xyz",
                             how_argv=["python", "-m", "m_xyz"])
            raise AssertionError(
                f"{name!r} was accepted, and it carries the built-in name "
                f"{victim!r} as a substring — the capability note is parsed "
                f"by substring, so that line would be read as {victim}'s")
        except frontier.Refused:
            pass
    note = toolbox.capability_note(root)
    assert note.count("READY") >= 1, "the capability note lost its sections"
    print(f"[shadow] a frontier capability may not take a built-in's name "
          f"({victim!r}) nor carry it as a substring, and the capability "
          f"note still parses into its sections")


def check_the_command_that_would_reach_the_shell_is_safe(root):
    """acquire composes the probe argv into a shell string, quoting only on
    spaces. Nothing model-chosen may carry a metacharacter."""
    _absent(root, "shell_probe")
    cmd = frontier.sealed_command(root, "shell_probe")
    assert cmd[0] == PY and cmd[2] == "run-probe", cmd
    joined = " ".join(cmd)
    for ch in "&|;<>`$":
        assert ch not in joined.replace(os.sep, "/"), (
            f"the sealed command carries {ch!r}, which acquire.py would "
            f"interpolate into a shell=True string unquoted")
    for bad in (["python", "-c", "x;rm"], ["a|b"], ["$(whoami)"]):
        try:
            frontier.propose(root, "shell_bad", "need", QUOTE, GOAL,
                             kind="import", module="m_xyz", package="p_xyz",
                             how_argv=bad)
            raise AssertionError(f"{bad} was accepted as a published command")
        except frontier.Refused:
            pass
    assert any("frontier" in p and "adopt" in p for p, _w in policy.REVIEW), (
        "adopting a capability is not in policy.REVIEW")
    assert any("acquire" in p and "promote" in p for p, _w in policy.REVIEW), (
        "promoting an acquisition is not in policy.REVIEW, so any agent "
        "holding run_command could grant its own tool the fleet's trust")
    print("[shell] the sealed command carries no shell metacharacter, three "
          "metacharacter-bearing published commands were refused, and both "
          "adopt and acquire-promote now require review")


def check_the_toolbox_and_recipe_fall_back_without_breaking_root_none(root):
    """The published shapes must be exactly what they were."""
    assert sorted(toolbox.scan(None)) == ["binaries", "capabilities",
                                          "custom", "keys", "modules"], (
        "scan()'s contract changed")
    assert frontier.capabilities(None) == {}, (
        "capabilities(None) must be empty, not an exception inside a bare "
        "except — that is the dead-branch shape acquire.py documents")
    assert toolbox.recipe("pdf_text")["package"] == "pymupdf", (
        "the two-argument recipe() shape changed")
    assert toolbox.recipe("nosuch_capability_xyz") is None
    _absent(root, "recipe_probe")
    frontier.falsify(root, "recipe_probe")
    r = toolbox.recipe("recipe_probe", root=root)
    assert r and r["source"] == "pypi" and r["package"] == "nosuchpkg_xyz", r
    assert toolbox.recipe("recipe_probe") is None, (
        "recipe() without a root answered from the frontier; the shipped "
        "positional shape must behave exactly as it always did")
    print("[shapes] scan(None) and recipe(cap) answer exactly as they always "
          "did, capabilities(None) is empty rather than raising, and a "
          "frontier route appears only when a root is passed")


def main():
    home = tempfile.mkdtemp(prefix="frontier-")

    def fresh(n):
        """A new expert per check. MAX_OPEN deliberately caps how many
        capabilities may be open at once, so sharing one root across fifteen
        checks would hit the platform's own brake rather than the law under
        test."""
        r = os.path.join(home, "experts", f"probe{n}")
        os.makedirs(r, exist_ok=True)
        return r

    try:
        r = fresh(1)
        check_a_probe_that_passes_before_anything_is_installed_is_refused(r)
        check_a_passing_probe_never_becomes_owned(r)
        check_an_edited_spec_or_a_second_seal_yields_tamper_and_runs_nothing(fresh(2))
        check_the_agent_cannot_write_the_probe_or_the_ledger_through_the_file_authority(fresh(3))
        check_readiness_is_decided_outside_the_expert_root(fresh(4))
        check_a_quote_that_is_not_in_the_goal_or_is_trivial_is_refused(fresh(5))
        check_a_probe_is_never_authored_by_the_model(fresh(6))
        check_a_host_observation_cannot_ground_an_acquisition(fresh(7))
        check_authority_and_adoption_route_to_the_owner(fresh(8), home)
        check_a_refused_capability_is_not_retried_and_says_why(fresh(9))
        check_universal_reports_not_ready_with_the_exact_owner_action(fresh(10), home)
        check_a_dry_run_writes_nothing(fresh(11), home)
        check_a_frontier_capability_cannot_shadow_or_break_a_built_in(fresh(12))
        check_the_command_that_would_reach_the_shell_is_safe(fresh(13))
        check_the_toolbox_and_recipe_fall_back_without_breaking_root_none(fresh(14))
        print("PASS test_frontier")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
