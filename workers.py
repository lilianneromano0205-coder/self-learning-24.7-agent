#!/usr/bin/env python3
"""WORKERS — the computers work runs on, and why this one was chosen.

Manual §13 and UI spec §7. The core economic principle the manual states:

    "The expert is persistent; its computer is not. State survives while
     compute scales to zero or pauses. One expert must not imply one
     always-on VM or GPU."

`sandbox.py` already answers WHERE a command runs for one expert. What was
missing is the fleet-level view: a registry of computers with capabilities,
trust zones, cost and state, and a router that picks the cheapest SAFE one
that can actually do the next task — and can say why in a sentence a person
understands.

UI spec §7: *"A mission should say 'Using Office Windows PC because Excel +
internal network are required' rather than just exposing a backend name."*
`explain()` produces exactly that sentence, and it is derived from the
requirement matching, not written by hand.

Trust zones, because "can it run this" and "should it run this" are
different questions:

    trusted     the owner's own machine. Never the default for
                model-authored code.
    isolated    a disposable container or microVM. The default.
    org         an organization machine reachable through an outbound
                authenticated connection; policy decides which experts may
                use it at all.
    external    a third-party host. Least trusted; no credentials.
"""

import json
import os
import time

REGISTRY = "workers.json"

ZONES = {
    "trusted": {"rank": 3, "means": "the owner's own machine"},
    "isolated": {"rank": 0, "means": "disposable, nothing of value inside"},
    "org": {"rank": 2, "means": "an organization machine on the internal network"},
    "external": {"rank": 1, "means": "a third-party host"},
}

# The shapes the manual names, with the cost posture each one implies.
KINDS = {
    "local-host": {
        "zone": "trusted", "cost_per_hour": 0.0, "starts_in_s": 0,
        "scales_to_zero": False,
        "what": "this machine",
        "implies": ("gui", "windows-or-host-os"),
        "caution": "never the default for model-authored code: a mistake here "
                   "lands on the owner's own filesystem",
    },
    "local-docker": {
        "zone": "isolated", "cost_per_hour": 0.0, "starts_in_s": 3,
        "scales_to_zero": True,
        "what": "a disposable container on this machine",
        "implies": ("docker", "install"),
        "caution": "",
    },
    "cloud-container": {
        "zone": "isolated", "cost_per_hour": 0.05, "starts_in_s": 5,
        "scales_to_zero": True,
        "what": "a short-lived cloud container for CPU work",
        "implies": ("docker", "install"),
        "caution": "",
    },
    "cloud-vm": {
        "zone": "isolated", "cost_per_hour": 0.25, "starts_in_s": 45,
        "scales_to_zero": True,
        "what": "a full cloud computer with a browser and a desktop",
        "implies": ("browser", "gui", "install", "docker"),
        "caution": "",
    },
    "gpu-worker": {
        "zone": "isolated", "cost_per_hour": 2.50, "starts_in_s": 90,
        "scales_to_zero": True,
        "what": "an accelerated worker for training or heavy inference",
        "implies": ("gpu", "cuda", "install"),
        "caution": "burst only — never a baseline per-agent cost",
    },
    "fleet-worker": {
        "zone": "org", "cost_per_hour": 0.0, "starts_in_s": 0,
        "scales_to_zero": False,
        "what": "an organization computer that dialled in and advertised "
                "what it can do",
        "implies": ("internal-network",),
        "caution": "reaches the internal network: policy decides which "
                   "experts may use it",
    },
}

STATES = ("online", "paused", "stopped", "unreachable")


def capabilities_of(row):
    """What a computer can do = what it declared + what its KIND implies.

    Found live: a machine registered with --kind gpu-worker was refused GPU
    work because nobody had typed "gpu" into its capability list. The registry
    already knew it was accelerated; requiring the owner to say so twice is a
    trap, and one that only shows up on the routing path rather than at
    registration. The implication is stated in KINDS so it is inspectable
    rather than inferred by a matcher nobody can predict.
    """
    kind = KINDS.get(row.get("kind"), {})
    return sorted(set(row.get("capabilities") or []) | set(kind.get("implies", ())))


def _path(home):
    return os.path.join(home, REGISTRY)


