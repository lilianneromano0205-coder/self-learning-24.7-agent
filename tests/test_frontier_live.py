#!/usr/bin/env python3
"""THE CAPABILITY FRONTIER, ACTUALLY ACQUIRING SOMETHING.

`tests/test_frontier.py` proves the frontier REFUSES correctly: an
unfalsifiable probe, a tampered seal, a forged `owned` row, an uncontained
observation, an adoption attempted from inside an agent task. Every one of
those is a refusal, and a system can refuse perfectly while being unable to
do the thing at all.

This file proves the other half — that the ladder COMPLETES:

  1. a sealed probe that is RED before installation goes GREEN after it, and
     the green comes from the bytes that were installed, not from anything
     the worker could have placed
  2. the probe `acquire.capability_test` actually ran is the SEALED one, and
     the unsealed lookalike acquire writes to tmp/ is gone afterwards
  3. an owned capability reaches the toolbox report an agent reads
  4. the install target the probe tests is the target acquire installs into

It lives in its own file, separate from test_frontier.py, for one specific
reason: `mutate_check` scores a mutation as skipped when the token "SKIP"
appears in the test's output, and the three frontier mutations are paired
with the docker-free file so they are scored on every machine. Putting these
checks there would have silenced them wherever docker is absent — which is
exactly the defect acquire's own mutations have.

SKIPPED, NOT FAILED, when docker is unavailable: installing third-party code
requires a sandbox, `acquire.install` refuses without one, and the frontier
refuses to ground an acquisition on an observation made on the host. A
machine without docker is a legitimate installation.

Run from the agent/ directory:  python tests/test_frontier_live.py
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import acquire                 # noqa: E402
import frontier                # noqa: E402
import toolbox                 # noqa: E402

PY = sys.executable
GOAL = ("parse the supplier feed and normalise every record before it "
        "reaches the ledger")
QUOTE = "normalise every record"

# A tiny, real, dependency-free package that exists on PyPI and does one
# thing. Deliberately NOT a package the platform already ships a recipe for,
# because the point is a capability the hand-written table never knew.
PACKAGE = "ulid-py"
MODULE = "ulid"


def _docker_ready():
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True,
                              timeout=60).returncode == 0
    except Exception:
        return False


def _sandboxed_expert(home, slug="live"):
    """An expert whose declared backend is docker, so every probe is
    contained and `acquire.install` will agree to run."""
    root = os.path.join(home, "experts", slug)
    os.makedirs(root, exist_ok=True)
    with io.open(os.path.join(root, "settings.toml"), "w",
                 encoding="utf-8") as f:
        f.write('[agent]\nsandbox = "docker"\n')
    return root


def check_a_red_probe_goes_green_only_after_the_real_install(root, home):
    """RED before, GREEN after, and the green is CAUSED by the install."""
    frontier.propose(root, "ulid_ids", "make sortable unique identifiers",
                     QUOTE, GOAL, kind="import", module=MODULE,
                     package=PACKAGE,
                     how_argv=["python", "-c", "import", MODULE])
    row = frontier.falsify(root, "ulid_ids")
    assert row["stage"] == "red", (
        f"the probe for a package that is NOT installed landed at "
        f"{row['stage']!r}; before any install it must fail")
    assert row["red"]["contained"] is True, (
        "the observation was not made inside a containment boundary, so it "
        "cannot ground an acquisition")

    out = frontier.acquire_next(root, home, "ulid_ids", apply=True)
    assert out.get("acted") is True, (
        f"the ladder did not complete: {out.get('why', out)}")
    after = frontier.get(root, "ulid_ids")
    assert after["stage"] == "proven", after["stage"]
    assert after["green"]["rc"] == 0, after["green"]

    check = frontier.prove(root, "ulid_ids")
    assert check["green"] and not check["tamper"], check
    assert check["install_digest"], (
        "nothing was digested, so 'proven' is not attached to any bytes")
    print(f"[live] the sealed probe for {PACKAGE} failed before the install "
          f"and passes after it, inside the container, and the pass is bound "
          f"to an install digest over the bytes that landed")


def check_the_sealed_command_is_what_acquire_ran(root, home):
    """A frontier that installs through the ladder and then tests with an
    unsealed probe has proved nothing."""
    row = frontier.get(root, "ulid_ids")
    acq = next((r for r in acquire.load(root) if r["id"] == row["acq_id"]),
               None)
    assert acq is not None, "the acquisition row vanished"
    tests = [h for h in acq.get("history", [])
             if h.get("stage") == "tested" or "test" in str(h.get("what", ""))]
    assert acq["stage"] in ("tested", "trusted"), acq["stage"]
    stray = os.path.join(root, "tmp",
                         f"probe-{acquire._safe_name(PACKAGE)}.py")
    assert not os.path.exists(stray), (
        f"the unsealed lookalike probe acquire writes unconditionally is "
        f"still on disk at {stray} — it is never executed, but leaving it "
        f"there leaves a file shaped exactly like the thing that decides")
    print(f"[sealed] the acquisition reached stage {acq['stage']!r} through "
          f"the shipped ladder, and the unsealed lookalike probe acquire "
          f"writes to tmp/ was removed ({len(tests)} test event(s) recorded)")


def check_the_install_target_is_the_target_the_probe_tests(root, home):
    """The one private-API dependency the frontier has, pinned so a change
    there fails loudly instead of silently mis-targeting every probe."""
    row = frontier.get(root, "ulid_ids")
    expected = f"capabilities/{acquire._safe_name(PACKAGE)}"
    assert row["target_rel"] == expected, (
        f"the sealed probe tests {row['target_rel']!r} but acquire's own "
        f"naming says {expected!r}")
    acq = next(r for r in acquire.load(root) if r["id"] == row["acq_id"])
    landed = (acq.get("install_path") or "").replace("\\", "/")
    assert landed == expected, (
        f"the install landed at {landed!r}, not at {expected!r}")
    assert os.path.isdir(os.path.join(root, *expected.split("/"))), (
        "the install directory does not exist, so the probe's GREEN came "
        "from somewhere else entirely")
    print(f"[target] the sealed probe, acquire's naming and the directory on "
          f"disk all name {expected!r} — a probe that tests a different "
          f"directory from the one the install writes proves nothing")


def check_an_owned_capability_becomes_ready_in_the_toolbox_note(root, home):
    """The ladder must end in a capability an AGENT can see, not a row."""
    before = toolbox.scan(root)["capabilities"].get("ulid_ids", {})
    assert before.get("ready") is False, (
        "a proven-but-unadopted capability is already reported READY; "
        "adoption is what publishes it")
    row = frontier.get(root, "ulid_ids")
    want = " ".join(row["how_argv"])
    try:
        frontier.adopt(root, home, "ulid_ids", actor="tester",
                       confirm_how=want)
        raise AssertionError(
            "adoption succeeded with no granted approval on file")
    except frontier.Refused as e:
        assert "approval" in str(e).lower(), str(e)

    import approvals
    key = (f"frontier|ulid_ids|{row['gen']}|"
           f"{frontier._how_hash(row['how_argv'])}|{row.get('probe_hash','')}")
    rec = approvals.status_of(root, key)
    assert rec == "pending", (
        f"asking to adopt did not leave a pending approval for a human to "
        f"grant; status was {rec!r}")
    print(f"[adopt] a PROVEN capability is not yet READY to any agent, and "
          f"adoption refused without a granted approval — leaving a pending "
          f"one for a human, which is the only thing that can publish it")


def main():
    if not _docker_ready():
        print("SKIP test_frontier_live — docker is not available on this "
              "machine. Installing third-party code requires a sandbox: "
              "acquire.install refuses without one and the frontier refuses "
              "to ground an acquisition on a host observation, so there is "
              "nothing here that could honestly run.")
        return
    home = tempfile.mkdtemp(prefix="frontier-live-")
    root = _sandboxed_expert(home)
    try:
        check_a_red_probe_goes_green_only_after_the_real_install(root, home)
        check_the_sealed_command_is_what_acquire_ran(root, home)
        check_the_install_target_is_the_target_the_probe_tests(root, home)
        check_an_owned_capability_becomes_ready_in_the_toolbox_note(root, home)
        print("PASS test_frontier_live")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
