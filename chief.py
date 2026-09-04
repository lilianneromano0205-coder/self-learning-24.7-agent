#!/usr/bin/env python3
"""Chief of Staff — the Personal Strategic Operator.

The owner's oldest idea in the corpus: one place that answers
"What should I do today?" from the ACTUAL state of everything — not from a
model's vibe, and never starting over.

This is deliberately deterministic. It reads the fleet's real instruments —
blocked questions, heartbeats, open gaps, armed intentions, goals in flight,
failures, skill promotions, spend, provider keys — and compiles a briefing
with a ranked action list. Rules produce the ranking; a model is never asked
to guess what matters. Zero tokens, runs in milliseconds, cannot hallucinate
a priority.

Ranking logic (highest first):
  1. APPROVE   risky tool actions paused for your decision
  1. ANSWER    agents blocked on you — they block everything else
  2. RESTART   loops claiming to run whose pulse went cold
  3. FUND      providers wired but missing their key (the fleet can't think)
  4. REPAIR    courses with open gaps (auto-repair queues, but you should know)
  5. PREPARE   intentions due within 24h
  6. REVIEW    skills quarantined recently — decide: fix or retire the lesson
  7. HARVEST   goals achieved / teams finished awaiting your read
  otherwise    all quiet: pointers to what could move your goals forward

Usage:  python chief.py [--home DIR] [--write]     (--write saves briefing.md)
API:    GET /api/briefing        Panel: Home → "Today"
"""

import argparse
import json
import os
import sys
import time

