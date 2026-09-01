#!/usr/bin/env python3
"""METRICS — the twelve numbers that say whether any of this is working.

Manual §29 names twelve. This module computes the ones the platform's own
ledgers can answer and **refuses to invent the rest**, which is the whole
point: a dashboard where every tile has a number is a dashboard where you
cannot tell measurement from decoration.

    python metrics.py                       # the fleet
    python metrics.py --expert cardio-consultant
    python metrics.py --json

Every figure is READ from a ledger some other subsystem already writes:

  competence      memory.competence      verified successes / gated attempts
  failures        memory.failure_summary the false-success count
  cases           cases.stats            did the fix hold?
  spend           modelgateway           per-call cost, purpose and model
  missions        mission.list_missions  actions bound to criteria; blockers
  acquisitions    acquire.load           the capability ladder
  exams           selfmodel.study        held-out scores and sittings
  confidence      logs/agent.log         the predicted band vs what happened

Nothing is computed twice. Two counts of the same thing eventually disagree,
and then nobody knows which to believe.

WHAT THIS MODULE WILL NOT DO
----------------------------
Three of §29's metrics cannot be computed here, and each says so by name
rather than being quietly dropped:

  * **Verified output / supervision-hour** — the denominator is a human's
    time, which this platform has no way to observe. It would have to be
    logged by the person, and a number nobody logs is a number nobody should
    read.
  * **Retention at 7/30/90 days** — the platform records every exam sitting,
    but a build whose longest observation is a test run has no 30-day
    interval to report. The structure is here; the elapsed time is not.
  * **Autonomy ratio, honestly** — what IS computed is "tasks that finished
    without blocking on a person". A pre-authorised policy decision is not
    distinguishable in the record from no decision at all, so the figure is
    an upper bound and is labelled as one.
"""

import json
import os
import re
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

# A rate over too few observations is noise wearing a percentage sign.
MIN_SAMPLE = 5


def _pct(num, den):
    return None if not den else round(num / den, 4)


def _experts(home):
    try:
        import fleet
        return fleet.list_experts(home)
    except Exception:
        return []


def _tasks(root):
    try:
        with open(os.path.join(root, "state.json"), encoding="utf-8") as f:
            return json.load(f).get("tasks", [])
    except (OSError, ValueError):
        return []


# ------------------------------------------------------------------ metrics

def _gated(home, slug=None):
    """Every GATE-JUDGED attempt, from one ledger, in one pass.

    Both headline reliability numbers are derived from this, so they share a
    denominator by construction. They did not, at first: competence counts
    tasks and the failure ledger counts events, so a task that was retried
    twice produced three false-success records against one competence
    attempt — and the two rates could sum past 100%. Two counts of the same
    thing eventually disagree, which is the sentence at the top of this file.

    Returns (judged, passed, claims, refused):
      judged   tasks that carried a definition of done and finished
      passed   of those, the ones a gate accepted
      claims   every time an agent said "finished" on a gated task
      refused  of those claims, the ones the gate threw back
    """
    judged = passed = claims = refused = 0
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        for t in _tasks(e["root"]):
            if not t.get("done_check") or t.get("status") not in ("done", "failed"):
                continue
            judged += 1
            rejects = int(t.get("done_rejects") or 0)
            refused += rejects
            claims += rejects
            if t.get("status") == "done":
                passed += 1
                claims += 1          # the one claim the gate accepted
    return judged, passed, claims, refused


def verified_success(home, slug=None):
    """VSR — the fraction of gated tasks that a gate actually passed.

    "Gated" is the load-bearing word: a task with no done-check is not
    counted, because nothing independent ever said whether it worked.
    """
    judged, passed, _claims, _refused = _gated(home, slug)
    return {"metric": "Verified Success Rate",
            "value": _pct(passed, judged), "numerator": passed,
            "denominator": judged, "enough": judged >= MIN_SAMPLE,
            "means": "of the tasks that carried a definition of done, this "
                     "fraction passed it",
            "source": "state.json (done_check + status)"}


def false_success(home, slug=None):
    """FSR — it said done, and an independent gate said otherwise.

    Manual §29 calls this "a primary reliability metric", and it is the one
    number a model cannot flatter: the claim and the verdict are recorded by
    different code. Counted per CLAIM rather than per task, because a task
    that eventually passed after three refusals made three false claims and
    hiding them would flatter exactly the thing this measures.
    """
    _judged, _passed, claims, refused = _gated(home, slug)
    return {"metric": "False-Success Rate",
            "value": _pct(refused, claims), "numerator": refused,
            "denominator": claims, "enough": claims >= MIN_SAMPLE,
            "means": "of the times an agent said it had finished a gated "
                     "task, this fraction was thrown back by the gate",
            "source": "state.json (done_rejects)"}


