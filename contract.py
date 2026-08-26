#!/usr/bin/env python3
"""THE GOAL CONTRACT — what "done" means, frozen before any work begins.

WHY THIS EXISTS. goal.py already refuses to trust a model's opinion of its
own progress: milestones carry mechanical checks, the judge sits on a
different model family, and the judge's verdict is re-checked against the
checks. An external audit of this platform found the hole in that design,
and it is worth stating in its own words:

    THE PLANNER WRITES ITS OWN GRADERS.

Milestone CHECK commands are authored by the same model family that then
does the work to satisfy them. A planner under pressure to finish can write
checks that are easy to pass rather than checks that prove the goal —
`test -f notes.md` instead of "the exam scored 90". That is reward hacking
with extra steps, and no amount of judging fixes it, because the judge reads
the same plan.

The audit's remedy, implemented here, is a CONTRACT:

  * ACCEPTANCE TESTS are fixed at contract creation — before any planning,
    by the caller (owner, or the harness on the owner's behalf), never by
    the worker. Each is a shell command that exits 0 when its criterion is
    met. They are the graders the worker cannot write.
  * The contract is FROZEN: its acceptance tests are hashed, the hash is
    SEALED into an append-only ledger OUTSIDE the expert's working root, and
    verify() refuses a contract whose current content no longer matches its
    seal. The worker's file tools cannot touch contract files at all
    (fileauth classifies them CONTROL); a worker that shells around that and
    edits the file anyway does not gain a passing verdict — it gains a
    TAMPER verdict, because the seal no longer matches.
  * COMPLETION IS A STATE TRANSITION, not a sentence. The pursuit may end
    `verified` ONLY when every acceptance test passed in a run the harness
    executed itself. A goal whose criteria could not be made mechanical can
    never reach `verified` — it ends `partial`, with the unmet criteria
    named, because "a reviewer would probably agree" is an opinion and this
    ledger records outcomes.
  * BUDGETS bound the pursuit: dollars, minutes, cycles. Exceeding one is a
    BLOCKED end-state naming what ran out, never a silent continuation.
  * EVERY TRANSITION IS AN EVENT in an append-only ledger, so a crashed
    pursuit can be reconstructed from what actually happened rather than
    from what a snapshot file remembers. replay() rebuilds the state purely
    from events and reports any divergence from the snapshot.

WHAT THIS DOES NOT CLAIM. Acceptance tests prove what a command can check.
A goal like "write a beautiful essay" has no honest mechanical acceptance,
and this module's contribution is that the pursuit then says PARTIAL out
loud instead of ACHIEVED quietly. The seal detects tampering; on the `host`
sandbox nothing PREVENTS a shell command from editing a file (policy.py says
the same about itself). Detection is the property tested here: a tampered
contract cannot verify.

States and their meaning:

    draft      created, acceptance not yet frozen — nothing may run
    ready      frozen; work may begin
    running    a pursuit is executing under this contract
    verified   every acceptance test passed, run by the harness   (terminal)
    partial    work ended; some criteria unmet or unmechanical    (terminal)
    blocked    stopped: budget, oscillation, authority, tamper — named
    exhausted  cycles ran out with tests still failing            (terminal)
    failed     the pursuit itself broke                           (terminal)

`blocked` is the one non-terminal ending: an owner who fixes the named
blocker may resume it to running.

    python contract.py create <expert-root> <gid> "goal text"
           --accept "exam scored::python verify.py databases"
           --max-usd 2.50 --max-minutes 120
    python contract.py verify <expert-root> <gid>
    python contract.py show   <expert-root> <gid>
    python contract.py events <expert-root> <gid>
    python contract.py replay <expert-root> <gid>
"""

import argparse
import hashlib
import json
import os
import sys
import time

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)

STATES = ("draft", "ready", "running", "verified", "partial", "blocked",
          "exhausted", "failed")
# The machine. A transition not listed here is refused — "verified" cannot
# be reached from "draft" by any spelling, and nothing leaves a terminal
# state except blocked, which an owner may deliberately resume.
TRANSITIONS = {
    "draft":     ("ready", "failed"),
    "ready":     ("running", "failed", "blocked"),
    "running":   ("verified", "partial", "blocked", "exhausted", "failed",
                  "running"),
    "blocked":   ("running", "failed"),
    "verified":  (),
    "partial":   (),
    "exhausted": (),
    "failed":    (),
}
MAX_ACCEPT = 12          # a goal needing more checks than this is several goals


class ContractError(Exception):
    pass


# ------------------------------------------------------------------- paths

def _dir(root, gid):
    return os.path.join(root, "goals", str(gid))


def path(root, gid):
    return os.path.join(_dir(root, gid), "contract.json")


