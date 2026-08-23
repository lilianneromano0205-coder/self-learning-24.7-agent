#!/usr/bin/env python3
"""Teams: chosen specialists collaborating on one piece of work.

The orchestration law (layer 7): a LEAD expert decomposes the goal into
subtasks and assigns each to the roster specialist whose training fits;
each specialist works ALONE, inside its own memory, with its own courses and
skills; handoffs happen only through written files; the lead synthesizes the
outputs into one deliverable. No shared mutable state, ever — agents that
share state corrupt each other.

A team run lives in teamwork/<run-id>/ at the fleet home:
  brief.md          the goal + the roster with each expert's specialty
  plan.md           the lead's decomposition:  - S1 [expert-slug]: deliverable
  output-S<n>.md    each specialist's deliverable
  result.md         the lead's synthesis — the answer to the brief
  team.json         the run's status record (what the UI reads)

Every subtask carries a DONE CHECK — finish_task is refused until the
deliverable file actually exists. Claims are hints; files are proof.

Usage:
  python team.py run "goal…" --experts shopify-master,seo-pro,copy-chief [--lead shopify-master]
  python team.py list
  python team.py result <run-id>
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
import fleet          # noqa: E402
import loop           # noqa: E402

PLAN_LINE = re.compile(r"^\s*-\s*S(\d+)\s*\[([a-z0-9-]+)\]\s*:\s*(.+?)\s*$", re.M)
MAX_SUBTASKS = 12

# Constraint digest (adapted from the Semantic Fidelity Protocol): the brief's
# hard constraints are extracted once, hashed, and carried into EVERY handoff.
# Each specialist must echo the digest line verbatim in its deliverable, so a
# constraint silently dropped across handoffs is detectable instead of
# discovered in the final output.
CONSTRAINT_WORDS = re.compile(
    r"\b(must|must not|never|always|only|do not|don't|shall|required|"
    r"forbidden|deadline|budget|no later than|at least|at most|exactly|"
    r"under \d|over \d|within \d|maximum|minimum|mandatory)\b", re.I)


def constraints_of(text, limit=12):
    """Pull the hard constraints out of a brief. Briefs are PROSE as often as
    bullets, so this works sentence-wise: any clause carrying an obligation
    word is a constraint, wherever it sits in the line."""
    seen, out = set(), []
    for line in (text or "").splitlines():
        for clause in re.split(r"(?<=[.;!?])\s+|\s+[-–—]\s+", line):
            c = " ".join(clause.strip(" -*\t").split())[:200]
            if not c or not CONSTRAINT_WORDS.search(c):
                continue
            k = c.lower().rstrip(".")
            if k in seen:
                continue
            seen.add(k)
            out.append(c)
            if len(out) >= limit:
                return out
    return out


def digest_of(constraints):
    import hashlib
    body = "\n".join(constraints)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def constraint_block(constraints):
    if not constraints:
        return "", ""
    d = digest_of(constraints)
    block = ("# BINDING CONSTRAINTS (carried through every handoff)\n"
             + "\n".join(f"- {c}" for c in constraints)
             + f"\n\nCONSTRAINT-DIGEST: {d}\n"
               "Echo the line `CONSTRAINT-DIGEST: " + d + "` verbatim in your "
               "deliverable to confirm you carried these. A deliverable "
               "missing it is treated as having lost the brief.\n")
    return block, d


def _expert_root(home, slug):
    p = os.path.join(home, "experts", slug)
    if not os.path.isdir(p):
        sys.exit(f"ERROR: no expert '{slug}' — python fleet.py list")
    return p


def _exists_check(rel):
    """A done_check that demands the deliverable file exist (run cwd = expert root)."""
    return (f'"{sys.executable}" -c "import os,sys;'
            f"sys.exit(0 if os.path.exists(r'{rel}') else 1)\"")


def _push(ws_home, root, run_id, names):
    """Copy run files INTO an expert's own fenced world (handoff by file)."""
    dst = os.path.join(root, "teamwork", run_id)
    os.makedirs(dst, exist_ok=True)
    for n in names:
        src = os.path.join(ws_home, n)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(dst, n))


def _pull(ws_home, root, run_id, name):
    src = os.path.join(root, "teamwork", run_id, name)
    if os.path.exists(src):
        shutil.copy(src, os.path.join(ws_home, name))
        return True
    return False


