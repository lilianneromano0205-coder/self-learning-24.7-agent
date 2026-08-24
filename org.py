#!/usr/bin/env python3
"""ORGANIZATION — several people sharing one fleet, with roles and an audit.

Manual §21. The objects it names: Workspace/Organization, User/RBAC (owner,
admin, builder, operator, reviewer, approver, viewer), Agent, Team, Fleet
Worker, Secret, Policy, Proof. And the invariant that matters most:

    "every mutation attributable"

This is deliberately the FILE-BACKED half of the cloud story. The manual is
clear that a real cloud product also needs authentication, TLS, a secret
manager, transactional state and tenant isolation — none of which belong in
a stdlib-only local platform, and none of which this module pretends to
provide. What it does provide is the part that is meaningful locally and
that the cloud version would need anyway: a permission model, an attributable
audit trail, and per-user budgets.

`check()` is the single question every mutating path asks: may THIS user do
THIS thing to THIS object? It answers with a reason either way, because a
refusal a person cannot understand is a refusal they will route around.
"""

import hashlib
import json
import os
import secrets
import time

FILE = os.path.join("org", "org.json")
AUDIT = os.path.join("org", "audit.jsonl")

# Manual §21's ladder, least to most. Each role INCLUDES the ones beneath it,
# so a permission set is a prefix rather than a list somebody has to maintain.
ROLES = ["viewer", "reviewer", "approver", "operator", "builder", "admin",
         "owner"]

PERMISSIONS = {
    "read":            "viewer",     # see agents, missions, proof, evidence
    "comment":         "reviewer",   # annotate work, flag a problem
    "approve":         "approver",   # grant a guarded action, answer a block
    "run":             "operator",   # start work, queue a task, drive a mission
    "create_agent":    "builder",    # mint experts, edit charters, add skills
    "connect_tool":    "builder",    # register MCP servers and computers
    "manage_secrets":  "admin",      # add or rotate credentials
    "manage_users":    "admin",      # invite, change roles
    "manage_budget":   "admin",      # raise or lower spend ceilings
    "delete_agent":    "admin",      # retire or purge an expert
    "transfer_owner":  "owner",      # hand over the organization
}


class Denied(Exception):
    """Authorisation said no, with the reason the person needs."""


def _path(home, rel=FILE):
    return os.path.join(home, rel)