def recovery(home, slug=None):
    """The fraction of failed tasks that a retry eventually rescued.

    Read from the task lineage: a retry names the attempt it follows, so a
    failure whose retry finished is a recovery and one whose retries all
    failed is not.
    """
    rescued = lost = 0
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        tasks = _tasks(e["root"])
        follows = {}
        for t in tasks:
            m = re.search(r"the previous attempt \(([0-9a-f]+)\)",
                          t.get("goal", ""))
            if m:
                follows.setdefault(m.group(1), []).append(t)
        for t in tasks:
            if t.get("status") != "failed":
                continue
            chain, seen = list(follows.get(t["id"], [])), set()
            done = False
            while chain:
                nxt = chain.pop()
                if nxt["id"] in seen:
                    continue
                seen.add(nxt["id"])
                if nxt.get("status") == "done":
                    done = True
                    break
                chain.extend(follows.get(nxt["id"], []))
            # only count originals, not the retries themselves
            if re.match(r"RETRY \d+ of", t.get("goal", "")):
                continue
            rescued += 1 if done else 0
            lost += 0 if done else 1
    n = rescued + lost
    return {"metric": "Recovery Rate",
            "value": _pct(rescued, n), "numerator": rescued, "denominator": n,
            "enough": n >= MIN_SAMPLE,
            "means": "of the tasks that failed, this fraction was rescued by "
                     "a retry without anybody being asked",
            "source": "state.json task lineage"}


def goal_fidelity(home, slug=None):
    """Manual §11: every action must reference an unresolved criterion.

    So fidelity is simply how much of the recorded work is bound — an action
    that serves no criterion is busy work, and busy work is how a long
    mission burns a budget while going nowhere.
    """
    import mission
    bound = total = 0
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        for st in mission.list_missions(e["root"]):
            for a in (mission.load(e["root"], st["id"]) or {}).get("actions", []):
                total += 1
                bound += 1 if a.get("criterion") else 0
    return {"metric": "Goal Fidelity",
            "value": _pct(bound, total), "numerator": bound,
            "denominator": total, "enough": total >= MIN_SAMPLE,
            "means": "of the actions taken under a mission, this fraction "
                     "names the success criterion it serves",
            "source": "mission actions"}


def _events_by_task(home, slug=None, kinds=()):
    """Which tasks emitted which of these events. Read once, reused."""
    hit = {k: set() for k in kinds}
    finished = {}
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        p = os.path.join(e["root"], "logs", "agent.log")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.search(r"(\{.*\})\s*$", line)
                    if not m:
                        continue
                    try:
                        ev = json.loads(m.group(1))
                    except ValueError:
                        continue
                    tid, kind = ev.get("task"), ev.get("event")
                    if not tid:
                        continue
                    if kind in hit:
                        hit[kind].add(tid)
                    if kind == "task_end":
                        finished[tid] = ev.get("status")
        except OSError:
            continue
    return hit, finished


def autonomy(home, slug=None):
    """An UPPER BOUND on the autonomy ratio, and labelled as one.

    §29 wants "completed without human intervention other than pre-authorised
    policy decisions". A task record does not carry a marker for having been
    blocked — a task that stopped, was answered and then finished ends up
    indistinguishable from one that never stopped — so this reads the LOG,
    where `approval_required` and `task_unblocked` are written at the moment
    a person was needed.

    It remains an upper bound for the reason §29 anticipates: a
    pre-authorised policy decision looks the same in the record as no
    decision at all.
    """
    hit, finished = _events_by_task(
        home, slug, ("approval_required", "task_unblocked"))
    needed = hit["approval_required"] | hit["task_unblocked"]
    total = len(finished)
    alone = sum(1 for tid in finished if tid not in needed)
    return {"metric": "Autonomy Ratio (upper bound)",
            "value": _pct(alone, total), "numerator": alone,
            "denominator": total, "enough": total >= MIN_SAMPLE,
            "means": "of the tasks that finished, this fraction never asked a "
                     "person for anything. An upper bound: a pre-authorised "
                     "decision looks the same as no decision in the record",
            "source": "logs/agent.log (approval_required, task_unblocked)",
            "also": (f"{len(needed)} task(s) needed a person"
                     if needed else "no task has needed a person yet")}


