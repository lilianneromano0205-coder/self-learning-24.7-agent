#!/usr/bin/env python3
"""The harness, as an inspectable object.

2026 harness research (Architectural Design Decisions in AI Agent Harnesses,
arXiv 2604.18071, 70 projects) found that harnesses converge on five design
dimensions — subagent architecture, context management, tool systems, safety
mechanisms, orchestration — and that "intermediate isolation is common but
high-assurance audit is rare". Agentic Harness Engineering (arXiv 2604.25850)
adds the missing discipline: **component observability** — every editable
harness component gets a file-level representation "so the action space is
explicit and revertible".

This module is that representation for THIS platform:

  manifest(root)         one machine-readable description of every component:
                         tools and their per-role allowlists, gates, policies,
                         memory tiers, budgets, loop events, versions and file
                         hashes. Nothing is inferred by a model; every field is
                         read from the code and the settings that actually run.
  check_contracts(root)  the harness auditing itself: every declared tool has
                         an execution branch, every event the panel claims to
                         render is a real loop event, every prompt the doctor
                         requires exists, every role points at a provider that
                         exists. A harness that disagrees with itself is a bug
                         you cannot see from any single file.
  integrity(root)        the session-start health ritual (Anthropic's
                         long-running-agent guidance: begin every session by
                         checking the world before doing new work). Sub-second,
                         model-free, never raises: settings parse, prompts
                         present, ledgers parse, no stale locks, disk writable.

Usage:
  python harness.py [--root DIR] [--json] [--check]
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

HARNESS_VERSION = "5.0"

# ledgers every expert may carry; each must be valid JSON if it exists
LEDGERS = [
    ("state.json", "task state"),
    ("skills/graph.json", "skill graph"),
    ("prospective.json", "prospective ledger"),
    ("variants/manifest.json", "variant manifest"),
    ("mcp.json", "MCP server config"),
    ("frontier/frontier.json", "capability frontier ledger"),
]
STALE_LOCK_SECONDS = 60
CORE_FILES = ["loop.py", "context.py", "policy.py", "effects.py",
              "approvals.py", "skills.py", "memory.py", "prospective.py",
              "variants.py", "workflows.py", "mcp.py", "sandbox.py",
              "harness.py"]


def _sha(path, n=12):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:n]
    except OSError:
        return None


def _settings(root):
    import tomllib
    for base in (root, HOME):
        p = os.path.join(base, "settings.toml")
        if os.path.isfile(p):
            try:
                with open(p, "rb") as f:
                    return tomllib.loads(f.read().decode("utf-8-sig")), p
            except Exception as e:
                return {"_error": str(e)}, p
    return {}, None


EVENT_SOURCES = ["loop.py", "prospective.py", "ingest.py", "consult.py",
                 "goal.py", "team.py", "workflows.py", "routines.py",
                 "context.py", "premise.py", "modelrouter.py"]


def loop_events():
    """Every event name the runtime can log — read from the sources that
    write to an agent's log, so the list cannot drift away from reality."""
    found = set()
    for fn in EVENT_SOURCES:
        try:
            with open(os.path.join(HOME, fn), encoding="utf-8") as f:
                found |= set(re.findall(r'"event":\s*"(\w+)"', f.read()))
        except OSError:
            continue
    return sorted(found)


def _context_budgets(a):
    """What every context window is allowed to spend, per source."""
    try:
        import context as ctx
        return ctx.budgets({"agent": a})
    except Exception:
        return {}


def _sandbox_state(cfg):
    """Where model-written commands actually run, and whether that is real."""
    try:
        import sandbox
        return sandbox.describe(cfg)
    except Exception as e:
        return {"backend": "host", "available": True, "why": f"unreadable: {e}"}


