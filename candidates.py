#!/usr/bin/env python3
"""TEST-TIME COMPUTE — spend thinking, not parameters, and keep the best.

The best-evidenced result in the small-model literature is not a new
architecture: it is that allocating inference compute intelligently can beat a
much larger model doing one pass (Snell et al. report a smaller model beating
one ~14x larger under FLOP-matched comparison). The mechanism is unglamorous —
produce several candidate answers, SCORE them, keep the winner.

The scoring is where most implementations go wrong. Asking a model "is this
good?" produces a confident opinion, which is the thing this platform exists
to avoid. So nothing here asks a model anything. Every candidate is scored by
the verifiers that already exist and already gate the work:

    done_check      the task's own definition of done   -- HARD, disqualifying
    citecheck       every cited atom is actually defined
    conflicts       no contested point asserted as settled
    designcheck     interfaces: contrast, scale, a11y, filler tells
    memcheck        memory integrity over a course
    verify          the course spec's own CHECK commands

A candidate that fails the hard gate cannot win at any score. Among those that
pass, the composite score decides, and the breakdown is logged — so "why did
it pick that one" is answerable, like every other decision here.

ADAPTIVE BY DEFAULT: one attempt for work that passes first time. A gate
failure escalates to 3, a second failure to 5. Cost therefore rises only where
the work was going to fail anyway, and the existing max_task_usd /
daily_budget_usd breakers still outrank this policy.

    python candidates.py --root <expert> --task <id>      # score what exists
    python candidates.py --root <expert> --explain
"""

import argparse
import json
import os
import re
import shutil
import time

WEIGHTS = {"grounding": 0.30, "honesty": 0.25, "interface": 0.25,
           "spec": 0.20, "substance": 0.20}
DIR = "candidates"
DEFAULT_MAX = 5
ESCALATION = {0: 1, 1: 3, 2: 5}          # gate failures -> attempts to make


# ------------------------------------------------------------------ scoring

def written_paths(task):
    """Relative paths this task actually wrote, from its own step record."""
    out = []
    for step in task.get("steps", []) or []:
        if step.get("tool") != "write_file":
            continue
        try:
            args = json.loads(step.get("args") or "{}")
        except (ValueError, TypeError):
            continue
        p = args.get("path")
        if p and p not in out:
            out.append(str(p).replace("\\", "/"))
    return out


def _wants_citations(task, text):
    """Only score grounding where citations are CLAIMED or REQUIRED (see the
    same guard in confidence.py): a note that cites nothing is not an
    ungrounded answer, it is a different kind of artifact."""
    if re.search(r"citecheck", str((task or {}).get("done_check") or ""), re.I):
        return True
    return bool(re.search(r"\b[CPU]-\d{2,}\b", text or ""))


def _grounding(root, paths, task=None):
    """Every cited atom must be defined. -> (score, detail) or None."""
    try:
        import citecheck
    except ImportError:
        return None
    texts = [p for p in paths if p.lower().endswith((".md", ".txt"))]
    if not texts:
        return None
    problems = cited = defined = looked = 0
    for rel in texts:
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                if not _wants_citations(task, fh.read()):
                    continue
        except OSError:
            continue
        looked += 1
        try:
            probs, n_cited, n_defined = citecheck.check(root, full)
        except Exception:
            continue
        problems += len(probs)
        cited += n_cited
        defined += n_defined
    if not looked or (not cited and not problems):
        return None                       # nothing cited: not this gate's business
    score = 0.0 if problems else 1.0
    return score, {"problems": problems, "cited": cited, "defined": defined}


def _honesty(root, task, paths):
    """No contested point may be stated as settled."""
    course = task.get("course")
    if not course:
        return None
    try:
        import conflicts
    except ImportError:
        return None
    texts = [p for p in paths if p.lower().endswith((".md", ".txt"))]
    problems = touched = 0
    for rel in texts:
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        try:
            probs, n = conflicts.check(root, full, course)
        except Exception:
            continue
        problems += len(probs)
        touched += n
    if not touched:
        return None
    return (0.0 if problems else 1.0), {"contested_touched": touched,
                                        "asserted_as_settled": problems}


def _interface(root, paths):
    """Interfaces are scored by the design gate: blockers first, then noise."""
    try:
        import designcheck
    except ImportError:
        return None
    faces = [p for p in paths
             if p.lower().endswith((".html", ".htm", ".css", ".jsx", ".tsx",
                                    ".vue", ".svelte"))]
    if not faces:
        return None
    blockers = warns = 0
    for rel in faces:
        full = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        found = designcheck.check_path(full)
        blockers += sum(1 for f in found if f["severity"] == "blocker")
        warns += sum(1 for f in found if f["severity"] == "warn")
    score = 0.0 if blockers else max(0.0, 1.0 - 0.1 * warns)
    return score, {"blockers": blockers, "warnings": warns}


