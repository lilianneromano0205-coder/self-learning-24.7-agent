#!/usr/bin/env python3
"""CAPABILITY PACKS — what competence MEANS, defined outside the student.

THE PROBLEM THIS SOLVES. The platform's strongest guarantee is that the
caller defines acceptance before the agent works — the graders the worker
cannot write. But the owner ultimately wants "here's a goal, figure the
rest out", and those two requirements conflict: if the agent invents its
own acceptance tests, it can game its own exam, which is the reward-hacking
loop one level up. Both external audits converged on the same missing
abstraction, and this module is it.

A CAPABILITY PACK is a domain's definition of competence, authored by the
owner (or drafted by a model and then FROZEN by the owner), living OUTSIDE
every expert's working root:

    <home>/packs/<name>/
      pack.json           the domain, its competencies, the mastery bar
      curriculum.json     per-competency study queries (feeds discover.py)
      exercises/*.json    PRACTICE tasks — visible during learning
      transfer/*.json     SEALED tasks — the unseen exam. Structurally
                          unreadable by the student (see below).
      validators/*.py     the graders, shipped WITH the pack

Then "become excellent at X" compiles into contracts WITHOUT letting the
student decide what excellence means: every practice and transfer task
carries acceptance checks from the pack, frozen per-pursuit exactly like
any other contract.

WHY THE SEAL IS REAL, NOT DECORATIVE:

  * packs live in the fleet HOME, outside every expert root. The worker's
    file tools resolve against its own root and refuse absolute paths and
    escapes (fileauth), so the student cannot read the transfer tasks, and
    cannot edit the validators that will grade it. The exam is unseen
    because the filesystem authority makes it unreachable, not because a
    prompt asked nicely.
  * the pack's entire content — definition, curriculum, every exercise,
    every transfer task, every validator — is hashed at freeze and sealed
    into <home>/org/pack-seals.jsonl. verify_pack() refuses a pack whose
    content no longer matches: an edited grader set is a TAMPER verdict
    with nothing run, the same law contracts already enforce.
  * a transfer task is handed to the student ONE AT A TIME, at exam time,
    by the harness — and what the student produced is graded by the
    harness running the pack's validators. The student's opinion of its
    own answer is worth exactly what it is worth everywhere else here:
    nothing.

WHAT A PACK IS NOT. It is not a claim that mechanical validators capture
everything a domain means — designcheck.py's own docstring says a
deterministic floor is not taste, and that stays true here. A pack's
mastery bar is the FLOOR of competence, honestly labeled; domains whose
excellence cannot be mechanically floored cap at what the validators can
check, and mastery.py records that ceiling instead of hiding it.

    python capability.py validate <home> <pack>
    python capability.py freeze   <home> <pack>
    python capability.py verify   <home> <pack>
    python capability.py show     <home> <pack>
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

PACKS_DIR = "packs"
SEALS = os.path.join("org", "pack-seals.jsonl")
MAX_TASKS = 40           # a pack needing more is several packs
MIN_TRANSFER = 2         # fewer sealed tasks than this cannot show transfer


class PackError(Exception):
    pass


# ------------------------------------------------------------------- paths

def pack_dir(home, name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", str(name)):
        raise PackError("invalid pack name")
    base = os.path.realpath(os.path.join(home, PACKS_DIR))
    path = os.path.join(base, str(name))
    if os.path.realpath(path) != os.path.abspath(path):
        raise PackError("pack path must not be a symlink")
    return path


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _tasks_in(d):
    out = []
    try:
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                t = _read_json(os.path.join(d, fn))
                t["_file"] = fn
                out.append(t)
    except OSError:
        pass
    return out


def exercises(home, name):
    return _tasks_in(os.path.join(pack_dir(home, name), "exercises"))


def transfer_tasks(home, name):
    """The sealed exam. Callable by the HARNESS only in practice: the path
    sits outside every expert root, where the worker's file tools cannot
    resolve. Nothing in the platform ever injects these into a study
    context, and test_mastery asserts both properties."""
    return _tasks_in(os.path.join(pack_dir(home, name), "transfer"))


def baseline_tasks(home, name):
    return _tasks_in(os.path.join(pack_dir(home, name), "baseline"))


def retention_tasks(home, name):
    return _tasks_in(os.path.join(pack_dir(home, name), "retention"))


def load(home, name):
    p = os.path.join(pack_dir(home, name), "pack.json")
    pk = _read_json(p)
    problems = validate(home, name, pk)
    if problems:
        raise PackError(f"pack {name!r} is malformed: " + "; ".join(problems))
    return pk


# -------------------------------------------------------------- validation

def _task_problems(t, kind, seen_ids):
    out = []
    tid = t.get("id")
    if not tid or tid in seen_ids:
        out.append(f"{kind} {t.get('_file')}: missing or duplicate id")
    seen_ids.add(tid)
    if not str(t.get("goal") or "").strip():
        out.append(f"{kind} {tid}: no goal")
    acc = t.get("accept")
    if not isinstance(acc, list) or not acc:
        out.append(f"{kind} {tid}: no acceptance checks — an ungraded task "
                   f"proves nothing and cannot be in a pack")
    else:
        for a in acc:
            if not isinstance(a, dict) or not str(a.get("check") or "").strip():
                out.append(f"{kind} {tid}: malformed acceptance entry")
            elif "TODO" in str(a.get("check")):
                out.append(f"{kind} {tid}: acceptance still carries a TODO "
                           f"— a drafted pack, not an exam")
    comps = t.get("competencies")
    if not isinstance(comps, list) or not comps:
        out.append(f"{kind} {tid}: names no competencies — a failure here "
                   f"could not be diagnosed to anything")
    return out


def validate(home, name, pk=None):
    """-> list of problems, empty when well-formed."""
    out = []
    d = pack_dir(home, name)
    if pk is None:
        try:
            pk = _read_json(os.path.join(d, "pack.json"))
        except (OSError, ValueError) as e:
            return [f"pack.json unreadable: {e}"]
    comps = pk.get("competencies")
    if not isinstance(comps, dict) or not comps:
        out.append("pack.json: competencies must be a non-empty object")
    m = pk.get("mastery") or {}
    for k in ("practice_pass", "transfer_pass"):
        v = m.get(k)
        if not isinstance(v, (int, float)) or not (0 < v <= 1):
            out.append(f"mastery.{k} must be a fraction in (0, 1] — a pack "
                       f"with no bar is an exam nobody can fail")
    author = pk.get("author")
    if not isinstance(author, str) or not author.strip():
        out.append("author must name who wrote this exam — "
                   "provenance the student law checks against")
    ex = _tasks_in(os.path.join(d, "exercises"))
    tr = _tasks_in(os.path.join(d, "transfer"))
    baseline = baseline_tasks(home, name)
    retention = retention_tasks(home, name)
    for label, group in (("baseline", baseline), ("retention", retention)):
        if len(group) < MIN_TRANSFER:
            out.append(f"{label} needs at least {MIN_TRANSFER} independent tasks")
    if not ex:
        out.append("no exercises — competence needs practice, not just facts")
    if len(tr) < MIN_TRANSFER:
        out.append(f"{len(tr)} transfer task(s); at least {MIN_TRANSFER} "
                   f"sealed unseen tasks are needed to show TRANSFER rather "
                   f"than memorisation")
    all_tasks = baseline + ex + tr + retention
    if len(all_tasks) > MAX_TASKS:
        out.append(f"{len(all_tasks)} tasks — this is several packs")
    seen = set()
    known = set((comps or {}).keys())
    for t in ex:
        out += _task_problems(t, "exercise", seen)
    for t in tr:
        out += _task_problems(t, "transfer", seen)
    for label, group in (("baseline", baseline), ("retention", retention)):
        for t in group:
            out += _task_problems(t, label, seen)
    prompts, instances = set(), set()
    for t in all_tasks:
        prompt = " ".join(str(t.get("goal", "")).lower().split())
        instance = t.get("instance_id")
        if prompt in prompts or (instance and instance in instances):
            out.append(f"task {t.get('id')}: duplicate content or instance overlap")
        prompts.add(prompt)
        if instance:
            instances.add(instance)
        for c in (t.get("competencies") or []):
            if known and c not in known:
                out.append(f"task {t.get('id')}: unknown competency {c!r}")
    # every competency must be examined by at least one SEALED task, or
    # mastery in it would rest on practice alone — the student saw those
    for label, group in (("baseline", baseline), ("transfer", tr), ("retention", retention)):
        covered = {c for t in group for c in t.get("competencies", [])}
        for c in known - covered:
            out.append(f"competency {c!r} has no {label} task")
    return out


# ------------------------------------------------------------------- seals

def _content_hash(home, name):
    """One hash over EVERYTHING the pack is: definition, curriculum, every
    task, every validator. Order-stable, so the same content always hashes
    the same way."""
    d = pack_dir(home, name)
    h = hashlib.sha256()
    for dirpath, dirs, files in sorted(os.walk(d)):
        dirs.sort()
        for fn in sorted(files):
            p = os.path.join(dirpath, fn)
            if os.path.islink(p) or not os.path.isfile(p):
                raise PackError("pack contains non-regular file")
            rel = os.path.relpath(p, d).replace(os.sep, "/")
            h.update(rel.encode("utf-8"))
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def freeze(home, name):
    """Validate, then seal the pack's full content hash. From here on,
    verify_pack() refuses any drift — including in the validators, because
    an editable grader is no grader."""
    problems = validate(home, name)
    if problems:
        raise PackError("cannot freeze a malformed pack: "
                        + "; ".join(problems[:5]))
    digest = _content_hash(home, name)
    existing = _sealed_hash(home, name)
    if existing is not None and existing != digest:
        raise PackError("seal conflict: publish a new pack version/name")
    sp = os.path.join(home, SEALS)
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    try:
        author = _read_json(os.path.join(pack_dir(home, name),
                                         "pack.json")).get("author")
    except (OSError, ValueError):
        author = None
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "pack": str(name),
           "hash": digest, "author": str(author or "owner")}
    with open(sp, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    return row


def _sealed_hash(home, name):
    found = None
    try:
        with open(os.path.join(home, SEALS), encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("pack") == str(name):
                    digest = row.get("hash")
                    if found is not None and found != digest:
                        raise PackError("conflicting pack seals: TAMPER")
                    found = digest
    except OSError:
        pass
    return found


def verify_pack(home, name):
    """-> {"ok", "tamper", "why"}. A pack that no longer matches its seal
    grades nothing: a forged grader that executes is a forged grader that
    can pass — the same law contracts enforce, applied to the exam itself."""
    try:
        sealed = _sealed_hash(home, name)
    except PackError as exc:
        return {"ok": False, "tamper": True, "why": str(exc)}
    if sealed is None:
        return {"ok": False, "tamper": False,
                "why": f"pack {name!r} was never frozen; freeze it first "
                       f"(python capability.py freeze <home> {name})"}
    try:
        current = _content_hash(home, name)
    except (PackError, OSError) as exc:
        return {"ok": False, "tamper": True, "why": str(exc)}
    if current != sealed:
        return {"ok": False, "tamper": True,
                "why": f"pack {name!r} no longer matches its seal — its "
                       f"definition, tasks or validators were edited after "
                       f"freezing. Nothing will be graded against it."}
    return {"ok": True, "tamper": False, "why": "", "hash": sealed}


# ------------------------------------------------------- task -> contract

def accept_for(home, name, task):
    """A task's acceptance list, with {PACK} in check commands resolved to
    the pack's absolute directory — so validators run from where the
    STUDENT CANNOT WRITE, against artifacts the student produced in its
    own root."""
    d = pack_dir(home, name).replace("\\", "/")
    out = []
    for i, a in enumerate(task.get("accept") or [], 1):
        out.append({"id": a.get("id") or f"A{i}",
                    "what": a.get("what") or a.get("check", "")[:80],
                    "check": str(a["check"]).replace("{PACK}", d)})
    return out


def study_queries(home, name):
    """Per-competency study queries for discover.py, from curriculum.json —
    falling back to the competency's own study text in pack.json."""
    d = pack_dir(home, name)
    try:
        cur = _read_json(os.path.join(d, "curriculum.json"))
    except (OSError, ValueError):
        cur = {}
    pk = load(home, name)
    out = {}
    for comp, spec in (pk.get("competencies") or {}).items():
        q = (cur.get(comp) or {}).get("study") if isinstance(
            cur.get(comp), dict) else cur.get(comp)
        out[comp] = str(q or (spec or {}).get("study") or
                        f"{pk.get('domain', name)} {comp}")
    return out


