#!/usr/bin/env python3
"""THE SELF-MODEL — the agent works from facts about itself, not a persona.

"Be aware of what you know" is the most-ignored line in every system prompt,
because a prompt cannot make it true: the model has no access to its own
record. This module gives it one. Before the first token of work, the agent
is handed a compiled, factual account of itself:

  WHO      its name and charter
  STUDIED  which courses, how many verified atoms, which exams it passed,
           and what tier of sources that knowledge rests on
  PROVEN   its measured competence per domain, and its proven skills --
           scored from gated outcomes, never self-reported
  SCARRED  what it has actually failed at, by category
  BLIND    the edges: open gaps, contested points, retracted claims, and the
           domains where it has no evidence at all
  NOW      the role, tools, stop condition, budget and sandbox of this run

None of it is generated. Every line is read from the ledgers the harness
already writes, so the self-model cannot flatter the agent: an expert with
one lucky success is told it has "insufficient evidence", and an expert that
has never been examined on a course is told so.

This is self-knowledge in the operational sense — an accurate model of its
own capabilities and limits, which is what makes calibrated refusal possible
("I have not studied that") instead of a fluent guess. It is not a claim
about consciousness, and the platform never makes one.

    python selfmodel.py --root <expert>
    python selfmodel.py --root <expert> --role practitioner --json
"""

import json
import os
import re
import time

MAX_LINES = 26


def _home_slug(root):
    """experts/<slug> -> (home, slug); a standalone root has no fleet."""
    parent = os.path.dirname(root)
    if os.path.basename(parent) == "experts":
        return os.path.dirname(parent), os.path.basename(root)
    return None, os.path.basename(root)