def load(home):
    try:
        with open(_path(home), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(home, rows):
    import fileauth
    tmp = f"{_path(home)}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    os.replace(tmp, _path(home))
    return rows


def register(home, name, kind, capabilities=None, experts=None, note="",
             endpoint="", cost_per_hour=None):
    """Add a computer. `capabilities` is what it can actually DO — the words
    a task's requirements are matched against."""
    if kind not in KINDS:
        raise ValueError(f"unknown worker kind {kind!r}; the kinds are: "
                         f"{', '.join(sorted(KINDS))}")
    rows = load(home)
    slug = "".join(c if c.isalnum() or c in "-_" else "-"
                   for c in str(name).lower()).strip("-")[:40] or "worker"
    if any(r["id"] == slug for r in rows):
        raise ValueError(f"a computer called {slug!r} is already registered")
    spec = KINDS[kind]
    rows.append({
        "id": slug, "name": name, "kind": kind, "zone": spec["zone"],
        "capabilities": sorted({str(c).lower() for c in (capabilities or [])}),
        "experts": list(experts or []),          # empty = every expert
        "state": "stopped" if spec["scales_to_zero"] else "online",
        "cost_per_hour": (spec["cost_per_hour"] if cost_per_hour is None
                          else float(cost_per_hour)),
        "starts_in_s": spec["starts_in_s"],
        "scales_to_zero": spec["scales_to_zero"],
        "endpoint": endpoint, "note": note,
        "last_used": None, "used_seconds": 0.0, "spend_usd": 0.0,
        "registered": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    return _save(home, rows)[-1]


def get(home, wid):
    return next((r for r in load(home) if r["id"] == wid), None)


def set_state(home, wid, state):
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}")
    rows = load(home)
    for r in rows:
        if r["id"] == wid:
            r["state"] = state
            _save(home, rows)
            return r
    raise KeyError(wid)


def note_use(home, wid, seconds=0.0):
    """Charge time to a worker. This is what makes 'scale to zero' visible:
    a paused computer accrues nothing, and the panel shows it."""
    rows = load(home)
    for r in rows:
        if r["id"] == wid:
            r["last_used"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            r["used_seconds"] = round(r["used_seconds"] + float(seconds), 1)
            r["spend_usd"] = round(
                r["spend_usd"] + float(seconds) / 3600.0 * r["cost_per_hour"], 6)
            _save(home, rows)
            return r
    raise KeyError(wid)


# ------------------------------------------------------------------ routing

def requirements(text, home=None):
    """What a task needs, read from its own words.

    Two sources, both literal — a router that guesses is a router nobody can
    predict. First a small table of English phrasings that imply a
    capability ("spreadsheet in Excel" -> excel). Second, and more
    importantly, ANY capability a registered computer actually declares: an
    organization that registers a worker with `finance-db` gets routing for
    "query the finance-db" without anyone editing this file. Capabilities are
    data, so the matcher reads the data.
    """
    t = str(text or "").lower()
    need = set()
    if home:
        for r in load(home):
            for cap in capabilities_of(r):
                if cap and cap in t:
                    need.add(cap)
    for word, cap in (
            ("excel", "excel"), ("outlook", "outlook"), ("word doc", "office"),
            ("powerpoint", "office"), ("sharepoint", "internal-network"),
            ("intranet", "internal-network"), ("internal network", "internal-network"),
            ("on our server", "internal-network"), ("vpn", "internal-network"),
            ("browser", "browser"), ("website", "browser"), ("click", "browser"),
            ("screenshot", "gui"), ("desktop", "gui"),
            ("train", "gpu"), ("fine-tune", "gpu"), ("finetune", "gpu"),
            ("gpu", "gpu"), ("cuda", "gpu"),
            ("docker", "docker"), ("container", "docker"),
            ("windows", "windows"), ("macos", "macos"),
            ("install", "install"), ("pip install", "install"),
            ("npm", "node"), ("node ", "node"),
    ):
        if word in t:
            need.add(cap)
    return sorted(need)


def choose(home, task_text, expert=None, allow_trusted=False):
    """-> (worker, why) — the CHEAPEST computer that can actually do this.

    Cost is the tie-breaker, not the criterion: a worker that cannot meet a
    requirement is not cheap, it is useless. And a trusted machine is never
    chosen automatically for model-authored work.
    """
    need = set(requirements(task_text, home))
    rows = load(home)
    considered, eligible = [], []
    for r in rows:
        why_not = None
        if r["state"] == "unreachable":
            why_not = "unreachable"
        elif r["experts"] and expert and expert not in r["experts"]:
            why_not = f"policy: not shared with {expert}"
        elif r["zone"] == "trusted" and not allow_trusted:
            why_not = ("trusted machine — not used automatically for "
                       "model-authored work")
        else:
            missing = need - set(capabilities_of(r))
            if missing:
                why_not = "cannot: " + ", ".join(sorted(missing))
        considered.append({"id": r["id"], "name": r["name"],
                           "eligible": why_not is None, "why_not": why_not,
                           "cost_per_hour": r["cost_per_hour"]})
        if why_not is None:
            eligible.append(r)
    if not eligible:
        return None, {
            "chosen": None, "needed": sorted(need), "considered": considered,
            "why": ("no registered computer can do this. Needed: "
                    + (", ".join(sorted(need)) or "nothing special")
                    + ". Add one under Resources -> Computers."),
        }
    # Cheapest first — then the MOST ISOLATED, and only then the fastest to
    # start. Ordering isolation below start time is a real mistake: an
    # organization machine on the internal network is often free and instant,
    # so it would quietly become the default computer for arbitrary
    # model-authored work. Cheap is a tie-breaker; blast radius is not.
    eligible.sort(key=lambda r: (r["cost_per_hour"],
                                 ZONES[r["zone"]]["rank"],
                                 r["starts_in_s"]))
    best = eligible[0]
    return best, {
        "chosen": best["id"], "needed": sorted(need), "considered": considered,
        "why": explain(best, need),
    }


def explain(worker, need):
    """The sentence the UI spec asks for: 'Using Office Windows PC because
    Excel + internal network are required'."""
    if need:
        return (f"Using {worker['name']} because "
                + " + ".join(sorted(need)) + " "
                + ("is" if len(need) == 1 else "are") + " required"
                + (f" (${worker['cost_per_hour']}/h)"
                   if worker["cost_per_hour"] else " (no compute cost)"))
    return (f"Using {worker['name']} — nothing special is required, and it is "
            + ("free" if not worker["cost_per_hour"]
               else f"the cheapest available at ${worker['cost_per_hour']}/h"))


def bootstrap(home):
    """A fleet with no computers registered still has one: this machine's
    Docker if it is there, otherwise the host with its caution stated."""
    if load(home):
        return None
    import shutil
    if shutil.which("docker"):
        return register(home, "Local Docker", "local-docker",
                        capabilities=["docker", "install", "node", "browser"],
                        note="disposable container on this machine; network "
                             "off by default")
    return register(home, "This Computer", "local-host",
                    capabilities=["install", "node"],
                    note="no Docker found, so work runs on the host. Install "
                         "Docker for a disposable worker.")


def summary(home):
    rows = load(home)
    return {
        "workers": [{**r, "capabilities": capabilities_of(r),
                     "declared": sorted(r.get("capabilities") or []),
                     "implied": sorted(set(KINDS.get(r.get("kind"), {})
                                           .get("implies", ()))
                                       - set(r.get("capabilities") or []))}
                    for r in rows],
        "total": len(rows),
        "online": sum(1 for r in rows if r["state"] == "online"),
        "spend_usd": round(sum(r["spend_usd"] for r in rows), 4),
        "kinds": {k: v["what"] for k, v in KINDS.items()},
        "zones": ZONES,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("name")
    p.add_argument("--kind", required=True, choices=sorted(KINDS))
    p.add_argument("--can", action="append", default=[],
                   help="a capability this computer has (repeatable)")
    p.add_argument("--expert", action="append", default=[],
                   help="restrict to these experts (default: all)")
    p.add_argument("--note", default="")
    p.add_argument("--home", default=".")
    p = sub.add_parser("list"); p.add_argument("--home", default=".")
    p = sub.add_parser("choose")
    p.add_argument("task")
    p.add_argument("--expert")
    p.add_argument("--home", default=".")
    p = sub.add_parser("state")
    p.add_argument("id"); p.add_argument("state", choices=STATES)
    p.add_argument("--home", default=".")
    p = sub.add_parser("kinds")
    a = ap.parse_args()
    if a.cmd == "kinds":
        for k, v in KINDS.items():
            print(f"{k:<16} {v['zone']:<9} ${v['cost_per_hour']:<6} "
                  f"{v['what']}")
            if v["caution"]:
                print(f"{'':<16} caution: {v['caution']}")
        return
    home = os.path.abspath(a.home)
    if a.cmd == "add":
        w = register(home, a.name, a.kind, a.can, a.expert, a.note)
        print(f"registered {w['id']} ({w['kind']}, {w['zone']} zone), "
              f"can: {', '.join(w['capabilities']) or 'general work'}")
        return
    if a.cmd == "state":
        w = set_state(home, a.id, a.state)
        print(f"{w['id']} is now {w['state']}")
        return
    if a.cmd == "choose":
        w, why = choose(home, a.task, a.expert)
        print(why["why"])
        if not w:
            for c in why["considered"]:
                print(f"  {c['name']:<24} {c['why_not']}")
        return
    s = summary(home)
    if not s["workers"]:
        print("no computers registered — python workers.py add \"Local Docker\" "
              "--kind local-docker --can docker")
    for w in s["workers"]:
        print(f"{w['id']:<20} {w['kind']:<16} {w['zone']:<9} {w['state']:<10} "
              f"${w['spend_usd']:<8} {', '.join(w['capabilities'])[:40]}")


if __name__ == "__main__":
    main()