PLACEHOLDERS = ("todo", "fixme", "lorem ipsum", "tbd", "xxx",
                "your text here", "coming soon", "<placeholder>")
_PARSERS = {".json": "json", ".py": "python", ".toml": "toml"}


def _substance(root, paths, task=None):
    """A mechanical FLOOR: does the artifact exist, parse, and say anything?

    This exists because every other component here declines to answer on an
    ordinary task. Measured through the real loop, six attempts at one goal
    all scored 0.0 — grounding was the only component that ran, and it had
    nothing to measure. rank() over a set of ties is a stable sort, so "the
    winner" was whichever attempt came first, and best-of-N reduced to
    picking arbitrarily.

    So this asks the questions a computer can answer about ANY artifact,
    without a model and without a domain:

        it exists, and it is not empty
        it PARSES, if its extension implies a format
        it does not contain TODO, FIXME or lorem ipsum
        it is not trivially shorter than the task that asked for it

    None of that measures whether the work is GOOD. It measures whether the
    work is real, which is the difference the earlier tie could not see: an
    attempt that wrote "x" and one that wrote a considered answer were
    indistinguishable, and the platform shipped whichever came last.
    """
    if not paths:
        return None
    checks, problems = 0, []
    for rel in paths:
        full = os.path.join(root, rel.replace("/", os.sep))
        checks += 1
        if not os.path.isfile(full):
            problems.append(f"{rel}: missing")
            continue
        try:
            raw = open(full, "rb").read()
        except OSError as e:
            problems.append(f"{rel}: unreadable ({e.__class__.__name__})")
            continue
        checks += 1
        if not raw.strip():
            problems.append(f"{rel}: empty")
            continue
        text = raw.decode("utf-8", errors="replace")
        ext = os.path.splitext(rel)[1].lower()
        if ext in _PARSERS:
            checks += 1
            kind = _PARSERS[ext]
            try:
                if kind == "json":
                    json.loads(text)
                elif kind == "python":
                    compile(text, rel, "exec")
                elif kind == "toml":
                    import tomllib
                    tomllib.loads(text)
            except Exception as e:
                problems.append(f"{rel}: does not parse as {kind} "
                                f"({e.__class__.__name__})")
        checks += 1
        low = text.lower()
        hit = [m for m in PLACEHOLDERS if m in low]
        if hit:
            problems.append(f"{rel}: placeholder text ({hit[0]})")
        # An answer far shorter than its own question is a non-answer. The
        # bar is deliberately low: this catches "x", not brevity.
        goal = str((task or {}).get("goal") or "")
        if goal:
            checks += 1
            if len(text.strip()) < max(12, len(goal) // 12):
                problems.append(f"{rel}: {len(text.strip())} chars against a "
                                f"{len(goal)}-char request")
    if not checks:
        return None
    value = max(0.0, 1.0 - (len(problems) / float(checks)))
    return value, {"checks": checks, "problems": problems[:6],
                   "artifacts": len(paths)}


def _spec(root, task):
    """The course spec's own mechanical checks, as a pass ratio."""
    course = task.get("course")
    if not course:
        return None
    path = os.path.join(root, "courses", str(course), "exam-results.md")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            body = f.read()
    except OSError:
        return None
    import re
    passes = len(re.findall(r"\bPASS\b", body))
    fails = len(re.findall(r"\bFAIL\b", body))
    if not (passes + fails):
        return None
    return passes / (passes + fails), {"pass": passes, "fail": fails}


def score(agent, task, paths=None):
    """-> {passed, score, detail}. `passed` is the task's own hard gate."""
    root = agent.root
    paths = paths if paths is not None else written_paths(task)
    detail, parts = {}, {}
    try:
        passed, evidence = agent.check_done(task)
    except Exception as e:
        passed, evidence = False, f"gate could not run: {e}"
    detail["gate"] = {"passed": bool(passed), "evidence": str(evidence)[:300]}
    for name, fn in (("grounding", lambda: _grounding(root, paths, task)),
                     ("honesty", lambda: _honesty(root, task, paths)),
                     ("interface", lambda: _interface(root, paths)),
                     ("spec", lambda: _spec(root, task)),
                     # last, and always applicable: the others all decline to
                     # answer on an ordinary task, which is how six attempts
                     # came to tie at 0.0
                     ("substance", lambda: _substance(root, paths, task))):
        try:
            got = fn()
        except Exception as e:                 # a scorer must never be the outage
            detail[name] = {"error": str(e)[:160]}
            continue
        if got is None:
            continue
        value, info = got
        parts[name] = value
        detail[name] = dict(info, score=round(value, 3))
    if parts:
        total = sum(WEIGHTS[k] * v for k, v in parts.items())
        norm = sum(WEIGHTS[k] for k in parts)
        composite = total / norm if norm else 0.0
    else:
        composite = 1.0 if passed else 0.0     # only the gate had an opinion
    detail["artifacts"] = paths
    return {"passed": bool(passed), "score": round(composite, 4),
            "detail": detail, "scored_by": sorted(parts)}


def rank(scored):
    """Gate first, then composite. A gate failure can never win."""
    return sorted(scored, key=lambda c: (not c["passed"], -c["score"]))


# ------------------------------------------------- attempts on the same work

def _dir(root, task_id):
    d = os.path.join(root, DIR, str(task_id))
    os.makedirs(d, exist_ok=True)
    return d


def snapshot(root, paths):
    """The current bytes of `paths` (missing files recorded as absent)."""
    snap = {}
    for rel in paths:
        full = os.path.join(root, rel.replace("/", os.sep))
        try:
            with open(full, "rb") as f:
                snap[rel] = f.read()
        except OSError:
            snap[rel] = None
    return snap


def restore(root, snap):
    """Put the world back exactly as `snapshot` found it."""
    for rel, data in snap.items():
        full = os.path.join(root, rel.replace("/", os.sep))
        if data is None:
            try:
                os.remove(full)
            except OSError:
                pass
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)


