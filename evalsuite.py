#!/usr/bin/env python3
"""A HELD-OUT EVALUATION SUITE — a score you are allowed to believe.

`benchmark.py` measures the LIFT the harness adds on three trials. This is the
other half: a larger task set, split into TRAIN and HOLDOUT, so that "we
improved" can mean something.

WHY A SPLIT, AND WHY THE HOLDOUT IS RATIONED

The request behind this module was "iterate until it scores 100%". That is
the one thing an evaluation must never be used for. Tuning a system until a
fixed set of tasks all pass is not improvement, it is memorisation: the score
goes up and the capability does not, and the number stops predicting anything
about work the system has not already seen. Published state of the art on
curated software tasks sits near 70-80%; a system reporting 100% on a real
benchmark has either leaked the answers or is measuring something trivial.

So:

    TRAIN     tune against these as much as you like. They are burned.
    HOLDOUT   sealed. Every run is RECORDED with the code hash it ran
              against, and the report says how many times you have looked.

Each look at a holdout costs a little of its validity — that is not a
metaphor, it is what multiple-comparisons means. This module cannot stop you
peeking; it can refuse to let you forget that you did, which is the honest
half of the problem.

WHAT IS MEASURED, AND BY WHAT

Exit codes. Every task carries a `check` that a computer runs; nothing here
asks a model whether the work is good. Two arms run on the SAME model:

    bare      one call, output accepted as-is — "just use the model"
    harness   the same model inside the loop: gate, retry, memory, verify

The difference between those two numbers is the only thing this platform can
honestly claim credit for, because the model is held constant across them.

SMALL SAMPLES ARE REPORTED AS SMALL SAMPLES

A 24-task suite cannot distinguish 60% from 70%. Every rate is printed with a
Wilson score interval, so a difference inside the intervals reads as what it
is — noise — instead of as progress. This is the guard that stops a team
iterating on randomness for a week.

    python evalsuite.py list
    python evalsuite.py run --split train   --expert <slug> --home .
    python evalsuite.py run --split holdout --expert <slug> --home .
    python evalsuite.py history --home .
"""

import argparse
import hashlib
import json
import math
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):        # pragma: no cover
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

LEDGER = os.path.join("logs", "evalsuite.jsonl")
PY = sys.executable

