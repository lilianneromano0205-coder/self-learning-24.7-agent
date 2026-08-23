#!/usr/bin/env python3
"""Doctor — one command that tells you whether the whole platform is healthy.

Checks, in order:
  1. runtime      python version, every core module imports cleanly
  2. anatomy      prompts (constitution, grounding, all 8 roles), page, units
  3. toolbox      what this machine can actually do right now
  4. fleet        every expert: settings parse, state parses, task counts,
                  and memcheck over every course's memory
  5. keys         which provider keys are present (names only, never values)
  --full          additionally runs the entire acceptance suite (~2-4 min)
  --live          additionally probes every provider with one real request

Exit 0 = healthy. Exit 1 = problems, each named. Run it after any change,
any update, any doubt:  python doctor.py

Usage:  python doctor.py [--home DIR] [--full] [--live]
"""

import argparse
import os
import subprocess
import sys

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

CORE_MODULES = ["loop", "ingest", "verify", "memcheck", "recall", "citecheck",
                "fleet", "team", "quick", "consult", "templates", "toolbox",
                "memory", "commons", "skills", "prospective", "variants",
                "approvals", "workflows", "effects", "policy", "mcp",
                "federation", "providers", "chief", "replay", "benchmark",
                "locks", "harness", "checkpoint", "context", "gotchas",
                "premise", "memrouter", "sandbox", "modelrouter", "routines",
                "trace", "uicards", "selfmodel", "sources", "conflicts",
                "standards", "designcheck", "backup", "preflight", "candidates",
                "curriculum", "evidence", "research",
                "confidence", "cases"]
PROMPTS = ["constitution.md", "_grounding.md", "ripper.md", "watcher.md",
           "librarian.md", "practitioner.md", "examiner.md", "student.md",
           "reflector.md", "consultant.md"]


class Report:
    def __init__(self):
        self.problems = []

    def ok(self, area, msg):
        print(f"  OK      {area:<10} {msg}")

    def bad(self, area, msg):
        self.problems.append(f"{area}: {msg}")
        print(f"  PROBLEM {area:<10} {msg}")


def check_runtime(r):
    print("[1/5] runtime")
    if sys.version_info >= (3, 11):
        r.ok("python", sys.version.split()[0])
    else:
        r.bad("python", f"{sys.version.split()[0]} — 3.11+ required (tomllib)")
    for m in CORE_MODULES:
        try:
            __import__(m)
        except Exception as e:
            r.bad("import", f"{m}.py failed: {e}")
    else:
        r.ok("modules", f"all {len(CORE_MODULES)} core modules import")
    try:
        import ast
        ast.parse(open(os.path.join(HOME, "ui.py"), encoding="utf-8").read())
        open(os.path.join(HOME, "ui.html"), encoding="utf-8").read()
        r.ok("panel", "ui.py parses, ui.html readable")
    except Exception as e:
        r.bad("panel", str(e))


def check_anatomy(r, home):
    """Code artifacts live with the code (HOME); a fleet home only needs its
    own prompts and settings. Conflating the two produced false alarms when
    the fleet lives elsewhere (e.g. /home/agent/fleet with code in /opt)."""
    print("[2/5] anatomy")
    prompt_dir = (os.path.join(home, "prompts")
                  if os.path.isdir(os.path.join(home, "prompts"))
                  else os.path.join(HOME, "prompts"))
    missing = [p for p in PROMPTS
               if not os.path.exists(os.path.join(prompt_dir, p))]
    if missing:
        r.bad("prompts", f"missing from {prompt_dir}: {', '.join(missing)}")
    else:
        r.ok("prompts", f"constitution + grounding + {len(PROMPTS) - 2} roles present")
    for f in ("agent.service", "Dockerfile", "ui.html"):   # code-side
        if os.path.exists(os.path.join(HOME, f)):
            r.ok("deploy", f)
        else:
            r.bad("deploy", f"{f} missing from the code directory")
    if os.path.exists(os.path.join(home, "settings.toml")):
        r.ok("files", "settings.toml (fleet template)")
    elif home != HOME:
        print("  note    files      no fleet-level settings.toml — each expert "
              "carries its own, which is fine")


def check_toolbox(r, home):
    print("[3/5] toolbox")
    import toolbox
    s = toolbox.scan(home)
    ready = [k for k, v in s["capabilities"].items() if v["ready"]]
    gone = [k for k, v in s["capabilities"].items() if not v["ready"]]
    r.ok("ready", ", ".join(ready) or "none")
    if gone:
        print(f"  note    missing    {', '.join(gone)} (agents are told; "
              f"they will ask you rather than attempt)")


