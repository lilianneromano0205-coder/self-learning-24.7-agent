#!/usr/bin/env python3
"""STANDING GRANTS — the owner says yes once, inside a boundary that holds.

The platform never lets an agent resolve an authority gap by itself, and that
rule stopped EVERY time — so a fleet meant to run all night parked on a human
at the first invoice, and an owner asked the same question forty times stops
reading the questions. grants.py adds the middle: a scoped, expiring,
revocable, logged permission.

What must be true for that to be safe rather than convenient:

  1. a grant covers ONLY its scope — a different vendor is still blocked
  2. it EXPIRES, and an expired grant is not a grant
  3. it can be REVOKED, immediately
  4. only the OWNER may create one — not an admin, and never the agent
  5. every USE is recorded, or a standing grant is a blank cheque
  6. universal.assess CONSUMES it: a covered gap stops blocking the run

Run from the agent/ directory:  python tests/test_grants.py
"""

import os
import sys
import time

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import grants                  # noqa: E402
import universal               # noqa: E402


def check_scope_is_the_whole_point(home):
    grants.grant(home, "owner@example.com", "credential", "acme.com", days=30,
                 why="Q3 invoices")
    ok, why = grants.check(home, "credential", "acme.com")
    assert ok, why
    bad, why2 = grants.check(home, "credential", "othervendor.com")
    assert not bad, (
        "a grant for acme.com covered othervendor.com — a scope that leaks is "
        "not a decision anybody made")
    # and a grant of one KIND does not imply another
    money, _ = grants.check(home, "money", "acme.com")
    assert not money, (
        "permission to use a credential became permission to spend money")
    # an unscoped grant is possible but must be asked for explicitly
    try:
        grants.grant(home, "owner@example.com", "money", "", days=5)
        raise AssertionError("a grant with no scope was accepted")
    except grants.Denied as e:
        assert "SCOPE" in str(e) or "scope" in str(e), str(e)
    print("[scope] a grant covers its own scope and nothing beside it: "
          "another vendor is refused, another KIND of authority is refused, "
          "and a scopeless grant must be spelled '*' rather than left blank")


def check_it_expires_and_revokes(home):
    r = grants.grant(home, "owner@example.com", "message", "team@acme.com",
                     days=1, why="status mail")
    assert grants.check(home, "message", "team@acme.com")[0]
    # expire it by hand — the same field live() reads
    rows = grants.load(home)
    for row in rows:
        if row["id"] == r["id"]:
            row["expires"] = time.strftime(
                "%Y-%m-%d", time.localtime(time.time() - 86400 * 2))
    grants._save(home, rows)
    ok, why = grants.check(home, "message", "team@acme.com")
    assert not ok, "an EXPIRED grant still authorised work"
    assert "no standing grant" in why, why

    r2 = grants.grant(home, "owner@example.com", "publish", "blog.acme.com",
                      days=30)
    assert grants.check(home, "publish", "blog.acme.com")[0]
    grants.revoke(home, "owner@example.com", r2["id"])
    assert not grants.check(home, "publish", "blog.acme.com")[0], (
        "a REVOKED grant still authorised work")
    print("[lifetime] a grant stops working the day it expires and the moment "
          "it is revoked — a permission that outlives its reason is how a "
          "temporary exception becomes standing access nobody approved")


def check_only_the_owner_grants(home):
    """The agent must never be able to widen its own authority."""
    import org
    org.create(home, "Check Co", "owner@example.com")
    org.add_user(home, "owner@example.com", "admin@example.com", "admin")
    org.add_user(home, "owner@example.com", "builder@example.com", "builder")
    for actor, role in (("admin@example.com", "admin"),
                        ("builder@example.com", "builder")):
        try:
            grants.grant(home, actor, "money", "acme.com", days=30)
            raise AssertionError(
                f"a {role} granted authority — these decide what the fleet may "
                f"do to the outside world, which is the owner's call")
        except (grants.Denied, org.Denied):
            pass
    r = grants.grant(home, "owner@example.com", "money", "acme.com", days=30,
                     cap_usd=200)
    assert r["cap_usd"] == 200.0
    print("[owner-only] neither an admin nor a builder can grant authority; "
          "only the owner can, and the agent has no path to it at all")


def check_the_cap_binds_and_uses_are_logged(home):
    ok, _ = grants.check(home, "money", "acme.com", amount_usd=50)
    assert ok, "a $50 spend was refused under a $200 cap"
    over, why = grants.check(home, "money", "acme.com", amount_usd=500)
    assert not over and "cap" in why, why
    grants.record_use(home, "money", "acme.com", detail="paid invoice 41",
                      amount_usd=120)
    left, why2 = grants.check(home, "money", "acme.com", amount_usd=120)
    assert not left, (
        "the cap did not consume: two $120 spends fit inside a $200 cap")
    rows = grants.uses(home)
    assert rows and rows[-1]["detail"] == "paid invoice 41", rows
    assert rows[-1]["amount_usd"] == 120.0
    print("[ledger] the cap is consumed by real use, a second spend that "
          "would breach it is refused, and every use is written to a ledger — "
          "a standing grant without a usage log is a blank cheque")