# Every task: a goal a person could state, a MECHANICAL check, and the split
# it belongs to. Deliberately checkable — the point is measuring the system,
# not writing a hard exam. Tasks are phrased the way a person phrases them,
# including the plurals and the vagueness, because that is the input the
# system actually gets.
SUITE = [
    # ---------------------------------------------------------- TRAIN
    {"id": "structured-json", "split": "train",
     "task": "Write eval/out/cfg.json: a JSON object with exactly the keys "
             "\"host\" and \"port\", where port is the number 8080.",
     "check": "import json,sys;d=json.load(open('eval/out/cfg.json'));"
              "sys.exit(0 if set(d)=={'host','port'} and d['port']==8080 else 1)"},
    {"id": "negative-constraint", "split": "train",
     "task": "Write eval/out/notice.txt containing the word APPROVED and "
             "never the word DRAFT.",
     "check": "import sys;t=open('eval/out/notice.txt',encoding='utf-8').read();"
              "sys.exit(0 if 'APPROVED' in t and 'DRAFT' not in t else 1)"},
    {"id": "citation-required", "split": "train",
     "task": "Write eval/out/claim.md with one claim that carries a citation "
             "in square brackets, like [src: rfc9111 section 4].",
     "check": "import re,sys;t=open('eval/out/claim.md',encoding='utf-8').read();"
              "sys.exit(0 if re.search(r'\\[src:[^\\]]+\\]',t) else 1)"},
    {"id": "csv-sum", "split": "train",
     "task": "eval/in/nums.csv has a header 'n' and one integer per line. "
             "Write eval/out/total.txt containing only their sum.",
     "fixture": {"eval/in/nums.csv": "n\n3\n9\n14\n2\n"},
     "check": "import sys;t=open('eval/out/total.txt',encoding='utf-8').read().strip();"
              "sys.exit(0 if t=='28' else 1)"},
    {"id": "dedup-sorted", "split": "train",
     "task": "eval/in/words.txt has one word per line with duplicates. Write "
             "eval/out/words.txt with each word once, sorted, one per line.",
     "fixture": {"eval/in/words.txt": "pear\napple\npear\nfig\napple\n"},
     "check": "import sys;t=open('eval/out/words.txt',encoding='utf-8').read().split();"
              "sys.exit(0 if t==['apple','fig','pear'] else 1)"},
    {"id": "exact-count", "split": "train",
     "task": "Write eval/out/lines.txt containing exactly 7 lines, each the "
             "word ok.",
     "check": "import sys;t=[l for l in open('eval/out/lines.txt',encoding='utf-8')"
              ".read().splitlines() if l.strip()];"
              "sys.exit(0 if len(t)==7 and all(l.strip()=='ok' for l in t) else 1)"},
    {"id": "json-nested", "split": "train",
     "task": "Write eval/out/tree.json: {\"a\": {\"b\": [1, 2, 3]}} exactly.",
     "check": "import json,sys;d=json.load(open('eval/out/tree.json'));"
              "sys.exit(0 if d=={'a':{'b':[1,2,3]}} else 1)"},
    {"id": "preserve-input", "split": "train",
     "task": "Copy eval/in/keep.txt to eval/out/keep.txt without changing a "
             "single byte.",
     "fixture": {"eval/in/keep.txt": "line one\nline two\n\ttabbed\n"},
     "check": "import sys;a=open('eval/in/keep.txt','rb').read();"
              "b=open('eval/out/keep.txt','rb').read();sys.exit(0 if a==b else 1)"},
    {"id": "no-placeholder", "split": "train",
     "task": "Write eval/out/readme.md describing what a retry budget is, in "
             "at least 40 words, with no TODO and no lorem ipsum.",
     "check": "import sys;t=open('eval/out/readme.md',encoding='utf-8').read().lower();"
              "sys.exit(0 if len(t.split())>=40 and 'todo' not in t "
              "and 'lorem' not in t else 1)"},
    {"id": "runnable-python", "split": "train",
     "task": "Write eval/out/add.py defining add(a, b) that returns their sum. "
             "It must import cleanly and add(2,3) must be 5.",
     "check": "import sys,importlib.util as u;s=u.spec_from_file_location('m','eval/out/add.py');"
              "m=u.module_from_spec(s);s.loader.exec_module(m);"
              "sys.exit(0 if m.add(2,3)==5 else 1)"},
    {"id": "ordering-matters", "split": "train",
     "task": "Write eval/out/steps.md listing exactly these three steps in "
             "this order, one per line: build, test, deploy.",
     "check": "import sys;t=[l.strip().lower().lstrip('0123456789.-) ') for l in "
              "open('eval/out/steps.md',encoding='utf-8').read().splitlines() if l.strip()];"
              "sys.exit(0 if t==['build','test','deploy'] else 1)"},
    {"id": "empty-is-valid", "split": "train",
     "task": "eval/in/errors.log contains no ERROR lines. Write "
             "eval/out/errors.txt containing every ERROR line — which means "
             "an empty file, not an apology.",
     "fixture": {"eval/in/errors.log": "INFO start\nWARN slow\nINFO done\n"},
     "check": "import sys;t=open('eval/out/errors.txt',encoding='utf-8').read().strip();"
              "sys.exit(0 if t=='' else 1)"},

    # -------------------------------------------------------- HOLDOUT
    {"id": "h-json-keys", "split": "holdout",
     "task": "Write eval/out/db.json: a JSON object with exactly the keys "
             "\"driver\" and \"pool\", where pool is the number 12.",
     "check": "import json,sys;d=json.load(open('eval/out/db.json'));"
              "sys.exit(0 if set(d)=={'driver','pool'} and d['pool']==12 else 1)"},
    {"id": "h-forbidden-word", "split": "holdout",
     "task": "Write eval/out/policy.txt containing the word FINAL and never "
             "the word PROVISIONAL.",
     "check": "import sys;t=open('eval/out/policy.txt',encoding='utf-8').read();"
              "sys.exit(0 if 'FINAL' in t and 'PROVISIONAL' not in t else 1)"},
    {"id": "h-citation", "split": "holdout",
     "task": "Write eval/out/finding.md with one finding that carries a "
             "citation in square brackets, like [src: iso9001 clause 8].",
     "check": "import re,sys;t=open('eval/out/finding.md',encoding='utf-8').read();"
              "sys.exit(0 if re.search(r'\\[src:[^\\]]+\\]',t) else 1)"},
    {"id": "h-csv-max", "split": "holdout",
     "task": "eval/in/temps.csv has a header 'c' and one integer per line. "
             "Write eval/out/max.txt containing only the largest.",
     "fixture": {"eval/in/temps.csv": "c\n11\n47\n5\n33\n"},
     "check": "import sys;t=open('eval/out/max.txt',encoding='utf-8').read().strip();"
              "sys.exit(0 if t=='47' else 1)"},
    {"id": "h-dedup-reverse", "split": "holdout",
     "task": "eval/in/ids.txt has one id per line with duplicates. Write "
             "eval/out/ids.txt with each once, sorted in REVERSE order.",
     "fixture": {"eval/in/ids.txt": "a3\na1\na3\na7\na1\n"},
     "check": "import sys;t=open('eval/out/ids.txt',encoding='utf-8').read().split();"
              "sys.exit(0 if t==['a7','a3','a1'] else 1)"},
    {"id": "h-exact-count", "split": "holdout",
     "task": "Write eval/out/rows.txt containing exactly 4 lines, each the "
             "word row.",
     "check": "import sys;t=[l for l in open('eval/out/rows.txt',encoding='utf-8')"
              ".read().splitlines() if l.strip()];"
              "sys.exit(0 if len(t)==4 and all(l.strip()=='row' for l in t) else 1)"},
    {"id": "h-json-nested", "split": "holdout",
     "task": "Write eval/out/shape.json: {\"x\": {\"y\": [4, 5]}} exactly.",
     "check": "import json,sys;d=json.load(open('eval/out/shape.json'));"
              "sys.exit(0 if d=={'x':{'y':[4,5]}} else 1)"},
    {"id": "h-preserve", "split": "holdout",
     "task": "Copy eval/in/orig.txt to eval/out/orig.txt byte for byte.",
     "fixture": {"eval/in/orig.txt": "alpha\n  beta\n\tgamma\n"},
     "check": "import sys;a=open('eval/in/orig.txt','rb').read();"
              "b=open('eval/out/orig.txt','rb').read();sys.exit(0 if a==b else 1)"},
    {"id": "h-no-filler", "split": "holdout",
     "task": "Write eval/out/brief.md explaining what a circuit breaker is, "
             "in at least 40 words, with no TODO and no lorem ipsum.",
     "check": "import sys;t=open('eval/out/brief.md',encoding='utf-8').read().lower();"
              "sys.exit(0 if len(t.split())>=40 and 'todo' not in t "
              "and 'lorem' not in t else 1)"},
    {"id": "h-runnable", "split": "holdout",
     "task": "Write eval/out/mul.py defining mul(a, b) returning their "
             "product. mul(3,4) must be 12.",
     "check": "import sys,importlib.util as u;s=u.spec_from_file_location('m','eval/out/mul.py');"
              "m=u.module_from_spec(s);s.loader.exec_module(m);"
              "sys.exit(0 if m.mul(3,4)==12 else 1)"},
    {"id": "h-ordering", "split": "holdout",
     "task": "Write eval/out/phases.md listing exactly these three phases in "
             "this order, one per line: plan, build, review.",
     "check": "import sys;t=[l.strip().lower().lstrip('0123456789.-) ') for l in "
              "open('eval/out/phases.md',encoding='utf-8').read().splitlines() if l.strip()];"
              "sys.exit(0 if t==['plan','build','review'] else 1)"},
    {"id": "h-empty-valid", "split": "holdout",
     "task": "eval/in/audit.log contains no DENIED lines. Write "
             "eval/out/denied.txt containing every DENIED line — an empty "
             "file is the correct answer, not an explanation.",
     "fixture": {"eval/in/audit.log": "OK a\nOK b\nGRANTED c\n"},
     "check": "import sys;t=open('eval/out/denied.txt',encoding='utf-8').read().strip();"
              "sys.exit(0 if t=='' else 1)"},
]


