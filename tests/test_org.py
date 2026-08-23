#!/usr/bin/env python3
"""SEVERAL PEOPLE, ONE FLEET, AND A RECORD OF WHO DID WHAT.

Manual §21: *"User/RBAC — owner, admin, builder, operator, reviewer,
approver, viewer; every mutation attributable."*

Two properties decide whether this is real:

  * a role cannot exceed its grant, and the refusal says what to do about it
  * a SOLO install is unaffected. Adding RBAC to a local platform must not
    make the person who owns the machine ask themselves for permission.

Run from the agent/ directory:  python tests/test_org.py
"""

import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import org                  # noqa: E402

OWNER = "owner@example.com"


def check_solo_install_is_unaffected(home):
    """No organization: everything works exactly as before."""
    assert org.load(home) is None
    assert org.check(home, "anybody", "delete_agent") is True
    assert org.may(home, "anybody", "manage_secrets") is True
    assert set(org.permissions_of(home, "anybody")) == set(org.PERMISSIONS)
    print("[solo] with no organization created, every capability is available "
          "— adding RBAC must not make a person ask themselves for permission")


def check_roles_are_a_ladder(home):
    org.create(home, "Acme", OWNER, "The Owner")
    org.add_user(home, OWNER, "builder@example.com", "builder")
    org.add_user(home, OWNER, "operator@example.com", "operator")
    org.add_user(home, OWNER, "viewer@example.com", "viewer")
    org.add_user(home, OWNER, "approver@example.com", "approver")

    # a higher role includes everything beneath it
    assert org.may(home, "builder@example.com", "run")
    assert org.may(home, "builder@example.com", "approve")
    assert org.may(home, "builder@example.com", "read")
    # and nothing above it
    assert not org.may(home, "builder@example.com", "manage_secrets")
    assert not org.may(home, "operator@example.com", "create_agent")
    assert not org.may(home, "viewer@example.com", "run")
    assert not org.may(home, "approver@example.com", "create_agent")
    assert org.may(home, "approver@example.com", "approve")
    assert org.may(home, OWNER, "transfer_owner")
    assert not org.may(home, "builder@example.com", "transfer_owner")
    print("[ladder] each role includes every role beneath it and nothing "
          "above: builder can run and approve, cannot manage secrets; "
          "only the owner can transfer ownership")


def check_refusals_are_actionable(home):
    try:
        org.check(home, "viewer@example.com", "delete_agent")
        raise AssertionError("a viewer must not delete an agent")
    except org.Denied as e:
        msg = str(e)
        assert "viewer" in msg and "admin" in msg, msg
        assert "Ask an admin" in msg or "ask" in msg.lower(), msg
    try:
        org.check(home, "stranger@example.com", "read")
        raise AssertionError("a non-member has no access")
    except org.Denied as e:
        assert "not a member" in str(e)
        assert "org.py invite" in str(e), "the refusal should say how to fix it"
    print("[refusals] a denial names the actor's role, the role required, and "
          "what to do next — a refusal nobody understands is one they route "
          "around")


def check_owner_cannot_be_removed_by_role_change(home):
    try:
        org.set_role(home, OWNER, OWNER, "viewer")
        raise AssertionError("the org must never end up with no owner")
    except org.Denied:
        pass
    try:
        org.add_user(home, OWNER, "second@example.com", "owner")
        raise AssertionError("there is one owner")
    except org.Denied:
        pass
    print("[owner] the organization cannot be left ownerless: the owner's "
          "role cannot be downgraded and a second owner cannot be invited")


def check_every_mutation_is_attributable(home):
    org.add_user(home, OWNER, "temp@example.com", "viewer")
    org.set_role(home, OWNER, "temp@example.com", "operator")
    rows = org.trail(home)
    assert rows, "the audit trail must not be empty"
    for r in rows:
        assert r["actor"] and r["action"] and r["at"], r
    actions = [r["action"] for r in rows]
    assert "create_org" in actions and "add_user" in actions
    assert "set_role" in actions
    mine = org.trail(home, actor=OWNER)
    assert len(mine) == len([r for r in rows if r["actor"] == OWNER])
    role_change = [r for r in rows if r["action"] == "set_role"][-1]
    assert "viewer -> operator" in role_change["detail"]
    print(f"[audit] {len(rows)} mutations recorded, each naming the actor, "
          f"the action, the object and the before/after — 'every mutation "
          f"attributable' is a query, not an aspiration")


def check_permission_escalation_is_refused(home):
    """The interesting attack: an operator promoting themselves."""
    try:
        org.set_role(home, "operator@example.com", "operator@example.com",
                     "admin")
        raise AssertionError("an operator must not be able to promote itself")
    except org.Denied as e:
        assert "manage_users" in str(e) or "admin" in str(e), str(e)
    assert org.user(home, "operator@example.com")["role"] == "operator"
    try:
        org.add_user(home, "builder@example.com", "friend@example.com", "admin")
        raise AssertionError("a builder must not be able to invite an admin")
    except org.Denied:
        pass
    print("[escalation] an operator could not promote itself and a builder "
          "could not invite an admin — the permission needed to change "
          "permissions is itself gated")


def main():
    home = make_sandbox("org", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"},
                        scripts={"s.json": [{"tool": "finish_task",
                                             "args": {"summary": "ok"}}]})
    check_solo_install_is_unaffected(home)
    check_roles_are_a_ladder(home)
    check_refusals_are_actionable(home)
    check_owner_cannot_be_removed_by_role_change(home)
    check_every_mutation_is_attributable(home)
    check_permission_escalation_is_refused(home)
    print("PASS test_org")


if __name__ == "__main__":
    main()