def manifest(root=None):
    """The whole harness in one dict."""
    root = os.path.abspath(root or HOME)
    cfg, cfg_path = _settings(root)
    a = cfg.get("agent", {}) if isinstance(cfg, dict) else {}
    roles = cfg.get("roles", {}) if isinstance(cfg, dict) else {}
    providers = cfg.get("providers", {}) if isinstance(cfg, dict) else {}

    import loop
    import skills as sg
    import variants as V
    import policy
    import memory as mem

    always = ["finish_task", "ask_human"]
    tools = []
    for t in loop.TOOL_DEFS:
        fn = t["function"]
        name = fn["name"]
        allowed_for, denied_for = [], []
        for rname, r in roles.items():
            allow = r.get("tools")
            if not allow or name in allow or name in always:
                allowed_for.append(rname)
            else:
                denied_for.append(rname)
        tools.append({
            "name": name,
            "description": (fn.get("description") or "").strip()[:160],
            "required": (fn.get("parameters") or {}).get("required", []),
            "always_allowed": name in always,
            "denied_roles": sorted(denied_for),
        })

    try:
        servers = __import__("mcp").load_servers(root)
    except Exception:
        servers = {}
    mcp_policy = {
        name: {"approval": spec.get("approval", "destructive"),
               "allow_roles": spec.get("allow_roles"),
               "allow_tools": spec.get("allow_tools"),
               "deny_tools": spec.get("deny_tools"),
               "risk_overrides": spec.get("risk")}
        for name, spec in servers.items()}

    return {
        "harness_version": HARNESS_VERSION,
        "root": root,
        "settings_file": cfg_path,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tools": tools,
        "gates": [
            {"name": "definition of done",
             "what": "finish_task is refused until the task's done_check "
                     "exits 0",
             "limit": f"max_done_rejects = {a.get('max_done_rejects', 6)}"},
            {"name": "citation gate (consultations)",
             "what": "every atom id cited must exist; uncovered ground must "
                     "say NOT IN MY TRAINING",
             "limit": "citecheck.py, wired as the task's done_check"},
            {"name": "memory integrity",
             "what": "duplicate ids, unresolvable citations, ungrounded spec "
                     "items and index gaps are rejected",
             "limit": "memcheck.py"},
            {"name": "mechanical spec verification",
             "what": "every spec item's CHECK: command must exit 0",
             "limit": "verify.py"},
            {"name": "skill promotion",
             "what": "a skill becomes PROVEN only on distinct gate-verified "
                     "wins; repeat losers are quarantined",
             "limit": f"{sg.PROMOTE_WINS} distinct wins (>=1 verified), "
                      f"{sg.QUARANTINE_LOSSES} losses"},
            {"name": "charter promotion",
             "what": "a variant must strictly beat the base on gated passes",
             "limit": f"min {V.MIN_TASKS} trial tasks; ties refused"},
            {"name": "declared prediction",
             "what": "a variant that declared what it would improve is "
                     "refused promotion when the trial did not deliver it",
             "limit": "variants.spawn(prediction=...) -> prediction_check"},
            {"name": "stop condition",
             "what": "a task's own deadline / max steps / max attempts "
                     "outrank the harness defaults",
             "limit": "loop.stop_text(task['stop'])"},
            {"name": "skill provenance",
             "what": "a community skill's bundled scripts may not run until "
                     "the owner promotes it",
             "limit": f"tiers: {', '.join(sg.PROVENANCE)}"},
            {"name": "closed book",
             "what": "the memory router may only REMOVE sources for the "
                     "student role, never add — an override cannot re-open it",
             "limit": "memrouter.CLOSED_BOOK"},
            {"name": "judge overrule",
             "what": "a goal judge claiming success while a check fails is "
                     "overruled and the overrule is recorded",
             "limit": "goal.py"},
            {"name": "constraint digest",
             "what": "a team handoff that drops a hard constraint changes the "
                     "digest and is detected",
             "limit": "team.py"},
            {"name": "approval",
             "what": "risky tool calls pause for the owner and resume "
                     "exactly once",
             "limit": "approvals.py + effects ledger"},
        ],
        "policies": {
            "shell_deny_rules": [why for _, why in policy.BUILTIN_DENY],
            "owner_deny_rules": len((a.get("command_policy") or {}).get("deny", [])),
            "role_allowlists": {r: v.get("tools") for r, v in roles.items()
                                if v.get("tools")},
            "protected_charters": sorted(V.PROTECTED_ROLES),
            "mcp_servers": mcp_policy,
            "sandbox": a.get("sandbox", "host"),
        },
        "memory_tiers": [
            {"tier": "working", "where": "contexts/<task>.json"},
            {"tier": "compaction summary", "where": "in-window note with "
                                                    "HARNESS FACTS"},
            {"tier": "verbatim archive",
             "where": "contexts/<task>.archive.jsonl (never lost)"},
            {"tier": "courses", "where": "courses/<c>/lessons/*/notes.md "
                                         "(cited atoms), spec, index, gaps"},
            {"tier": "skills", "where": "skills/ + skills/graph.json"},
            {"tier": "gotchas", "where": "courses/<c>/gotchas.md, gotchas/"},
            {"tier": "prospective", "where": "prospective.json"},
            {"tier": "commons", "where": "commons/ (fleet-shared)"},
            {"tier": "failures", "where": "commons/failures/<category>.jsonl",
             "categories": mem.CATEGORIES},
            {"tier": "competence", "where": "commons/competence/<expert>.jsonl"},
            {"tier": "effects", "where": "logs/effects.jsonl"},
            {"tier": "approvals", "where": "approvals/"},
            {"tier": "task archive", "where": "logs/tasks-archive.jsonl"},
            {"tier": "retired agents", "where": "retired/"},
            {"tier": "context manifests",
             "where": "contexts/<task>.compile.json (what each window held)"},
            {"tier": "checkpoints",
             "where": "checkpoints/ (resumable long tool work)"},
            {"tier": "events", "where": "events/ (payloads delivered by wake)"},
            {"tier": "routines", "where": "routines/ + skills/<name>/SKILL.md"},
            {"tier": "routing evidence",
             "where": "logs/model-outcomes.jsonl (what each model earned)"},
        ],
        "context_budgets": _context_budgets(a),
        "sandbox": _sandbox_state(cfg),
        "budgets": {k: a.get(k) for k in (
            "max_steps", "max_task_usd", "daily_budget_usd", "max_done_rejects",
            "escalate_after_errors", "context_token_threshold",
            "context_keep_recent_messages", "command_timeout_seconds",
            "model_timeout_seconds", "retain_finished_tasks",
            "max_skills_loaded", "max_malformed_tool_calls", "exam_threshold",
            "poll_interval_seconds") if k in a},
        "roles": {r: {"provider": v.get("provider"), "model": v.get("model"),
                      "tools": v.get("tools")} for r, v in roles.items()},
        "providers": sorted(providers),
        "loop_events": loop_events(),
        "versions": {
            "harness": HARNESS_VERSION,
            "mcp_legacy": getattr(__import__("mcp"), "LEGACY_VERSION", None),
            "mcp_modern": getattr(__import__("mcp"), "MODERN_VERSION", None),
            "a2a": "1.0",
            "prompts": {p: _sha(os.path.join(
                root if os.path.isdir(os.path.join(root, "prompts")) else HOME,
                "prompts", p))
                for p in sorted(os.listdir(os.path.join(
                    root if os.path.isdir(os.path.join(root, "prompts"))
                    else HOME, "prompts")))
                if p.endswith(".md")},
            "code": {f: _sha(os.path.join(HOME, f)) for f in CORE_FILES
                     if os.path.exists(os.path.join(HOME, f))},
        },
    }


