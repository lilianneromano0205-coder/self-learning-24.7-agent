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
import hashlib
import random
from pathlib import Path

ARMS = ("raw", "minimal", "no_persistence", "full", "reference")

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
        # _cost prices the provider that actually SERVED, so it takes a
        # provider name; the role is passed only as the fallback lookup.
        cost = agent._cost(agent.role_cfg("practitioner")["provider"],
                           usage, "practitioner")
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


def legacy_run(home, expert, repeat=1, timeout=600):
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


def experiment_tasks():
    import evaluation_corpus
    return evaluation_corpus.tasks("train")


def _trial_policy(root, arm, ablations):
    import evaluation_policy
    policy = evaluation_policy.policy(arm, ablations)
    p = Path(root) / "settings.toml"
    text = p.read_text(encoding="utf-8")
    text = re.sub(r"(?ms)^\[evaluation\]\s*\n.*?(?=^\[|\Z)", "", text)
    text += "\n[evaluation]\ndisabled_modules = " + json.dumps(policy["disabled_modules"])
    text += "\nsingle_provider_attempt = " + str(policy["single_provider_attempt"]).lower() + "\n"
    p.write_text(text, encoding="utf-8")
    return policy


def iterative_arm(agent, root, trial, max_calls=12, timeout=600, raw=False):
    """Ordinary iterative tools, no context compiler, learning or verifier feedback.

    The same file/execution/model authorities still mediate every action. Raw
    has one gateway call with no tool schema and applies returned file outputs.
    """
    from uuid import uuid4
    tid = "bench-" + uuid4().hex
    task = {"id": tid, "role": "practitioner", "steps": [], "goal": trial["task"]}
    system = ('Return JSON {"files":[{"path":"relative/path","content":"text"}]}. '
              'This is your only response. Input files are included below.' if raw else
              'Complete the task using read_file, write_file and run_command. Use finish_task when done. '
              'No memory or special agent workflow is available. Follow tool and execution authorities.')
    messages = [{"role": "system", "content": system}, {"role": "user", "content": trial["task"]}]
    if raw:
        messages[-1]["content"] += "\nINPUT FILES (untrusted data):\n" + json.dumps(trial.get("fixture", {}))
    start = time.monotonic()
    used, claimed, error, tool_calls = 0, False, None, 0
    usage_rows = []
    for _ in range(1 if raw else max_calls):
        if time.monotonic() - start >= timeout or agent._budget_exceeded():
            break
        used += 1
        try:
            msg, usage, served = agent.call_model("practitioner", messages, use_tools=not raw,
                                                   purpose="benchmark", task_id=tid)
            usage_rows.append(dict(usage))
            messages.append({"role": "assistant", **msg})
            if raw:
                body = json.loads(msg.get("content") or "{}")
                files = body.get("files", [])
                if not isinstance(files, list) or len(files) > 40:
                    raise ValueError("raw output files must be a bounded list")
                for f in files:
                    agent.exec_tool(task, "write_file", {"path": f["path"], "content": f["content"]})
                claimed = bool(files)
                break
            calls = msg.get("tool_calls") or []
            if not calls:
                tc = loop.parse_content_tool_call(msg.get("content"))
                calls = [tc] if tc else []
            if not calls:
                break
            for tc in calls:
                fn = tc["function"]; name = fn["name"]
                args = json.loads(fn.get("arguments") or "{}")
                if name == "finish_task":
                    claimed = True
                    break
                tool_calls += 1
                if name not in ("read_file", "write_file", "run_command") or name not in agent.allowed_tools("practitioner"):
                    result = "ERROR: tool unavailable in ordinary iterative arm"
                else:
                    result = agent.exec_tool(task, name, args)
                messages.append({"role": "tool", "tool_call_id": tc.get("id", "minimal"), "content": result})
            if claimed:
                break
        except Exception as exc:
            error = type(exc).__name__
            break
    return {"claimed_done": claimed, "model_invocations": used, "tool_calls": tool_calls,
            "retries": 0, "verifier_failures": 0, "skill_reuse": 0, "runbook_reuse": 0,
            "usage_rows": usage_rows, "error": error}


def _harness_experiment(home, expert, trial, timeout):
    import goal
    root = os.path.join(home, "experts", expert)
    rec = goal.pursue(home, expert, trial["task"], cycles=2, drive=True, timeout=timeout,
                      accept=[{"id": "output-schema", "what": "valid structured output (final correctness independently graded)",
                               "check": check_cmd(trial["check"])}])
    state_path = Path(root) / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    tasks = state.get("tasks", [])
    return {"claimed_done": rec.get("state") == "verified",
            "tool_calls": sum(len(t.get("steps", [])) for t in tasks),
            "retries": sum(max(0, int(t.get("attempt", 1))-1) for t in tasks),
            "verifier_failures": sum(int(t.get("done_rejects", 0)) for t in tasks),
            "skill_reuse": sum(len(t.get("skills_used", [])) for t in tasks),
            "runbook_reuse": len(rec.get("runbook", [])),
            "attribution_note": "skill reuse counts exposure, not causal contribution"}