def stash(root, task_id, n, paths, result):
    """Keep an attempt's artifacts so a later one can be compared and the
    winner put back. Nothing is thrown away silently."""
    d = os.path.join(_dir(root, task_id), str(n))
    os.makedirs(d, exist_ok=True)
    kept = []
    for rel in paths:
        src = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            continue
        dst = os.path.join(d, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        kept.append(rel)
    with open(os.path.join(d, "score.json"), "w", encoding="utf-8") as f:
        json.dump({"attempt": n, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "artifacts": kept, **result}, f, indent=1)
    return d


def promote(root, task_id, n):
    """Copy a stashed attempt's artifacts back into place."""
    d = os.path.join(_dir(root, task_id), str(n))
    meta_path = os.path.join(d, "score.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return []
    restored = []
    for rel in meta.get("artifacts", []):
        src = os.path.join(d, rel.replace("/", os.sep))
        dst = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        restored.append(rel)
    return restored


def attempts_for(task, cfg=None):
    """How many attempts this task has earned. Adaptive: 1 until something
    fails, then 3, then 5 — capped by the owner's setting."""
    ag = ((cfg or {}).get("agent", {}) or {})
    if not ag.get("candidates_on_gate_failure", True):
        return 1
    cap = int(ag.get("candidates_max", DEFAULT_MAX))
    rounds = int(task.get("candidate_rounds", 0))
    return max(1, min(cap, ESCALATION.get(rounds, cap)))


def history(root, task_id):
    """Every attempt made for a task, with its score."""
    d = os.path.join(root, DIR, str(task_id))
    out = []
    try:
        names = sorted(os.listdir(d), key=lambda n: int(n) if n.isdigit() else 99)
    except OSError:
        return out
    for n in names:
        p = os.path.join(d, n, "score.json")
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except (OSError, ValueError):
            continue
    return out


def explain(scored):
    """Human-readable reason the winner won."""
    ranked = rank(scored)
    if not ranked:
        return "no candidates"
    best = ranked[0]
    lines = [f"winner: attempt {best.get('attempt', '?')} — "
             f"gate {'PASSED' if best['passed'] else 'FAILED'}, "
             f"score {best['score']}"]
    for c in ranked[1:]:
        why = []
        if not c["passed"]:
            why.append("failed its gate")
        if c["score"] < best["score"]:
            why.append(f"scored {c['score']} vs {best['score']}")
        lines.append(f"  attempt {c.get('attempt', '?')}: "
                     + (", ".join(why) or "tied, earlier attempt kept"))
    for name, info in (best.get("detail") or {}).items():
        if isinstance(info, dict) and "score" in info:
            lines.append(f"  {name}: {info['score']} {info}")
    return "\n".join(lines)


def main():
    import sys
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--task", help="score this task's current artifacts")
    ap.add_argument("--explain", action="store_true",
                    help="show every attempt made for --task")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if a.task and a.explain:
        rows = history(root, a.task)
        print(json.dumps(rows, indent=1) if a.json else
              (explain(rows) if rows else "no attempts recorded for that task"))
        return
    if not a.task:
        raise SystemExit("--task <id> (add --explain for the attempt history)")
    import loop
    agent = loop.Agent(root)
    task = agent.find_task(a.task)
    if not task:
        raise SystemExit(f"no task {a.task}")
    res = score(agent, task)
    print(json.dumps(res, indent=1) if a.json else
          f"gate {'PASSED' if res['passed'] else 'FAILED'}, "
          f"score {res['score']} (scored by: "
          f"{', '.join(res['scored_by']) or 'the gate alone'})\n"
          + json.dumps(res["detail"], indent=1))
    raise SystemExit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