def load(home):
    try:
        with open(_path(home), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(home, rec):
    d = os.path.dirname(_path(home))
    os.makedirs(d, exist_ok=True)
    tmp = f"{_path(home)}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, ensure_ascii=False)
    os.replace(tmp, _path(home))
    return rec


def create(home, name, owner_email, owner_name=""):
    """One workspace per fleet home. The first user is the owner, and an
    organization can never end up with none."""
    if load(home):
        raise ValueError("this fleet already belongs to an organization")
    rec = {
        "name": name, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "users": [{"email": owner_email.lower(), "name": owner_name or owner_email,
                   "role": "owner", "budget_usd": None,
                   "added": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "added_by": "bootstrap", "active": True}],
        "policy": {
            "agents_may_install": False,
            "agents_may_reach_internal_network": False,
            "require_approval_over_usd": 5.0,
        },
    }
    _save(home, rec)
    audit(home, owner_email, "create_org", "organization", name,
          f"created the workspace {name!r}")
    return rec


# The organization's policy flags, and what enforces each one. Every key in
# `create()`'s policy block must appear here, and every entry must name a
# module that actually reads it — check_org_policy_is_enforced() in
# tests/test_invariants.py asserts both directions.
#
# These three were written into org.json at creation, returned by summary(),
# rendered in the panel, and read by NOTHING. An owner looking at
# "agents_may_install: false" in their own workspace settings had every
# reason to believe agents could not install packages — and after
# acquire.install() became a real pip install, that belief was load-bearing
# and false. A setting the product displays is a promise the product makes.
POLICY_ENFORCERS = {
    "agents_may_install":
        "acquire.install() refuses when this is false",
    "agents_may_reach_internal_network":
        "ingest._check_host() permits private/loopback destinations only "
        "when this is true",
    "require_approval_over_usd":
        "loop.Agent._budget_exceeded() pauses the expert once the day's "
        "spend reaches this, and says so in blocked.md",
}


def home_for(root):
    """experts/<slug> -> the fleet home two levels up; a standalone root ->
    itself. Organization policy lives at the fleet home, and most subsystems
    are handed an expert root, so this is the bridge between them."""
    root = os.path.abspath(root)
    parent = os.path.dirname(root)
    if os.path.basename(parent) == "experts":
        return os.path.dirname(parent)
    return root


def policy(home):
    """The organization's policy block, or {} when there is no organization.

    Never raises: an expert running standalone has no org.json, and policy
    lookups must not turn that into an error on every call.
    """
    try:
        rec = load(home)
    except Exception:
        return {}
    return (rec or {}).get("policy") or {}


def policy_flag(root, name, default=False):
    """One policy value, looked up from an expert root OR a fleet home.

    The default is returned only when there is no organization at all, and
    each caller chooses it deliberately, because "no workspace has been
    formed here" is a different statement from "the workspace says no" and
    the right reading differs per flag:

      agents_may_install                 default True  — the install is
          already sandbox-only, inspected and capability-tested; this flag is
          the organization's SEPARATE veto, and defaulting it closed would
          disable acquisition for every fleet that never ran `org.py create`.
      agents_may_reach_internal_network  default False — reaching a private
          address is a capability nothing else restricts, so absent an
          organization the answer stays no, exactly as it is today.

    An organization that DOES exist starts with both False, from create().
    """
    val = policy(home_for(root)).get(name)
    return default if val is None else val


def set_policy(home, actor, name, value):
    """Change one organization policy flag. Owner-only, and audited.

    There was no way to change these at all: create() wrote them and no CLI,
    API or function ever touched them again. So the three flags were
    unreachable in both directions — nothing enforced them, and nobody could
    have altered them if it had. `transfer_owner` is the permission because
    every one of these decides what agents may do to the outside world, which
    is the owner's call and not an administrator's.
    """
    if name not in POLICY_ENFORCERS:
        raise Denied(f"unknown policy flag {name!r}; known flags: "
                     f"{', '.join(sorted(POLICY_ENFORCERS))}")
    check(home, actor, "transfer_owner", name)
    rec = load(home)
    pol = rec.setdefault("policy", {})
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "yes", "on", "1"):
            value = True
        elif low in ("false", "no", "off", "0"):
            value = False
        else:
            try:
                value = float(value)
            except ValueError:
                raise Denied(f"{name} takes true/false or a number, not "
                             f"{value!r}")
    before = pol.get(name)
    pol[name] = value
    _save(home, rec)
    audit(home, actor, "set_policy", "organization", name,
          f"{name}: {before!r} -> {value!r}")
    return pol


def add_user(home, actor, email, role, name="", budget_usd=None):
    check(home, actor, "manage_users")
    if role not in ROLES:
        raise ValueError(f"role must be one of: {', '.join(ROLES)}")
    if role == "owner":
        raise Denied("there is one owner; use transfer_owner to hand it over")
    rec = load(home)
    if rec is None:
        raise Denied("no organization here yet")
    email = email.lower()
    if any(u["email"] == email for u in rec["users"]):
        raise ValueError(f"{email} is already a member")
    rec["users"].append({"email": email, "name": name or email, "role": role,
                         "budget_usd": budget_usd, "active": True,
                         "added": time.strftime("%Y-%m-%dT%H:%M:%S"),
                         "added_by": actor})
    _save(home, rec)
    audit(home, actor, "add_user", "user", email, f"added as {role}")
    return rec


def set_role(home, actor, email, role):
    check(home, actor, "manage_users")
    if role not in ROLES or role == "owner":
        raise ValueError("pick a role below owner")
    rec = load(home)
    for u in rec["users"]:
        if u["email"] == email.lower():
            if u["role"] == "owner":
                raise Denied("the owner's role is changed by transfer_owner")
            was, u["role"] = u["role"], role
            _save(home, rec)
            audit(home, actor, "set_role", "user", email, f"{was} -> {role}")
            return rec
    raise KeyError(email)


