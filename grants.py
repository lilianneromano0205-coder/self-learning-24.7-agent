#!/usr/bin/env python3
"""STANDING GRANTS — the owner says yes ONCE, inside a boundary that holds.

The platform's hardest rule is that an agent never resolves an AUTHORITY gap
by itself: a credential, an account, a payment, a publication, an outgoing
message. `universal.authority_gaps` routes those to the owner and stops.
That rule is right, and it has one very real cost:

    it stops EVERY time.

A fleet that is supposed to run all night parks on a human at the first
invoice, and an owner who is asked the same question forty times stops
reading the questions. "Ask every time" and "never ask" fail the same way in
the end — the boundary becomes noise, and noise gets switched off.

So this module adds the missing middle, which is how authority actually works
between people: a SCOPE, granted deliberately, bounded, expiring, revocable,
and logged. The owner says once

    you may use the supplier-portal credential, for 30 days
    you may spend up to $200 with this vendor
    you may send mail from fleet@example.com to @acme.com addresses

and the agent proceeds unattended INSIDE that, and stops at its edge exactly
as before. Nothing here weakens the boundary; it moves the decision from
"every action" to "the shape of the work", which is the only place a human
can actually make it well.

FOUR PROPERTIES, AND WHY EACH ONE IS NOT OPTIONAL

  SCOPED    a grant names a kind AND a target. "may spend money" is not a
            grant, it is a surrender. "may spend up to $200 at vendor X" is
            a decision someone can actually make.
  EXPIRING  every grant has a last day. A permission that outlives the reason
            it was given is how a temporary exception becomes permanent
            access nobody remembers approving.
  REVOCABLE one command, effective immediately, no negotiation.
  RECORDED  every USE is appended to a ledger. A standing grant without a
            usage log is a blank cheque: the owner authorised a shape of
            work and has no way to see what was actually done in their name.

WHAT THIS DELIBERATELY DOES NOT DO

It does not create accounts, hold passwords, or act on the owner's behalf by
itself. A grant is a RECORD OF PERMISSION, checked before an action; the
credential itself still lives where credentials.py puts it, and the action
still runs through the same effect ledger and approval path as before. An
agent that could write its own grant would be back to having no boundary, so
`grant()` requires owner authority and refuses anyone else — including an
admin, because these decide what the fleet may do to the outside world.

    python grants.py list   --home .
    python grants.py grant  --kind credential --scope supplier-portal \
                            --as owner@example.com --days 30 --why "Q3 invoices"
    python grants.py check  --kind credential --scope supplier-portal
    python grants.py revoke <id> --as owner@example.com
    python grants.py uses   --home .
"""

import argparse
import json
import os
import re
import sys
import time

try:                                    # a Windows console defaults to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):       # pragma: no cover
    pass

FILE = os.path.join("org", "grants.json")
USES = os.path.join("org", "grant-uses.jsonl")
DEFAULT_DAYS = 30
MAX_DAYS = 365

# The kinds map ONE-TO-ONE onto the authority gaps universal.py already
# routes to the owner. That is deliberate: a grant can only ever answer a
# question the platform already knows how to ask, so a new kind of authority
# cannot be granted before it can be detected.
KINDS = {
    "account": "creating an account",
    "money": "spending money",
    "credential": "a credential only you can issue",
    "publish": "publishing something to the world",
    "message": "sending something on your behalf",
    "destroy": "destroying something that cannot be restored",
}


class Denied(Exception):
    """The grant does not cover this, with the reason a person can act on."""


def _path(home, rel=FILE):
    return os.path.join(home, rel)


def load(home):
    try:
        with open(_path(home), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(home, rows):
    p = _path(home)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)
    return rows


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _today():
    return time.strftime("%Y-%m-%d")


def _norm(s):
    """Scopes compare case-insensitively and ignore surrounding punctuation,
    so `Supplier-Portal` and `supplier-portal` are one scope rather than two
    that silently fail to match."""
    return re.sub(r"[^a-z0-9@.*_-]+", "-", str(s or "").strip().lower()).strip("-")


def _scope_matches(granted, asked):
    """Does a granted scope cover the one being asked about?

    Exact match, or a single trailing `*` wildcard. Deliberately not a regex
    and not a substring test: substring matching is how "a thing" came to
    match "everything" elsewhere in this codebase, and a scope is the half of
    a grant that makes it a decision rather than a surrender.
    """
    g, a = _norm(granted), _norm(asked)
    if not g or g == "*":
        return True                     # an owner may grant unscoped, loudly
    if g.endswith("*"):
        return a.startswith(g[:-1])
    return g == a