def interruptions(home, slug=None):
    """How often a mission needs the owner. Not a rate — a count per mission,
    because the question is 'how much of my attention does this cost'."""
    import mission
    needs = missions = 0
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        for st in mission.list_missions(e["root"]):
            missions += 1
            needs += len(st.get("needs_human") or [])
    return {"metric": "Human interruptions per mission",
            "value": round(needs / missions, 3) if missions else None,
            "numerator": needs, "denominator": missions,
            "enough": missions >= 1,
            "means": "blockers that route to the owner, per mission — the "
                     "ones that cannot be solved by trying harder",
            "source": "mission blockers", "unit": "count"}


def cost_per_verified(home, slug=None):
    """The number that decides whether any of this is worth running."""
    import modelgateway
    spent = 0.0
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        try:
            spent += modelgateway.summary(e["root"])["total"]["cost_usd"]
        except Exception:
            pass
    vsr = verified_success(home, slug)
    ok = vsr["numerator"]
    return {"metric": "Cost per verified task",
            "value": round(spent / ok, 6) if ok else None,
            "numerator": round(spent, 6), "denominator": ok,
            "enough": ok >= MIN_SAMPLE,
            "means": "provider spend divided by tasks that passed a gate — "
                     "spend on work that failed is still spend",
            "source": "modelgateway ledger",
            "unit": "USD"}


def repeat_failure(home, slug=None):
    """A failure that comes back after a fix is the one worth your attention;
    the rest the platform handles itself."""
    import cases
    recurred = solved = total = 0
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        st = cases.stats(e["root"])
        recurred += st.get("recurred", 0)
        solved += st.get("solved", 0)
        total += st.get("total", 0)
    return {"metric": "Repeat-failure rate",
            "value": _pct(recurred, total), "numerator": recurred,
            "denominator": total, "enough": total >= MIN_SAMPLE,
            "means": "of the failures somebody fixed, this fraction came back",
            "source": "cases ledger",
            "also": f"{solved} of {total} case(s) solved"}


def acquisition(home, slug=None):
    """Manual §12's ladder, as a number: how much of what was requested was
    actually acquired, tested and trusted."""
    import acquire
    stages = {}
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        for row in acquire.load(e["root"]):
            stages[row["stage"]] = stages.get(row["stage"], 0) + 1
    asked = sum(stages.values())
    got = stages.get("trusted", 0) + stages.get("tested", 0)
    return {"metric": "Tool acquisition success",
            "value": _pct(got, asked), "numerator": got, "denominator": asked,
            "enough": asked >= 1,
            "means": "of the capabilities an agent asked for, this fraction "
                     "passed a capability test — an install that was never "
                     "tested does not count",
            "source": "acquisitions ledger", "by_stage": stages}


def calibration(home, slug=None):
    """Do the confidence bands predict anything?

    The loop writes a `low_confidence` event with its predicted band before
    the outcome is known, and a `task_end` with the outcome. Joining them on
    the task id is the only honest way to ask whether the number means
    anything — a confidence score that does not track success is a number
    that costs compute and buys nothing.
    """
    bands = {}
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        pred, done = {}, {}
        p = os.path.join(e["root"], "logs", "agent.log")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.search(r"(\{.*\})\s*$", line)
                    if not m:
                        continue
                    try:
                        ev = json.loads(m.group(1))
                    except ValueError:
                        continue
                    if ev.get("event") == "low_confidence" and ev.get("task"):
                        pred[ev["task"]] = ev.get("band")
                    elif ev.get("event") == "task_end" and ev.get("task"):
                        done[ev["task"]] = ev.get("status")
        except OSError:
            continue
        for tid, band in pred.items():
            if tid not in done:
                continue
            b = bands.setdefault(band, {"n": 0, "done": 0})
            b["n"] += 1
            b["done"] += 1 if done[tid] == "done" else 0
    rows = {b: {**v, "success": _pct(v["done"], v["n"])}
            for b, v in sorted(bands.items())}
    n = sum(v["n"] for v in bands.values())
    ordered = [rows[b]["success"] for b in ("low", "medium", "high")
               if b in rows and rows[b]["success"] is not None]
    monotone = all(a <= b for a, b in zip(ordered, ordered[1:])) \
        if len(ordered) > 1 else None
    return {"metric": "Calibration",
            "value": monotone, "numerator": n, "denominator": n,
            "enough": n >= MIN_SAMPLE,
            "means": "whether a higher predicted confidence band actually "
                     "succeeded more often. True/False, not a rate — and None "
                     "when fewer than two bands have been observed",
            "source": "low_confidence + task_end events", "bands": rows,
            "note": (f"{len(rows)} band(s) observed"
                     if len(rows) < 2 else
                     "bands: " + ", ".join(
                         f"{b} {v['success']:.0%} over {v['n']}"
                         for b, v in rows.items() if v["success"] is not None))}


