#!/usr/bin/env python3
"""MASTERY — learn a domain, prove it on unseen work, keep it, reuse it.

THE GAP THIS CLOSES, in both external audits' words: the platform learned
INFORMATION well (sources → cited notes → closed-book exam) but never
proved PROCEDURAL COMPETENCE — a design expert is not an expert because it
scores 95% on a typography quiz; it must build something it has never seen
and pass graders it cannot touch. This module is that loop, and it is
deliberately nothing but a CONDUCTOR over primitives that already carry
their own tested laws:

    capability.py   what competence MEANS (the pack: sealed, outside the
                    student's reach — the student never writes its exam)
    contract.py     every task runs as a frozen-acceptance pursuit
    goal.py         the model works at the frontier, judged and overruled
    repair.py       failures drive grounded re-study, never reflection
    runbook.py      verified wins distill into deterministic capability
    discover.py     study sources come from curated catalogues only

THE STAGES (the audits' "Experiment B", machine-runnable):

  pretest    run the SEALED transfer tasks BEFORE any study. The baseline
             is recorded, however bad — improvement claims need a floor.
  study      per-competency: discover real sources, pursue learning goals
             (the platform's study shape: sources → cited notes → exam)
  practice   every exercise runs as a CONTRACT pursuit with the pack's
             acceptance, graded by the harness
  exam       the sealed transfer tasks, handed over ONE AT A TIME by the
             harness, each a fresh contract pursuit graded by the pack's
             validators. The student meets each task for the first time
             at the moment it is examined on it.
  diagnose   failing transfer tasks map to the competencies they examine;
             each gets targeted re-study driven by the FAILING CHECK's
             recorded evidence (LAW 1 of repair: no signal, no action)
  verdict    MASTERED / NOT MASTERED, computed ONLY from harness-run
             grader results against the pack's frozen thresholds. There
             is no code path in which anything self-declares mastery.
  distill    verified practice pursuits become runbook drafts, so the
             competence outlives the transcript that earned it
  retest     later, in a fresh context: the same sealed tasks re-run with
             new pursuit ids and no study artifacts injected — retention
             measured, not assumed.

WHAT A VERDICT MEANS, honestly: MASTERED means "passed the pack's
mechanical floor on unseen tasks". A pack's validators are a FLOOR, not
taste — that ceiling is recorded in the verdict rather than hidden, and a
domain whose excellence cannot be mechanically floored caps at what its
validators can check.

    python mastery.py run     <home> <expert> <pack> [--drive] [--skip-study]
    python mastery.py pretest <home> <expert> <pack> [--drive]
    python mastery.py exam    <home> <expert> <pack> [--drive]
    python mastery.py retest  <home> <expert> <pack> [--drive]
    python mastery.py status  <home> <expert> <pack>
"""

import argparse
import json
import os
import sys
import time
import uuid

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

MAX_RELEARN_ROUNDS = 2      # kept as run()'s `max_rounds` default only.
                            # There is no re-exam to bound: the exposure
                            # authority consumes a sealed set at the
                            # sitting that used it, so relearn_rounds is
                            # always 0 and a gap ends in fresh_pack_required.
DIR = "mastery"


class MasteryError(Exception):
    pass


# ------------------------------------------------------------------ ledger

def _dir(root, pack):
    d = os.path.join(root, DIR, str(pack))
    os.makedirs(d, exist_ok=True)
    return d


def _event(root, pack, kind, **data):
    """Append-only, under the platform lock — the same discipline as the
    contract ledger, for the same reason: this file is the evidence."""
    import locks
    p = os.path.join(_dir(root, pack), "events.jsonl")
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": str(kind)}
    row.update(data)
    with locks.holding(p, timeout=10.0, stale=8.0):
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:                  # pragma: no cover
                pass
    return row


