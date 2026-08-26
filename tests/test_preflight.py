#!/usr/bin/env python3
"""The production audit tells the truth about THIS installation (M11).

`doctor.py` says the software is healthy; `harness.py --check` says the
contracts hold. This one answers the owner's real question -- if it runs
unattended for a month, what will hurt? -- and it has to be honest in both
directions: no false alarms on a sound fleet, and no green light on a fleet
with no backups or no spend cap.

1. a fresh fleet with no backup is NOT READY, and says exactly which command
   fixes it
2. taking a backup clears the blocker
3. a spend cap turned off is reported as a risk, per settings file
4. a stale backup is reported; a damaged one is a blocker
5. exposure is audited only when the panel is actually exposed, and a missing
   token is then a blocker
6. every finding carries a fix, the verdict matches the findings, and the
   exit code matches the verdict
7. a check that throws never takes the audit down with it

Run from the agent/ directory:  python tests/test_preflight.py
"""

import json
import os
import subprocess
import sys

from common import AGENT_DIR, PY, agent_setting, make_sandbox

sys.path.insert(0, AGENT_DIR)
import backup
import credentials
import fleet
import preflight


def levels(rep, area=None):
    return [f for f in rep["findings"]
            if area is None or f["area"] == area]


def main():
    home = make_sandbox("preflight", providers={"m": {"script": "s.json"}},
                        roles={"tester": "m"}, scripts={"s.json": []})
    fleet.create(home, "Operator", "runs the business")

    # --- 1. no backups -> NOT READY, with the command that fixes it
    rep = preflight.run(home)
    assert rep["verdict"] == "NOT READY", rep["verdict"]
    blockers = [f for f in rep["findings"] if f["level"] == preflight.BLOCKER]
    assert any(f["area"] == "backups" for f in blockers), blockers
    fix = next(f["fix"] for f in blockers if f["area"] == "backups")
    assert "backup.py create" in fix, fix
    assert all(f["fix"] for f in blockers), "a blocker without a fix is a rant"
    print("[blocker] a fleet with no backup is NOT READY, and the finding "
          "carries the exact command that fixes it")

    # --- 2. taking one clears it
    backup.create(home, os.path.join(home, "backups"))
    rep2 = preflight.run(home)
    assert not [f for f in rep2["findings"]
                if f["level"] == preflight.BLOCKER and f["area"] == "backups"]
    ok_backup = [f for f in levels(rep2, "backups") if f["level"] == preflight.OK]
    assert ok_backup and "checksums verified" in ok_backup[0]["what"]
    print("[cleared] taking a backup cleared the blocker -- and the audit "
          "verified its checksums rather than trusting the filename")

    # --- 3. spend caps
    root = os.path.join(home, "experts", "operator")
    agent_setting(root, "daily_budget_usd = 0")
    rep3 = preflight.run(home)
    cost = [f for f in levels(rep3, "cost") if f["level"] == preflight.RISK]
    mine = [f for f in cost if "operator" in f["what"]]
    assert mine, cost
    assert "daily_budget_usd" in mine[0]["fix"] and root in mine[0]["fix"]
    # it audits EVERY settings file, so the fleet default is named too
    assert any("the fleet default" in f["what"] for f in cost), cost
    agent_setting(root, "daily_budget_usd = 25")
    rep4 = preflight.run(home)
    assert not [f for f in levels(rep4, "cost")
                if f["level"] == preflight.RISK and "operator" in f["what"]]
    print("[cost] a disabled daily breaker was named per settings file -- the "
          "expert's and the fleet default's -- and setting it cleared that one")

    # --- 4. a damaged backup is a blocker, not a shrug
    newest = backup.latest(os.path.join(home, "backups"))["path"]
    with open(newest, "r+b") as f:
        f.seek(len(f.read()) // 2)
        f.write(b"\x00\x00\x00\x00")
    rep5 = preflight.run(home)
    bad = [f for f in levels(rep5, "backups")
           if f["level"] == preflight.BLOCKER]
    assert bad, "a corrupted archive is a BLOCKER, not a shrug"
    assert "verification" in bad[0]["what"] or "damaged" in bad[0]["what"], bad
    assert rep5["verdict"] == "NOT READY", rep5["verdict"]
    print("[integrity] a corrupted archive was caught by the audit, not "
          "discovered on the day it was needed")

    # --- 5. exposure
    home2 = make_sandbox("preflight_net", providers={"m": {"script": "s.json"}},
                         roles={"tester": "m"}, scripts={"s.json": []})
    quiet = preflight.run(home2)
    assert any(f["level"] == preflight.OK and f["area"] == "access"
               for f in quiet["findings"])
    loud = preflight.run(home2, exposed=True)
    acc = [f for f in levels(loud, "access") if f["level"] == preflight.BLOCKER]
    assert acc and "no token" in acc[0]["what"], acc
    # write it the way the platform does. Writing it by hand with a bare
    # open() left it at 0644 on Linux, and preflight was RIGHT to call a
    # world-readable fleet token a blocker: the test manufactured the very
    # finding it went on to assert was absent. This is why the writer now
    # lives in one place -- see credentials.write_secret.
    credentials.write_secret(os.path.join(home2, "ui-token.txt"), "tok\n")
    if os.name != "nt":
        mode = os.stat(os.path.join(home2, "ui-token.txt")).st_mode & 0o777
        assert mode == 0o600, f"the authority wrote a secret at {oct(mode)}"
    loud2 = preflight.run(home2, exposed=True)
    assert not [f for f in levels(loud2, "access")
                if f["level"] == preflight.BLOCKER]
    assert any("HTTPS" in f["fix"] or "Tailscale" in f["fix"]
               for f in levels(loud2, "access"))
    print("[access] exposure is audited only when the panel is exposed; a "
          "missing token is then a blocker, and transport is still flagged")

    # --- 6. the verdict and the exit code agree
    for rep_x in (rep, rep2, rep5, loud, loud2):
        c = rep_x["counts"]
        expected = ("NOT READY" if c[preflight.BLOCKER] else
                    "READY WITH RISKS" if c[preflight.RISK] else "READY")
        assert rep_x["verdict"] == expected, (rep_x["verdict"], c)
        assert all(f["fix"] or f["level"] == preflight.OK
                   for f in rep_x["findings"]), "every finding needs a fix"
    r = subprocess.run([PY, os.path.join(AGENT_DIR, "preflight.py"),
                        "--home", home, "--json"],
                       capture_output=True, text=True)
    assert r.returncode == 2, r.returncode          # still blocked (damaged)
    out = json.loads(r.stdout)
    assert out["verdict"] == "NOT READY" and out["home"]
    backup.create(home2, os.path.join(home2, "backups"))   # clear its blocker
    r2 = subprocess.run([PY, os.path.join(AGENT_DIR, "preflight.py"),
                        "--home", home2], capture_output=True, text=True)
    assert r2.returncode in (0, 1), (r2.returncode, r2.stdout[-400:])
    assert "VERDICT:" in r2.stdout and "NOT READY" not in r2.stdout
    print("[verdict] the verdict follows the findings and the exit code "
          "follows the verdict: 2 blocked, 1 risks, 0 clean")

    # --- 6b. a reviewer sharing the author's model is named
    fleet.create(home2, "Solo", "one model for everything")
    solo = os.path.join(home2, "experts", "solo")
    settings = os.path.join(solo, "settings.toml")

    def wire(examiner_model):
        lines = ["[agent]", "daily_budget_usd = 5", "max_task_usd = 1", "",
                 "[providers.m]", 'type = "mock"', 'script = "s.json"', "",
                 "[roles.practitioner]", 'provider = "m"',
                 'model = "same-model"', "",
                 "[roles.examiner]", 'provider = "m"',
                 f'model = "{examiner_model}"', ""]
        with open(settings, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    wire("same-model")
    rep_c = preflight.run(home2)
    critic = levels(rep_c, "critic")
    assert critic and any("same model" in f["what"] for f in critic), critic
    assert any("different provider or model" in f["fix"] for f in critic)
    wire("a-different-model")
    rep_d = preflight.run(home2)
    assert not [f for f in levels(rep_d, "critic")
                if "same model" in f["what"]], levels(rep_d, "critic")
    print("[critic] an examiner running the author's own model was named as "
          "review theatre; pointing it at a different model cleared it")

    # --- 7. a broken check cannot take the audit down
    original = preflight.check_disk

    def explodes(_home):
        raise RuntimeError("disk check went wrong")
    preflight.check_disk = explodes
    try:
        preflight.CHECKS = tuple((n, explodes if n == "capacity" else f)
                                 for n, f in preflight.CHECKS)
        rep6 = preflight.run(home2)
        assert rep6["verdict"] in ("READY", "READY WITH RISKS", "NOT READY")
        assert any("the check itself failed" in f["what"]
                   for f in rep6["findings"]), rep6["findings"]
    finally:
        preflight.check_disk = original
    print("[robust] a check that threw was reported as a failed check; the "
          "audit still produced a verdict")
    check_one_readiness_truth()
    print("PASS test_preflight")


def check_one_readiness_truth():
    """Doctor and preflight must give ONE answer to "can this fleet think?".

    The audit found them contradicting: preflight said "ready with risks"
    while doctor said the system cannot think, because each surface computed
    a different question and published it under the same word. An operator
    reading one surface made a decision the other surface would have
    refused. The fix is structural — preflight ASKS doctor — and this pins
    it in both directions:

      * a fleet whose only live provider has NO KEY: doctor reports a
        blocking item, and preflight must be NOT READY with a `thinking`
        BLOCKER carrying doctor's own words — not "ready with risks";
      * give it the key: doctor's blocker disappears and so does
        preflight's, without either surface being edited.
    """
    import shutil
    import tempfile

    import doctor

    home = tempfile.mkdtemp(prefix="one-truth-")
    try:
        os.makedirs(os.path.join(home, "experts"), exist_ok=True)
        root = fleet.create(home, "Thinker", "needs a real provider")
        cfg = ('[agent]\npoll_interval_seconds = 1\nreflect_after = []\n'
               'daily_budget_usd = 5\nmax_task_usd = 1\n\n'
               '[providers.real]\nbase_url = "https://api.example.com/v1"\n'
               'api_key_env = "ONE_TRUTH_TEST_KEY"\n'
               'input_per_mtok = 1.0\noutput_per_mtok = 1.0\n\n'
               '[roles.default]\nprovider = "real"\nmodel = "m"\n')
        # doctor scans the HOME's settings as well as every expert's, and
        # fleet.create seeds the home with the shipped template (whose live
        # providers are keyless here) — so both files must be this test's,
        # or the assertion measures the template instead of the fixture
        for p in (os.path.join(home, "settings.toml"),
                  os.path.join(root, "settings.toml")):
            with open(p, "w", encoding="utf-8") as f:
                f.write(cfg)
        os.environ.pop("ONE_TRUTH_TEST_KEY", None)

        doc = doctor.readiness(home)
        doc_blockers = [i for i in doc["items"] if i["blocking"]]
        assert doc_blockers and not doc["ready"], (
            f"doctor should refuse a keyless live provider: {doc['items']}")

        rep = preflight.run(home)
        assert rep["verdict"] == "NOT READY", (
            f"doctor says this fleet cannot think and preflight says "
            f"{rep['verdict']!r} — the exact contradiction the audit filed. "
            f"Two surfaces, one word, two meanings.")
        think = [f for f in rep["findings"]
                 if f["area"] == "thinking" and f["level"] == preflight.BLOCKER]
        assert think, rep["findings"]
        assert any(d["what"] == t["what"] for d in doc_blockers
                   for t in think), (
            f"preflight's thinking blocker is not doctor's own item — a "
            f"paraphrase is a second computation wearing a quote's clothes: "
            f"doctor={doc_blockers} preflight={think}")

        # the key arrives -> BOTH surfaces clear, neither was edited
        os.environ["ONE_TRUTH_TEST_KEY"] = "sk-test-not-real"
        try:
            doc2 = doctor.readiness(home)
            assert not [i for i in doc2["items"] if i["blocking"]], doc2
            rep2 = preflight.run(home)
            assert not [f for f in rep2["findings"]
                        if f["area"] == "thinking"
                        and f["level"] == preflight.BLOCKER], (
                "doctor cleared and preflight still blocks — the two "
                "surfaces have diverged again")
        finally:
            os.environ.pop("ONE_TRUTH_TEST_KEY", None)
        print("[one-truth] a keyless fleet is NOT READY on BOTH surfaces, "
              "with preflight quoting doctor's own blocking item verbatim; "
              "supplying the key cleared both at once — one computation, "
              "two renderers, no second opinion")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