def harness_contribution(home, slug=None):
    """Manual §14 — what the fleet caught that a bare model would have shipped.

    §14 sets a product target: *"verified useful output per dollar and per
    human-supervision hour versus the same raw model without the fleet."*

    **This is NOT that number, and does not pretend to be.** The comparison
    §14 asks for needs the same work run twice — once through this harness and
    once against the raw model — and the second half has never been run here.
    Reporting a multiplier without the baseline would be the single most
    flattering thing this codebase could print.

    What CAN be counted, from events the loop already writes, is the harness's
    *observable* contribution: the specific moments where something the fleet
    does changed the outcome. Each row below is a count of a real event, and
    each says what a bare model would have done instead.
    """
    seen = {}
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        p = os.path.join(e["root"], "logs", "agent.log")
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.search(r'"event":\s*"([a-z_]+)"', line)
                    if m:
                        seen[m.group(1)] = seen.get(m.group(1), 0) + 1
        except OSError:
            continue
    _judged, passed, _claims, refused = _gated(home, slug)
    levers = [
        {"lever": "Verification",
         "count": refused,
         "instead": "a bare model would have returned each of these as "
                    "finished work"},
        {"lever": "Retry with the failure in hand",
         "count": seen.get("retry_queued", 0),
         "instead": "a bare model would have stopped, or repeated the same "
                    "attempt with the same information"},
        {"lever": "Escalation to a stronger model on doubt",
         "count": seen.get("escalated", 0),
         "instead": "a bare model has one setting and spends the same on a "
                    "trivial task and a hard one"},
        {"lever": "Institutional memory (gotchas filed)",
         "count": seen.get("gotcha_filed", 0),
         "instead": "a bare model meets every environment failure for the "
                    "first time, every time"},
        {"lever": "Recognised a failure it had seen before",
         "count": seen.get("failure_recurred", 0),
         "instead": "a bare model cannot recognise a repeat, because it has "
                    "no record of the first"},
        {"lever": "Refused an unsafe or out-of-policy command",
         "count": seen.get("command_refused", 0),
         "instead": "a bare model with a shell would have run it"},
        {"lever": "Stopped for a human on an irreducible decision",
         "count": seen.get("approval_required", 0),
         "instead": "a bare model would have guessed and continued"},
        {"lever": "Stopped at a declared spend ceiling",
         "count": seen.get("budget_exceeded", 0)
                  + seen.get("task_cost_ceiling", 0),
         "instead": "a bare model has no ceiling and no idea what it has "
                    "spent"},
        {"lever": "Survived a crash mid-task and resumed",
         "count": seen.get("step_crash", 0),
         "instead": "a bare model's run ends with the process"},
        {"lever": "Closed a case: the fix held",
         "count": seen.get("case_fixed", 0),
         "instead": "a bare model does not know whether last week's fix "
                    "worked"},
    ]
    total = sum(l["count"] for l in levers)
    return {
        "metric": "Harness contribution (NOT the §14 multiplier)",
        # deliberately not a rate: dividing interventions by completions
        # would produce a number that looks like a multiplier and is not one
        "value": None, "unit": "narrative",
        "numerator": total, "denominator": passed,
        "enough": total >= MIN_SAMPLE,
        "means": (f"{total} recorded interventions across {len(levers)} "
                  f"levers, against {passed} verified completions. This is "
                  f"what the fleet DID, not what it was worth"),
        "source": "logs/agent.log events + state.json",
        "levers": levers,
        "not_the_multiplier": (
            "§14 defines the multiplier as verified output per dollar versus "
            "the SAME raw model without the fleet. That comparison needs the "
            "same work run twice, and the baseline half has never been run "
            "here. These counts say what the harness did; they say nothing "
            "about what it was worth, and no arithmetic on them yields a "
            "multiplier."),
    }


def _family_of(task):
    return (task.get("family") or task.get("course")
            or task.get("task_class") or "general")


