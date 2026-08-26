#!/usr/bin/env python3
"""Goal pursuit — state what you want; the system pursues it until it is
objectively achieved, not until the model feels finished.

The smart loop (a supervisor above the task loop):

  1. PLAN       a planner writes plan.md: numbered milestones, each with a
                MECHANICAL check where one is possible. A goal that names a
                topic to LEARN gets a study-shaped plan seeded for it:
                gather sources -> ingest -> study into cited notes -> spec ->
                closed-book self-exam -> re-study what was missed.
  2. WORK       each milestone runs as a real gated task inside the expert
                (its done_check must exit 0 or finish_task is refused).
  3. JUDGE      an evaluator on a DIFFERENT model family reads the goal, the
                success criteria, and the evidence on disk, then writes
                assessment.md ending in VERDICT: ACHIEVED | NOT ACHIEVED with
                what is still missing. Its own claim is checked: a verdict of
                ACHIEVED is rejected when a milestone check still fails.
  4. LEARN      every failed milestone becomes a fleet lesson in the commons,
                so no expert repeats it.
  5. REPEAT     not achieved -> re-plan WITH the assessment in hand. Bounded
                by cycles and by the expert's own cost brakes.

Nothing here trusts a model's opinion of its own progress: milestones carry
checks, the judge is a different family, and the judge's verdict is itself
verified against the checks.

Usage:
  python goal.py pursue "the goal" --expert <slug> [--criteria "..."]
        [--cycles 4] [--home DIR] [--drive]
  python goal.py list [--home DIR]
  python goal.py show <goal-id> [--home DIR]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
import commons        # noqa: E402
import contract as contractmod  # noqa: E402
import loop           # noqa: E402
import toolbox        # noqa: E402

MILESTONE_RE = re.compile(r"^\s*-\s*M(\d+)\s*:\s*(.+?)\s*(?:CHECK:\s*(.+))?$", re.M)
VERDICT_RE = re.compile(r"VERDICT:\s*(ACHIEVED|NOT ACHIEVED)", re.I)
LEARN_WORDS = ("learn", "study", "master", "understand", "become expert",
               "apprendre", "maîtriser", "training on", "get good at")
MAX_MILESTONES = 8

LEARNING_SHAPE = """
This goal is about LEARNING a subject. Shape the plan like a serious student,
not a summarizer — milestones in this order, each verifiable:
  M1 gather real sources (ingest.py add-url / --crawl / search results the
     human supplied) into the course, CHECK that source files exist
  M2 study each lesson into cited notes in the house format (C-/P-/U- atoms
     with [src:]), CHECK with memcheck.py that the memory is sound
  M3 extract spec.md requirements from what was studied
  M4 sit a CLOSED-BOOK self-exam: write questions to exam/pending/, let the
     Student answer them, CHECK that answers exist
  M5 re-study exactly what the exam missed (gaps.md), CHECK gaps.md is empty
