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


# EVERY PATH IN THIS SECTION IS MODEL-INFLUENCED, and none of them went
# through the File Authority.
#
# `written_paths` reads the artifact list out of the task own write_file
# steps -- and a REFUSED write_file is still recorded as a step, so the list
# could name any path the model ever typed. The stash directory itself
# (candidates/) classified as ZONE_ROOT, which the file tool may write.
# Together, a role holding ONLY write_file -- the Rule-of-Two roles that are
# deliberately denied a shell -- could:
#
#   * write candidates/<id>/<n>/score.json declaring the artifact list
#     ["prompts/constitution.md"] with a score of 1.0, write its own
#     constitution beside it, and let the loop own _promote_best_attempt copy
#     that over the FIRST block of every system prompt; and
#   * name "../../../../OUT.txt" as an artifact and have promote() write it
#     outside the expert root entirely.
#
# Both reproduced, and both need no shell at all. It is the defect class the
# File Authority exists for -- "a control that lives at a call site protects
# that call site and nothing else" -- reappearing in a module written after
# it, because this module reached the filesystem with os.path.join.
#
# So every path crosses _contained(), which is fileauth.resolve with the
# AGENT rights: an artifact the agent could not have written is not an
# artifact it may have restored, and a traversal is refused rather than
# normalised. The refusals are counted into score.json so a dropped artifact
# is visible rather than silent.

def _contained(root, rel, mode="write"):
    """-> an absolute path inside `root` that the AGENT is allowed to touch,
    or None. The zone rules are what make a model-supplied artifact list safe
    to act on at all."""
    try:
        import fileauth
        return fileauth.resolve(root, rel, mode, "agent")
    except Exception:
        return None


def _stash_dst(d, rel):
    """Where an artifact copy lives INSIDE the stash, contained against the
    stash directory so `../..` cannot place it elsewhere."""
    dst = os.path.abspath(os.path.join(d, str(rel).replace("/", os.sep)))
    base = os.path.abspath(d)
    if dst != base and not dst.startswith(base + os.sep):
        return None
    return dst


def snapshot(root, paths):
    """The current bytes of `paths` (missing files recorded as absent)."""
    snap = {}
    for rel in paths:
        full = _contained(root, rel, "read")
        if full is None:
            continue
        try:
            with open(full, "rb") as f:
                snap[rel] = f.read()
        except OSError:
            snap[rel] = None
    return snap