def events_path(root, gid):
    return os.path.join(_dir(root, gid), "events.jsonl")


def seal_path(root):
    """The seal ledger lives OUTSIDE the expert's working root when the
    expert lives in a fleet home — <home>/org/contract-seals.jsonl — so a
    worker editing files under its own root cannot also edit the reference
    its contract is checked against. A bare root (tests, standalone) seals
    beside itself and the seal row records which kind it got, because a
    protection that silently degrades is a protection that lies."""
    parent = os.path.dirname(os.path.abspath(root))
    if os.path.basename(parent).lower() == "experts":
        home = os.path.dirname(parent)
        return os.path.join(home, "org", "contract-seals.jsonl"), "home"
    return os.path.join(root, "org", "contract-seals.jsonl"), "root"


# ------------------------------------------------------------------ events

def event(root, gid, kind, **data):
    """Append one event. The ledger is the source of truth; the snapshot in
    contract.json is a convenience projection of it."""
    p = events_path(root, gid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": str(kind)}
    row.update(data)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:                      # pragma: no cover
            pass
    return row


def events(root, gid):
    out = []
    try:
        with open(events_path(root, gid), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    out.append({"kind": "corrupt_line", "raw": line[:200]})
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- contract

def _accept_hash(accept):
    """The frozen identity of the graders. Canonical JSON, so key order and
    whitespace cannot make one acceptance set hash two ways."""
    canon = json.dumps(accept, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def parse_accept(items):
    """CLI shape: 'what it proves::the command'. -> [{"id","what","check"}]"""
    out = []
    for i, raw in enumerate(items or [], 1):
        raw = str(raw)
        if "::" in raw:
            what, check = raw.split("::", 1)
        else:
            what, check = raw, raw
        what, check = what.strip(), check.strip()
        if not check:
            raise ContractError(f"acceptance {i} has an empty command")
        out.append({"id": f"A{i}", "what": what or check, "check": check})
    return out


def create(root, gid, goal, criteria="", accept=None, non_goals="",
           max_usd=0.0, max_minutes=0, max_cycles=4):
    """Write the contract, in `draft`. Freezing is a separate, explicit act
    so a caller can review what is about to become the definition of done."""
    accept = list(accept or [])
    if len(accept) > MAX_ACCEPT:
        raise ContractError(
            f"{len(accept)} acceptance tests; more than {MAX_ACCEPT} means "
            f"this is several goals wearing one id — split it")
    for a in accept:
        if not isinstance(a, dict) or not a.get("check"):
            raise ContractError(f"malformed acceptance entry: {a!r}")
    c = {
        "gid": str(gid), "version": 1,
        "goal": str(goal), "criteria": str(criteria or ""),
        "non_goals": str(non_goals or ""),
        "acceptance": accept,
        "budget": {"max_usd": float(max_usd or 0.0),
                   "max_minutes": int(max_minutes or 0),
                   "max_cycles": int(max_cycles or 4)},
        "state": "draft", "state_why": "",
        "accept_hash": None, "sealed": None,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _write(root, gid, c)
    event(root, gid, "contract_created", goal=str(goal)[:200],
          acceptance=len(accept), max_usd=c["budget"]["max_usd"],
          max_minutes=c["budget"]["max_minutes"], max_cycles=max_cycles)
    return c


def _write(root, gid, c):
    p = path(root, gid)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def load(root, gid):
    with open(path(root, gid), encoding="utf-8") as f:
        return json.load(f)


def freeze(root, gid):
    """draft -> ready. The acceptance set is hashed and SEALED into the
    ledger outside the working root. From this moment the graders are fixed:
    verify() will refuse a contract whose content no longer matches."""
    c = load(root, gid)
    if c["state"] != "draft":
        raise ContractError(f"cannot freeze from state {c['state']!r}")
    h = _accept_hash(c["acceptance"])
    sp, kind = seal_path(root)
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "gid": c["gid"],
           "accept_hash": h, "n": len(c["acceptance"]), "where": kind}
    with open(sp, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    c["accept_hash"] = h
    c["sealed"] = {"where": kind, "at": row["at"]}
    c["state"] = "ready"
    c["state_why"] = "acceptance frozen and sealed"
    _write(root, gid, c)
    event(root, gid, "acceptance_frozen", accept_hash=h, where=kind)
    return c


def _sealed_hash(root, gid):
    """The hash the OUTSIDE ledger remembers for this contract. The LAST
    seal wins (a legitimately amended contract is re-sealed); a missing seal
    is 'never frozen', which verify treats as failure, not as licence."""
    sp, _kind = seal_path(root)
    found = None
    try:
        with open(sp, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("gid") == str(gid):
                    found = row.get("accept_hash")
    except OSError:
        pass
    return found


def transition(root, gid, new_state, why=""):
    """The ONLY way state changes. Illegal jumps are refused by the machine,
    not by the caller's discipline."""
    c = load(root, gid)
    cur = c["state"]
    if new_state not in STATES:
        raise ContractError(f"no such state {new_state!r}")
    if new_state not in TRANSITIONS.get(cur, ()):
        raise ContractError(
            f"illegal transition {cur} -> {new_state}: a contract cannot "
            f"{'leave a terminal state' if not TRANSITIONS.get(cur) else 'jump there'}"
            + (f" ({why})" if why else ""))
    c["state"] = new_state
    c["state_why"] = str(why or "")
    _write(root, gid, c)
    event(root, gid, "state", to=new_state, why=str(why or "")[:300])
    return c


# ------------------------------------------------------------ verification

def verify(root, gid, cfg=None, timeout=120):
    """Run every frozen acceptance test, harness-side. THE completion
    authority: nothing else in the platform may declare a contract verified.

    Returns {"tamper", "mechanical", "all", "passed", "failed", "results"}.
      * tamper=True  -> the contract on disk no longer matches its seal;
                        nothing was run, nothing can pass.
      * mechanical=False -> no acceptance tests were frozen. `all` is False
                        BY FICTION-REFUSAL: an empty test set passing
                        "all of them" is the vacuous assertion this
                        platform keeps hunting, so emptiness fails loudly.
    """
    c = load(root, gid)
    sealed = _sealed_hash(root, gid)
    current = _accept_hash(c.get("acceptance") or [])
    if c.get("accept_hash") is None or sealed is None:
        event(root, gid, "verify", tamper=False, mechanical=False,
              all=False, why="never frozen")
        return {"tamper": False, "mechanical": False, "all": False,
                "passed": [], "failed": [], "results": [],
                "why": "this contract was never frozen; freeze it first"}
    if current != sealed or c.get("accept_hash") != sealed:
        event(root, gid, "verify_tamper", sealed=sealed, current=current)
        return {"tamper": True, "mechanical": bool(c.get("acceptance")),
                "all": False, "passed": [], "failed": [], "results": [],
                "why": ("the contract's acceptance tests no longer match "
                        "the sealed hash — the graders were edited after "
                        "freezing. Nothing was run; a tampered contract "
                        "cannot verify.")}
    accept = c.get("acceptance") or []
    if not accept:
        event(root, gid, "verify", tamper=False, mechanical=False, all=False)
        return {"tamper": False, "mechanical": False, "all": False,
                "passed": [], "failed": [], "results": [],
                "why": ("no mechanical acceptance tests exist, so nothing "
                        "can be VERIFIED — the honest ceiling for this "
                        "contract is PARTIAL")}
    import execution
    results, passed, failed = [], [], []
    for a in accept:
        try:
            rc, out, err = execution.run(
                "gate", a["check"], root, cfg=cfg, role="examiner",
                timeout=timeout, reason=f"acceptance {a['id']}")
        except Exception as e:                # a broken check is a FAILING one
            rc, out, err = 1, "", f"{type(e).__name__}: {e}"
        row = {"id": a["id"], "what": a["what"], "rc": int(rc),
               "err": str(err)[:200]}
        results.append(row)
        (passed if rc == 0 else failed).append(a["id"])
    ok = not failed
    event(root, gid, "verify", tamper=False, mechanical=True, all=ok,
          passed=passed, failed=failed)
    return {"tamper": False, "mechanical": True, "all": ok,
            "passed": passed, "failed": failed, "results": results,
            "why": "" if ok else f"{len(failed)} acceptance test(s) failing"}


# ---------------------------------------------------------------- budgets

def budget_state(root, gid, spent_usd=None):
    """What remains, and what has run out. Wall-clock is measured from the
    first event; spend is the caller's running total (goal.py accumulates
    real task costs into `spent` events), re-derived here from the ledger so
    a crashed pursuit still knows what it already paid."""
    c = load(root, gid)
    ev = events(root, gid)
    b = c.get("budget") or {}
    if spent_usd is None:
        spent_usd = sum(float(e.get("usd") or 0.0)
                        for e in ev if e.get("kind") == "spent")
    started = next((e["at"] for e in ev), None)
    minutes = 0.0
    if started:
        try:
            t0 = time.mktime(time.strptime(started, "%Y-%m-%dT%H:%M:%S"))
            minutes = max(0.0, (time.time() - t0) / 60.0)
        except ValueError:                    # pragma: no cover
            minutes = 0.0
    cycles = sum(1 for e in ev if e.get("kind") == "cycle_started")
    exceeded = []
    if b.get("max_usd") and spent_usd > b["max_usd"]:
        exceeded.append(f"spend ${spent_usd:.2f} > ${b['max_usd']:.2f}")
    if b.get("max_minutes") and minutes > b["max_minutes"]:
        exceeded.append(f"wall-clock {minutes:.0f}m > {b['max_minutes']}m")
    if b.get("max_cycles") and cycles > b["max_cycles"]:
        exceeded.append(f"cycles {cycles} > {b['max_cycles']}")
    return {"spent_usd": round(spent_usd, 4), "minutes": round(minutes, 1),
            "cycles": cycles, "exceeded": exceeded}


# ------------------------------------------------------------- oscillation

def oscillating(root, gid):
    """A pursuit that fails the same way twice in a row is not converging,
    and spending its remaining cycles on the identical wall is not
    persistence — it is a loop wearing persistence's clothes. Returns a
    diagnosis string, or None.

    The signature is (milestone n, its check): the same MILESTONE failing
    for a DIFFERENT reason is progress of a kind and is allowed to
    continue; the same check failing in consecutive cycles is not."""
    fails = {}
    for e in events(root, gid):
        if e.get("kind") != "milestone_failed":
            continue
        key = (e.get("n"), (e.get("check") or "")[:120])
        fails.setdefault(key, []).append(int(e.get("cycle") or 0))
    for (n, check), cycles in fails.items():
        cs = sorted(set(cycles))
        for a, b in zip(cs, cs[1:]):
            if b == a + 1:
                return (f"milestone M{n} failed the same check in cycles "
                        f"{a} and {b} — the plan is not converging on this "
                        f"wall, and cycle {b + 1} would hit it a third time. "
                        f"Check: {check or '(evidence-note check)'}")
    return None


# ------------------------------------------------------------------ replay

def replay(root, gid):
    """Reconstruct the contract's state PURELY from the event ledger, then
    compare with the snapshot. Divergence means one of the two is lying,
    and since the ledger is append-only and the snapshot is rewritten, the
    ledger wins. This is the property that makes a crash survivable: the
    truth is what happened, not what a file remembers."""
    state, frozen, n_accept = "draft", False, 0
    cycles, verdicts = 0, []
    for e in events(root, gid):
        k = e.get("kind")
        if k == "contract_created":
            n_accept = int(e.get("acceptance") or 0)
        elif k == "acceptance_frozen":
            frozen, state = True, "ready"
        elif k == "cycle_started":
            cycles += 1
            state = "running"
        elif k == "verdict":
            verdicts.append(e.get("verdict"))
        elif k == "state":
            state = e.get("to") or state
    derived = {"state": state, "frozen": frozen, "cycles": cycles,
               "acceptance": n_accept, "verdicts": verdicts}
    try:
        snap = load(root, gid)
        derived["diverges"] = (snap.get("state") != state)
        derived["snapshot_state"] = snap.get("state")
    except (OSError, ValueError):
        derived["diverges"] = True
        derived["snapshot_state"] = None
    return derived


# --------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create")
    p.add_argument("root"); p.add_argument("gid"); p.add_argument("goal")
    p.add_argument("--criteria", default="")
    p.add_argument("--accept", action="append", default=[],
                   help="'what it proves::command exiting 0 when met'")
    p.add_argument("--non-goals", default="")
    p.add_argument("--max-usd", type=float, default=0.0)
    p.add_argument("--max-minutes", type=int, default=0)
    p.add_argument("--max-cycles", type=int, default=4)
    p.add_argument("--freeze", action="store_true",
                   help="freeze immediately after creating")
    for name in ("verify", "show", "events", "replay", "freeze"):
        p = sub.add_parser(name)
        p.add_argument("root"); p.add_argument("gid")
    a = ap.parse_args()

    if a.cmd == "create":
        c = create(a.root, a.gid, a.goal, a.criteria,
                   accept=parse_accept(a.accept), non_goals=a.non_goals,
                   max_usd=a.max_usd, max_minutes=a.max_minutes,
                   max_cycles=a.max_cycles)
        if a.freeze:
            c = freeze(a.root, a.gid)
        print(json.dumps(c, indent=1))
    elif a.cmd == "freeze":
        print(json.dumps(freeze(a.root, a.gid), indent=1))
    elif a.cmd == "verify":
        r = verify(a.root, a.gid)
        print(json.dumps(r, indent=1))
        raise SystemExit(0 if (r["all"] and not r["tamper"]) else 1)
    elif a.cmd == "show":
        print(json.dumps(load(a.root, a.gid), indent=1))
    elif a.cmd == "events":
        for e in events(a.root, a.gid):
            print(json.dumps(e, ensure_ascii=False))
    elif a.cmd == "replay":
        r = replay(a.root, a.gid)
        print(json.dumps(r, indent=1))
        raise SystemExit(1 if r.get("diverges") else 0)


if __name__ == "__main__":
    main()