def events(root, pack):
    out = []
    try:
        with open(os.path.join(_dir(root, pack), "events.jsonl"),
                  encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        out.append({"kind": "corrupt_line"})
    except OSError:
        pass
    return out


# ----------------------------------------------------------- running tasks

def _run_task(home, expert, pack, task, phase, drive=False, timeout=900):
    """One pack task as a full CONTRACT pursuit. The acceptance comes from
    the PACK (frozen per-pursuit, sealed like any contract); the verdict
    comes from contract.verify — the harness, never the worker.

    Cheap path first: if the acceptance already passes (or a proven runbook
    can make it pass), no model is consulted — the same economics as every
    goal here."""
    import capability
    import contract
    import goal as goalmod
    root = os.path.join(home, "experts", expert)
    if phase != "practice":
        # Only practice may file trajectories/memory into the persistent student.
        # Baseline/exam/retention run in distinct homes, with packs still outside
        # the actor root. No artifacts, prompts, answers or graders return.
        import evaluation_workspace
        import shutil
        with evaluation_workspace.arena(root, expert=expert) as (temp_home, temp_root, snap):
            target = capability.pack_dir(temp_home, pack)
            shutil.copytree(capability.pack_dir(home, pack), target)
            capability.freeze(temp_home, pack)
            result = _execute_task(temp_home, expert, pack, task, phase, drive, timeout)
        _event(root, pack, "task_graded", phase=phase, task=task["id"],
               gid=result["gid"], passed=result["passed"],
               competencies=result["competencies"], failed_checks=result["failed_checks"],
               pack_hash=capability.verify_pack(home, pack)["hash"], snapshot_hash=snap,
               evidence_scope="disposable-evaluation-no-training-export")
        return result
    return _execute_task(home, expert, pack, task, phase, drive, timeout)


def _execute_task(home, expert, pack, task, phase, drive, timeout):
    import capability
    import contract
    import goal as goalmod
    root = os.path.join(home, "experts", expert)
    gid = f"m-{pack}-{phase}-{task['id']}-{uuid.uuid4().hex[:12]}"
    accept = capability.accept_for(home, pack, task)
    rec = goalmod.pursue(home, expert, task["goal"], cycles=2, drive=drive,
                         timeout=timeout, gid=gid, accept=accept)
    vr = contract.verify(root, gid)
    passed = bool(vr.get("mechanical") and vr.get("all")
                  and not vr.get("tamper"))
    _event(root, pack, "task_graded", phase=phase, task=task["id"],
           gid=gid, passed=passed,
           failed_checks=vr.get("failed") or [],
           competencies=task.get("competencies") or [])
    return {"task": task["id"], "gid": gid, "passed": passed,
            "failed_checks": vr.get("failed") or [],
            "competencies": task.get("competencies") or []}


def _refuse_unless_sealed(home, pack, expert=None):
    import capability
    v = capability.verify_pack(home, pack)
    if not v["ok"]:
        raise MasteryError(
            f"refusing to run against pack {pack!r}: {v['why']}"
            + (" — an exam whose graders were edited after sealing grades "
               "nothing." if v.get("tamper") else ""))
    # THE AUTHOR LAW: file zones stop the student EDITING its exam;
    # provenance stops the student having WRITTEN it. An expert may draft
    # packs all day — for other experts. Examining it on its own pack would
    # measure authorship memory and call it transfer.
    if expert is not None:
        try:
            author = str(capability.load(home, pack).get("author") or "")
        except Exception:
            author = ""
        if author and author == str(expert):
            raise MasteryError(
                f"expert {expert!r} authored pack {pack!r} — the student "
                f"never sits an exam it wrote. Examine a different expert, "
                f"or have a different author own this pack.")


# ------------------------------------------------------------------ stages

def pretest(home, expert, pack, drive=False, phase="pretest",
            timeout=900):
    """One previously unexposed independent set, never persisted as training."""
    import capability
    _refuse_unless_sealed(home, pack, expert=expert)
    root = os.path.join(home, "experts", expert)
    selectors = {"pretest": capability.baseline_tasks, "exam": capability.transfer_tasks,
                 "retest": capability.retention_tasks}
    if phase not in selectors:
        raise MasteryError("unknown evaluation phase")
    selected = selectors[phase](home, pack)
    _reserve_exposure(home, expert, pack, phase, selected)
    results = [
        _run_task(home, expert, pack, t, phase, drive=drive,
                  timeout=timeout)
        for t in selected]
    score = (sum(1 for r in results if r["passed"]) / len(results)
             if results else 0.0)
    _event(root, pack, phase, score=round(score, 3),
           passed=[r["task"] for r in results if r["passed"]],
           failed=[r["task"] for r in results if not r["passed"]])
    return {"score": round(score, 3), "results": results}


def _reserve_exposure(home, expert, pack, phase, tasks):
    """Consume before dispatch, even on crash. The student cannot erase history."""
    import capability
    import locks
    p = os.path.join(home, "org", "mastery-exposures.jsonl")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    digest = capability.verify_pack(home, pack)["hash"]
    with locks.holding(p, timeout=10, stale=8):
        rows = []
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    rows = [json.loads(line) for line in f if line.strip()]
            except (ValueError, OSError) as exc:
                raise MasteryError("corrupt exposure authority; refusing") from exc
        ids = {t["id"] for t in tasks}
        if any(r.get("expert") == expert and r.get("pack_hash") == digest
               and ids.intersection(r.get("tasks", [])) for r in rows):
            raise MasteryError("evaluation set already exposed; use a fresh independently sealed pack")
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"expert": expert, "pack": pack, "pack_hash": digest,
                                "phase": phase, "tasks": sorted(ids), "at": time.time()}) + "\n")
            f.flush()
            os.fsync(f.fileno())