def _read(path, limit=4000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _courses(root):
    d = os.path.join(root, "courses")
    try:
        return sorted(n for n in os.listdir(d)
                      if os.path.isdir(os.path.join(d, n)))
    except OSError:
        return []


def _atoms_in(root, course):
    n = 0
    cdir = os.path.join(root, "courses", course)
    for dirpath, _, names in os.walk(cdir):
        for fn in names:
            if fn == "notes.md":
                n += len(re.findall(r"^\s*-\s*[CPU]-\d{2,}",
                                    _read(os.path.join(dirpath, fn), 400_000),
                                    re.M))
    return n


def _exam(root, course):
    """The last exam result recorded for a course, if it sat one."""
    body = _read(os.path.join(root, "courses", course, "exam-results.md"),
                 40_000)
    if not body:
        return None
    # The canonical line the loop's own completion check reads is
    # "SCORE: 95" (loop.py, course_status). This used to look only for a
    # percent SIGN, which that line does not carry — so an expert could pass
    # an exam at 95 and then describe itself, in its own self-model and in
    # the panel, as never having been scored. Read the canonical form first,
    # and keep accepting "95%" for anything already written that way.
    scores = (re.findall(r"^\s*SCORE:\s*(\d{1,3})", body, re.M)
              or re.findall(r"(\d{1,3})\s*%", body))
    passed = re.findall(r"\b(PASS|FAIL)\b", body.upper())
    return {"score": int(scores[-1]) if scores else None,
            "verdict": passed[-1].lower() if passed else None,
            "sittings": max(len(scores), len(passed))}


def _gaps(root, course):
    body = _read(os.path.join(root, "courses", course, "gaps.md"), 40_000)
    return [ln.strip("- ").strip() for ln in body.splitlines()
            if ln.strip().startswith("-")][:6]


def study(root):
    """What this expert has actually studied, per course."""
    out = []
    for c in _courses(root):
        rec = {"course": c, "atoms": _atoms_in(root, c),
               "exam": _exam(root, c), "gaps": _gaps(root, c),
               "sources": {}, "contested": 0}
        try:
            import sources as S
            rows = S.load(root, c)
            for r in rows:
                t = f"tier{r.get('tier', 4)}"
                rec["sources"][t] = rec["sources"].get(t, 0) + 1
        except Exception:
            pass
        try:
            import conflicts as C
            rec["contested"] = sum(1 for x in C.load(root, c)
                                   if x.get("verdict") == "contested")
        except Exception:
            pass
        out.append(rec)
    return out


def proven(root):
    """Measured competence + the skills that earned PROVEN status."""
    home, slug = _home_slug(root)
    comp = {}
    if home:
        try:
            import memory
            comp = memory.competence(home, slug).get(slug, {})
        except Exception:
            comp = {}
    skills = {"proven": [], "quarantined": []}
    try:
        import skills as SK
        s = SK.summary(root)
        skills["proven"] = [x["skill"] for x in s.get("proven", [])][:10]
        skills["quarantined"] = [x["skill"] for x in s.get("quarantined", [])][:6]
    except Exception:
        pass
    return {"competence": comp, "skills": skills}


def scars(root):
    """What it has failed at — categories, not anecdotes."""
    home, slug = _home_slug(root)
    out = {"by_category": {}, "gotchas": 0, "recurring": 0}
    if home:
        try:
            import memory
            # failure_summary returns {by_category, total, most_recurrent}
            summary = memory.failure_summary(home, slug) or {}
            out["by_category"] = summary.get("by_category", {})
            out["total"] = summary.get("total", 0)
        except Exception:
            pass
    try:
        import gotchas
        g = gotchas.summary(root)
        out["gotchas"], out["recurring"] = g.get("total", 0), g.get("repeats", 0)
    except Exception:
        pass
    return out


def now(root, role=None, task=None, cfg=None):
    """The constraints of THIS run — the part that changes every task."""
    state = {}
    try:
        import sandbox
        state["sandbox"] = sandbox.describe(cfg or {})["backend"]
    except Exception:
        state["sandbox"] = "host"
    state["role"] = role or (task or {}).get("role")
    if task:
        state["task"] = task.get("id")
        state["stop"] = task.get("stop")
        state["done_check"] = bool(task.get("done_check"))
    if role:
        try:
            import loop as L
            state["tools"] = sorted(L.Agent(root).allowed_tools(role))
        except RuntimeError as e:
            # a role with no provider is not a crash, it is a fact worth
            # knowing about yourself before you try to think with it
            state["role_problem"] = str(e)[:140]
        except Exception:
            pass
    pend = os.path.join(root, "approvals")
    try:
        state["approvals_pending"] = sum(
            1 for n in os.listdir(pend) if n.endswith(".json"))
    except OSError:
        state["approvals_pending"] = 0
    return state


def build(root, role=None, task=None, cfg=None):
    ident = _read(os.path.join(root, "identity.md"), 1200).strip()
    home, slug = _home_slug(root)
    return {"name": slug, "identity": ident[:400],
            "studied": study(root), "proven": proven(root),
            "scars": scars(root), "now": now(root, role, task, cfg),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def render(model, cap=MAX_LINES):
    """The context block. Short, factual, and honest about the edges."""
    m = model
    lines = ["SELF — what you are, what you have actually verified, and where "
             "your knowledge ends. Everything here was measured, not claimed."]
    if m.get("identity"):
        lines.append(f"- you are {m['name']}: "
                     f"{' '.join(m['identity'].split())[:160]}")
    studied = m.get("studied") or []
    if studied:
        for s in studied[:6]:
            bits = [f"{s['atoms']} verified atom(s)"]
            ex = s.get("exam")
            if ex and ex.get("score") is not None:
                bits.append(f"exam {ex['score']}%"
                            + (f" ({ex['verdict']})" if ex.get("verdict") else ""))
            elif ex:
                bits.append("examined")
            else:
                bits.append("NEVER EXAMINED — treat as unproven")
            src = s.get("sources") or {}
            if src:
                bits.append("sources: " + ", ".join(
                    f"{n}x {t.replace('tier', 'tier ')}"
                    for t, n in sorted(src.items())))
            if s.get("contested"):
                bits.append(f"{s['contested']} CONTESTED point(s)")
            lines.append(f"- studied {s['course']}: " + "; ".join(bits))
    else:
        lines.append("- you have studied NOTHING yet: you hold no verified "
                     "material, so answer from the task's own files or say so")
    comp = (m.get("proven") or {}).get("competence") or {}
    for dom, c in sorted(comp.items(),
                         key=lambda kv: -kv[1].get("attempts", 0))[:4]:
        lines.append(f"- competence in {dom}: {c['claim']} "
                     f"({c['successes']}/{c['attempts']} tasks, "
                     f"confidence {c['confidence']})")
    sk = (m.get("proven") or {}).get("skills") or {}
    if sk.get("proven"):
        lines.append("- proven playbooks: " + ", ".join(sk["proven"][:6]))
    if sk.get("quarantined"):
        lines.append("- quarantined playbooks (do NOT use): "
                     + ", ".join(sk["quarantined"][:4]))
    sc = m.get("scars") or {}
    cats = sorted((sc.get("by_category") or {}).items(),
                  key=lambda kv: -kv[1])[:3]
    if cats:
        lines.append("- your own failure record: "
                     + ", ".join(f"{k} x{v}" for k, v in cats)
                     + (f"; {sc.get('recurring', 0)} recurring gotcha(s)"
                        if sc.get("recurring") else ""))
    blind = []
    for s in studied:
        for g in (s.get("gaps") or [])[:2]:
            blind.append(f"{s['course']}: {g[:80]}")
    if blind:
        lines.append("- known gaps: " + " | ".join(blind[:3]))
    n = m.get("now") or {}
    bits = []
    if n.get("role"):
        bits.append(f"role {n['role']}")
    if n.get("tools"):
        bits.append("tools " + ", ".join(n["tools"]))
    if n.get("sandbox"):
        bits.append(f"commands run in: {n['sandbox']}")
    if n.get("approvals_pending"):
        bits.append(f"{n['approvals_pending']} approval(s) waiting on the owner")
    if n.get("role_problem"):
        bits.append(f"WARNING: {n['role_problem']}")
    if bits:
        lines.append("- right now: " + "; ".join(bits))
    lines.append("- at the edge: if the task needs something you have NOT "
                 "studied or verified, say exactly that and stop. An honest "
                 "'not in my training' outranks a fluent guess, and the gates "
                 "will catch the guess anyway.")
    return "\n".join(lines[:cap])


def main():
    import argparse
    import tomllib
    ap = argparse.ArgumentParser(description="the agent's factual self-model")
    ap.add_argument("--root", default=".")
    ap.add_argument("--role")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    cfg = {}
    try:
        with open(os.path.join(root, "settings.toml"), "rb") as f:
            cfg = tomllib.loads(f.read().decode("utf-8-sig"))
    except OSError:
        pass
    m = build(root, a.role, None, cfg)
    print(json.dumps(m, indent=1) if a.json else render(m))


if __name__ == "__main__":
    main()