Master the subject; do not merely collect text about it.
"""


def _goal_dir(root, gid):
    d = os.path.join(root, "goals", gid)
    os.makedirs(d, exist_ok=True)
    return d


def _record(d, data):
    loop.atomic_write_json(os.path.join(d, "goal.json"), data)


def _is_learning(goal):
    g = goal.lower()
    return any(w in g for w in LEARN_WORDS)


def _wait(root, tid, drive, timeout=1800):
    proc = None
    if drive:
        proc = subprocess.Popen(
            [sys.executable, os.path.join(HOME, "loop.py"), "run", "--drain",
             "--root", root], stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUTF8": "1"})
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                with open(os.path.join(root, "state.json"), "r",
                          encoding="utf-8") as f:
                    t = next(x for x in json.load(f)["tasks"] if x["id"] == tid)
            except (OSError, json.JSONDecodeError, StopIteration):
                time.sleep(0.4)
                continue
            if t["status"] in ("done", "failed", "blocked"):
                return t
            time.sleep(0.4)
        return {"id": tid, "status": "failed", "error": f"timeout {timeout}s"}
    finally:
        if proc is not None:
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.terminate()


def _exists_check(rel):
    return (f'"{sys.executable}" -c "import os,sys;'
            f"sys.exit(0 if os.path.exists(r'{rel}') else 1)\"")


def _expert_cfg(root):
    """This expert's settings, for the policy + sandbox that screen the
    planner's own milestone checks. Never fatal: an unreadable settings file
    means default containment, not no containment."""
    try:
        import tomllib
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig"))
    except (OSError, ValueError, ImportError):
        return {}


def pursue(home, expert, goal, criteria="", cycles=4, drive=False,
           timeout=1800, gid=None, accept=None, max_usd=0.0, max_minutes=0):
    root = os.path.join(home, "experts", expert)
    if not os.path.isdir(root):
        sys.exit(f"ERROR: no expert '{expert}'")
    gid = gid or time.strftime("g-%Y%m%d-%H%M%S")
    d = _goal_dir(root, gid)
    rel_dir = f"goals/{gid}"
    criteria = criteria.strip() or ("The goal is achieved when a competent "
                                    "reviewer, seeing only the artifacts on "
                                    "disk, would agree it is done.")
    with open(os.path.join(d, "goal.md"), "w", encoding="utf-8") as f:
        f.write(f"# GOAL\n{goal}\n\n# SUCCESS CRITERIA\n{criteria}\n")
    with open(os.path.join(d, "toolbox.md"), "w", encoding="utf-8") as f:
        f.write(toolbox.capability_note(root))
    commons.refresh_directory(home)
    commons_rel = commons.write_digest(home, root)

    # THE CONTRACT: what "done" means, frozen BEFORE any planning happens.
    #
    # The audit's finding, in one line: the planner writes its own graders.
    # Milestone CHECKs are authored by the model that then works to satisfy
    # them, so a plan under pressure can grade itself generously. Acceptance
    # tests arrive from the CALLER, are hashed and sealed outside this
    # expert's root, and the harness runs them itself at the end — the
    # worker cannot write them, cannot edit them without tripping the seal,
    # and cannot talk its way past them. No acceptance tests means the
    # pursuit can end "achieved" (the judge's checked opinion) but never
    # VERIFIED — that ceiling is recorded, not hidden.
    try:
        contractmod.load(root, gid)
        contractmod.event(root, gid, "resumed", expert=expert)
    except (OSError, ValueError):
        contractmod.create(root, gid, goal, criteria=criteria,
                           accept=accept or [], max_usd=max_usd,
                           max_minutes=max_minutes, max_cycles=cycles)
        contractmod.freeze(root, gid)
    rec = {"id": gid, "goal": goal, "criteria": criteria, "expert": expert,
           "status": "planning", "cycles": [], "verdict": None,
           "verified": False,
           "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _record(d, rec)
    agent = loop.Agent(root)
    learning = _is_learning(goal)
    print(f"[goal {gid}] {'LEARNING ' if learning else ''}pursuit on {expert}")

    assessment_note = ""
    for cycle in range(1, cycles + 1):
        # BUDGETS END A PURSUIT BY NAME, NEVER BY SURPRISE. Checked at the
        # top of every cycle (and spend accrues per finished task below), so
        # the most one cycle can overshoot is the cycle already running —
        # the same honest boundary the audit calls "checked between steps".
        bstate = contractmod.budget_state(root, gid)
        if bstate["exceeded"]:
            why = "; ".join(bstate["exceeded"])
            rec["status"] = "blocked"
            rec["blocked"] = f"budget: {why}"
            _record(d, rec)
            try:
                contractmod.transition(root, gid, "blocked",
                                       why=f"budget: {why}")
            except contractmod.ContractError:
                pass
            commons.learn(home, f"goal '{goal[:60]}' stopped on budget "
                                f"({why}) — re-scope or raise the budget",
                          from_expert=expert, tag="goal")
            print(f"[goal {gid}] BLOCKED on budget: {why}")
            return rec
        contractmod.event(root, gid, "cycle_started", cycle=cycle)
        if cycle == 1:
            try:
                contractmod.transition(root, gid, "running",
                                       why="pursuit started")
            except contractmod.ContractError:
                pass
        cyc = {"n": cycle, "milestones": [], "verdict": None}
        rec["cycles"].append(cyc)
        rec["status"] = f"cycle {cycle}: planning"
        _record(d, rec)

        # ---------- 1. PLAN -------------------------------------------------
        plan_rel = f"{rel_dir}/plan-{cycle}.md"
        base_mem = [f"{rel_dir}/goal.md", f"{rel_dir}/toolbox.md"]
        if commons_rel:
            base_mem.insert(0, commons_rel)
        if assessment_note:
            base_mem.append(assessment_note)
        tid = agent.add_task(
            "practitioner",
            f"PLAN cycle {cycle} for goal {gid}. Read the goal and its success "
            f"criteria in your context, plus the TOOLBOX (use only READY "
            f"tools) and the fleet COMMONS (its lessons are binding). "
            + (f"The previous cycle's assessment is in your context — your new "
               f"plan must attack exactly what it found missing. "
               if assessment_note else "")
            + (LEARNING_SHAPE if learning else "")
            + f"\nWrite {plan_rel} with at most {MAX_MILESTONES} milestones, "
              f"one per line, EXACTLY:\n"
              f"- M1: what to do CHECK: <shell command exiting 0 when done>\n"
              f"Give every milestone a mechanical CHECK where one is possible; "
              f"omit CHECK only where nothing mechanical can prove it. No prose "
              f"outside the list.",
            memory_files=base_mem, done_check=_exists_check(plan_rel))
        t = _wait(root, tid, drive, timeout)
        plan_path = os.path.join(root, plan_rel)
        if t["status"] != "done" or not os.path.exists(plan_path):
            rec["status"] = "failed"
            rec["error"] = f"planning {t['status']}: {(t.get('error') or '')[:200]}"
            _record(d, rec)
            commons.learn(home, f"goal planning failed for '{goal[:60]}': "
                                f"{(t.get('error') or 'no plan produced')[:120]}",
                          from_expert=expert, tag="goal")
            return rec
        with open(plan_path, "r", encoding="utf-8") as f:
            plan_text = f.read()
        milestones = [{"n": int(m.group(1)), "what": m.group(2).strip(),
                       "check": (m.group(3) or "").strip() or None}
                      for m in MILESTONE_RE.finditer(plan_text)]
        milestones = sorted(milestones, key=lambda x: x["n"])[:MAX_MILESTONES]
        if not milestones:
            rec["status"] = "failed"
            rec["error"] = "the plan contained no parseable milestones"
            _record(d, rec)
            return rec
        print(f"[goal {gid}] cycle {cycle}: {len(milestones)} milestone(s)")

        # ---------- 2. WORK -------------------------------------------------
        for ms in milestones:
            out_rel = f"{rel_dir}/m{cycle}-{ms['n']}.md"
            done = ms["check"] or _exists_check(out_rel)
            mtid = agent.add_task(
                "practitioner",
                f"MILESTONE M{ms['n']} of goal {gid} (cycle {cycle}): "
                f"{ms['what']}\nUse only READY tools from the toolbox in your "
                f"context. When done, write a short evidence note to {out_rel} "
                f"stating what you produced and where it lives. If you need "
                f"knowledge another expert in the fleet has, ask them: "
                f"`python commons.py ask <expert> \"question\" --from {expert} "
                f"--home {os.path.abspath(home)} --wait 120 --drive` (the "
                f"directory of who knows what is in your commons block).",
                memory_files=base_mem + [plan_rel], done_check=done)
            mt = _wait(root, mtid, drive, timeout)
            ms["status"] = mt["status"]
            ms["task"] = mtid
            cyc["milestones"].append(ms)
            _record(d, rec)
            cost = float(mt.get("cost_usd") or 0.0)
            if cost:
                contractmod.event(root, gid, "spent", usd=cost, task=mtid)
            contractmod.event(
                root, gid,
                "milestone_done" if mt["status"] == "done"
                else "milestone_failed",
                n=ms["n"], cycle=cycle, check=(ms.get("check") or "")[:120],
                what=ms["what"][:120],
                error=(mt.get("error") or "")[:200])
            print(f"[goal {gid}]   M{ms['n']} {mt['status']}")
            if mt["status"] != "done":
                # 4. LEARN — a real failure becomes a fleet lesson, once
                commons.learn(
                    home,
                    f"milestone '{ms['what'][:80]}' failed: "
                    f"{(mt.get('error') or 'unknown')[:120]}",
                    from_expert=expert, tag="milestone")

        # ---------- 3. JUDGE ------------------------------------------------
        rec["status"] = f"cycle {cycle}: judging"
        _record(d, rec)
        assess_rel = f"{rel_dir}/assessment-{cycle}.md"
        evidence = [f"{rel_dir}/m{cycle}-{m['n']}.md" for m in milestones
                    if os.path.exists(os.path.join(root, f"{rel_dir}/m{cycle}-{m['n']}.md"))]
        jtid = agent.add_task(
            "examiner",
            f"JUDGE goal {gid} after cycle {cycle}. The goal and its success "
            f"criteria, the plan, and every milestone's evidence are in your "
            f"context. Verify against the ARTIFACTS, not the claims: run the "
            f"milestone CHECK commands yourself and inspect what exists on "
            f"disk. Write {assess_rel}: what is proven done, what is missing, "
            f"and end with a final line exactly 'VERDICT: ACHIEVED' or "
            f"'VERDICT: NOT ACHIEVED'. Say ACHIEVED only if the success "
            f"criteria are demonstrably met by evidence you checked.",
            memory_files=base_mem + [plan_rel] + evidence,
            done_check=_exists_check(assess_rel))
        jt = _wait(root, jtid, drive, timeout)
        verdict, text = "NOT ACHIEVED", ""
        apath = os.path.join(root, assess_rel)
        if os.path.exists(apath):
            with open(apath, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            m = VERDICT_RE.search(text)
            if m:
                verdict = m.group(1).upper()
        # the judge's own claim is checked: ACHIEVED cannot stand while a
        # milestone check still fails
        failed_checks = []
        for ms in milestones:
            if not ms.get("check"):
                continue
            try:
                # milestone CHECK: lines are written by the PLANNER model, so
                # they run under the same containment as any model-authored
                # command — policy screens, sandbox scrubs the environment
                import execution
                rc, _out, _err = execution.run(
                    "gate", ms["check"], root, cfg=_expert_cfg(root),
                    role="examiner", timeout=120,
                    reason=f"milestone M{ms['n']} check")
                if rc != 0:
                    failed_checks.append(f"M{ms['n']}")
            except Exception:
                failed_checks.append(f"M{ms['n']}")
        cyc["failed_checks"] = failed_checks
        if verdict == "ACHIEVED" and failed_checks:
            verdict = "NOT ACHIEVED"
            # durable record of the overrule: a later task can rewrite the
            # assessment file, but the judgement history must not be losable
            cyc["overruled"] = {"claimed": "ACHIEVED", "failing": failed_checks}
            note = (f"\n\n[OVERRULED by the harness: the judge said ACHIEVED "
                    f"while these milestone checks still fail: "
                    f"{', '.join(failed_checks)}]\n")
            with open(apath, "a", encoding="utf-8") as f:
                f.write(note)
            commons.learn(home, "an evaluator declared a goal ACHIEVED while "
                                "milestone checks still failed — verdicts are "
                                "always re-checked against the mechanical checks",
                          from_expert=expert, tag="judging")
        cyc["verdict"] = verdict
        rec["verdict"] = verdict
        contractmod.event(root, gid, "verdict", cycle=cycle, verdict=verdict,
                          overruled=bool(failed_checks and
                                         verdict == "NOT ACHIEVED"))
        print(f"[goal {gid}] cycle {cycle} verdict: {verdict}"
              + (f" (overruled: {', '.join(failed_checks)})" if failed_checks
                 and verdict == "NOT ACHIEVED" else ""))
        if verdict == "ACHIEVED":
            # THE ACCEPTANCE AUTHORITY OUTRANKS THE JUDGE. The judge's
            # verdict was already re-checked against milestone checks; both
            # of those were authored by the planner. The contract's tests
            # were authored by the caller and frozen before planning — so an
            # ACHIEVED that fails them is overruled a second time, and the
            # failure list goes into the next cycle's assessment so the plan
            # attacks exactly what the graders still refuse.
            vr = contractmod.verify(root, gid, cfg=_expert_cfg(root))
            if vr["tamper"]:
                rec["status"] = "blocked"
                rec["blocked"] = "contract tamper: " + vr["why"]
                rec["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                _record(d, rec)
                try:
                    contractmod.transition(root, gid, "blocked",
                                           why="acceptance tests tampered")
                except contractmod.ContractError:
                    pass
                commons.learn(home, "a goal's frozen acceptance tests were "
                                    "edited after freezing — the pursuit was "
                                    "stopped, not passed",
                              from_expert=expert, tag="goal")
                print(f"[goal {gid}] BLOCKED: {vr['why'][:120]}")
                return rec
            if vr["mechanical"] and not vr["all"]:
                cyc["acceptance_failed"] = vr["failed"]
                # durable in the LEDGER, not only in the assessment file —
                # the next cycle's judge task replays its script and
                # rewrites assessment-1.md, clobbering any note appended
                # there (the original overrule learned this same lesson and
                # keeps its record in goal.json for the same reason)
                contractmod.event(root, gid, "acceptance_overruled",
                                  cycle=cycle, failed=vr["failed"])
                rec["verdict"] = "NOT ACHIEVED"
                cyc["verdict"] = "NOT ACHIEVED"
                note = (f"\n\n[OVERRULED by the CONTRACT: the judge said "
                        f"ACHIEVED while these frozen acceptance tests still "
                        f"fail: {', '.join(vr['failed'])}. These graders were "
                        f"written by the caller before planning began; "
                        f"satisfy them, not the plan.]\n")
                with open(apath, "a", encoding="utf-8") as f:
                    f.write(note)
                print(f"[goal {gid}] ACHIEVED overruled by acceptance: "
                      f"{', '.join(vr['failed'])}")
                assessment_note = assess_rel
                _record(d, rec)
                osc = contractmod.oscillating(root, gid)
                if osc:
                    rec["status"] = "blocked"
                    rec["blocked"] = f"no convergence: {osc}"
                    rec["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    _record(d, rec)
                    try:
                        contractmod.transition(root, gid, "blocked", why=osc)
                    except contractmod.ContractError:
                        pass
                    print(f"[goal {gid}] BLOCKED: {osc[:140]}")
                    return rec
                continue
            rec["status"] = "achieved"
            rec["verified"] = bool(vr["mechanical"] and vr["all"])
            if not rec["verified"]:
                rec["verification"] = vr["why"]
            rec["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _record(d, rec)
            try:
                contractmod.transition(
                    root, gid,
                    "verified" if rec["verified"] else "partial",
                    why=("all frozen acceptance tests passed, run by the "
                         "harness" if rec["verified"] else vr["why"]))
            except contractmod.ContractError:
                pass
            if not rec["verified"]:
                print(f"[goal {gid}] achieved but NOT verified: {vr['why']}")
            return rec
        # A PLAN THAT HITS THE SAME WALL TWICE IN A ROW WILL HIT IT A THIRD
        # TIME. Burning the remaining cycles on an identical failure is a
        # loop wearing persistence's clothes; ending BLOCKED with the wall
        # named lets the owner fix the actual obstacle.
        osc = contractmod.oscillating(root, gid)
        if osc:
            rec["status"] = "blocked"
            rec["blocked"] = f"no convergence: {osc}"
            rec["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _record(d, rec)
            try:
                contractmod.transition(root, gid, "blocked", why=osc)
            except contractmod.ContractError:
                pass
            commons.learn(home, f"goal '{goal[:60]}' stopped: {osc[:140]}",
                          from_expert=expert, tag="goal")
            print(f"[goal {gid}] BLOCKED: {osc[:140]}")
            return rec
        assessment_note = assess_rel
        _record(d, rec)

    rec["status"] = "exhausted"
    rec["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _record(d, rec)
    try:
        contractmod.transition(root, gid, "exhausted",
                               why=f"{cycles} cycle(s) spent, not achieved")
    except contractmod.ContractError:
        pass
    commons.learn(home, f"goal '{goal[:70]}' was not achieved within {cycles} "
                        f"cycles — re-scope it or hand the gap to a human",
                  from_expert=expert, tag="goal")
    return rec


def list_goals(home, limit=25):
    out = []
    experts = os.path.join(home, "experts")
    if not os.path.isdir(experts):
        return out
    for slug in sorted(os.listdir(experts)):
        gdir = os.path.join(experts, slug, "goals")
        if not os.path.isdir(gdir):
            continue
        for gid in sorted(os.listdir(gdir), reverse=True):
            p = os.path.join(gdir, gid, "goal.json")
            try:
                with open(p, "r", encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue
    return out[:limit]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pursue")
    p.add_argument("goal")
    p.add_argument("--expert", required=True)
    p.add_argument("--criteria", default="")
    p.add_argument("--cycles", type=int, default=4)
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--drive", action="store_true")
    p.add_argument("--id", default=None, dest="gid",
                   help="name this pursuit (default: a timestamp)")
    p.add_argument("--accept", action="append", default=[],
                   help="frozen acceptance test, 'what::command'; the "
                        "harness runs these itself and only they can make "
                        "the outcome VERIFIED")
    p.add_argument("--max-usd", type=float, default=0.0)
    p.add_argument("--max-minutes", type=int, default=0)
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("list")
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("show")
    p.add_argument("goal_id")
    p.add_argument("--home", default=HOME)
    args = ap.parse_args()

    if args.cmd == "pursue":
        import contract as _c
        r = pursue(args.home, args.expert, args.goal, args.criteria,
                   args.cycles, args.drive, args.timeout, args.gid,
                   accept=_c.parse_accept(args.accept),
                   max_usd=args.max_usd, max_minutes=args.max_minutes)
        print(f"\n[goal {r['id']}] {r['status'].upper()}"
              + (f" — {r.get('error','')}" if r.get("error") else ""))
        sys.exit(0 if r["status"] == "achieved" else 1)
    elif args.cmd == "list":
        for g in list_goals(args.home):
            print(f"{g['id']}  {g['status']:<22} {g['expert']:<18} "
                  f"{g['goal'][:60]}")
    elif args.cmd == "show":
        for g in list_goals(args.home):
            if g["id"] == args.goal_id:
                print(json.dumps(g, indent=2))
                return
        sys.exit(f"no goal {args.goal_id}")


if __name__ == "__main__":
    main()