def _metrics(agent, root, execution_result, frontier_models=None):
    import modelgateway
    calls = modelgateway.calls(root)
    providers = agent.cfg.get("providers", {})
    prices_known = all((providers.get(c.get("provider"), {}).get("free") is True or
                        all(k in providers.get(c.get("provider"), {}) for k in ("input_per_mtok", "output_per_mtok"))) for c in calls)
    usage = execution_result.pop("usage_rows", None)
    known_usage = (all("prompt_tokens" in u and "completion_tokens" in u for u in usage)
                   if usage is not None else all(c.get("tokens_in", 0) + c.get("tokens_out", 0) > 0 for c in calls))
    all_mock = bool(calls) and all(providers.get(c.get("provider"), {}).get("type") == "mock" for c in calls)
    expected_calls = execution_result.get("model_invocations")
    metering_complete = expected_calls is None or expected_calls == len(calls)
    frontier = [c for c in calls if (c.get("provider") + ":" + c.get("model")) in (frontier_models or [])]
    return {**execution_result,
            "model_calls": len(calls) if metering_complete else None,
            "tokens_in": sum(c["tokens_in"] for c in calls) if known_usage and metering_complete else None,
            "tokens_out": sum(c["tokens_out"] for c in calls) if known_usage and metering_complete else None,
            "cost_usd": round(sum(c["cost_usd"] for c in calls), 8) if prices_known and metering_complete else None,
            "pricing_evidence": "simulated-mock" if all_mock else "configured-prices" if prices_known else "unknown-pricing",
            "frontier_model_calls": len(frontier) if frontier_models is not None and metering_complete else None,
            "frontier_tokens": sum(c["tokens_in"] + c["tokens_out"] for c in frontier) if frontier_models is not None and known_usage and metering_complete else None,
            "human_interventions": 0,
            "false_accepts": None, "false_rejects": None, "regression_rate": None,
            "transport_retries": None,
            "unknown_reasons": {"false_accepts": "no independent per-verifier adjudication",
                                "false_rejects": "no independent per-verifier adjudication",
                                "regression_rate": "no matched prior-success battery supplied",
                                "transport_retries": "gateway ledger does not count every failed transport attempt"},
            "model_ledger": calls}


def summarize_experiment(rows):
    import evalsuite
    out = {}
    metrics = ("tokens_in", "tokens_out", "model_calls", "tool_calls", "retries", "seconds", "verifier_failures",
               "false_accepts", "false_rejects", "human_interventions", "frontier_model_calls", "frontier_tokens",
               "skill_reuse", "runbook_reuse", "cost_usd")
    for name in sorted({r["arm"] for r in rows}):
        selected = [r for r in rows if r["arm"] == name]
        passed = sum(r.get("passed") is True for r in selected)
        totals = {k: sum(r[k] for r in selected) if all(isinstance(r.get(k), (int, float)) for r in selected) else None for k in metrics}
        cost = totals["cost_usd"]
        out[name] = {**totals, "trials": len(selected), "passed": passed, "pass_rate": passed/len(selected),
                     "pass_rate_ci95": list(evalsuite.wilson(passed, len(selected))),
                     "cost_per_verified_success": cost/passed if cost is not None and passed else None,
                     "verified_work_per_dollar": passed/cost if cost is not None and cost > 0 else None,
                     "seconds_per_verified_success": totals["seconds"]/passed if totals["seconds"] is not None and passed else None,
                     "frontier_calls_per_verified_success": totals["frontier_model_calls"]/passed if totals["frontier_model_calls"] is not None and passed else None,
                     "regression_rate": None}
    return {"arms": out, "n": len(rows), "evidence": "experiment-receipts-not-general-intelligence"}


def paired_delta(rows, baseline="minimal", treatment="full", seed=1701, samples=10000):
    """Task-cluster bootstrap: repeat observations remain together, not IID."""
    grouped = {}
    for r in rows:
        if r["arm"] in (baseline, treatment):
            grouped.setdefault(r["trial"], {}).setdefault(r["arm"], {})[r["repeat"]] = r
    deltas = []
    for task in grouped.values():
        if set(task) != {baseline, treatment} or set(task[baseline]) != set(task[treatment]):
            raise ValueError("unmatched experiment pairs")
        for rep in task[baseline]:
            a, b = task[baseline][rep], task[treatment][rep]
            if a["snapshot_hash"] != b["snapshot_hash"] or a["task_hash"] != b["task_hash"]:
                raise ValueError("paired comparison has unequal starting state or task")
        deltas.append(sum(int(task[treatment][rep]["passed"])-int(task[baseline][rep]["passed"]) for rep in task[baseline])/len(task[baseline]))
    if not deltas:
        return {"delta": None, "ci95": None, "task_clusters": 0}
    rng = random.Random(seed)
    boot = sorted(sum(rng.choice(deltas) for _ in deltas)/len(deltas) for _ in range(samples))
    return {"delta": sum(deltas)/len(deltas), "ci95": [boot[int(samples*.025)], boot[min(samples-1,int(samples*.975))]],
            "task_clusters": len(deltas), "bootstrap_seed": seed}