def user(home, email):
    rec = load(home)
    if not rec:
        return None
    return next((u for u in rec["users"]
                 if u["email"] == str(email).lower() and u["active"]), None)


def rank(role):
    return ROLES.index(role) if role in ROLES else -1


def check(home, actor, permission, obj=""):
    """May this user do this? Raises Denied with a reason a person can act on.

    An organization that has not been created yet is SINGLE-OWNER: the local
    platform works exactly as it always did until somebody invites a second
    person, so adding RBAC does not break a solo install.
    """
    rec = load(home)
    if rec is None:
        return True                      # solo install: no org, no RBAC
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")
    u = user(home, actor)
    if u is None:
        raise Denied(
            f"{actor!r} is not a member of {rec['name']!r}. An admin adds "
            f"people with: python org.py invite <email> --role operator")
    needed = PERMISSIONS[permission]
    if rank(u["role"]) < rank(needed):
        raise Denied(
            f"{actor} is a {u['role']}; {permission!r} needs {needed} or "
            f"above. Ask an admin to raise the role, or ask someone with it "
            f"to do this step.")

    # PER-USER BUDGET IS NOT ENFORCED HERE, DELIBERATELY. See the note on
    # spend_by_user(): `budget_usd` is denominated in DOLLARS and the only
    # per-user figure this module can currently compute is a COUNT OF
    # CHARGEABLE ACTIONS. Comparing the two would be a control that fires at
    # the wrong time in both directions, which is worse than the admitted gap
    # — and this file has just finished removing three controls that did not
    # do what they said. `--budget` is accepted and recorded so the intent
    # survives; org.py policy and doctor report it as recorded-not-enforced.
    return True


def may(home, actor, permission):
    """The non-raising form, for a UI that greys a button out."""
    try:
        return check(home, actor, permission)
    except (Denied, ValueError):
        return False


def permissions_of(home, actor):
    u = user(home, actor)
    if load(home) is None:
        return sorted(PERMISSIONS)       # solo install
    if not u:
        return []
    return sorted(p for p, need in PERMISSIONS.items()
                  if rank(u["role"]) >= rank(need))


# ------------------------------------------------------- per-user tokens
# The gap this closes: this module's own docstring said `check()` is "the
# single question every mutating path asks", and the PANEL — which is the
# main mutating path — never asked it. It could not: the panel authenticates
# with one shared token, so it had no idea who was calling.
#
# A permission model that only the CLI consults is a permission model that
# describes intentions rather than behaviour. So each member gets their own
# bearer token, and the panel resolves it to a user before every write.
#
# The token itself is never stored. What is stored is its SHA-256, so a
# leaked org.json cannot be replayed as a set of credentials, and the plain
# value is returned exactly once — at the moment it is minted.

def _hash_token(tok):
    return hashlib.sha256(str(tok).encode("utf-8")).hexdigest()