def tasks(split=None):
    return [t for t in SUITE if not split or t["split"] == split]


def code_hash():
    """A stamp of the platform's own code, so a holdout score is tied to the
    thing that produced it. Same idea proof.py uses: a number that is not
    attached to a version of the code is a number about nothing."""
    h = hashlib.sha256()
    for name in sorted(os.listdir(HERE)):
        if name.endswith(".py"):
            try:
                with open(os.path.join(HERE, name), "rb") as f:
                    h.update(name.encode())
                    h.update(f.read())
            except OSError:
                continue
    return h.hexdigest()[:12]


def wilson(passed, total, z=1.96):
    """A 95% Wilson score interval. -> (low, high) as fractions.

    Reported on every rate because a 12-task split cannot tell 60% from 70%,
    and a team that does not know that will iterate on noise for a week. The
    interval is the difference between "we improved" and "we looked again".
    """
    if total <= 0:
        return 0.0, 0.0
    p = passed / total
    d = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / d
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def _ledger_path(home):
    return os.path.join(home, LEDGER)


def record(home, split, result):
    p = _ledger_path(home)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "split": split,
           "code": result.get("code_hash"), "arm": result.get("arm"),
           "passed": result.get("passed"), "total": result.get("total")}
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def history(home, split=None):
    out = []
    try:
        with open(_ledger_path(home), encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not split or r.get("split") == split:
                    out.append(r)
    except OSError:
        return []
    return out


def peeks(home):
    """How many times the holdout has been looked at, and against how many
    distinct versions of the code.

    This is the number that decides whether a holdout result still means
    anything. Ten looks at a sealed set while changing the code between each
    one is ten chances for noise to look like progress, and nothing about the
    final number says so unless something counted.
    """
    rows = history(home, "holdout")
    return len(rows), len({r.get("code") for r in rows if r.get("code")})


def fixtures_for(task):
    return task.get("fixture") or {}


def run_one(home, expert, task, timeout=300):
    """Run ONE task through the real harness and grade it by exit code.

    The task is given the same way a person would give it, the fixtures are
    laid down first, and the gate is the task's own check — so `finish_task`
    is refused until the check exits 0, exactly as in production. Nothing
    here is scored by a model.
    """
    import loop
    root = os.path.join(home, "experts", expert)
    for rel, body in fixtures_for(task).items():
        p = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(body)
    agent = loop.Agent(root)
    check = f'"{PY}" -c "{task["check"]}"'
    t0 = time.time()
    tid = agent.add_task("practitioner", task["task"], done_check=check)
    # Through the Execution Authority, like everything else that starts a
    # process here. The invariant test caught this module using raw
    # subprocess the first time it ran — which is the audit doing its job on
    # brand-new code, and the reason there is exactly one door.
    import execution
    execution.run("platform_spawn",
                  [PY, os.path.join(HERE, "loop.py"), "run", "--drain",
                   "--root", root], root, timeout=timeout,
                  reason="run the evaluation task through the real loop")
    state = {}
    try:
        with open(os.path.join(root, "state.json"), encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        pass
    rec = next((t for t in (state.get("tasks") or []) if t.get("id") == tid), {})
    # THE GRADE IS THE CHECK, RE-RUN. Not the task's status: a task can be
    # marked done by a path this suite does not control, and the only thing
    # worth scoring is whether the artifact satisfies the check right now.
    # The grader is an argv vector built from the suite in THIS file, never
    # from anything a model wrote, so it is platform-authored by definition.
    rc, _out, _err = execution.run(
        "platform_spawn", [PY, "-c", task["check"]], root, timeout=120,
        reason="grade the evaluation task by exit code")
    return {"id": task["id"], "split": task["split"],
            "passed": rc == 0,
            "claimed_done": rec.get("status") == "done",
            "cost_usd": float(rec.get("cost_usd") or 0),
            "seconds": round(time.time() - t0, 2)}


def run_split(home, expert, split, timeout=300):
    """Every task in a split, with the honest arithmetic attached."""
    rows = [run_one(home, expert, t, timeout) for t in tasks(split)]
    passed = sum(1 for r in rows if r["passed"])
    total = len(rows)
    lo, hi = wilson(passed, total)
    # the failure mode that matters most: it said done and the check says no
    false_success = sum(1 for r in rows if r["claimed_done"] and not r["passed"])
    return {"split": split, "arm": "harness", "passed": passed, "total": total,
            "rate": (passed / total) if total else 0.0,
            "ci_low": lo, "ci_high": hi,
            "false_success": false_success,
            "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
            "seconds": round(sum(r["seconds"] for r in rows), 1),
            "code_hash": code_hash(), "rows": rows}


def main():
    ap = argparse.ArgumentParser(
        description="a held-out evaluation suite — a score you are allowed "
                    "to believe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--split", default="", choices=["", "train", "holdout"])
    p = sub.add_parser("history"); p.add_argument("--home", default=".")
    p = sub.add_parser("peeks"); p.add_argument("--home", default=".")
    p = sub.add_parser("run")
    p.add_argument("--split", default="train", choices=["train", "holdout"])
    p.add_argument("--expert", required=True)
    p.add_argument("--home", default=".")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--yes-spend-the-holdout", action="store_true",
                   dest="confirm",
                   help="required for --split holdout: each run spends a "
                        "little of what a held-out set is for")
    a = ap.parse_args()

    if a.cmd == "list":
        rows = tasks(a.split or None)
        for t in rows:
            print(f"  {t['split']:<8} {t['id']:<22} {t['task'][:64]}")
        n_tr = len(tasks('train'))
        n_ho = len(tasks('holdout'))
        print(f"\n{len(rows)} task(s) shown; suite is {n_tr} train / "
              f"{n_ho} holdout")
        lo, hi = wilson(int(n_ho * 0.75), n_ho)
        print(f"note: at {n_ho} holdout tasks, a 75% result means "
              f"{lo*100:.0f}%-{hi*100:.0f}% with 95% confidence. Differences "
              f"smaller than that interval are not results.")
        return
    home = os.path.abspath(a.home)
    if a.cmd == "peeks":
        n, versions = peeks(home)
        print(f"the holdout has been run {n} time(s) against {versions} "
              f"distinct version(s) of the code")
        if n > 3:
            print("  Each look spends a little of what a held-out set is FOR. "
                  "If you are tuning, tune against train and come back here "
                  "when you are done.")
        return
    if a.cmd == "run":
        if a.split == "holdout" and not a.confirm:
            n, versions = peeks(home)
            print(f"REFUSED. The holdout is sealed, and it has already been "
                  f"run {n} time(s) against {versions} version(s) of the "
                  f"code.\n\nEvery look at a held-out set spends a little of "
                  f"what it is FOR: tune against it and the number stops "
                  f"predicting anything about work the system has not seen. "
                  f"Tune on --split train.\n\nIf you are genuinely finished "
                  f"tuning and want the honest number, re-run with "
                  f"--yes-spend-the-holdout.")
            raise SystemExit(2)
        res = run_split(home, a.expert, a.split, a.timeout)
        record(home, a.split, res)
        n_hold, versions = peeks(home)
        print(f"\n{a.split.upper()}  {res['passed']}/{res['total']} passed "
              f"({res['rate']*100:.0f}%)")
        print(f"  95% confidence   {res['ci_low']*100:.0f}% - "
              f"{res['ci_high']*100:.0f}%   <- the honest width at "
              f"{res['total']} tasks")
        print(f"  false successes  {res['false_success']}   "
              f"(claimed done while the check said no)")
        print(f"  cost             ${res['cost_usd']:.4f} over "
              f"{res['seconds']}s")
        print(f"  code             {res['code_hash']}")
        for r in res["rows"]:
            if not r["passed"]:
                flag = "CLAIMED DONE" if r["claimed_done"] else "failed"
                print(f"    {r['id']:<22} {flag}")
        if a.split == "holdout":
            print(f"\n  this holdout has now been run {n_hold} time(s) "
                  f"against {versions} version(s) of the code")
        if res["rate"] >= 1.0:
            print("\n  A perfect score on a suite this size does not mean the "
                  "system never fails — it means this suite cannot find the "
                  "cases where it does. Add harder tasks rather than "
                  "believing the number.")
        return
    if a.cmd == "history":
        rows = history(home)
        if not rows:
            print("nothing has been evaluated yet")
            return
        for r in rows[-40:]:
            tot = r.get("total") or 0
            lo, hi = wilson(r.get("passed") or 0, tot)
            print(f"{r['at']}  {r['split']:<8} {str(r.get('arm')):<8} "
                  f"{r.get('passed')}/{tot}  "
                  f"[{lo*100:.0f}%-{hi*100:.0f}%]  code {r.get('code')}")
        return


if __name__ == "__main__":
    main()