def run(home, expert, repeat=3, timeout=600, arms=("raw", "minimal", "no_persistence", "full"),
        seed=1701, ablations=(), tasks=None, reference=None, frontier_models=None, allow_provider=False):
    """Matched LIFT-001A runner. Actual provider use requires explicit opt-in."""
    import evaluation_corpus
    import evaluation_workspace
    import evaluation_policy
    import tempfile
    source = Path(home) / "experts" / expert
    if not source.is_dir() or repeat < 1:
        raise ValueError("existing expert and positive repeat count required")
    if set(arms) - set(ARMS) or ("reference" in arms and reference is None):
        raise ValueError("unsupported arm or missing explicit reference adapter")
    evaluation_policy.policy("full", ablations)
    agent = loop.Agent(str(source))
    if not allow_provider and any(p.get("type") != "mock" for p in agent.cfg.get("providers", {}).values()):
        raise ValueError("provider experiments require allow_provider=True and an owner-approved budget")
    trials = list(tasks if tasks is not None else experiment_tasks())
    if not trials or len({t["id"] for t in trials}) != len(trials):
        raise ValueError("unique nonempty task list required")
    code_hash = hashlib.sha256(b"".join((Path(HOME)/f).read_bytes() for f in
                                      ("benchmark.py", "evaluation_corpus.py", "evaluation_policy.py", "loop.py", "goal.py"))).hexdigest()
    rows = []
    output = Path(home) / "experiments" / ("lift-001a-" + str(time.time_ns()) + ".jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="experiment-snapshot-") as temp:
        snapshot = Path(temp) / "snapshot"
        snapshot_hash = evaluation_workspace.copy_snapshot(source, snapshot)
        for rep in range(repeat):
            for trial in trials:
                order = list(arms)
                random.Random(f"{seed}:{rep}:{trial['id']}").shuffle(order)
                for arm in order:
                    with evaluation_workspace.arena(snapshot, expert=expert, persistent=arm not in ("raw", "minimal", "no_persistence")) as (arena_home, root, input_hash):
                        evaluation_workspace.fixture(root, trial.get("fixture", {}))
                        policy = _trial_policy(root, arm, ablations if arm == "full" else ())
                        runner = loop.Agent(root)
                        start = time.monotonic()
                        try:
                            if arm in ("raw", "minimal"):
                                result = iterative_arm(runner, root, trial, timeout=timeout, raw=arm == "raw")
                            elif arm == "reference":
                                result = reference(runner, root, trial, timeout=timeout)
                            else:
                                result = _harness_experiment(arena_home, expert, trial, timeout)
                        except Exception as exc:
                            result = {"claimed_done": False, "error": type(exc).__name__}
                        elapsed = time.monotonic() - start
                        metrics = _metrics(runner, root, result, frontier_models)
                        row = {**metrics, "arm": arm, "trial": trial["id"], "family": trial.get("family"),
                               "repeat": rep, "seed": seed, "provider_seed_support": "unknown",
                               "snapshot_hash": snapshot_hash, "effective_input_hash": input_hash,
                               "task_hash": hashlib.sha256(json.dumps(trial, sort_keys=True).encode()).hexdigest(),
                               "code_hash": code_hash, "policy": policy,
                               "passed": evaluation_corpus.grade(root, trial), "seconds": round(elapsed, 4)}
                        rows.append(row)
                        with output.open("a", encoding="utf-8") as f:
                            f.write(json.dumps(row, sort_keys=True) + "\n"); f.flush(); os.fsync(f.fileno())
    result = summarize_experiment(rows)
    result.update(rows=rows, receipt_path=str(output), code_hash=code_hash, corpus_hash=evaluation_corpus.corpus_hash())
    if "minimal" in arms and "full" in arms:
        result["paired_success_delta"] = paired_delta(rows)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--expert", required=True)
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--home", default=HOME)
    p.add_argument("--allow-provider", action="store_true")
    p.add_argument("--seed", type=int, default=1701)
    p.add_argument("--ablate", action="append", default=[])
    sub.add_parser("suite")
    args = ap.parse_args()
    if args.cmd == "suite":
        for t in experiment_tasks():
            print(f"{t['id']}\n  task:  {t['task']}\n  check: {t['check'][:90]}\n")
        return
    print(json.dumps(run(args.home, args.expert, args.repeat, args.timeout,
                         seed=args.seed, ablations=args.ablate, allow_provider=args.allow_provider), indent=2))


if __name__ == "__main__":
    main()