# A Windows console defaults to cp1252, which cannot encode the arrows in
# this module's help text -- `--help` used to end in a UnicodeEncodeError,
# which is a poor first impression for the first command anyone types.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):        # pragma: no cover
    pass

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
import fleet          # noqa: E402


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _tail(path, n=4000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    except OSError:
        return ""


def briefing(home):
    import loop
    import prospective as pm
    import skills as sg

    experts = fleet.list_experts(home)
    b = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "experts": len(experts),
         "needs_you": [], "approvals": [], "stalled": [], "unfunded": [], "gaps": [],
         "due_soon": [], "quarantined_skills": [], "recent_failures": [],
         "goals": [], "spend_today": 0.0, "recommendations": [],
         "safe_mode": []}

    now = time.time()
    for e in experts:
        root = e["root"]
        b["spend_today"] += e.get("spend_today_usd", 0)

        # 1. blocked on the owner
        blocked = e["tasks"].get("blocked", 0)
        if blocked:
            q = ""
            for line in reversed(_tail(os.path.join(root, "blocked.md"))
                                 .splitlines()):
                if line.strip() and not line.startswith("#"):
                    q = line.strip()[:120]
                    break
            b["needs_you"].append({"expert": e["name"], "count": blocked,
                                   "question": q})

        # 1b. risky actions waiting for the owner's approval
        try:
            import approvals as ap_mod
            for rec in ap_mod.pending(root):
                b["approvals"].append({"expert": e["name"], "id": rec["id"],
                                       "what": f"{rec['server']}.{rec['tool']} "
                                               f"{json.dumps(rec['args'])[:80]}",
                                       "reason": rec.get("reason", "")})
        except Exception:
            pass

        # 1c. fault protection (docs/DESIGN-P9b): an expert in safe mode
        # does no model-driven work until the owner clears it
        sm = os.path.join(root, "safe_mode.json")
        if os.path.isfile(sm):
            try:
                with open(sm, encoding="utf-8") as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                rec = {}
            b["safe_mode"].append({"expert": e["name"], "since": rec.get("at"),
                                   "trips": [t.get("limit") for t in
                                             rec.get("trips") or []]})

        # 2. stalled pulse (claims work exists, pulse cold > 15 min)
        hb = e.get("heartbeat")
        working = e["tasks"].get("running", 0) > 0
        if working and hb and hb.get("age_s", 0) > 900:
            b["stalled"].append({"expert": e["name"],
                                 "cold_minutes": round(hb["age_s"] / 60)})

        # 3. unfunded providers
        try:
            import tomllib
            with open(os.path.join(root, "settings.toml"), "rb") as f:
                cfg = tomllib.loads(f.read().decode("utf-8-sig"))
            env_keys = set()
            try:
                with open(os.path.join(root, "agent.env"), encoding="utf-8") as f:
                    for line in f:
                        if "=" in line and not line.strip().startswith("#"):
                            env_keys.add(line.split("=", 1)[0].strip())
            except OSError:
                pass
            import credentials
            for name, p in (cfg.get("providers") or {}).items():
                # every source the runtime honours, not api_key_env alone — a
                # provider funded by api_key_file used to be advised as
                # UNFUNDED, sending the owner to fix something that worked
                if p.get("type") == "mock" or credentials.key_present(p, root):
                    continue
                srcs = credentials.sources_for(p)
                b["unfunded"].append(
                    {"expert": e["name"], "provider": name,
                     "env": srcs[0][1] if srcs else "no key source declared"})
        except Exception:
            pass

        # 4. open gaps per course
        cdir = os.path.join(root, "courses")
        if os.path.isdir(cdir):
            for c in sorted(os.listdir(cdir)):
                gp = os.path.join(cdir, c, "gaps.md")
                try:
                    with open(gp, encoding="utf-8") as f:
                        n = sum(1 for line in f
                                if line.strip().startswith(("- G-", "G-")))
                except OSError:
                    n = 0
                if n:
                    b["gaps"].append({"expert": e["name"], "course": c,
                                      "open": n})

        # 5. intentions due within 24h
        for it in pm.load(root):
            if it.get("status") != "armed":
                continue
            w = it["when"]
            due_h = None
            if w["kind"] == "at":
                try:
                    t = time.mktime(time.strptime(w["iso"][:19],
                                                  "%Y-%m-%dT%H:%M:%S"))
                    due_h = (t - now) / 3600
                except (ValueError, KeyError):
                    pass
            elif w["kind"] == "every_days":
                last = w.get("last") or it["created"]
                try:
                    t = time.mktime(time.strptime(last[:19],
                                                  "%Y-%m-%dT%H:%M:%S"))
                    due_h = (t + float(w.get("n", 1)) * 86400 - now) / 3600
                except ValueError:
                    pass
            if due_h is not None and due_h <= 24:
                b["due_soon"].append({"expert": e["name"], "id": it["id"],
                                      "in_hours": max(0, round(due_h, 1)),
                                      "goal": it["then"]["goal"][:90]})

        # 6. recently quarantined skills (last 48h)
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                               time.localtime(now - 48 * 3600))
        for stem, ent in sg.load_graph(root).items():
            if (ent.get("status") == "quarantined"
                    and (ent.get("updated") or "") >= cutoff):
                b["quarantined_skills"].append(
                    {"expert": e["name"], "skill": stem,
                     "losses": ent.get("losses", 0)})

    # fleet-level: recent failures + goals
    try:
        import memory
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                               time.localtime(now - 24 * 3600))
        for r in memory.failures(home, limit=200, since=cutoff)[:6]:
            b["recent_failures"].append(
                {"expert": r["expert"], "category": r["category"],
                 "recurrence": r.get("recurrence", 1),
                 "cause": (r.get("cause") or "")[:90]})
    except Exception:
        pass
    try:
        import goal as goal_mod
        for g in goal_mod.list_goals(home):
            if g.get("status") in ("running", "achieved", "failed"):
                b["goals"].append({k: g.get(k) for k in
                                   ("id", "expert", "status", "goal")})
    except Exception:
        pass

    # ---- the ranked answer to "what should I do today?"
    rec = b["recommendations"]
    for x in b["safe_mode"]:
        rec.append({"rank": 0, "verb": "RESTORE",
                    "what": f"{x['expert']} is in SAFE MODE since "
                            f"{x['since']} ({', '.join(str(t) for t in x['trips']) or 'by hand'})"
                            f" — investigate, then clear it with a reason",
                    "where": f"python watchdog.py clear --root <{x['expert']}> --why ..."})
    for x in b["approvals"]:
        rec.append({"rank": 1, "verb": "APPROVE",
                    "what": f"{x['expert']} wants to run {x['what']} "
                            f"({x['reason']}) — grant or deny",
                    "where": f"agent {x['expert']} → Overview → Approvals"})
    for x in b["needs_you"]:
        rec.append({"rank": 1, "verb": "ANSWER",
                    "what": f"{x['expert']} is blocked on you "
                            f"({x['count']}): “{x['question']}”",
                    "where": f"agent {x['expert']} → Overview"})
    for x in b["stalled"]:
        rec.append({"rank": 2, "verb": "RESTART",
                    "what": f"{x['expert']} claims to be working but its "
                            f"pulse is {x['cold_minutes']}m cold",
                    "where": "System → Pulses"})
    seen = set()
    for x in b["unfunded"]:
        k = (x["provider"], x["env"])
        if k in seen:
            continue
        seen.add(k)
        rec.append({"rank": 3, "verb": "FUND",
                    "what": f"provider '{x['provider']}' is wired but "
                            f"{x['env']} is not set — agents on it "
                            f"cannot think",
                    "where": "agent.env beside the code"})
    for x in b["gaps"]:
        rec.append({"rank": 4, "verb": "REPAIR",
                    "what": f"{x['expert']}/{x['course']} has {x['open']} "
                            f"open gap(s) — repair tasks queue "
                            f"automatically; start its loop",
                    "where": f"agent {x['expert']} → Overview"})
    for x in b["due_soon"]:
        rec.append({"rank": 5, "verb": "PREPARE",
                    "what": f"intention fires in ~{x['in_hours']}h: "
                            f"{x['goal']}",
                    "where": f"agent {x['expert']}"})
    for x in b["quarantined_skills"]:
        rec.append({"rank": 6, "verb": "REVIEW",
                    "what": f"skill '{x['skill']}' on {x['expert']} was "
                            f"quarantined ({x['losses']} losses) — fix "
                            f"the playbook or let it rest",
                    "where": f"agent {x['expert']} → Mind → skills"})
    for g in b["goals"]:
        if g["status"] == "achieved":
            rec.append({"rank": 7, "verb": "HARVEST",
                        "what": f"goal achieved on {g['expert']}: "
                                f"{(g['goal'] or '')[:80]} — read the "
                                f"result",
                        "where": "Work → Goals"})
    rec.sort(key=lambda r: r["rank"])
    if not rec:
        rec.append({"rank": 9, "verb": "ADVANCE",
                    "what": "all quiet — nothing is blocked, stalled, "
                            "unfunded, or overdue. Give an agent a goal, or "
                            "teach one something new.",
                    "where": "Work → Goals · Agents → Teach"})
    b["spend_today"] = round(b["spend_today"], 4)
    return b


def render_markdown(b):
    lines = [f"# Today — {b['at'][:10]}",
             f"{b['experts']} agents · ${b['spend_today']} spent today", ""]
    for r in b["recommendations"]:
        lines.append(f"{r['rank']}. **{r['verb']}** — {r['what']}  "
                     f"_({r['where']})_")
    if b["recent_failures"]:
        lines.append("\n## Failures in the last 24h")
        for f in b["recent_failures"]:
            lines.append(f"- {f['expert']} [{f['category']}]"
                         + (f" ×{f['recurrence']}"
                            if f["recurrence"] > 1 else "")
                         + f": {f['cause']}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--home", default=HOME)
    ap.add_argument("--write", action="store_true",
                    help="also save briefing.md at the fleet home")
    a = ap.parse_args()
    b = briefing(os.path.abspath(a.home))
    md = render_markdown(b)
    print(md)
    if a.write:
        with open(os.path.join(a.home, "briefing.md"), "w",
                  encoding="utf-8") as f:
            f.write(md)


if __name__ == "__main__":
    main()
