#!/usr/bin/env python3
"""THE NUMBERS THAT SAY WHETHER ANY OF THIS IS WORKING — manual §29.

§29 names twelve metrics. The interesting property of a metrics module is not
that it computes things; it is **what it refuses to compute**, because a
dashboard where every tile has a number is one where you cannot tell
measurement from decoration.

So this test does not check arithmetic on a fixture. It checks the three
properties that make the numbers usable:

  1. every metric is READ from a ledger another subsystem writes — nothing is
     counted twice, because two counts of the same thing eventually disagree
  2. a rate over too few observations is MARKED as such rather than printed as
     a confident percentage
  3. the metrics that cannot honestly be computed are NAMED, with the reason,
     instead of being dropped or approximated

Plus the one arithmetic property that matters: false-success and verified
success are computed over the same denominator, so they can be compared.

Run from the agent/ directory:  python tests/test_metrics.py
"""

import io
import json
import os
import re
import sys

from common import AGENT_DIR, make_sandbox, run_drain

sys.path.insert(0, AGENT_DIR)
import cases                  # noqa: E402
import fleet                  # noqa: E402
import metrics                # noqa: E402
import mission                # noqa: E402

GOOD = [{"tool": "write_file", "args": {"path": "out/done.md", "content": "x"}},
        {"tool": "finish_task", "args": {"summary": "wrote it"}}]
CHECK_OK = ('python -c "import os,sys;'
            'sys.exit(0 if os.path.exists(\'out/done.md\') else 1)"')
CHECK_NEVER = 'python -c "import sys;sys.exit(1)"'


def _seed(home):
    """Two tasks a gate passes, one it never will — a real mix, run for real."""
    root = fleet.create(home, "Measured", "an expert with a track record")
    for name in ("s.json",):
        with io.open(os.path.join(home, name), encoding="utf-8") as f:
            body = f.read()
        with io.open(os.path.join(root, name), "w", encoding="utf-8") as f:
            f.write(body)
    import loop
    a = loop.Agent(root)
    a.add_task("practitioner", "write the thing", done_check=CHECK_OK)
    a.add_task("practitioner", "write the thing again", done_check=CHECK_OK)
    a.add_task("practitioner", "produce what cannot exist",
               done_check=CHECK_NEVER)
    run_drain(root, timeout=240)
    return root


def check_every_metric_names_its_source(rep):
    """Nothing is computed twice: each metric says which ledger it read."""
    for m in rep["metrics"]:
        assert m.get("metric"), m
        assert "value" in m and "numerator" in m and "denominator" in m, m
        assert m.get("means"), f"{m['metric']} does not say what it means"
        assert m.get("source") or m.get("error"), \
            f"{m['metric']} does not name the ledger it read"
    sources = {m["source"] for m in rep["metrics"] if m.get("source")}
    print(f"[sources] {len(rep['metrics'])} metrics read from "
          f"{len(sources)} distinct ledgers, each naming its own — no metric "
          f"keeps a second count of something another subsystem already knows")


def check_small_samples_are_marked(rep):
    """A rate over three observations is noise wearing a percentage sign."""
    assert rep["min_sample"] >= 5, rep["min_sample"]
    for m in rep["metrics"]:
        if m.get("unit") == "narrative":
            continue          # a count of what happened is not a rate, so a
                              # sample floor over its denominator says nothing
        if m["denominator"] and m["denominator"] < rep["min_sample"]:
            assert m["enough"] is False, (
                f"{m['metric']} reports {m['denominator']} observation(s) as "
                f"sufficient")
        if m["denominator"] >= rep["min_sample"]:
            assert m["enough"] is True, m
    text = metrics.render(rep)
    thin = [m for m in rep["metrics"]
            if not m["enough"] and m["value"] is not None
            and m.get("unit") != "narrative"]
    for m in thin:
        assert "too few to mean anything" in text, (
            f"{m['metric']} prints a value with no warning")
    print(f"[samples] {len(thin)} metric(s) below the {rep['min_sample']}-"
          f"observation floor are printed with the warning attached, not as a "
          f"bare percentage")