def check_assess_consumes_the_grant(home):
    """The point of the whole module: a covered gap stops blocking."""
    import fleet
    fleet.create(home, "Buyer", "does procurement")
    # its OWN vendor, so earlier checks in this file cannot decide the answer
    goal = "log into the supplier-co.example portal and pay each invoice"

    def authority_gaps():
        a = universal.assess(home, "buyer", goal)
        return sorted(g["what"] for g in a["gaps"] if g["dimension"] == "authority")

    before = authority_gaps()
    assert "a credential only you can issue" in before, before
    assert "spending money" in before, before

    g = grants.grant(home, "owner@example.com", "credential",
                     "supplier-co.example", days=30, why="Q3 invoices")
    covered = authority_gaps()
    assert "a credential only you can issue" not in covered, (
        f"the owner's standing grant was ignored by assess(): {covered}")
    assert "spending money" in covered, (
        "granting a credential silently granted spending too — the two are "
        "separate decisions and a grant of one must not imply the other")

    # and REVOKING puts the boundary straight back, with no code change
    grants.revoke(home, "owner@example.com", g["id"])
    reverted = authority_gaps()
    assert "a credential only you can issue" in reverted, (
        f"revoking the grant did not restore the boundary: {reverted}")
    # a different vendor is untouched
    other = universal.assess(home, "buyer",
                             "log into the othervendor.com portal and pay")
    assert any(g["what"] == "a credential only you can issue"
               for g in other["gaps"] if g["dimension"] == "authority"), (
        "the acme.com grant leaked to another vendor through assess()")
    print("[wired] universal.assess honours a live grant — the credential gap "
          "clears for the granted vendor, the MONEY gap still blocks, and another "
          "vendor is still blocked; nothing self-grants, and the moment the "
          "grant expires or is revoked this reverts with no code change")


def main():
    home = make_sandbox("grants", providers={"m": {"script": "s.json"}},
                        roles={"practitioner": "m"}, scripts={"s.json": []})
    check_scope_is_the_whole_point(home)
    check_it_expires_and_revokes(home)
    check_only_the_owner_grants(home)
    check_the_cap_binds_and_uses_are_logged(home)
    check_assess_consumes_the_grant(home)
    check_acting_under_a_grant_is_recorded(home)
    print("PASS test_grants")


def check_acting_under_a_grant_is_recorded(_home):
    """A standing grant without a usage log is a blank cheque.

    grants.py says exactly that, in record_use's own docstring — and nothing
    in the platform called it. The grant machinery worked: a covered
    authority gap was suppressed and the run proceeded. But an owner who
    wrote "yes, this expert may send messages about invoices, for 90 days"
    had no way to see what had been done in their name, and
    `python grants.py uses` printed an empty ledger however much work the
    grant had authorised. The module documented the failure mode and then
    committed it.

    For a platform meant to be trusted with anything consequential, this is
    the part an auditor actually reads: not "was there permission" but "what
    was done with it".

    Two halves, and the second is what makes the first usable:
      1. ACTING under a grant records a use, one per grant consumed;
      2. LOOKING does not. assess() runs on every panel read — while
         somebody is still typing the sentence — and logging those would
         bury the real entries under readings.
    """
    import shutil
    import tempfile

    import fleet

    home = tempfile.mkdtemp(prefix="grant-uses-")
    try:
        os.makedirs(os.path.join(home, "experts"), exist_ok=True)
        fleet.create(home, "Mailer", "sends invoice mail")
        goal = "send the quarterly invoice email to the vendor"

        # the goal implies two authority gaps; grant both, scoped as the
        # platform itself derives the scope
        scope = universal._scope_of(goal)
        for kind in ("message", "money"):
            grants.grant(home, "owner", kind, scope, days=90,
                         why="routine invoicing")

        # 2. LOOKING RECORDS NOTHING
        universal.resolve(home, "mailer", goal, apply=False)
        assert grants.uses(home) == [], (
            "a read-only assessment logged a grant use. The panel calls this "
            "on every keystroke-driven refresh, so the ledger would fill "
            "with readings and the real entries become unfindable.")

        # 1. ACTING RECORDS IT
        plan = universal.resolve(home, "mailer", goal, apply=True)
        rows = grants.uses(home)
        kinds = {r.get("kind") for r in rows}
        assert kinds == {"message", "money"}, (
            f"work proceeded under grants and the ledger holds {sorted(kinds)}"
            f" — every grant that suppressed a gap must appear, or the owner "
            f"sees only part of what was done in their name")
        assert all(r.get("scope") for r in rows), rows
        assert all("mailer" in str(r.get("detail", "")) for r in rows), (
            "a use was recorded without saying WHICH expert did it or what "
            "for; 'something happened' is not an audit trail")
        assert not plan.get("needs_owner"), (
            "the grants covered both gaps, so nothing should still route to "
            "the owner")

        # and the counter on the grant itself moved, so `grants.py list`
        # shows an owner how heavily each standing permission is being used
        listed = {g["kind"]: g for g in grants.status(home)} \
            if hasattr(grants, "status") else {}
        if listed:
            assert all(listed[k].get("uses", 0) >= 1 for k in ("message",
                                                               "money")), listed
        print(f"[recorded] acting under {len(kinds)} standing grant(s) wrote "
              f"{len(rows)} usage row(s) naming the expert and the work, "
              f"while a read-only assessment wrote none — the difference "
              f"between a permission and a blank cheque is the log of what "
              f"was done with it")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