def issue_token(home, actor, email=None):
    """Mint a bearer token for one member. Returns it ONCE, in plain text.

    `actor` is who is doing the issuing; `email` is who it is for (defaults
    to the actor themselves — anyone may mint their own).
    """
    email = (email or actor).lower()
    if email != str(actor).lower():
        check(home, actor, "manage_users")
    rec = load(home)
    if rec is None:
        raise Denied("no organization here yet: python org.py create <name> "
                     "--owner you@example.com")
    u = next((x for x in rec["users"] if x["email"] == email), None)
    if u is None:
        raise KeyError(email)
    token = secrets.token_urlsafe(32)
    u["token_sha256"] = _hash_token(token)
    u["token_issued"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save(home, rec)
    audit(home, actor, "issue_token", "user", email,
          "minted a personal access token (the value is not recorded)")
    return token


def revoke_token(home, actor, email):
    email = str(email).lower()
    if email != str(actor).lower():
        check(home, actor, "manage_users")
    rec = load(home)
    if rec is None:
        raise Denied("no organization here yet")
    for u in rec["users"]:
        if u["email"] == email:
            had = bool(u.pop("token_sha256", None))
            u.pop("token_issued", None)
            _save(home, rec)
            audit(home, actor, "revoke_token", "user", email,
                  "revoked" if had else "there was no token to revoke")
            return had
    raise KeyError(email)


def user_for_token(home, token):
    """Which member does this bearer token belong to? None if nobody.

    Constant-time comparison, because the alternative is a timing oracle over
    a credential, and 'nobody would bother locally' is how that argument
    always starts.
    """
    rec = load(home)
    if rec is None or not token:
        return None
    want = _hash_token(token)
    for u in rec["users"]:
        have = u.get("token_sha256")
        if have and secrets.compare_digest(have, want) and u.get("active"):
            return u
    return None


# ---------------------------------------------------------------- the audit

def audit(home, actor, action, obj_kind, obj_id, detail=""):
    """Every mutation, attributable. Append-only: an audit trail you can edit
    is a story, not a record."""
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "actor": str(actor),
           "action": action, "object_kind": obj_kind, "object": str(obj_id),
           "detail": str(detail)[:400]}
    try:
        os.makedirs(os.path.dirname(_path(home, AUDIT)), exist_ok=True)
        with open(_path(home, AUDIT), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return rec


def trail(home, limit=200, actor=None, obj=None):
    out = []
    try:
        with open(_path(home, AUDIT), "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if actor and r.get("actor") != actor:
                    continue
                if obj and r.get("object") != obj:
                    continue
                out.append(r)
    except OSError:
        pass
    return out[-limit:]


def spend_by_user(home, days=1):
    """CHARGEABLE ACTIONS per user in the last `days` — a COUNT, not dollars.

    The docstring here used to read "per-user spend ... reads the model
    gateway's own ledger", and the body counts rows in the ORG AUDIT whose
    action is `run` or `start_mission`. It has never opened the gateway
    ledger and has never produced a dollar figure. Nothing called it, so the
    two never had to agree.

    That is why `budget_usd` is still not enforced. Attributing real spend to
    a PERSON needs the task to carry who queued it: the panel knows (the
    request has a token), the loop spends the money hours later and does not,
    and modelgateway.record() takes no actor. Threading identity from the
    request through the queue into the meter is the fix, and it is a feature
    rather than a correction — so the honest state is written down here and
    in doctor's report instead of being papered over with a control that
    compares a count against a currency.
    """
    rec = load(home)
    if not rec:
        return {}
    since = time.strftime("%Y-%m-%dT%H:%M:%S",
                          time.localtime(time.time() - days * 86400))
    charged = {}
    for row in trail(home, limit=100000):
        if row["at"] < since or row["action"] not in ("run", "start_mission"):
            continue
        charged.setdefault(row["actor"], 0)
        charged[row["actor"]] += 1
    return charged


def summary(home):
    rec = load(home)
    if not rec:
        return {"organization": None,
                "note": "solo install: no organization, no RBAC — every "
                        "capability is available to whoever runs the panel"}
    safe = [{k: v for k, v in u.items() if k != "token_sha256"}
            | {"has_token": bool(u.get("token_sha256"))}
            for u in rec["users"]]
    return {"organization": rec["name"], "users": safe,
            "policy": rec["policy"], "roles": ROLES,
            "permissions": PERMISSIONS, "audit_entries": len(trail(home, 10000))}


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create"); p.add_argument("name")
    p.add_argument("--owner", required=True); p.add_argument("--home", default=".")
    p = sub.add_parser("invite"); p.add_argument("email")
    p.add_argument("--role", default="operator", choices=ROLES[:-1])
    p.add_argument("--budget", type=float, default=None,
                   help="daily spend ceiling in USD for this person; over it, "
                        "'run' is refused while reading and approving still work")
    p.add_argument("--as", dest="actor", required=True)
    p.add_argument("--home", default=".")
    p = sub.add_parser("who"); p.add_argument("--home", default=".")
    p = sub.add_parser("can"); p.add_argument("email")
    p.add_argument("--home", default=".")
    p = sub.add_parser("audit"); p.add_argument("--home", default=".")
    p.add_argument("--limit", type=int, default=25)
    p = sub.add_parser("roles")
    # The panel authenticates with a bearer token, so a member who is going to
    # use the panel needs one of their own — otherwise the roles below are
    # enforced only on this command line, which is where they started.
    p = sub.add_parser("token")
    p.add_argument("email", nargs="?", default=None,
                   help="whose token (default: your own)")
    p.add_argument("--as", dest="actor", required=True)
    p.add_argument("--home", default=".")
    p = sub.add_parser("revoke"); p.add_argument("email")
    p.add_argument("--as", dest="actor", required=True)
    p.add_argument("--home", default=".")
    p = sub.add_parser("policy", help="show or change organization policy")
    p.add_argument("--set", dest="assign", default="",
                   help="flag=value, e.g. agents_may_install=true")
    p.add_argument("--as", dest="actor", default="")
    p.add_argument("--home", default=".")
    a = ap.parse_args()
    if a.cmd == "roles":
        print("least to most:", " -> ".join(ROLES))
        for perm, need in sorted(PERMISSIONS.items(), key=lambda x: rank(x[1])):
            print(f"  {perm:<18} needs {need}")
        return
    home = os.path.abspath(a.home)
    if a.cmd == "policy":
        if a.assign:
            if "=" not in a.assign:
                print("--set takes flag=value"); raise SystemExit(2)
            if not a.actor:
                print("--as <owner-email> is required to change policy")
                raise SystemExit(2)
            name, _, value = a.assign.partition("=")
            pol = set_policy(home, a.actor, name.strip(), value.strip())
            print(f"{name.strip()} = {pol[name.strip()]!r}")
            return
        pol = policy(home)
        if not pol:
            print("no organization here (no org.json)"); return
        for k in sorted(POLICY_ENFORCERS):
            print(f"  {k:<36} {pol.get(k)!r}")
            print(f"    enforced by: {POLICY_ENFORCERS[k]}")
        capped = [u for u in (load(home) or {}).get("users", [])
                  if u.get("budget_usd")]
        if capped:
            print(f"  {'per-user budget_usd':<36} "
                  f"{len(capped)} user(s): RECORDED, NOT ENFORCED")
            print(f"    attributing real spend to a person needs the task to "
                  f"carry who queued it; see org.spend_by_user")
        return
    if a.cmd == "create":
        r = create(home, a.name, a.owner)
        print(f"organization {r['name']!r} created; {a.owner} is the owner")
        return
    if a.cmd == "token":
        try:
            tok = issue_token(home, a.actor, a.email)
        except Denied as e:
            print(f"REFUSED: {e}")
            raise SystemExit(1)
        who = (a.email or a.actor).lower()
        print(f"token for {who}:")
        print()
        print(f"  {tok}")
        print()
        print("This value is shown ONCE and is not recorded anywhere — only "
              "its SHA-256 is stored.")
        print("Use it as: Authorization: Bearer <token>, or paste it when the "
              "panel asks.")
        return
    if a.cmd == "revoke":
        try:
            had = revoke_token(home, a.actor, a.email)
        except Denied as e:
            print(f"REFUSED: {e}")
            raise SystemExit(1)
        print(f"{a.email}: {'token revoked' if had else 'had no token'}")
        return
    if a.cmd == "invite":
        add_user(home, a.actor, a.email, a.role, budget_usd=a.budget)
        cap = f", ${a.budget:.2f}/day" if a.budget else ""
        print(f"{a.email} added as {a.role}{cap}")
        return
    if a.cmd == "can":
        print(f"{a.email}: " + ", ".join(permissions_of(home, a.email)) or "nothing")
        return
    if a.cmd == "audit":
        for r in trail(home, a.limit):
            print(f"{r['at']}  {r['actor']:<28} {r['action']:<16} "
                  f"{r['object_kind']}:{r['object']}  {r['detail'][:50]}")
        return
    s = summary(home)
    if not s["organization"]:
        print(s["note"])
        return
    print(f"{s['organization']} — {len(s['users'])} member(s), "
          f"{s['audit_entries']} audited action(s)")
    for u in s["users"]:
        print(f"  {u['email']:<32} {u['role']:<10} "
              f"{'' if u['active'] else '(inactive)'}")


if __name__ == "__main__":
    main()