def study(home, expert, pack, drive=False, competencies=None,
          because=None):
    """Per-competency study: discovery from the curated catalogues, then a
    learning-shaped pursuit. `because` carries the failing evidence when
    diagnosis sends us back here — the study is targeted at what FAILED,
    never a lap of the whole curriculum (repair's LAW 1, one level up)."""
    import capability
    import discover
    _refuse_unless_sealed(home, pack, expert=expert)
    root = os.path.join(home, "experts", expert)
    queries = capability.study_queries(home, pack)
    todo = {c: q for c, q in queries.items()
            if competencies is None or c in set(competencies)}
    out = []
    for comp, query in todo.items():
        found = []
        try:
            res = discover.search(query, limit=6)
            found = discover.add_url_commands(res, root=root)
        except Exception:
            pass
        goal_text = (f"learn {query} to working competence: gather real "
                     f"sources, study them into cited notes, and be ready "
                     f"to BUILD with it")
        if because:
            goal_text += (f". This re-study is targeted: the transfer "
                          f"check(s) {because} failed, attack exactly that.")
        _event(root, pack, "study", competency=comp, query=query,
               sources=len(found), targeted=bool(because))
        out.append({"competency": comp, "query": query,
                    "ingest_commands": found})
        if drive:
            import goal as goalmod
            goalmod.pursue(home, expert, goal_text, cycles=2, drive=True,
                           gid=f"m-{pack}-study-{comp}-"
                               f"{time.strftime('%H%M%S')}")
    return out


def practice(home, expert, pack, drive=False, timeout=900):
    """Every exercise as a graded contract pursuit. Practice is where the
    model is allowed to fail cheaply and repair is allowed to work."""
    import capability
    _refuse_unless_sealed(home, pack, expert=expert)
    root = os.path.join(home, "experts", expert)
    results = [
        _run_task(home, expert, pack, t, "practice", drive=drive,
                  timeout=timeout)
        for t in capability.exercises(home, pack)]
    score = (sum(1 for r in results if r["passed"]) / len(results)
             if results else 0.0)
    _event(root, pack, "practice_done", score=round(score, 3))
    return {"score": round(score, 3), "results": results}


def exam(home, expert, pack, drive=False, phase="exam", timeout=900):
    """Transfer set B: independent of baseline A, and single-use."""
    return pretest(home, expert, pack, drive=drive, phase=phase,
                   timeout=timeout)


def diagnose(exam_results):
    """Failing tasks -> the competencies they examine, each carrying the
    failing checks as its evidence. No signal, no re-study."""
    plan = {}
    for r in exam_results.get("results", []):
        if r["passed"]:
            continue
        for comp in r["competencies"]:
            plan.setdefault(comp, {"competency": comp, "failed_tasks": [],
                                   "failed_checks": []})
            plan[comp]["failed_tasks"].append(r["task"])
            plan[comp]["failed_checks"] += r["failed_checks"]
    return list(plan.values())


def verdict(home, expert, pack, practice_score, exam_score):
    """MASTERED or NOT, from the pack's frozen thresholds and NOTHING else.
    The scores fed in here are computed exclusively from contract.verify
    results — grader runs the harness performed. There is no argument, no
    override, and no code path where a worker's claim reaches this."""
    import capability
    pk = capability.load(home, pack)
    m = pk.get("mastery") or {}
    need_p = float(m.get("practice_pass", 0.8))
    need_t = float(m.get("transfer_pass", 0.7))
    mastered = practice_score >= need_p and exam_score >= need_t
    root = os.path.join(home, "experts", expert)
    row = {"mastered": mastered,
           "practice_score": practice_score, "practice_bar": need_p,
           "exam_score": exam_score, "transfer_bar": need_t,
           "ceiling": ("this verdict is the pack's MECHANICAL FLOOR — "
                       "validators check what validators can check, and "
                       "excellence beyond the floor is not claimed")}
    _event(root, pack, "verdict", **row)
    return row


