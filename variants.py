#!/usr/bin/env python3
"""Charter evolution — the Agent Selection Farm idea, governed.

The owner's evolutionary thesis: don't hand-design the perfect agent; create
variants, test them, score them, promote winners, keep descendants. The 2026
fragility research adds the discipline that makes it safe: improvement must
be EXPERIMENTAL, MEASURED, and PROMOTED ONLY ON EVIDENCE — an agent that
rewrites its own charter because it feels smarter today is accumulating
superstition, not evolving.

So this module is a genome-lite with a promotion gate:

  spawn     a VARIANT of one or more role prompts (the agent's charter),
            stored under variants/<id>/ — the live prompts are untouched.
  trial     the SAME battery of gated tasks runs twice — once with the base
            charter, once with the variant (selected by an environment
            variable, so nothing on disk changes) — and both arms are scored
            by the same mechanical done-checks. EACH ARM RUNS IN ITS OWN
            CLONE of the expert; see `trial` for why that is not a detail.
  promote   REFUSED unless the variant strictly beat the base on gated
            passes over at least two tasks. Promotion backs up the replaced
            prompts first; the record keeps both scores.
  rollback  restores the pre-promotion prompts from the backup, and says so
            in the record. Evolution here is reversible by construction.

No model ever judges a variant. Exit codes do.

Usage:
  python variants.py spawn  --root R --id v2 --role practitioner --file new.md [--note ...]
  python variants.py trial  --root R --id v2 --battery battery.json [--timeout 600]
  python variants.py promote  --root R --id v2
  python variants.py rollback --root R --id v2
  python variants.py list --root R
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

ENV_VAR = "AGENT_PROMPT_VARIANT"
MIN_TASKS = 2


def _dir(root, vid=None):
    d = os.path.join(root, "variants")
    return os.path.join(d, vid) if vid else d


def _manifest_path(root):
    return os.path.join(_dir(root), "manifest.json")


def load_manifest(root):
    try:
        with open(_manifest_path(root), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_manifest(root, m):
    os.makedirs(_dir(root), exist_ok=True)
    tmp = _manifest_path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=1, ensure_ascii=False)
    for attempt in range(8):
        try:
            os.replace(tmp, _manifest_path(root))
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, _manifest_path(root))


# The learner may propose changes to WORKER charters. It may never touch
# the constitution, the grounding contract, or the roles that judge it —
# an agent that can rewrite its own evaluator improves its score, not its
# work. Enforced here, in code, for every caller including the panel.
PROTECTED_ROLES = {"constitution", "_grounding", "examiner", "student"}


def spawn(root, vid, role, prompt_text, note="", prediction=None):
    """prediction: {"metric": "passes"|"gate_rejects", "expected_delta": N}

    DECISION OBSERVABILITY (arXiv 2604.25850, Agentic Harness Engineering):
    the harness improved fastest when every edit came with a SELF-DECLARED
    PREDICTION that was later checked against the measured outcome. A change
    whose author cannot say what it should improve, by how much, is not an
    experiment — it is a preference. So a variant may carry a prediction, and
    promote() refuses it if the prediction did not hold, even when the raw
    numbers happen to look better.
    """
    if not vid.replace("-", "").replace("_", "").isalnum():
        raise ValueError("variant id must be alphanumeric-with-dashes")
    if role in PROTECTED_ROLES or role.startswith("_"):
        raise SystemExit(f"REFUSED: '{role}' is a protected charter — the "
                         f"constitution, grounding contract, examiner and "
                         f"student prompts cannot be evolved by variants.")
    vdir = _dir(root, vid)
    os.makedirs(vdir, exist_ok=True)
    with open(os.path.join(vdir, f"{role}.md"), "w", encoding="utf-8") as f:
        f.write(prompt_text)
    m = load_manifest(root)
    e = m.setdefault(vid, {"id": vid, "roles": [], "note": note,
                           "status": "spawned", "trials": None,
                           "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "promoted_at": None, "rolled_back_at": None})
    if role not in e["roles"]:
        e["roles"].append(role)
    if note:
        e["note"] = note
    if prediction:
        metric = str(prediction.get("metric") or "passes")
        if metric not in ("passes", "gate_rejects"):
            raise ValueError("prediction metric must be passes or gate_rejects")
        try:
            delta = float(prediction.get("expected_delta"))
        except (TypeError, ValueError):
            raise ValueError("prediction needs a numeric expected_delta")
        e["prediction"] = {"metric": metric, "expected_delta": delta,
                           "declared": time.strftime("%Y-%m-%dT%H:%M:%S")}
    save_manifest(root, m)
    return e


def _owner_only(cmd, vid):
    """Installing or reverting a CHARTER is an owner action: it rewrites
    prompts/, which is what every future agent of that role is told it is.

    The seal around every model-authored command (controlplane.py) would
    revert such a write anyway — this refuses FIRST, with a sentence, rather
    than letting the work happen and then undoing it. Two independent
    controls; neither relies on the other."""
    import controlplane
    controlplane.owner_only(f"{cmd} of charter variant {vid!r}")


def _drain(root, env_extra, timeout):
    env = {**os.environ, "PYTHONUTF8": "1", **env_extra}
    env.pop(ENV_VAR, None) if not env_extra else None
    r = subprocess.run(
        [sys.executable, os.path.join(HOME, "loop.py"), "run", "--drain",
         "--root", root],
        capture_output=True, timeout=timeout, env=env)
    return r.returncode


def _clone_root(root, dest, arm):
    """A pristine copy of the expert for ONE arm to work in.

    Excluded, and why each is safe to leave behind: backups/ (large, and an
    arm never reads it), logs/ and contexts/ (the harness's own record of a
    DIFFERENT run — copying them would make the arm's own heartbeat check see
    a stale pulse), and __pycache__.
    """
    skip = {"backups", "logs", "contexts", "__pycache__", ".git"}
    shutil.copytree(root, dest,
                    ignore=lambda d, names: [n for n in names if n in skip],
                    dirs_exist_ok=True)
    os.makedirs(os.path.join(dest, "logs"), exist_ok=True)
    os.makedirs(os.path.join(dest, "contexts"), exist_ok=True)
    # a state.json carried over would let the arm adopt the other arm's tasks
    for leftover in ("state.json",):
        p = os.path.join(dest, leftover)
        if os.path.exists(p):
            os.remove(p)
    return dest


def trial(root, vid, battery, timeout=600, isolate=True):
    """Run the battery under BOTH charters and score with the same gates.
    battery: list of {role, goal, done_check, course?}. The variant arm is
    selected purely by an environment variable in the child process — the
    live prompts on disk never change during a trial.

    EACH ARM GETS ITS OWN CLONE OF THE EXPERT, and this is the difference
    between an experiment and an anecdote.

    Both arms used to run sequentially against the SAME root, base first,
    every time. So the base arm's work was still there when the variant
    started: its out/ files, its courses/, its skills and gotchas, its
    finished tasks, its memory. A battery whose done_check is `test -f
    out/report.md` — the ordinary shape — is satisfied for the variant by the
    file the BASE wrote, and "the variant beat the base" measures the order
    the arms ran in. The arm order was fixed, so the confound was systematic
    rather than noisy, which is the worse kind: it points the same way every
    time and looks like a result.

    With independent clones the order stops mattering, which is why this is
    isolation rather than counterbalancing — counterbalancing would only
    average the contamination out.

    `isolate=False` restores the old shared-root behaviour for a caller that
    has its own isolation. Nothing in the platform passes it; it exists so the
    honest default cannot be mistaken for the only option.
    """
    if len(battery) < MIN_TASKS:
        raise SystemExit(f"a trial needs >= {MIN_TASKS} tasks — one task "
                         f"proves nothing (that is the fragility lesson)")
    import loop
    m = load_manifest(root)
    if vid not in m:
        raise KeyError(vid)
    # a live loop on this expert would claim trial tasks WITHOUT the variant
    # env — contaminating the arms. Trials demand a quiet expert.
    try:
        with open(os.path.join(root, "logs", "heartbeat.json"),
                  encoding="utf-8") as f:
            hb = json.load(f)
        exited = hb.get("note") in ("drain_complete", "drain_budget_stop")
        if not exited and time.time() - hb.get("ts", 0) < 90:
            raise SystemExit(
                "REFUSED: a loop pulsed on this expert seconds ago — stop it "
                "before a trial, or its claims would contaminate the arms")
    except (OSError, ValueError):
        pass
    results = {}
    import tempfile
    arena = tempfile.mkdtemp(prefix=f"trial-{vid}-") if isolate else None
    try:
        for arm, env_extra in (("base", {}), ("variant", {ENV_VAR: vid})):
            arm_root = (_clone_root(root, os.path.join(arena, arm), arm)
                        if isolate else root)
            agent = loop.Agent(arm_root)
            ids = []
            for item in battery:
                ids.append(agent.add_task(
                    item.get("role", "practitioner"), item["goal"],
                    course=item.get("course"),
                    done_check=item.get("done_check")))
            _drain(arm_root, env_extra, timeout)
            agent = loop.Agent(arm_root)
            passes = rejects = 0
            for tid in ids:
                t = agent.find_task(tid) or {}
                if t.get("status") == "done":
                    passes += 1
                rejects += t.get("done_rejects", 0)
            results[arm] = {"tasks": len(ids), "passes": passes,
                            "gate_rejects": rejects, "task_ids": ids,
                            "root": arm_root if isolate else root}
    finally:
        if arena:
            shutil.rmtree(arena, ignore_errors=True)
    observed = {"passes": results["variant"]["passes"] - results["base"]["passes"],
                "gate_rejects": (results["variant"]["gate_rejects"]
                                 - results["base"]["gate_rejects"])}
    m[vid]["trials"] = {**results, "observed_delta": observed,
                        "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    pred = m[vid].get("prediction")
    if pred:
        # a prediction about gate_rejects is a prediction that they FALL, so
        # "held" means the observed delta reached the declared one in the
        # declared direction
        exp = float(pred["expected_delta"])
        obs = observed[pred["metric"]]
        held = obs >= exp if exp >= 0 else obs <= exp
        m[vid]["prediction_check"] = {
            "metric": pred["metric"], "expected_delta": exp,
            "observed_delta": obs, "held": bool(held),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    m[vid]["status"] = "trialed"
    save_manifest(root, m)
    return results


def promote(root, vid):
    """The gate: strictly better gated passes, or no promotion. Ties lose —
    churn without evidence is how charters rot."""
    m = load_manifest(root)
    e = m.get(vid)
    if not e:
        raise KeyError(vid)
    tr = e.get("trials")
    if not tr:
        raise SystemExit("REFUSED: no trial on record — run the trial first")
    b, v = tr["base"], tr["variant"]
    if v["tasks"] < MIN_TASKS:
        raise SystemExit(f"REFUSED: trial too small ({v['tasks']} tasks)")
    if v["passes"] <= b["passes"]:
        raise SystemExit(
            f"REFUSED: variant did not strictly beat base "
            f"({v['passes']}/{v['tasks']} vs {b['passes']}/{b['tasks']} gated "
            f"passes). Evolution without evidence is superstition.")
    # a declared prediction is a second, stricter gate: better-by-accident is
    # not the same as understood, and only the understood change is kept
    chk = e.get("prediction_check")
    if e.get("prediction") and not chk:
        raise SystemExit("REFUSED: this variant declared a prediction but the "
                         "trial on record predates it — re-run the trial")
    if chk and not chk["held"]:
        sign = "+" if chk["expected_delta"] >= 0 else ""
        raise SystemExit(
            f"REFUSED: prediction did not hold (predicted {sign}"
            f"{chk['expected_delta']:g} {chk['metric']}, observed "
            f"{chk['observed_delta']:+g}). The charter may be better by "
            f"accident, but it is not understood — revise the prediction or "
            f"the change, then trial again.")
    vdir = _dir(root, vid)
    for role in e["roles"]:
        live = os.path.join(root, "prompts", f"{role}.md")
        backup = os.path.join(vdir, f"backup-{role}.md")
        if os.path.exists(live) and not os.path.exists(backup):
            shutil.copy(live, backup)
        os.makedirs(os.path.dirname(live), exist_ok=True)
        shutil.copy(os.path.join(vdir, f"{role}.md"), live)
    e["status"] = "promoted"
    e["promoted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_manifest(root, m)
    return e


def rollback(root, vid):
    m = load_manifest(root)
    e = m.get(vid)
    if not e or e.get("status") != "promoted":
        raise SystemExit("REFUSED: only a promoted variant can roll back")
    vdir = _dir(root, vid)
    for role in e["roles"]:
        backup = os.path.join(vdir, f"backup-{role}.md")
        live = os.path.join(root, "prompts", f"{role}.md")
        if os.path.exists(backup):
            shutil.copy(backup, live)
        else:
            try:
                os.remove(live)     # there was no base prompt before
            except OSError:
                pass
    e["status"] = "rolled_back"
    e["rolled_back_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_manifest(root, m)
    return e


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("spawn")
    p.add_argument("--root", required=True); p.add_argument("--id", required=True)
    p.add_argument("--role", required=True); p.add_argument("--file", required=True)
    p.add_argument("--note", default="")
    p.add_argument("--predict-metric", choices=["passes", "gate_rejects"],
                   help="what this charter change should improve")
    p.add_argument("--predict-delta", type=float,
                   help="by how much (e.g. 2 more gated passes, -3 rejects)")
    p = sub.add_parser("trial")
    p.add_argument("--root", required=True); p.add_argument("--id", required=True)
    p.add_argument("--battery", required=True)
    p.add_argument("--timeout", type=int, default=600)
    for c in ("promote", "rollback"):
        p = sub.add_parser(c)
        p.add_argument("--root", required=True); p.add_argument("--id", required=True)
    p = sub.add_parser("list"); p.add_argument("--root", required=True)
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    if a.cmd == "spawn":
        pred = None
        if a.predict_metric is not None or a.predict_delta is not None:
            pred = {"metric": a.predict_metric or "passes",
                    "expected_delta": a.predict_delta}
        with open(a.file, "r", encoding="utf-8") as f:
            e = spawn(root, a.id, a.role, f.read(), a.note, pred)
        print(f"spawned variant {e['id']} for roles {e['roles']}"
              + (f" — prediction: {e['prediction']['metric']} "
                 f"{e['prediction']['expected_delta']:+g}" if pred else ""))
    elif a.cmd == "trial":
        with open(a.battery, "r", encoding="utf-8") as f:
            battery = json.load(f)
        r = trial(root, a.id, battery, a.timeout)
        print(json.dumps(r, indent=2))
    elif a.cmd == "promote":
        _owner_only(a.cmd, a.id)
        promote(root, a.id)
        print(f"PROMOTED {a.id} — base prompts backed up; rollback available")
    elif a.cmd == "rollback":
        _owner_only(a.cmd, a.id)
        rollback(root, a.id)
        print(f"rolled back {a.id}")
    elif a.cmd == "list":
        for vid, e in load_manifest(root).items():
            tr = e.get("trials") or {}
            score = (f" base {tr['base']['passes']}/{tr['base']['tasks']} vs "
                     f"variant {tr['variant']['passes']}/{tr['variant']['tasks']}"
                     if tr else "")
            print(f"{vid:<12} {e['status']:<11} roles={','.join(e['roles'])}{score}")


if __name__ == "__main__":
    main()