def amortization(home, slug=None):
    """THE LEARNING CLAIM, AS A NUMBER: does the second encounter with a
    family of work cost less than the first?

    This is the objective the whole architecture is pointed at — expensive
    reasoning on novel work, converging on cheap deterministic execution once
    the work is understood — and until now nothing measured it. A system that
    accumulates knowledge without this number can only assert that it is
    learning.

    Method: gated tasks that a gate PASSED, grouped by family, in the order
    they were created, split into an earlier and a later half. The ratio is
    earlier-mean / later-mean, so a value above 1 means the later work was
    cheaper. Families with fewer than 2*MIN_HALF verified successes are not
    split at all — half of two tasks is one task, and one task is an anecdote.

    THE UNIT IS MODEL STEPS, not dollars, and that is deliberate. Steps are
    observed for every task on every provider; spend is only observed when
    the provider carries prices, and a free or mock provider reports 0.0,
    which would make every ratio either 1.0 or a division by zero. Spend is
    reported ALONGSIDE, and is None when nothing was metered rather than 0 —
    an unmeasured cost is not a free one.

    What it cannot tell you: whether the later tasks were EASIER. Families
    group by name, not by difficulty, so a ratio above 1 is evidence of
    cheaper work on similar-shaped tasks, not proof of transfer. That is why
    `deterministic_share` is reported separately: a verified success that took
    zero model steps is the one case where cheapness is not a judgement call.
    """
    MIN_HALF = 3
    families, det_runs, det_total = {}, 0, 0
    metered = False
    for e in _experts(home):
        if slug and e["name"] != slug:
            continue
        rows = sorted(_tasks(e["root"]),
                      key=lambda t: (t.get("created") or "", t.get("id") or ""))
        for t in rows:
            if not t.get("done_check") or t.get("status") != "done":
                continue          # only VERIFIED work — a cheap failure is
            fam = _family_of(t)   # not a saving
            steps = len(t.get("steps") or [])
            try:
                cost = float(t.get("cost_usd") or 0)
            except (TypeError, ValueError):
                cost = 0.0
            metered = metered or cost > 0
            families.setdefault(fam, []).append({"steps": steps, "cost": cost})
            det_total += 1
            if t.get("procedure_routed"):
                det_runs += 1

    per_family, ratios = [], []
    for fam, rows in sorted(families.items()):
        row = {"family": fam, "verified": len(rows), "split": False}
        if len(rows) >= 2 * MIN_HALF:
            half = len(rows) // 2
            early, late = rows[:half], rows[half:]
            e_steps = sum(r["steps"] for r in early) / len(early)
            l_steps = sum(r["steps"] for r in late) / len(late)
            row.update(
                split=True,
                early_steps=round(e_steps, 3), later_steps=round(l_steps, 3),
                step_ratio=(round(e_steps / l_steps, 3) if l_steps else None),
                cheaper=(l_steps < e_steps))
            if l_steps:
                ratios.append(e_steps / l_steps)
            elif e_steps:
                row["step_ratio"] = None
                row["note"] = ("later work took zero model steps — the ratio "
                               "is unbounded, which is the intended end state "
                               "and not a number to average")
            if metered:
                e_cost = sum(r["cost"] for r in early) / len(early)
                l_cost = sum(r["cost"] for r in late) / len(late)
                row.update(early_cost_usd=round(e_cost, 6),
                           later_cost_usd=round(l_cost, 6),
                           cost_ratio=(round(e_cost / l_cost, 3)
                                       if l_cost else None))
        per_family.append(row)

    split = [r for r in per_family if r["split"]]
    value = round(sum(ratios) / len(ratios), 3) if ratios else None
    return {"metric": "Amortization (earlier / later model steps per "
                      "verified success)",
            "value": value,
            "numerator": len(split), "denominator": len(per_family),
            "enough": len(split) >= 1 and len(ratios) >= 1,
            "means": "above 1.0 means repeated work of the same shape now "
                     "costs fewer model steps; families are grouped by name, "
                     "so this is evidence of cheaper work on similar tasks, "
                     "not proof of transfer",
            "source": "state.json task ledger (verified, gated tasks only)",
            # A RATIO, NOT A RATE. Without this the panel's fallthrough branch
            # rendered 2.0 as "200%", which reads as a success rate going
            # impossibly well rather than "half the model steps it used to
            # take". Both renderers key on this.
            "unit": "ratio",
            "also": (f"{det_runs} of {det_total} verified success(es) used a "
                     f"proven procedure and took no model step at all"),
            "deterministic_share": _pct(det_runs, det_total),
            "spend_measured": metered or None,
            "spend_note": (None if metered else
                           "no task carried a metered cost, so the dollar "
                           "ratio is NOT MEASURED — not zero"),
            "families": per_family}


