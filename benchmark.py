#!/usr/bin/env python3
"""Lift benchmark — what does the harness actually add to the rented model?

The claim worth defending is that scaffolding turns a model's per-call ability
into system capability it cannot have alone. That claim is only worth anything
if it is MEASURED, on the same model, on the same tasks, with only the harness
varying. This runs both arms and reports the multiplier.

  ARM A — BARE      one model call. No gates, no retries, no verification, no
                    memory. What the model alone produces, accepted as-is.
                    (This is what "just use the model" actually means.)
  ARM B — HARNESS   the same model inside the loop: definition-of-done gate,
                    retries with the error in hand, escalation, memory, and
                    mechanical verification.

Both arms are scored by the SAME mechanical checks — exit codes, not opinions:

  pass_rate         the check passed
  false_success     it CLAIMED done while the check failed (the failure mode
                    that makes an unharnessed agent dangerous)
  constraint_kept   the task's hard constraints survived into the output
  cost_usd, seconds what the lift actually cost

Honest reporting: lift is printed with the sample size, and a run of 5 trials
is reported as a run of 5 trials — never as a law of nature.

Usage:
  python benchmark.py run --expert <slug> [--repeat 3] [--home DIR]
  python benchmark.py suite            # show the trials
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
import loop           # noqa: E402

PY = sys.executable

# Each trial: a real task, a MECHANICAL check, and constraints that must
# survive. Deliberately small and checkable — the point is measuring the
# harness, not benchmarking model IQ.
SUITE = [
    {
        "id": "T1-artifact",
        "task": ("Write a file bench/out/config.json containing a JSON object "
                 "with exactly the keys \"name\" and \"retries\", where "
                 "retries is the number 5. It must be valid JSON."),
        "check": ("import json,sys;d=json.load(open('bench/out/config.json'));"
                  "sys.exit(0 if set(d)=={'name','retries'} and d['retries']==5 else 1)"),
        "constraints": ["exactly the keys", "must be valid JSON"],
    },
    {
        "id": "T2-constraint",
        "task": ("Write bench/out/notice.txt. It must contain the word "
                 "APPROVED and must never contain the word DRAFT."),
        "check": ("import sys;t=open('bench/out/notice.txt',encoding='utf-8').read();"
                  "sys.exit(0 if 'APPROVED' in t and 'DRAFT' not in t else 1)"),
        "constraints": ["must contain the word APPROVED", "must never contain"],
    },
    {
        "id": "T3-evidence",
        "task": ("Write bench/out/claim.md stating one claim, and it must "
                 "carry a citation in square brackets like [src: file line]."),
        "check": ("import re,sys;t=open('bench/out/claim.md',encoding='utf-8').read();"
                  "sys.exit(0 if re.search(r'\\[src:[^\\]]+\\]',t) else 1)"),
        "constraints": ["must carry a citation"],
    },
]


def check_cmd(check):
    return f'"{PY}" -c "{check}"'


def run_check(root, check):
    """The benchmark's own acceptance check. It grades BOTH arms, so it runs
    through the Execution Authority like any other gate — a measurement path
    that skipped containment would be a measurement path worth attacking."""
    try:
        import execution
        rc, _out, _err = execution.run("gate", check_cmd(check), root,
                                       role="examiner", timeout=60,
                                       reason="benchmark acceptance check")
        return rc == 0
    except Exception:
        return False


def clean(root):
    import shutil
    shutil.rmtree(os.path.join(root, "bench", "out"), ignore_errors=True)
    os.makedirs(os.path.join(root, "bench", "out"), exist_ok=True)


# ------------------------------------------------------------------ arm A

def bare_arm(agent, root, trial):
    """One model call, output accepted as-is — no gate, no retry, no check."""
    clean(root)
    t0 = time.time()
    messages = [
        {"role": "system", "content":
         "You are a capable assistant with file-writing ability. Respond with "
         "exactly one tool call as JSON: {\"tool\": \"write_file\", "
         "\"args\": {\"path\": ..., \"content\": ...}}."},
        {"role": "user", "content": trial["task"]},
    ]
    claimed, cost = True, 0.0
    try:
        msg, usage, _ = agent.call_model("practitioner", messages,
                                         purpose="benchmark")
        cost = agent._cost("practitioner", usage)
        calls = msg.get("tool_calls") or []
        if not calls:
            tc = loop.parse_content_tool_call(msg.get("content"))
            calls = [tc] if tc else []
        if calls:
            name = calls[0]["function"]["name"]
            args = json.loads(calls[0]["function"]["arguments"] or "{}")
            if name == "write_file":
                agent.exec_tool({"id": "bare", "role": "practitioner",
                                 "steps": []}, "write_file", args)
        else:
            claimed = False        # produced no artifact at all
    except Exception:
        claimed = False
    ok = run_check(root, trial["check"])
    return {"arm": "bare", "trial": trial["id"], "passed": ok,
            "claimed_done": claimed, "false_success": claimed and not ok,
            "constraint_kept": constraints_kept(root, trial),
            "cost_usd": round(cost, 6), "seconds": round(time.time() - t0, 2)}


def constraints_kept(root, trial):
    """Did the produced artifact actually honour the stated constraints?"""
    out = os.path.join(root, "bench", "out")
    text = ""
    for dirpath, _, files in os.walk(out):
        for fn in files:
            try:
                with open(os.path.join(dirpath, fn), "r", encoding="utf-8",
                          errors="replace") as f:
                    text += f.read()
            except OSError:
                pass
    if not text.strip():
        return False
    # the check IS the operational form of the constraints
    return run_check(root, trial["check"])


# ------------------------------------------------------------------ arm B

def harness_arm(agent, root, trial, timeout=600):
    """The same model inside the loop: gated, retried, verified."""
    clean(root)
    t0 = time.time()
    tid = agent.add_task(
        "practitioner",
        trial["task"] + "\nProduce the file, then finish_task.",
        done_check=check_cmd(trial["check"]))
    proc = subprocess.Popen(
        [PY, os.path.join(HOME, "loop.py"), "run", "--drain", "--root", root],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUTF8": "1"})
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
    t = agent.find_task(tid) or {}
    ok = run_check(root, trial["check"])
    claimed = t.get("status") == "done"
    return {"arm": "harness", "trial": trial["id"], "passed": ok,
            "claimed_done": claimed,
            # a gated task cannot claim done while its check fails — that is
            # the whole point, and this measures whether it held
            "false_success": claimed and not ok,
            "constraint_kept": constraints_kept(root, trial),
            "refusals": t.get("done_rejects", 0),
            "attempts": t.get("attempt", 1),
            "cost_usd": round(t.get("cost_usd", 0), 6),
            "seconds": round(time.time() - t0, 2)}


# ------------------------------------------------------------------ report

def summarize(rows):
    out = {}
    for arm in ("bare", "harness"):
        a = [r for r in rows if r["arm"] == arm]
        n = len(a) or 1
        out[arm] = {
            "trials": len(a),
            "pass_rate": round(sum(r["passed"] for r in a) / n, 3),
            "false_success_rate": round(sum(r["false_success"] for r in a) / n, 3),
            "constraint_kept_rate": round(sum(r["constraint_kept"] for r in a) / n, 3),
            "cost_usd": round(sum(r["cost_usd"] for r in a), 4),
            "seconds": round(sum(r["seconds"] for r in a), 1),
        }
    b, h = out["bare"], out["harness"]
    lift = {
        "pass_rate_multiplier": (round(h["pass_rate"] / b["pass_rate"], 2)
                                 if b["pass_rate"] else None),
        "false_success_removed": round(b["false_success_rate"] -
                                       h["false_success_rate"], 3),
        "cost_multiplier": (round(h["cost_usd"] / b["cost_usd"], 2)
                            if b["cost_usd"] else None),
    }
    return {"arms": out, "lift": lift, "n": len(rows) // 2}


def report(summary):
    a, l = summary["arms"], summary["lift"]
    print("\n" + "=" * 64)
    print(f"LIFT BENCHMARK — same model, same tasks, {summary['n']} trial(s) per arm")
    print("=" * 64)
    print(f"{'':<22}{'BARE MODEL':>16}{'IN HARNESS':>16}")
    for k, label in (("pass_rate", "pass rate"),
                     ("false_success_rate", "false 'done'"),
                     ("constraint_kept_rate", "constraints kept"),
                     ("cost_usd", "cost (USD)"),
                     ("seconds", "wall time (s)")):
        print(f"{label:<22}{a['bare'][k]:>16}{a['harness'][k]:>16}")
    print("-" * 64)
    if l["pass_rate_multiplier"] is not None:
        print(f"pass-rate multiplier: {l['pass_rate_multiplier']}x")
    else:
        print("pass-rate multiplier: undefined (bare arm passed 0 — the honest "
              "reading is 'the model alone could not do these at all')")
    print(f"false 'done' eliminated: {l['false_success_removed']:+.3f} "
          f"(the failure mode that makes an unharnessed agent unsafe)")
    if l["cost_multiplier"]:
        print(f"cost of the lift: {l['cost_multiplier']}x tokens")
    print(f"\nSample size: {summary['n']} trial(s) per arm. This is a "
          f"measurement, not a law — re-run it on YOUR models and YOUR tasks "
          f"before quoting any number.")
    print("=" * 64)


def run(home, expert, repeat=1, timeout=600):
    root = os.path.join(home, "experts", expert)
    if not os.path.isdir(root):
        sys.exit(f"ERROR: no expert '{expert}'")
    agent = loop.Agent(root)
    rows = []
    for _ in range(repeat):
        for trial in SUITE:
            rows.append(bare_arm(agent, root, trial))
            print(f"  bare    {trial['id']:<16} "
                  f"{'PASS' if rows[-1]['passed'] else 'fail'}")
            rows.append(harness_arm(agent, root, trial, timeout))
            r = rows[-1]
            print(f"  harness {trial['id']:<16} "
                  f"{'PASS' if r['passed'] else 'fail'}"
                  f"{f'  (refused {r[chr(114)+chr(101)+chr(102)+chr(117)+chr(115)+chr(97)+chr(108)+chr(115)]}x)' if r.get('refusals') else ''}")
    s = summarize(rows)
    s["rows"] = rows
    with open(os.path.join(root, "bench", "results.json"), "w",
              encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--expert", required=True)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--home", default=HOME)
    sub.add_parser("suite")
    args = ap.parse_args()
    if args.cmd == "suite":
        for t in SUITE:
            print(f"{t['id']}\n  task:  {t['task']}\n  check: {t['check'][:90]}\n")
        return
    report(run(args.home, args.expert, args.repeat, args.timeout))


if __name__ == "__main__":
    main()