def _owner_check(home, actor):
    """Only the OWNER grants authority. Not an admin.

    org.py's ladder puts `transfer_owner` at the top precisely because it
    decides what the organisation itself may become; these grants decide what
    the fleet may do to the outside world in the owner's name, which is the
    same class of decision. Where no organisation exists the fleet is
    single-owner by definition and whoever runs the CLI is that owner — the
    same rule org.check already applies.
    """
    try:
        import org
    except Exception:                    # pragma: no cover
        return True
    if org.load(home) is None:
        return True                      # solo install: no org, no RBAC
    if not actor:
        raise Denied("--as <owner-email> is required to change what this "
                     "fleet may do on your behalf")
    org.check(home, actor, "transfer_owner", "grant")
    return True


def grant(home, actor, kind, scope, days=DEFAULT_DAYS, cap_usd=None, why=""):
    """Record a standing permission. Owner-only, bounded, expiring."""
    k = str(kind or "").strip().lower()
    if k not in KINDS:
        raise Denied(f"unknown authority kind {kind!r}; grantable: "
                     f"{', '.join(sorted(KINDS))}")
    if not str(scope or "").strip():
        raise Denied(
            "a grant needs a SCOPE. 'may spend money' is not a permission "
            "anybody can reason about; 'may spend up to $200 at acme.com' is. "
            "Pass --scope '*' if you genuinely mean everywhere, and it will "
            "be recorded that way.")
    try:
        days = int(days)
    except (TypeError, ValueError):
        raise Denied("--days must be a whole number of days")
    if days < 1 or days > MAX_DAYS:
        raise Denied(f"--days must be between 1 and {MAX_DAYS}. A permission "
                     f"that outlives the reason it was given is how a "
                     f"temporary exception becomes standing access.")
    _owner_check(home, actor)
    rows = load(home)
    gid = f"g-{int(time.time()):x}-{len(rows) + 1:02d}"
    rec = {
        "id": gid, "kind": k, "what": KINDS[k], "scope": str(scope).strip(),
        "cap_usd": (float(cap_usd) if cap_usd not in (None, "") else None),
        "spent_usd": 0.0, "uses": 0,
        "granted_by": actor or "owner", "granted": _now(),
        "expires": time.strftime("%Y-%m-%d",
                                 time.localtime(time.time() + days * 86400)),
        "why": str(why)[:300], "revoked": None,
    }
    rows.append(rec)
    _save(home, rows)
    _audit(home, actor, "grant_authority", gid,
           f"{k} scope={rec['scope']} until {rec['expires']}")
    return rec


def revoke(home, actor, gid):
    """End a grant now. Effective immediately, no negotiation."""
    _owner_check(home, actor)
    rows = load(home)
    for r in rows:
        if r["id"] == gid:
            if r.get("revoked"):
                return r
            r["revoked"] = _now()
            _save(home, rows)
            _audit(home, actor, "revoke_authority", gid, r["scope"])
            return r
    raise Denied(f"no grant {gid!r}")


def live(home):
    """Grants that are in force RIGHT NOW — not revoked, not expired."""
    today = _today()
    return [r for r in load(home)
            if not r.get("revoked") and str(r.get("expires", "")) >= today]


def check(home, kind, scope, amount_usd=0.0):
    """-> (allowed, reason). Never raises; the caller decides what to do.

    The reason is returned either way and is written for a human, because a
    refusal nobody understands is a refusal they route around.
    """
    k = str(kind or "").strip().lower()
    if k not in KINDS:
        return False, (f"{kind!r} is not a grantable kind of authority")
    for r in live(home):
        if r["kind"] != k or not _scope_matches(r["scope"], scope):
            continue
        cap = r.get("cap_usd")
        if cap is not None and amount_usd:
            room = float(cap) - float(r.get("spent_usd") or 0)
            if float(amount_usd) > room:
                return False, (
                    f"grant {r['id']} covers {k} for {r['scope']!r} but only "
                    f"${room:.2f} of its ${float(cap):.2f} cap is left; this "
                    f"needs ${float(amount_usd):.2f}")
        return True, (f"grant {r['id']}: {r['what']} for {r['scope']!r}, "
                      f"granted {r['granted'][:10]} by {r['granted_by']}, "
                      f"expires {r['expires']}")
    return False, (
        f"no standing grant covers {KINDS[k]} for {scope!r}. The owner can "
        f"give one with: python grants.py grant --kind {k} "
        f"--scope {scope!r} --as <owner-email> --days 30 --why '…'")


def record_use(home, kind, scope, detail="", amount_usd=0.0, task=""):
    """Append what was actually DONE under a grant.

    A standing grant without a usage log is a blank cheque: the owner
    authorised a shape of work and would have no way to see what happened in
    their name. This is the half that makes the grant reviewable.
    """
    ok, why = check(home, kind, scope, amount_usd)
    if not ok:
        raise Denied(why)
    rows = load(home)
    hit = None
    for r in rows:
        if (r["kind"] == str(kind).lower()
                and _scope_matches(r["scope"], scope)
                and not r.get("revoked") and str(r.get("expires", "")) >= _today()):
            hit = r
            break
    if hit is not None:
        hit["uses"] = int(hit.get("uses") or 0) + 1
        if amount_usd:
            hit["spent_usd"] = round(float(hit.get("spent_usd") or 0)
                                     + float(amount_usd), 4)
        _save(home, rows)
    p = _path(home, USES)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "at": _now(), "grant": (hit or {}).get("id"), "kind": kind,
            "scope": scope, "detail": str(detail)[:400],
            "amount_usd": float(amount_usd or 0), "task": task,
        }, ensure_ascii=False) + "\n")
    return hit