def check_fleet(r, home):
    print("[4/5] fleet")
    import fleet
    import loop
    experts = fleet.list_experts(home)
    if not experts:
        r.ok("fleet", "no experts yet (create one in the panel or fleet.py)")
        return
    for e in experts:
        root = e["root"]
        try:
            agent = loop.Agent(root)
        except Exception as ex:
            r.bad(e["name"], f"settings broken: {ex}")
            continue
        t = e["tasks"]
        note = (f"tasks q{t['queued']}/r{t['running']}/d{t['done']}"
                f"/f{t['failed']}/b{t['blocked']}")
        # the newer ledgers must PARSE — a corrupt graph/intention file
        # silently disables skills or future actions, which is worse than
        # crashing. The doctor makes it loud.
        import json as _json
        for rel, label in (("skills/graph.json", "skill graph"),
                           ("prospective.json", "prospective ledger"),
                           ("variants/manifest.json", "variant manifest"),
                           ("mcp.json", "MCP server config")):
            path = os.path.join(root, rel)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        _json.load(f)
                except (OSError, ValueError) as ex:
                    r.bad(e["name"], f"{label} corrupt ({rel}): {ex}")
        for lock in ("prospective.json.lock", "skills/graph.json.lock"):
            lp = os.path.join(root, lock)
            try:
                import time as _t
                if os.path.exists(lp) and _t.time() - os.path.getmtime(lp) > 60:
                    r.bad(e["name"], f"stale ledger lock: {lock} "
                                     f"(safe to delete; a holder died)")
            except OSError:
                pass
        bad_courses = []
        import memcheck as mc
        for c in e["courses"]:
            errs, *_ = mc.check(c, root)
            if errs:
                bad_courses.append(f"{c}({len(errs)})")
        # a wedged loop looks exactly like an idle one from outside — the
        # heartbeat is what separates them
        hb = e.get("heartbeat")
        if hb and t["running"] and hb["age_s"] > 900:
            r.bad(e["name"], f"task {hb['task']} claims to be running but the "
                             f"loop has not pulsed for {int(hb['age_s'])}s — "
                             f"likely wedged; restart it")
            continue
        stale = ""
        if t["running"] and not hb:
            stale = "  (no heartbeat file — old loop, or never started here)"
        # retention health: the hot queue must stay small on a long-running fleet
        try:
            size_kb = os.path.getsize(os.path.join(root, "state.json")) / 1024
        except OSError:
            size_kb = 0
        if size_kb > 2048:
            r.bad(e["name"], f"state.json is {size_kb:.0f} KB — retention is not "
                             f"trimming (check retain_finished_tasks)")
        elif bad_courses:
            r.bad(e["name"], f"memory violations in: {', '.join(bad_courses)}")
        else:
            r.ok(e["name"], f"{len(e['courses'])} course(s) sound; {note}; "
                            f"state {size_kb:.0f} KB{stale}")


def check_chief(r, home):
    """The owner's morning question must always be answerable."""
    try:
        import chief
        b = chief.briefing(home)
        r.ok("chief", f"briefing compiles: {len(b['recommendations'])} "
                      f"recommendation(s), ${b['spend_today']} today")
    except Exception as ex:
        r.bad("chief", f"briefing failed to compile: {ex}")


def check_keys(r, home):
    print("[5/5] keys")
    import toolbox
    s = toolbox.scan(home)
    have = [k for k, v in s["keys"].items() if v]
    lack = [k for k, v in s["keys"].items() if not v]
    if have:
        r.ok("keys", ", ".join(have))
    if lack:
        print(f"  note    unset      {', '.join(lack)} — fill agent.env; "
              f"one free NVIDIA or HF key runs everything")
    if not have:
        r.bad("keys", "no provider key set — agents cannot think yet "
                      "(demo.py still works keyless)")