def check_contracts(root=None):
    """The harness audits itself. Returns a list of problem strings."""
    root = os.path.abspath(root or HOME)
    problems = []
    import loop

    try:
        with open(os.path.join(HOME, "loop.py"), encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        return [f"loop.py unreadable: {e}"]
    for t in loop.TOOL_DEFS:
        name = t["function"]["name"]
        if f'if name == "{name}"' not in src:
            problems.append(f"tool '{name}' is declared but has no execution "
                            f"branch in loop.py")

    events = set(loop_events())
    try:
        import ui
        for ev in ui.FEED_EVENTS:
            if ev not in events:
                problems.append(f"the panel renders event '{ev}' which the "
                                f"loop never logs")
    except Exception as e:
        problems.append(f"ui.py could not be inspected: {e}")

    try:
        import doctor
        prompt_dir = (os.path.join(root, "prompts")
                      if os.path.isdir(os.path.join(root, "prompts"))
                      else os.path.join(HOME, "prompts"))
        for p in doctor.PROMPTS:
            if not os.path.exists(os.path.join(prompt_dir, p)):
                problems.append(f"required prompt missing: {p}")
    except Exception as e:
        problems.append(f"doctor.py could not be inspected: {e}")

    cfg, _ = _settings(root)
    providers = set(cfg.get("providers", {}) if isinstance(cfg, dict) else {})
    for rname, r in (cfg.get("roles", {}) if isinstance(cfg, dict) else {}).items():
        prov = r.get("provider")
        if prov and prov not in providers:
            problems.append(f"role '{rname}' points at provider '{prov}' "
                            f"which is not configured")
    return problems


def integrity(root=None):
    """The session-start health ritual: fast, model-free, never raises."""
    root = os.path.abspath(root or HOME)
    t0 = time.time()
    problems = []

    cfg, cfg_path = _settings(root)
    if isinstance(cfg, dict) and cfg.get("_error"):
        problems.append(f"settings.toml does not parse: {cfg['_error']}")
    elif not cfg_path:
        problems.append("no settings.toml found for this root")

    prompt_dir = (os.path.join(root, "prompts")
                  if os.path.isdir(os.path.join(root, "prompts"))
                  else os.path.join(HOME, "prompts"))
    for p in ("constitution.md", "_grounding.md"):
        if not os.path.exists(os.path.join(prompt_dir, p)):
            problems.append(f"prompt missing: {p}")

    for rel, label in LEDGERS:
        path = os.path.join(root, rel)
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    json.load(f)
            except (OSError, ValueError) as e:
                problems.append(f"{label} corrupt ({rel}): "
                                f"{str(e)[:120]}")

    now = time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in ("__pycache__", "contexts", "retired")]
        for fn in filenames:
            if fn.endswith(".lock") or fn.endswith(".mutex"):
                p = os.path.join(dirpath, fn)
                try:
                    if now - os.path.getmtime(p) > STALE_LOCK_SECONDS:
                        rel = os.path.relpath(p, root).replace(os.sep, "/")
                        problems.append(f"stale lock: {rel} (a holder died; "
                                        f"safe to delete)")
                except OSError:
                    pass

    probe = os.path.join(root, "logs", ".health-probe")
    try:
        os.makedirs(os.path.dirname(probe), exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        problems.append(f"logs/ is not writable: {e}")

    try:
        import shutil as _sh
        free_mb = _sh.disk_usage(root).free / (1024 * 1024)
        if free_mb < 200:
            problems.append(f"only {free_mb:.0f} MB free on this disk")
    except Exception:
        pass

    try:
        import sandbox
        # sandbox.available() takes the WHOLE config and reads cfg["agent"]
        # ["sandbox"] itself. This passed cfg["agent"], so the lookup became
        # cfg["agent"]["agent"]["sandbox"], found nothing, and fell back to
        # the "host" default -- which is the one backend that is always
        # available. The check therefore returned OK for every fleet ever
        # run, including one configured for docker on a machine with no
        # docker. It could not fail; a health check that cannot fail is not
        # a health check, it is a line of output.
        #
        # Now that acquire.install() routes pip through sandbox.run, a
        # missing backend is not cosmetic: installs fail at the moment the
        # agent needs a tool, and this is the check that was supposed to say
        # so first. policy.check(cmd, role, cfg) takes the [agent] TABLE and
        # sandbox.available(cfg) takes the ROOT -- neighbouring modules with
        # opposite conventions and nothing that would notice a mix-up.
        ok, why = sandbox.available(cfg if isinstance(cfg, dict) else {})
        if not ok:
            problems.append(f"sandbox unavailable: {why}")
    except Exception:
        pass

    return {"ok": not problems, "problems": problems,
            "ms": round((time.time() - t0) * 1000, 1),
            "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=HOME)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="audit the harness against itself; exit 1 on any "
                         "contract violation")
    a = ap.parse_args()
    root = os.path.abspath(a.root)

    if a.check:
        problems = check_contracts(root)
        health = integrity(root)
        if a.json:
            print(json.dumps({"contracts": problems, "health": health},
                             indent=2))
        else:
            for p in problems:
                print(f"CONTRACT  {p}")
            for p in health["problems"]:
                print(f"HEALTH    {p}")
            print(f"\n{len(problems)} contract problem(s), "
                  f"{len(health['problems'])} health problem(s) "
                  f"({health['ms']} ms)")
        sys.exit(1 if problems else 0)

    m = manifest(root)
    if a.json:
        print(json.dumps(m, indent=2, ensure_ascii=False))
        return
    print(f"HARNESS {m['harness_version']} — {m['root']}\n")
    print(f"tools ({len(m['tools'])})")
    for t in m["tools"]:
        deny = (f"  [denied to: {', '.join(t['denied_roles'])}]"
                if t["denied_roles"] else "")
        print(f"  {t['name']:<14}{t['description'][:70]}{deny}")
    print(f"\ngates ({len(m['gates'])})")
    for g in m["gates"]:
        print(f"  {g['name']:<28} {g['limit']}")
    print(f"\npolicies")
    print(f"  shell deny rules   {len(m['policies']['shell_deny_rules'])}")
    print(f"  protected charters {', '.join(m['policies']['protected_charters'])}")
    print(f"  sandbox            {m['policies']['sandbox']}")
    print(f"  mcp servers        {', '.join(m['policies']['mcp_servers']) or 'none'}")
    print(f"\nmemory tiers ({len(m['memory_tiers'])})")
    for t in m["memory_tiers"]:
        print(f"  {t['tier']:<20} {t['where']}")
    print(f"\nbudgets")
    for k, v in m["budgets"].items():
        print(f"  {k:<32} {v}")
    print(f"\nloop events ({len(m['loop_events'])}): "
          f"{', '.join(m['loop_events'])}")


if __name__ == "__main__":
    main()