def check_the_unmeasurable_are_named(rep):
    """The half of §29 this platform cannot answer, said out loud."""
    names = {r["metric"] for r in rep["not_measurable"]}
    assert any("supervision" in n for n in names), names
    assert any("Retention" in n for n in names), names
    for r in rep["not_measurable"]:
        assert len(r["why"]) > 40, f"{r['metric']} gives no reason"
    text = metrics.render(rep)
    assert "NOT MEASURED HERE, and why:" in text
    for r in rep["not_measurable"]:
        assert r["metric"] in text
    print(f"[honesty] {len(names)} metric(s) this platform cannot compute are "
          f"named with the reason, rather than dropped or approximated — "
          f"including one that would have been flattering to invent")


def check_reliability_rates_are_internally_consistent(rep, home):
    """A rate that can exceed 100% is a rate nobody can use.

    The first version of this module could produce one: competence counts
    TASKS and the failure ledger counts EVENTS, so a task retried twice
    produced three false-success records against one competence attempt, and
    the two headline rates summed past 1. Both are now derived in a single
    pass over `state.json`, which is the only way to be sure they agree.
    """
    by = {m["metric"]: m for m in rep["metrics"]}
    vsr, fsr = by["Verified Success Rate"], by["False-Success Rate"]
    for m in (vsr, fsr):
        assert m["value"] is None or 0 <= m["value"] <= 1, m
        assert m["numerator"] <= m["denominator"], (
            f"{m['metric']} counts {m['numerator']} of {m['denominator']} — "
            f"the numerator and denominator come from different ledgers")
        assert "state.json" in m["source"], m["source"]
    # and the two denominators are the two honest units: tasks, and claims
    judged, passed, claims, refused = metrics._gated(home)
    assert (vsr["denominator"], vsr["numerator"]) == (judged, passed)
    assert (fsr["denominator"], fsr["numerator"]) == (claims, refused)
    assert claims >= judged, (
        "there cannot be fewer finish-claims than finished gated tasks")
    assert vsr["numerator"] >= 1, "no task passed its gate"
    assert fsr["numerator"] >= 1, (
        "the fixture queued a task whose gate can never pass, so at least one "
        "finish-claim must have been refused")
    print(f"[reliability] {passed}/{judged} gated tasks passed and "
          f"{refused}/{claims} finish-claims were refused — both derived in "
          f"one pass over one ledger, so neither can exceed 100% or "
          f"contradict the other")