def distill(home, expert, pack):
    """Verified practice pursuits -> runbook drafts, so the competence
    outlives the transcript. Drafts carry TODOs and zero trust — the
    existing runbook law: the machine keeps what was PROVEN, and earns
    trust for the how three verified wins at a time."""
    import contract
    import runbook
    root = os.path.join(home, "experts", expert)
    drafted = []
    for e in events(root, pack):
        if e.get("kind") == "task_graded" and e.get("passed") \
                and e.get("phase") == "practice":
            try:
                if contract.load(root, e["gid"])["state"] == "verified":
                    out, rb = runbook.draft(root, e["gid"])
                    drafted.append(rb["name"])
            except Exception:
                continue
    _event(root, pack, "distilled", runbooks=drafted)
    return drafted


def retest(home, expert, pack, drive=False, timeout=900):
    """Retention C, never seen in A/practice/B. Record elapsed interval honestly."""
    r = pretest(home, expert, pack, drive=drive, phase="retest",
                timeout=timeout)
    root = os.path.join(home, "experts", expert)
    last_exam = next((e for e in reversed(events(root, pack))
                      if e.get("kind") == "exam"), None)
    delta = (round(r["score"] - float(last_exam.get("score") or 0.0), 3)
             if last_exam else None)
    elapsed = None
    if last_exam:
        elapsed = max(0, time.time() - time.mktime(time.strptime(last_exam["at"], "%Y-%m-%dT%H:%M:%S")))
    _event(root, pack, "retention", score=r["score"], delta_vs_exam=delta,
           elapsed_since_exam_seconds=elapsed,
           limitation="fresh-instance performance; duration alone does not prove long-term retention")
    return {**r, "delta_vs_exam": delta, "elapsed_since_exam_seconds": elapsed}


# ---------------------------------------------------------------- the loop

def run(home, expert, pack, drive=False, skip_study=False,
        max_rounds=MAX_RELEARN_ROUNDS, timeout=900):
    """The whole loop: pretest → study → practice → exam → diagnose →
    verdict → distill.

    THERE IS NO RE-EXAM, and `relearn_rounds` is therefore always 0. The
    exposure authority consumes a sealed set at the sitting that used it, so
    a competency whose transfer tasks failed cannot be re-examined on those
    tasks at any distance — re-study then re-sit would be measuring memory of
    the exam. A diagnosis ends in `fresh_pack_required` instead, and the
    owner supplies an independently sealed pack. `max_rounds` is kept in the
    signature for callers that pass it; it bounds nothing today."""
    root = os.path.join(home, "experts", expert)
    _event(root, pack, "run_started", expert=expert,
           skip_study=bool(skip_study))
    base = pretest(home, expert, pack, drive=drive, timeout=timeout)
    if not skip_study:
        study(home, expert, pack, drive=drive)
    prac = practice(home, expert, pack, drive=drive, timeout=timeout)
    ex = exam(home, expert, pack, drive=drive, timeout=timeout)

    rounds = 0
    if diagnose(ex):
        _event(root, pack, "fresh_pack_required", reason="exam consumed; re-study cannot reuse transfer tasks")

    v = verdict(home, expert, pack, prac["score"], ex["score"])
    drafted = distill(home, expert, pack)
    return {"baseline": base["score"], "practice": prac["score"],
            "exam": ex["score"], "improvement": round(
                ex["score"] - base["score"], 3),
            "verdict": v, "distilled": drafted, "relearn_rounds": rounds}


# --------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("run", "pretest", "exam", "retest", "status"):
        p = sub.add_parser(c)
        p.add_argument("home"); p.add_argument("expert")
        p.add_argument("pack")
        if c != "status":
            p.add_argument("--drive", action="store_true")
        if c == "run":
            p.add_argument("--skip-study", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run":
        r = run(a.home, a.expert, a.pack, drive=a.drive,
                skip_study=a.skip_study)
        print(json.dumps(r, indent=1))
        raise SystemExit(0 if r["verdict"]["mastered"] else 1)
    elif a.cmd in ("pretest", "exam", "retest"):
        fn = {"pretest": pretest, "exam": exam, "retest": retest}[a.cmd]
        print(json.dumps(fn(a.home, a.expert, a.pack, drive=a.drive),
                         indent=1))
    elif a.cmd == "status":
        root = os.path.join(a.home, "experts", a.expert)
        for e in events(root, a.pack)[-25:]:
            print(json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()