def uses(home, limit=200):
    out = []
    try:
        with open(_path(home, USES), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return out[-limit:]


def _audit(home, actor, action, obj_id, detail):
    try:
        import org
        if org.load(home) is not None:
            org.audit(home, actor or "owner", action, "authority", obj_id, detail)
    except Exception:                    # pragma: no cover — never the outage
        pass


def summary(home):
    rows = live(home)
    return {
        "live": len(rows),
        "grants": [{"id": r["id"], "kind": r["kind"], "scope": r["scope"],
                    "expires": r["expires"], "uses": r.get("uses", 0),
                    "cap_usd": r.get("cap_usd"),
                    "spent_usd": r.get("spent_usd", 0.0)} for r in rows],
        "kinds": KINDS,
    }


def main():
    ap = argparse.ArgumentParser(
        description="standing authority grants — the owner says yes once, "
                    "inside a boundary that holds")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--home", default=".")
    p.add_argument("--all", action="store_true",
                   help="include expired and revoked grants")
    p = sub.add_parser("kinds")
    p = sub.add_parser("grant")
    p.add_argument("--kind", required=True, choices=sorted(KINDS))
    p.add_argument("--scope", required=True)
    p.add_argument("--as", dest="actor", default="")
    p.add_argument("--days", type=int, default=DEFAULT_DAYS)
    p.add_argument("--cap-usd", dest="cap", default=None)
    p.add_argument("--why", default="")
    p.add_argument("--home", default=".")
    p = sub.add_parser("check")
    p.add_argument("--kind", required=True); p.add_argument("--scope", required=True)
    p.add_argument("--amount-usd", dest="amount", type=float, default=0.0)
    p.add_argument("--home", default=".")
    p = sub.add_parser("revoke"); p.add_argument("id")
    p.add_argument("--as", dest="actor", default=""); p.add_argument("--home", default=".")
    p = sub.add_parser("uses"); p.add_argument("--home", default=".")
    p.add_argument("--limit", type=int, default=40)
    a = ap.parse_args()

    if a.cmd == "kinds":
        print("grantable authority, one per gap universal.py already detects:")
        for k, what in sorted(KINDS.items()):
            print(f"  {k:<12} {what}")
        return
    home = os.path.abspath(a.home)
    if a.cmd == "list":
        rows = load(home) if a.all else live(home)
        if not rows:
            print("no standing grants — every authority gap goes to you, "
                  "every time")
            return
        for r in rows:
            state = ("REVOKED" if r.get("revoked")
                     else ("EXPIRED" if str(r["expires"]) < _today() else "live"))
            cap = (f" cap ${r['cap_usd']:.2f} spent ${r.get('spent_usd', 0):.2f}"
                   if r.get("cap_usd") is not None else "")
            print(f"{r['id']:<16} {state:<8} {r['kind']:<11} "
                  f"{r['scope']:<24} until {r['expires']} "
                  f"uses={r.get('uses', 0)}{cap}")
            if r.get("why"):
                print(f"                 why: {r['why']}")
        return
    if a.cmd == "grant":
        try:
            r = grant(home, a.actor, a.kind, a.scope, a.days, a.cap, a.why)
        except Denied as e:
            print(e); raise SystemExit(2)
        print(f"{r['id']}: {r['what']} for {r['scope']!r} until {r['expires']}")
        print("  the fleet may now do this unattended within that scope; "
              "revoke any time with `python grants.py revoke " + r["id"] + "`")
        return
    if a.cmd == "check":
        ok, why = check(home, a.kind, a.scope, a.amount)
        print(("ALLOWED  " if ok else "REFUSED  ") + why)
        raise SystemExit(0 if ok else 1)
    if a.cmd == "revoke":
        try:
            r = revoke(home, a.actor, a.id)
        except Denied as e:
            print(e); raise SystemExit(2)
        print(f"{r['id']} revoked; {r['kind']} for {r['scope']!r} now goes "
              f"back to asking you every time")
        return
    if a.cmd == "uses":
        rows = uses(home, a.limit)
        if not rows:
            print("nothing has been done under a standing grant yet")
            return
        for u in rows:
            amt = f" ${u['amount_usd']:.2f}" if u.get("amount_usd") else ""
            print(f"{u['at']}  {u['kind']:<11} {u['scope']:<22}{amt}  "
                  f"{u.get('detail', '')[:60]}")
        return


if __name__ == "__main__":
    main()