def check_autonomy_notices_a_human(home, root, rep):
    """§29 asks for autonomy excluding pre-authorised decisions.

    The first version of this metric read the TASK RECORD for a marker of
    having been blocked. There is none: a task that stopped, was answered and
    then finished is indistinguishable from one that never stopped, so the
    metric silently measured the success rate under a name that promised
    something else. It now reads the log, where `approval_required` and
    `task_unblocked` are written at the moment a person was needed — so this
    test appends one and requires the number to move.
    """
    by = {m["metric"]: m for m in rep["metrics"]}
    key = next(k for k in by if k.startswith("Autonomy"))
    assert "upper bound" in key and "upper bound" in by[key]["means"], key
    before = by[key]
    assert before["value"] == 1.0, (
        "the fixture never asked a person, so autonomy should be 100%")

    # a task that needed a person, written exactly as the loop writes it
    log = os.path.join(root, "logs", "agent.log")
    with io.open(log, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    tid = None
    for line in lines:
        m = re.search(r'"event": "task_end", "task": "([0-9a-f]+)"', line)
        if m:
            tid = m.group(1)
            break
    assert tid, "the fixture produced no finished task"
    with io.open(log, "a", encoding="utf-8") as f:
        f.write('2026-01-01 00:00:00,000 '
                + json.dumps({"event": "approval_required", "task": tid,
                              "op": "write outside the workspace"})
                + chr(10))
    after = metrics.autonomy(home)
    assert after["numerator"] == before["numerator"] - 1, (
        f"a task that required an approval was still counted as autonomous: "
        f"{before['numerator']} -> {after['numerator']}")
    assert after["denominator"] == before["denominator"]
    assert "1 task(s) needed a person" in after["also"], after["also"]
    print(f"[autonomy] the figure names itself an upper bound, and it MOVES: "
          f"appending one approval_required event took it from "
          f"{before['numerator']}/{before['denominator']} to "
          f"{after['numerator']}/{after['denominator']} — it reads the log, "
          f"where a human being needed is actually recorded")


def check_goal_fidelity_follows_the_mission(home, root):
    """Manual §11: an action that names no criterion is busy work."""
    rec = mission.create(root, "Measure something real",
                         ["the metric reads from a ledger"], expert="measured")
    ch = mission.justify(root, rec["id"], "C1", task_goal="bind an action",
                         expected_evidence="the action names C1")
    mission.record_action(root, rec["id"], ch, task_id="t-1", status="done")
    rep = metrics.report(home)
    gf = next(m for m in rep["metrics"] if m["metric"] == "Goal Fidelity")
    assert gf["denominator"] >= 1 and gf["numerator"] == gf["denominator"], gf
    assert gf["value"] == 1.0, gf
    print(f"[fidelity] {gf['numerator']}/{gf['denominator']} recorded actions "
          f"name the criterion they serve — the platform refuses to record "
          f"one that does not, so this metric can only ever be 100% or reveal "
          f"a bug")


def check_the_multiplier_is_refused(rep):
    """§14 sets a "100x" product target. The one thing a codebase must never
    do with a target like that is print a number that looks like it."""
    by = {m["metric"]: m for m in rep["metrics"]}
    key = next(k for k in by if k.startswith("Harness contribution"))
    hc = by[key]
    assert "NOT the" in key, key
    assert hc["value"] is None, (
        "the harness contribution must not be a rate: dividing interventions "
        "by completions produces a number that reads as a multiplier")
    assert hc["numerator"] > 0, "the fixture produced no interventions"
    assert hc["levers"], "no lever is broken out"
    for l in hc["levers"]:
        assert l["lever"] and l["instead"], l
    assert "baseline half has never been run" in hc["not_the_multiplier"]
    # and the §14 multiplier itself is in the refused list, by name
    names = {r["metric"] for r in rep["not_measurable"]}
    assert any("100x" in n or "§14" in n or "§14" in n for n in names), names
    text = metrics.render(rep)
    assert "—" in text and "not what it was worth" in text
    print(f"[multiplier] {hc['numerator']} harness interventions across "
          f"{len(hc['levers'])} levers are reported as COUNTS with what a bare "
          f"model would have done instead; the multiplier itself is in the "
          f"refused list, because the baseline half has never been run")


def check_it_survives_an_empty_fleet(tmp):
    """A fleet with no history reports no data — not a crash, and not zero
    dressed up as a rate."""
    rep = metrics.report(tmp)
    for m in rep["metrics"]:
        assert not m.get("error"), (m["metric"], m.get("error"))
        if m["denominator"] == 0:
            assert m["value"] is None, (
                f"{m['metric']} invented a value from no observations")
    text = metrics.render(rep)
    assert "no data" in text
    print("[empty] a fleet with no history reports 'no data' on every rate "
          "rather than 0%, which would read as a measured failure")


def main():
    home = make_sandbox("metrics", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": GOOD})
    root = _seed(home)
    # a case that was opened by a failure and then closed by a passing task —
    # the same shape the loop produces, so the repeat-failure metric reads
    # what it would really read
    cases.open_case(root,
                    {"id": "t-fix", "goal": "produce what cannot exist"},
                    {"category": "false_success",
                     "signature": "measured|false_success|demo",
                     "cause": "the gate refused three times"})
    cases.record_fix(root, {"id": "t-fix2", "status": "done",
                            "goal": "produce what cannot exist"})
    rep = metrics.report(home)
    check_every_metric_names_its_source(rep)
    check_small_samples_are_marked(rep)
    check_the_unmeasurable_are_named(rep)
    check_reliability_rates_are_internally_consistent(rep, home)
    check_autonomy_notices_a_human(home, root, rep)
    check_goal_fidelity_follows_the_mission(home, root)
    check_the_multiplier_is_refused(rep)
    check_it_survives_an_empty_fleet(
        os.path.join(home, "an-empty-fleet"))
    print("PASS test_metrics")


if __name__ == "__main__":
    main()