# ------------------------------------------------------------------ drafts

def draft(home, name, domain, competencies, author="owner"):
    """A pack SKELETON for a NEW domain — the entry point for 'become
    excellent at X' where no pack exists yet.

    Competencies are named, curriculum stubs point discover.py at real
    study, and every acceptance check is a TODO — so validate() REFUSES the
    draft until a person or a different expert fills the exam in (the same
    honesty as runbook drafts: the shape is recovered, the substance is
    earned). The author is RECORDED, because the law lives one level down:
    mastery refuses to examine a student on a pack that student authored.
    Drafting your own curriculum is fine; drafting your own diploma is
    structurally impossible."""
    if not isinstance(competencies, dict) or not competencies:
        raise PackError("competencies must be a non-empty {name: study} map")
    d = pack_dir(home, name)
    if os.path.exists(os.path.join(d, "pack.json")):
        raise PackError(f"pack {name!r} already exists — draft a new name")
    os.makedirs(os.path.join(d, "exercises"), exist_ok=True)
    os.makedirs(os.path.join(d, "transfer"), exist_ok=True)
    os.makedirs(os.path.join(d, "baseline"), exist_ok=True)
    os.makedirs(os.path.join(d, "retention"), exist_ok=True)
    os.makedirs(os.path.join(d, "validators"), exist_ok=True)
    pk = {"name": str(name), "version": 1, "domain": str(domain),
          "author": str(author),
          "competencies": {
              str(c): {"study": str(s), "why": "TODO: why this matters"}
              for c, s in competencies.items()},
          "mastery": {"practice_pass": 0.75, "transfer_pass": 0.7,
                      "note": "the bar is the validators' MECHANICAL FLOOR"}}
    with open(os.path.join(d, "pack.json"), "w", encoding="utf-8") as f:
        json.dump(pk, f, indent=1)
    with open(os.path.join(d, "curriculum.json"), "w", encoding="utf-8") as f:
        json.dump({c: {"study": s} for c, s in competencies.items()}, f,
                  indent=1)
    comps = sorted(competencies)
    stub_accept = [{"id": "A1", "what": "TODO: what this proves",
                    "check": "TODO: a command exiting 0 when done"}]
    with open(os.path.join(d, "exercises", "e1.json"), "w",
              encoding="utf-8") as f:
        json.dump({"id": "e1", "goal": f"TODO: a practice task in {domain}",
                   "competencies": comps, "accept": stub_accept}, f, indent=1)
    for split, prefix in (("baseline", "b"), ("transfer", "t"), ("retention", "r")):
        for i in range(1, MIN_TRANSFER + 1):
            with open(os.path.join(d, split, f"{prefix}{i}.json"), "w", encoding="utf-8") as f:
                json.dump({"id": f"{prefix}{i}", "goal": f"TODO: independent {split} instance {i} examining {domain}",
                           "competencies": comps, "accept": stub_accept}, f, indent=1)
    return {"pack": str(name), "dir": d, "author": str(author),
            "problems": validate(home, name)}