def readiness(home):
    """Exactly what stands between this install and running today — as a
    numbered list of things to do, each with HOW. Blocking items stop the
    bootstrap; notes name what an optional tool would unlock. Key material
    is never read, only the ENV NAMES."""
    import tomllib
    import shutil
    import json as _json
    items = []

    def add(what, how, blocking):
        items.append({"what": what, "how": how, "blocking": blocking})

    if sys.version_info < (3, 11):
        add(f"Python {sys.version.split()[0]} is too old",
            "install Python 3.11+ (tomllib)", True)
    for f in ("ui.py", "ui.html", "loop.py"):
        if not os.path.exists(os.path.join(HOME, f)):
            add(f"{f} is missing from the code directory",
                "re-extract learning-agent-core.zip", True)

    # keys: every non-mock provider that a role actually uses needs its env
    env_names = set()
    try:
        with open(os.path.join(home, "agent.env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if v.strip():
                        env_names.add(k.strip())
    except OSError:
        pass
    roots = [home]
    try:
        import fleet
        roots += [e["root"] for e in fleet.list_experts(home)]
    except Exception:
        pass
    needed = {}
    for root in roots:
        try:
            with open(os.path.join(root, "settings.toml"), "rb") as f:
                cfg = tomllib.loads(f.read().decode("utf-8-sig"))
        except Exception:
            continue
        provs = cfg.get("providers", {})
        used = {r.get("provider") for r in cfg.get("roles", {}).values()}
        for name, p in provs.items():
            if p.get("type") == "mock" or name not in used:
                continue
            env = p.get("api_key_env")
            if env and not os.environ.get(env) and env not in env_names:
                needed.setdefault(env, set()).add(name)
        sb = (cfg.get("agent") or {}).get("sandbox", "host")
        if sb == "docker" and not shutil.which("docker"):
            add(f"settings ask for the docker sandbox but docker is not installed",
                "install Docker Desktop or set [agent] sandbox = \"host\"", True)
    for env, provs in sorted(needed.items()):
        add(f"no key for provider(s) {', '.join(sorted(provs))}",
            f"put {env}=<your key> in agent.env (copy agent.env.example)", True)

    for tool, unlock in (("node", "frontend syntax checks and npx MCP servers"),
                         ("ffmpeg", "audio/video ingestion"),
                         ("pandoc", "docx/epub conversion"),
                         ("docker", "the isolated docker sandbox backend")):
        if not shutil.which(tool):
            add(f"{tool} not installed", f"optional: unlocks {unlock}", False)
    try:
        import fitz  # noqa: F401
    except Exception:
        add("pymupdf not installed", "optional: pip install pymupdf unlocks "
                                     "PDF page rendering", False)

    try:
        import fleet
        experts = fleet.list_experts(home)
        if not experts:
            add("no experts yet", "create one: python fleet.py create \"Name\" "
                                 "--identity \"...\" (or the panel)", False)
        for e in experts:
            hp = os.path.join(e["root"], "logs", "health.json")
            try:
                with open(hp, encoding="utf-8") as f:
                    h = _json.load(f)
                for p in h.get("problems", [])[:3]:
                    add(f"{e['name']}: {p}", "fix, then restart its loop", False)
            except OSError:
                pass
    except Exception:
        pass
    return {"ready": not any(i["blocking"] for i in items), "items": items}


def print_readiness(home):
    r = readiness(home)
    print("[readiness]")
    if r["ready"] and not r["items"]:
        print("  READY TO RUN TODAY")
    elif r["ready"]:
        print("  READY TO RUN TODAY (optional notes below)")
    n = 0
    for it in r["items"]:
        n += 1
        tag = "TODO" if it["blocking"] else "note"
        print(f"  {tag} {n}. {it['what']} -- {it['how']}")
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--home", default=HOME)
    ap.add_argument("--full", action="store_true",
                    help="also run the entire acceptance suite")
    ap.add_argument("--live", action="store_true",
                    help="also probe every provider with a real request")
    args = ap.parse_args()
    home = os.path.abspath(args.home)
    r = Report()
    print(f"EXPERT FLEET DOCTOR — {home}\n")
    check_runtime(r)
    check_anatomy(r, home)
    check_toolbox(r, home)
    check_fleet(r, home)
    check_chief(r, args.home)
    check_keys(r, home)
    print_readiness(home)

    if args.live:
        print("[live] probing providers…")
        import loop
        rows, ok = loop.Agent(home).check_providers()
        for role, prov, model, status in rows:
            (r.ok if status.startswith("OK") else r.bad)(
                "provider", f"{role} -> {prov}/{model}: {status}")
    if args.full:
        print("[full] acceptance suite…")
        res = subprocess.run(
            [sys.executable, os.path.join(HOME, "tests", "run_all.py")],
            cwd=os.path.join(HOME, "tests"), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800,
            env={**os.environ, "PYTHONUTF8": "1"})
        if res.returncode == 0:
            r.ok("suite", "ALL TESTS PASSED")
        else:
            tail = "\n".join((res.stdout or "").splitlines()[-5:])
            r.bad("suite", f"failures:\n{tail}")

    print("\n" + ("=" * 60))
    if r.problems:
        print(f"VERDICT: {len(r.problems)} PROBLEM(S)")
        for p in r.problems:
            print(f"  - {p}")
        sys.exit(1)
    keyless = not any(os.environ.get(k) for k in
                      ("DEEPSEEK_API_KEY", "NVIDIA_API_KEY", "HF_TOKEN",
                       "OPENROUTER_API_KEY", "GROQ_API_KEY"))
    print("VERDICT: HEALTHY"
          + (" (keys pending — mocked demo only until agent.env is filled)"
             if keyless and not args.live else ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
