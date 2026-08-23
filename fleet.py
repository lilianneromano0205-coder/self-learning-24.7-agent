#!/usr/bin/env python3
"""Fleet manager: mint and inspect expert agents.

Each expert is a complete, isolated copy of the system under
experts/<name>/ — its own identity, settings, memory, courses, skills,
state, and logs. The code (loop.py, ingest.py, verify.py, memcheck.py) is
shared; the mind is not. Teach each expert its own field and run as many as
you want, side by side.

Usage:
  python fleet.py create <name> [--identity "what this expert masters"]
  python fleet.py list
  python fleet.py delete <name> --confirm
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import unicodedata

HOME = os.path.dirname(os.path.abspath(__file__))


def slugify(name):
    # accents transliterate instead of vanishing: Économie -> economie
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "expert"


def expert_dir(home, name):
    return os.path.join(home, "experts", slugify(name))


def create(home, name, identity):
    """THE one place an expert is born, on every path.

    Four callers reach this function — bootstrap.py, quick.py, and the panel's
    two creation routes — and only bootstrap.py used to prepare the home
    first. Pointing --home at a directory that had never been bootstrapped
    therefore produced a raw FileNotFoundError from copytree, and the panel's
    POST /api/experts turned it into a 500. The seeding belongs HERE, at the
    single gateway, rather than in whichever caller happened to remember it:
    a control that only guards the path its author was thinking about is the
    defect this platform keeps finding in itself.
    """
    dest = expert_dir(home, name)
    if os.path.exists(dest):
        sys.exit(f"ERROR: expert '{slugify(name)}' already exists at {dest}")
    seed_home(home)
    os.makedirs(os.path.join(home, "experts"), exist_ok=True)
    try:
        return _create_inner(home, dest, name, identity)
    except Exception:
        # never leave a half-born expert behind: an interrupted creation
        # rolls back completely rather than leaving a mind without settings
        shutil.rmtree(dest, ignore_errors=True)
        raise


def seed_home(home):
    """A fresh directory is not a fleet yet — give it the charters and default
    settings this install ships with, never overwriting what is already there.

    Delegates to bootstrap.seed_home so there is ONE implementation of what a
    fleet home contains; two copies would drift the day somebody adds a file.
    Imported lazily because bootstrap imports fleet.
    """
    try:
        os.makedirs(home, exist_ok=True)
    except OSError as e:
        sys.exit(f"ERROR: cannot use {home!r} as a fleet home: {e.strerror or e}. "
                 f"Pick a directory that exists, or whose parent does.")
    try:
        import bootstrap
    except ImportError:                      # pragma: no cover - defensive
        return []
    try:
        copied = bootstrap.seed_home(home)
    except OSError as e:
        sys.exit(f"ERROR: cannot prepare {home!r} as a fleet home: "
                 f"{e.strerror or e}. Check permissions and free space.")
    missing = [n for n in ("prompts", "settings.toml")
               if not os.path.exists(os.path.join(home, n))]
    if missing:
        sys.exit(f"ERROR: {home} is not a fleet home and cannot become one: "
                 f"{', '.join(missing)} is missing here AND in the install at "
                 f"{HOME}. Reinstall, or run: python bootstrap.py --home {home}")
    return copied


def _create_inner(home, dest, name, identity):
    os.makedirs(dest)
    shutil.copytree(os.path.join(home, "prompts"), os.path.join(dest, "prompts"))
    shutil.copy(os.path.join(home, "settings.toml"), os.path.join(dest, "settings.toml"))
    env_src = os.path.join(home, "agent.env")
    if os.path.exists(env_src):
        shutil.copy(env_src, os.path.join(dest, "agent.env"))
    for d in ("inbox", "courses", "logs", "contexts", "skills"):
        os.makedirs(os.path.join(dest, d))
    with open(os.path.join(dest, "identity.md"), "w", encoding="utf-8") as f:
        f.write(
            f"# IDENTITY — {name}\n"
            f"You are {name}, a dedicated expert agent with your own private "
            f"memory, courses, and skills.\n"
            f"Specialty and mission: {identity or 'to master whatever material the human feeds you.'}\n"
            f"Depth over breadth: everything you study and execute serves this "
            f"specialty. Your notes, spec items, and skills compound into "
            f"mastery of it — do not dilute them with unrelated material.\n")
    with open(os.path.join(dest, "reputation.md"), "w", encoding="utf-8") as f:
        f.write("# Reputation — role × model × prompt-version\n\n(no entries yet)\n")
    print(f"created expert '{slugify(name)}' at {dest}")
    print(f"  teach it:  drop files in {os.path.join(dest, 'inbox')}")
    print(f"             python ingest.py add-url <url> --root {dest}")
    print(f"  run it:    python loop.py run --root {dest}")
    return dest


def today_spend(root):
    p = os.path.join(root, "logs", f"spend-{time.strftime('%Y%m%d')}.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f).get("usd", 0.0)
    except OSError:
        return 0.0


def describe(home, slug):
    root = os.path.join(home, "experts", slug)
    tasks = {"queued": 0, "running": 0, "done": 0, "failed": 0, "blocked": 0}
    last_activity = None
    try:
        with open(os.path.join(root, "state.json"), "r", encoding="utf-8") as f:
            all_tasks = json.load(f)["tasks"]
        for t in all_tasks:
            tasks[t["status"]] = tasks.get(t["status"], 0) + 1
        if all_tasks:
            last_activity = all_tasks[-1].get("created")
    except (OSError, json.JSONDecodeError):
        pass
    identity = ""
    try:
        with open(os.path.join(root, "identity.md"), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("Specialty and mission:"):
                    identity = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    courses_dir = os.path.join(root, "courses")
    courses = sorted(c for c in os.listdir(courses_dir)
                     if os.path.isdir(os.path.join(courses_dir, c))) \
        if os.path.isdir(courses_dir) else []
    hb = None
    try:
        with open(os.path.join(root, "logs", "heartbeat.json"),
                  "r", encoding="utf-8") as f:
            h = json.load(f)
        hb = {"age_s": round(time.time() - h.get("ts", 0), 1),
              "note": h.get("note"), "task": h.get("task"),
              "role": h.get("role"), "pid": h.get("pid")}
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {"name": slug, "root": root, "identity": identity,
            "tasks": tasks, "courses": courses,
            "last_activity": last_activity,
            "heartbeat": hb,
            "spend_today_usd": round(today_spend(root), 4)}


def list_experts(home):
    base = os.path.join(home, "experts")
    if not os.path.isdir(base):
        return []
    return [describe(home, s) for s in sorted(os.listdir(base))
            if os.path.isdir(os.path.join(base, s))]


def delete_expert(home, name, purge=False, reason=""):
    """Retire by default — retirement stops compute, not existence. The whole
    world (identity, memory, courses, skills, logs, lineage) is preserved
    under retired/ and stays queryable and restorable. Only an explicit purge
    destroys it, because a deleted mind cannot teach the ones that follow."""
    dest = expert_dir(home, name)
    if not os.path.isdir(dest):
        raise KeyError(name)
    if purge:
        shutil.rmtree(dest)
        return {"purged": dest}
    sys.path.insert(0, HOME)
    import memory
    return memory.retire(home, slugify(name), reason=reason)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create")
    p.add_argument("name")
    p.add_argument("--identity", default="")
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("list")
    p.add_argument("--home", default=HOME)
    p = sub.add_parser("delete")
    p.add_argument("name")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--home", default=HOME)
    args = ap.parse_args()

    if args.cmd == "create":
        create(args.home, args.name, args.identity)
    elif args.cmd == "list":
        experts = list_experts(args.home)
        if not experts:
            print("no experts yet — python fleet.py create <name> --identity \"...\"")
        for e in experts:
            t = e["tasks"]
            print(f"{e['name']:<20} courses={len(e['courses']):<3} "
                  f"q={t['queued']} run={t['running']} done={t['done']} "
                  f"fail={t['failed']} blk={t['blocked']}  "
                  f"${e['spend_today_usd']} today  — {e['identity'][:50]}")
    elif args.cmd == "delete":
        if not args.confirm:
            sys.exit("refusing to delete an expert's entire memory without --confirm")
        print(f"deleted {delete_expert(args.home, args.name)}")


if __name__ == "__main__":
    main()