# --------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("validate", "freeze", "verify", "show"):
        p = sub.add_parser(c)
        p.add_argument("home"); p.add_argument("pack")
    pd = sub.add_parser("draft")
    pd.add_argument("home"); pd.add_argument("pack")
    pd.add_argument("--domain", required=True)
    pd.add_argument("--competency", action="append", required=True,
                    metavar="NAME=STUDY_QUERY")
    pd.add_argument("--author", default="owner")
    a = ap.parse_args()
    if a.cmd == "validate":
        problems = validate(a.home, a.pack)
        if problems:
            for p in problems:
                print(f"  {p}")
            raise SystemExit(1)
        print(f"{a.pack}: well-formed "
              f"({len(exercises(a.home, a.pack))} exercise(s), "
              f"{len(transfer_tasks(a.home, a.pack))} sealed transfer task(s))")
    elif a.cmd == "freeze":
        row = freeze(a.home, a.pack)
        print(f"sealed {a.pack} @ {row['hash'][:16]}…")
    elif a.cmd == "verify":
        r = verify_pack(a.home, a.pack)
        print(json.dumps(r, indent=1))
        raise SystemExit(0 if r["ok"] else 1)
    elif a.cmd == "show":
        pk = load(a.home, a.pack)
        print(json.dumps(pk, indent=1))
    elif a.cmd == "draft":
        comps = {}
        for spec in a.competency:
            c, _, q = spec.partition("=")
            comps[c.strip()] = q.strip() or c.strip()
        r = draft(a.home, a.pack, a.domain, comps, author=a.author)
        print(f"drafted {r['pack']} at {r['dir']} (author {r['author']})")
        print(f"  {len(r['problems'])} TODO(s) before it can freeze — the "
              f"draft is a shape, the exam is still to be written:")
        for p in r["problems"][:8]:
            print(f"    {p}")


if __name__ == "__main__":
    main()