def _wait_task(root, tid, drive=True, timeout=1800):
    """Wait for one task to leave the queue. With drive=True the run spawns a
    --drain loop for the expert (stop its 24/7 daemon during team runs, or
    pass --no-drive to rely on it instead)."""
    proc = None
    if drive:
        proc = subprocess.Popen(
            [sys.executable, os.path.join(HOME, "loop.py"), "run", "--drain",
             "--root", root],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1"})
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                with open(os.path.join(root, "state.json"), "r", encoding="utf-8") as f:
                    t = next(x for x in json.load(f)["tasks"] if x["id"] == tid)
            except (OSError, json.JSONDecodeError, StopIteration):
                time.sleep(0.4)
                continue
            if t["status"] in ("done", "failed", "blocked"):
                return t
            time.sleep(0.4)
        return {"id": tid, "status": "failed", "error": f"team timeout after {timeout}s"}
    finally:
        if proc is not None:
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                proc.terminate()


def _record(ws, data):
    loop.atomic_write_json(os.path.join(ws, "team.json"), data)


def run_team(home, goal, experts, lead=None, run_id=None, drive=True,
             timeout=1800):
    lead = lead or experts[0]
    if lead not in experts:
        experts = [lead] + experts
    roots = {s: _expert_root(home, s) for s in experts}
    run_id = run_id or time.strftime("t-%Y%m%d-%H%M%S")
    ws = os.path.join(home, "teamwork", run_id)
    os.makedirs(ws, exist_ok=True)

    roster = []
    for s in experts:
        d = fleet.describe(home, s)
        roster.append(f"- {s}: {d['identity'] or 'generalist'}"
                      + (f" (courses: {', '.join(d['courses'][:6])})" if d["courses"] else ""))
    cons = constraints_of(goal)
    cblock, cdigest = constraint_block(cons)
    with open(os.path.join(ws, "brief.md"), "w", encoding="utf-8") as f:
        f.write(f"# TEAM BRIEF — run {run_id}\n\n## Goal\n{goal}\n\n"
                f"## Roster (assign work ONLY to these specialists)\n"
                + "\n".join(roster) + f"\n\n## Lead\n{lead}\n"
                + (f"\n{cblock}" if cblock else ""))
    record = {"id": run_id, "goal": goal, "lead": lead, "experts": experts,
              "status": "planning", "subtasks": [], "result": None,
              "constraints": cons, "constraint_digest": cdigest,
              "digest_losses": [],
              "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _record(ws, record)
    print(f"[team {run_id}] lead={lead}  roster={', '.join(experts)}")

    # ---- 1. the lead decomposes ------------------------------------------
    _push(ws, roots[lead], run_id, ["brief.md"])
    rel_plan = f"teamwork/{run_id}/plan.md"
    tid = loop.Agent(roots[lead]).add_task(
        "practitioner",
        f"TEAM PLAN for run {run_id}. You lead a team of specialists; the "
        f"brief (goal + roster) is in your context. Decompose the goal into at "
        f"most {MAX_SUBTASKS} INDEPENDENT subtasks and write {rel_plan} with "
        f"EXACTLY one line per subtask in this format:\n"
        f"- S1 [expert-slug]: what that expert must deliver\n"
        f"Assign each subtask to the roster expert whose specialty fits it "
        f"best (including yourself). No other format, no prose outside the list.",
        memory_files=[f"teamwork/{run_id}/brief.md"],
        done_check=_exists_check(rel_plan))
    t = _wait_task(roots[lead], tid, drive, timeout)
    if t["status"] != "done" or not _pull(ws, roots[lead], run_id, "plan.md"):
        record.update(status="failed",
                      error=f"planning {t['status']}: {t.get('error') or ''}")
        _record(ws, record)
        sys.exit(f"[team {run_id}] planning failed: {t.get('error')}")
    with open(os.path.join(ws, "plan.md"), "r", encoding="utf-8") as f:
        plan_text = f.read()
    subtasks = []
    for m in PLAN_LINE.finditer(plan_text):
        n, slug, desc = int(m.group(1)), m.group(2), m.group(3)
        subtasks.append({"n": n, "expert": slug if slug in roots else lead,
                         "desc": desc, "task": None, "status": "pending"})
    subtasks = sorted(subtasks, key=lambda x: x["n"])[:MAX_SUBTASKS]
    if not subtasks:
        record.update(status="failed", error="the plan contained no parseable subtasks")
        _record(ws, record)
        sys.exit(f"[team {run_id}] empty plan")
    record.update(status="working", subtasks=subtasks)
    _record(ws, record)
    print(f"[team {run_id}] plan: "
          + "; ".join(f"S{s['n']}->{s['expert']}" for s in subtasks))

    # ---- 2. specialists work, isolated; handoffs by file -----------------
    produced = []
    for s in subtasks:
        root = roots[s["expert"]]
        out_name = f"output-S{s['n']}.md"
        rel_out = f"teamwork/{run_id}/{out_name}"
        _push(ws, root, run_id, ["brief.md", "plan.md"] + produced)
        mem = [f"teamwork/{run_id}/{n}" for n in
               (["brief.md", "plan.md"] + produced)]
        s["task"] = loop.Agent(root).add_task(
            "practitioner",
            f"TEAM SUBTASK S{s['n']} of run {run_id}: {s['desc']}\n"
            f"Apply YOUR OWN specialty memory — your courses, notes, and "
            f"skills — this subtask was assigned to you because of it. Prior "
            f"team outputs are in teamwork/{run_id}/. Write your COMPLETE "
            f"deliverable to {rel_out}; cite your course atoms "
            f"(C-/P-nnnn) where claims come from what you learned.",
            memory_files=mem, done_check=_exists_check(rel_out))
        t = _wait_task(root, s["task"], drive, timeout)
        s["status"] = t["status"]
        if t["status"] == "done" and _pull(ws, root, run_id, out_name):
            produced.append(out_name)
            if cdigest:
                with open(os.path.join(ws, out_name), "r", encoding="utf-8",
                          errors="replace") as f:
                    body = f.read()
                s["digest_echoed"] = f"CONSTRAINT-DIGEST: {cdigest}" in body
                if not s["digest_echoed"]:
                    record["digest_losses"].append(f"S{s['n']}:{s['expert']}")
                    print(f"[team {run_id}]   ! S{s['n']} did not echo the "
                          f"constraint digest — the brief may have been lost")
            print(f"[team {run_id}] S{s['n']} done by {s['expert']}")
        else:
            s["error"] = (t.get("error") or "no output produced")[:300]
            print(f"[team {run_id}] S{s['n']} {t['status']}: {s.get('error','')}")
        _record(ws, record)

    # ---- 3. the lead synthesizes -----------------------------------------
    record["status"] = "synthesizing"
    _record(ws, record)
    _push(ws, roots[lead], run_id, ["brief.md", "plan.md"] + produced)
    rel_res = f"teamwork/{run_id}/result.md"
    failed = [f"S{s['n']}" for s in subtasks if s["status"] != "done"]
    tid = loop.Agent(roots[lead]).add_task(
        "librarian",
        f"TEAM SYNTHESIS for run {run_id}. All specialist outputs are in your "
        f"context. Combine them into ONE coherent deliverable that answers the "
        f"brief, written to {rel_res}. Keep every specialist's citations."
        + (f" Note plainly that {', '.join(failed)} failed and what is missing."
           if failed else "")
        + (f" The brief's binding constraints are in your context; verify the "
           f"combined deliverable satisfies EVERY one and echo the line "
           f"`CONSTRAINT-DIGEST: {cdigest}` in it."
           if cdigest else "")
        + (f" WARNING: {', '.join(record['digest_losses'])} did not echo the "
           f"constraint digest — re-check their work against the constraints "
           f"specifically before combining it."
           if record["digest_losses"] else ""),
        memory_files=[f"teamwork/{run_id}/{n}" for n in
                      (["brief.md", "plan.md"] + produced)],
        done_check=_exists_check(rel_res))
    t = _wait_task(roots[lead], tid, drive, timeout)
    ok = t["status"] == "done" and _pull(ws, roots[lead], run_id, "result.md")
    if ok and cdigest:
        with open(os.path.join(ws, "result.md"), "r", encoding="utf-8",
                  errors="replace") as f:
            record["result_digest_echoed"] = \
                f"CONSTRAINT-DIGEST: {cdigest}" in f.read()
    record.update(
        status=("done" if ok and not failed else
                "done_with_failures" if ok else "failed"),
        result=os.path.join("teamwork", run_id, "result.md") if ok else None,
        finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
    _record(ws, record)
    print(f"[team {run_id}] {record['status']}"
          + (f" -> {os.path.join(ws, 'result.md')}" if ok else ""))
    return record


def list_runs(home):
    base = os.path.join(home, "teamwork")
    out = []
    if os.path.isdir(base):
        for rid in sorted(os.listdir(base), reverse=True):
            p = os.path.join(base, rid, "team.json")
            try:
                with open(p, "r", encoding="utf-8") as f:
                    out.append(json.load(f))
            except (OSError, json.JSONDecodeError):
                continue
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("goal")
    p.add_argument("--experts", required=True,
                   help="comma-separated expert slugs, e.g. a,b,c")
    p.add_argument("--lead", default=None)
    p.add_argument("--id", default=None, dest="run_id")
    p.add_argument("--no-drive", action="store_true",
                   help="rely on already-running expert daemons instead of "
                        "driving drain loops")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("list")
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("result")
    p.add_argument("run_id")
    p.add_argument("--home", default=HOME)
    args = ap.parse_args()

    if args.cmd == "run":
        run_team(args.home, args.goal,
                 [s.strip() for s in args.experts.split(",") if s.strip()],
                 args.lead, args.run_id, drive=not args.no_drive,
                 timeout=args.timeout)
    elif args.cmd == "list":
        for r in list_runs(args.home):
            subs = "".join("✓" if s["status"] == "done" else "✗"
                           for s in r.get("subtasks", []))
            print(f"{r['id']}  {r['status']:<20} lead={r['lead']:<18} "
                  f"[{subs}]  {r['goal'][:60]}")
    elif args.cmd == "result":
        p = os.path.join(args.home, "teamwork", args.run_id, "result.md")
        with open(p, "r", encoding="utf-8") as f:
            print(f.read())


if __name__ == "__main__":
    main()