def restore(root, snap):
    """Put the world back exactly as `snapshot` found it."""
    for rel, data in snap.items():
        full = _contained(root, rel)
        if full is None:
            continue
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
    """Keep an attempt artifacts so a later one can be compared and the
    winner put back. Nothing is thrown away silently."""
    d = os.path.join(_dir(root, task_id), str(n))
    os.makedirs(d, exist_ok=True)
    kept, refused = [], []
    for rel in paths:
        # WRITE rights, not read rights, even though this only copies. An
        # artifact the agent could not have WRITTEN is not the agent's work,
        # so keeping a copy of it as "an attempt's artifact" is wrong twice
        # over: promote would refuse to put it back anyway, and until then
        # the stash carries a copy of control state under a name the worker
        # chose.
        src = _contained(root, rel, "write")
        dst = _stash_dst(d, rel)
        if src is None or dst is None:
            refused.append(rel)
            continue
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        kept.append(rel)
    rec = {"attempt": n, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "artifacts": kept, **result}
    # CONTENT FINGERPRINT — the diversity input next_attempt() was reading
    # and nothing was writing, so diversity was constantly 1.0 and identical
    # retries looked as promising as genuinely different ones. Hashed from
    # the stashed artifact BYTES: two attempts that wrote the same files the
    # same way are the same attempt, whatever their prose said.
    import hashlib
    h = hashlib.sha256()
    for rel in sorted(kept):
        p = _stash_dst(d, rel)
        try:
            with open(p, "rb") as f:
                h.update(rel.encode() + b"\0" + f.read() + b"\0")
        except OSError:
            h.update(rel.encode() + b"\0!unreadable\0")
    rec["fingerprint"] = h.hexdigest()
    if refused:
        rec["refused_paths"] = refused[:20]
    with open(os.path.join(d, "score.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1)
    return d


def promote(root, task_id, n):
    """Copy a stashed attempt artifacts back into place.

    Restoring is a WRITE, so every destination is checked with the AGENT own
    rights. score.json lives under candidates/, which the agent can write, so
    its artifact list is model-supplied data and never a licence.
    """
    d = os.path.join(_dir(root, task_id), str(n))
    meta_path = os.path.join(d, "score.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return []
    restored = []
    for rel in meta.get("artifacts", []):
        src = _stash_dst(d, rel)
        dst = _contained(root, str(rel))
        if src is None or dst is None or not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        restored.append(rel)
    return restored


def attempts_for(task, cfg=None):
    """How many attempts this task has earned. Adaptive: 1 until something
    fails, then 3, then 5 — capped by the owner's setting."""
    ag = ((cfg or {}).get("agent", {}) or {})
    try:
        from evaluation_policy import disabled
        if disabled(cfg or {}, 'candidates'):
            return 1
    except ImportError:
        pass
    if not ag.get("candidates_on_gate_failure", True):
        return 1
    cap = int(ag.get("candidates_max", DEFAULT_MAX))
    rounds = int(task.get("candidate_rounds", 0))
    return max(1, min(cap, ESCALATION.get(rounds, cap)))


def next_attempt(task, attempts, cfg=None, *, recovery_probability=None,
                 remaining_budget_usd=None, recovery_observations=()):
    """Adaptive sequential stopping, evaluated after EVERY mechanical attempt.

    Historical samples must be development observations of *another* task,
    scored by L0. Held-out evaluations never tune this policy. Without these,
    the configured recovery prior is explicitly heuristic. This augments the
    compatibility 1/3/5 API; the loop uses this decision to stop further work.
    """
    from scheduler import _number
    ag = ((cfg or {}).get('agent', {}) or {})
    cap = max(1, int(ag.get('candidates_max', DEFAULT_MAX)))
    # THE STOPPING CEILING IS THE RETRY SETTING, NOT THE STASH SETTING.
    # min() of the two silently lowered the documented `max_done_rejects = 6`
    # to `candidates_max = 5`: the task failed one refusal early, and the
    # message it printed still counted to six. candidates_max caps how many
    # attempts are SCORED and kept; when the task gives up is a different
    # question, and settings.toml answers it in one place.
    hard_cap = max(1, int(ag.get('max_done_rejects', cap)))
    n = len(attempts)
    try:
        from evaluation_policy import disabled
        ablated = disabled(cfg or {}, 'candidates')
    except ImportError:
        ablated = False
    reason = None
    if ablated or not ag.get('candidates_on_gate_failure', True):
        reason = 'candidate sampling disabled'
    elif any(a.get('passed') is True for a in attempts):
        reason = 'mechanical success already obtained'
    elif n >= hard_cap:
        reason = 'hard candidate ceiling reached'
    model_cost = _number(ag.get('candidate_model_cost_usd'), .01)
    verifier_cost = _number(ag.get('candidate_verifier_cost_usd'), .001)
    latency_cost = _number(ag.get('candidate_latency_cost_usd'))
    cost = model_cost + verifier_cost + latency_cost
    budget = _number(task.get('budget_usd'), _number(ag.get('candidate_budget_usd'), 1.))
    spent = max(_number(task.get('cost_usd')), sum(_number(a.get('cost_usd')) for a in attempts))
    remaining = max(0., budget - spent)
    if remaining_budget_usd is not None:
        remaining = min(remaining, _number(remaining_budget_usd))
    if cost > remaining or remaining <= 0:
        reason = 'remaining budget cannot cover another model and verifier attempt'
    best = max((_number(a.get('score')) for a in attempts), default=0.)
    fingerprints = [a.get('fingerprint') for a in attempts if a.get('fingerprint')]
    diversity = len(set(fingerprints)) / len(fingerprints) if fingerprints else 1.
    cls = str(task.get('task_class') or task.get('kind') or 'general')
    seen, samples = set(), []
    for row in recovery_observations:
        tid = row.get('task_id')
        if tid == task.get('id') or not tid or tid in seen or row.get('split') != 'development' or \
                row.get('verified_l0') is not True or type(row.get('next_success')) is not bool or \
                row.get('task_class', 'general') != cls or \
                int(_number(row.get('attempt'), 1)) != max(1, n) or \
                abs(_number(row.get('best_score')) - best) > .25:
            continue
        seen.add(tid)
        samples.append(row['next_success'])
    kind = 'caller_supplied_estimate' if recovery_probability is not None else 'heuristic_prior'
    if recovery_probability is None:
        if len(samples) >= max(1, int(ag.get('candidate_min_observations', 5))):
            probability = (sum(samples) + 1) / (len(samples) + 2)
            kind = 'empirical_smoothed'
        else:
            probability = _number(ag.get('candidate_recovery_prior'), .2)
        probability *= diversity
    else:
        probability = _number(recovery_probability)
    probability = min(1., probability)
    value = _number(task.get('task_value_usd'), _number(ag.get('candidate_task_value_usd'), 1.))
    benefit = probability * value
    if reason is None and benefit <= cost:
        reason = 'expected marginal verified benefit does not exceed marginal compute cost'
    return {'continue': reason is None, 'reason': reason or 'positive marginal expected value',
            'attempts': n, 'hard_ceiling': hard_cap, 'best_mechanical_score': best,
            'diversity': diversity, 'recovery_probability': probability,
            'estimate_kind': kind, 'calibrated': False, 'historical_n': len(samples),
            'expected_marginal_benefit': benefit, 'marginal_compute_cost': cost,
            'model_cost_usd': model_cost, 'verifier_cost_usd': verifier_cost,
            'remaining_budget_usd': remaining}


RECOVERY = os.path.join("logs", "candidate-recovery.jsonl")


def record_recovery(root, task):
    """File this task's attempt sequence as DEVELOPMENT observations.

    next_attempt()'s empirical branch reads rows shaped {task_id, task_class,
    attempt, best_score, next_success, split, verified_l0} — and nothing in
    the platform ever wrote one, so the "historical probability another
    sample fixes this failure" input was a documented field with no writer
    and every stopping decision fell to the configured prior. Written once,
    at the task's terminal outcome, from the same stash ledger the scores
    came from. All live rows are split=development: held-out evaluations
    never tune this policy (the module's own rule)."""
    attempts = history(root, task["id"])
    if not attempts:
        return 0
    verified = bool(task.get("done_check"))
    cls = str(task.get("task_class") or task.get("kind") or "general")
    rows, best = [], 0.0
    for i, a in enumerate(attempts):
        try:
            best = max(best, float(a.get("score") or 0.0))
        except (TypeError, ValueError):
            pass
        if i + 1 < len(attempts):
            nxt = attempts[i + 1].get("passed") is True
        elif task.get("status") == "done":
            # a stash happens on REFUSAL, so a terminal `done` means the try
            # after this stash is the one that passed the gate
            nxt = True
        else:
            # THE SAMPLE THAT WAS NEVER DRAWN. The task stopped here, so
            # nothing observed what another attempt would have done. Writing
            # False would teach the stopping rule that sampling does not help
            # using the very cases where sampling was never tried — a policy
            # trained on its own decision to stop, which converges on
            # stopping. None fails next_attempt's `is not bool` filter by
            # construction, so the row is kept as history and excluded from
            # the estimate.
            nxt = None
        rows.append({"task_id": task["id"], "task_class": cls,
                     "attempt": i + 1, "best_score": round(best, 4),
                     "next_success": (None if nxt is None else bool(nxt)),
                     "sampling_stopped_here": nxt is None,
                     "split": "development", "verified_l0": verified,
                     "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    target = os.path.join(root, RECOVERY)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return len(rows)


def recovery_observations(root, limit=5000):
    """The development-split rows next_attempt() filters for similarity."""
    try:
        with open(os.path.join(root, RECOVERY), encoding="utf-8") as f:
            rows = []
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
            return rows[-limit:]
    except OSError:
        return []


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