# ------------------------------------------------------ the ones we will not

NOT_MEASURABLE = [
    {"metric": "Verified output per supervision-hour",
     "why": "the denominator is a person's time, which this platform cannot "
            "observe. It would have to be logged by hand, and a number "
            "nobody logs is a number nobody should read"},
    {"metric": "Retention at 7 / 30 / 90 days",
     "why": "every exam sitting is recorded with its date, so the structure "
            "is here — but the longest observation this build has is a test "
            "run. Come back in ninety days"},
    {"metric": "The §14 \"100x\" multiplier",
     "why": "defined as verified output per dollar versus the SAME raw model "
            "without the fleet. That needs the same work run twice and the "
            "baseline half has never been run. What IS reported is the "
            "harness's observable contribution — what it did, not what it "
            "was worth — and no arithmetic on those counts yields a "
            "multiplier"},
    {"metric": "Safety violations per 1000 tasks",
     "why": "not in §29's list, and deliberately not invented here: every "
            "refusal this platform records is a control WORKING. A count of "
            "refusals is not a count of violations, and reporting it as one "
            "would be the most flattering possible mistake"},
]

ALL = (verified_success, false_success, recovery, goal_fidelity, autonomy,
       interruptions, cost_per_verified, repeat_failure, acquisition,
       calibration, harness_contribution, amortization)


def report(home, slug=None):
    rows = []
    for fn in ALL:
        try:
            rows.append(fn(home, slug))
        except Exception as e:                    # a missing ledger is zero,
            rows.append({"metric": fn.__name__,   # not a crash
                         "value": None, "numerator": 0, "denominator": 0,
                         "enough": False, "error": str(e)[:120],
                         "means": "", "source": ""})
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "scope": slug or "the whole fleet",
            "min_sample": MIN_SAMPLE,
            "metrics": rows,
            "not_measurable": NOT_MEASURABLE,
            "caveat": "Every model call recorded here ran against the "
                      "scripted mock provider unless a real key was "
                      "configured. These numbers describe the harness, not "
                      "any provider's intelligence."}


def render(rep):
    out = [f"METRICS — {rep['scope']}", ""]
    for r in rep["metrics"]:
        v = r.get("value")
        if v is None:
            shown = ("—" if r.get("unit") == "narrative"
                     else "not yet" if r.get("note") else "no data")
        elif isinstance(v, bool):
            shown = "holds" if v else "DOES NOT HOLD"
        elif r.get("unit") == "USD":
            shown = f"${v:,.4f}"
        elif r.get("unit") == "count":
            shown = f"{v:g}"
        elif r.get("unit") == "ratio":
            shown = f"{v:.2f}x"          # never a percentage
        elif r["denominator"] and r["numerator"] is not None \
                and isinstance(v, float) and v <= 1:
            shown = f"{v:.1%}"
        else:
            shown = str(v)
        mark = "" if r.get("enough") else "  (too few to mean anything)"
        out.append(f"  {r['metric']:<34} {shown:>12}"
                   f"   {r['numerator']}/{r['denominator']}{mark}")
        if r.get("means"):
            out.append(f"      {r['means']}")
        if r.get("note"):
            out.append(f"      {r['note']}")
        if r.get("also"):
            out.append(f"      {r['also']}")
        for l in r.get("levers", []):
            if l["count"]:
                out.append(f"        {l['count']:>5}  {l['lever']}")
                out.append(f"               instead: {l['instead']}")
        if r.get("not_the_multiplier"):
            out.append(f"      {r['not_the_multiplier']}")
        if r.get("error"):
            out.append(f"      unavailable: {r['error']}")
        out.append("")
    out.append("NOT MEASURED HERE, and why:")
    for r in rep["not_measurable"]:
        out.append(f"  {r['metric']}")
        out.append(f"      {r['why']}")
    out.append("")
    out.append(rep["caveat"])
    return "\n".join(out)


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--home", default=".")
    ap.add_argument("--expert", default=None,
                    help="one expert's slug (default: the whole fleet)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    rep = report(os.path.abspath(a.home), a.expert)
    print(json.dumps(rep, indent=1) if a.json else render(rep))


if __name__ == "__main__":
    main()
