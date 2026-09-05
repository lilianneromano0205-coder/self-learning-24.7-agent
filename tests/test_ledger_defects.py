#!/usr/bin/env python3
"""Phase 7.2 exit benchmark — the ledger defects, held green.

docs/DESIGN-P7.2-ledger-defects.md preregistered exactly this: ten places
found by the Capability Ledger where the code said one thing and did
another, each closed by a property that FAILS on the tree before the fix:

  1. DOCTOR         an import failure is a PROBLEM, never "all modules
                    import"; the authority modules are in the core list
  2. PANEL GATE     the task dialog names a gate from the catalogue and
                    posts no free-form command; _net_gate accepts the
                    object it builds and still refuses a raw string
  3. INVITE         the invite dialog posts no actor field
  4. SUB-CALL       "subquery" is a declared gateway purpose
  5. CASE LEDGER    memory/cases.jsonl is CONTROL: agent write refused,
                    harness write allowed, enumerated in the leakage suite
  6. RECIPES        python toolbox.py --recipes prints the pinned recipes
  7. MANIFEST       the harness manifest's A2A entry says what federation
                    says
  8. PROSE          REFERENCE, MANUAL and README carry the counts the
                    tree has

Run from the agent/ directory:  python tests/test_ledger_defects.py
"""
import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile

from common import AGENT_DIR, PY

sys.path.insert(0, AGENT_DIR)
import doctor                   # noqa: E402
import federation               # noqa: E402
import fileauth                 # noqa: E402
import harness                  # noqa: E402
import modelgateway             # noqa: E402
import templates                # noqa: E402
import ui                       # noqa: E402


def _read(rel):
    return io.open(os.path.join(AGENT_DIR, rel), encoding="utf-8").read()


# --------------------------------------------------------------- 1 doctor
def check_doctor_reports_import_failures():
    original = list(doctor.CORE_MODULES)
    doctor.CORE_MODULES = ["loop", "no_such_module_p72"]
    out = io.StringIO()
    try:
        r = doctor.Report()
        with contextlib.redirect_stdout(out):
            doctor.check_runtime(r)
    finally:
        doctor.CORE_MODULES = original
    text = out.getvalue()
    assert "PROBLEM import" in text and "no_such_module_p72" in text, text
    assert "core modules import" not in text, \
        "an import failure must never be reported as all modules importing"
    assert r.problems, r.problems
    for name in ("org", "controlplane", "fileauth", "execution",
                 "credentials", "modelgateway", "workers", "training",
                 "metrics", "gates", "scheduler", "procedure", "verifier",
                 "verification", "operators", "dbstate", "gitstate",
                 "xlsxstate", "tabular", "tabletypes"):
        assert name in doctor.CORE_MODULES, f"{name} is not import-checked"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        doctor.check_runtime(doctor.Report())
    assert f"all {len(doctor.CORE_MODULES)} core modules import" in out.getvalue()
    print("[doctor] a failed import is reported as a PROBLEM and the "
          "all-clear line is withheld; every authority module is on the "
          "list; a clean tree still reports the all-clear")


# ------------------------------------------------------------ 2 panel gate
def check_panel_names_a_gate():
    page = _read("ui.html")
    assert 'id="ntCheck"' not in page, \
        "the free-form done-check field is still in the task dialog"
    assert 'id="ntGate"' in page and 'id="ntGateParam"' in page, \
        "the task dialog must carry a gate picker"
    for gate in ("exists", "designcheck", "citecheck", "verify", "memcheck"):
        assert f'value="{gate}"' in page, gate
    built = ui._net_gate({"gate": "exists", "path": "out/index.html"})
    assert built and "out/index.html" in built, built
    built = ui._net_gate({"gate": "verify", "course": "onboarding"})
    assert built and "onboarding" in built, built
    assert ui._net_gate(None) is None and ui._net_gate({}) is None
    try:
        ui._net_gate("python check.py")
    except ValueError as exc:
        assert "free-form" in str(exc), exc
    else:
        raise AssertionError("a raw string must still be refused")
    print("[panel] the task dialog names a gate from the catalogue (exists, "
          "designcheck, citecheck, verify, memcheck) with one parameter; "
          "the object it posts builds a command and a raw string is refused")


# ---------------------------------------------------------------- 3 invite
def check_invite_posts_no_actor():
    page = _read("ui.html")
    body = page[page.index("async function doInvite"):][:600]
    assert "actor" not in body, body
    assert 'id="ivAs"' not in page
    print("[invite] the invite dialog no longer asks for an actor the server "
          "ignores; the token identity is the actor")


# -------------------------------------------------------------- 4 subquery
def check_subquery_purpose_is_declared():
    assert "subquery" in modelgateway.PURPOSES, modelgateway.PURPOSES
    with tempfile.TemporaryDirectory(prefix="p72-gw-") as root:
        modelgateway.record(root, purpose="subquery", role="r", provider="p",
                            model="m", usage=None, cost=0.0, task="t1", ms=1,
                            ok=True)
        rows = modelgateway.by_purpose(root)
    assert "subquery" in rows and "unknown" not in rows, rows
    print("[subquery] a sub-call is metered under its own purpose, not "
          "'unknown'")


# ------------------------------------------------------------ 5 case ledger
def check_case_ledger_is_control():
    import cases
    rel = cases.LEDGER.replace("\\", "/")
    assert fileauth.zone_of(rel) == fileauth.ZONE_CONTROL, fileauth.zone_of(rel)
    with tempfile.TemporaryDirectory(prefix="p72-cases-") as root:
        try:
            fileauth.resolve(root, rel, "write", "agent")
        except fileauth.Denied:
            pass
        else:
            raise AssertionError("the agent may still write the case ledger")
        assert fileauth.resolve(root, rel, "write", "harness")
    suite = _read(os.path.join("tests", "test_promotion_leakage.py"))
    assert rel in suite, "the case ledger is not enumerated in the leakage suite"
    print("[cases] memory/cases.jsonl is CONTROL: the agent's write is "
          "refused, the harness's allowed, and the path is enumerated in "
          "the promotion-leakage suite")


# ---------------------------------------------------------------- 6 recipes
def check_recipes_command():
    proc = subprocess.run([PY, os.path.join(AGENT_DIR, "toolbox.py"),
                           "--recipes"], capture_output=True, text=True,
                          cwd=AGENT_DIR, timeout=120)
    assert proc.returncode == 0, proc.stderr
    import toolbox
    for name in toolbox.ACQUIRE:
        assert name in proc.stdout, name
    comment = _read("toolbox.py")
    assert "toolbox.py recipes" not in comment, \
        "the comment still promises a subcommand that does not exist"
    print("[recipes] `python toolbox.py --recipes` prints every pinned "
          "acquisition recipe, and the comment names the flag that exists")


# --------------------------------------------------------------- 7 manifest
def check_manifest_tells_the_truth_about_a2a():
    with tempfile.TemporaryDirectory(prefix="p72-manifest-") as root:
        m = harness.manifest(root)
    a2a = m["versions"]["a2a"]
    assert isinstance(a2a, dict) and a2a.get("task_api") is False \
        and a2a.get("card") is True, a2a
    # the same fact federation states on its own card (test_lanes reads the
    # live card; this pins the manifest to the same declaration)
    src = _read("federation.py")
    assert '"a2a_task_api": False' in src, "federation's declaration moved"
    assert callable(federation.a2a_card)
    print("[manifest] the harness manifest's A2A entry states what "
          "federation states: a card is served, the task API is not "
          "implemented")


def _home():
    d = tempfile.mkdtemp(prefix="p72-home-")
    return d


# ----------------------------------------------------------------- 8 prose
def check_prose_matches_the_tree():
    ref = _read("REFERENCE.md")
    manual = _read("MANUAL.md")
    readme = _read("README.md")
    n_templates = len(templates.all_templates())
    assert str(n_templates) in ref and "twenty templates" not in ref.lower(), \
        f"REFERENCE must name {n_templates} templates"
    kinds = ["at", "every_days", "file_exists", "file_contains", "task_done",
             "event", "check"]
    src = _read("prospective.py")
    for k in kinds:
        assert f'"{k}"' in src, f"prospective.py no longer names kind {k}"
    assert "Four kinds:" not in ref and all(f"`{k}`" in ref for k in kinds), \
        "REFERENCE must list every intention kind"
    import proof
    n_caps = len(proof.REGISTRY)
    assert f"{n_caps} capabilities" in ref and f"{n_caps} capabilities" in manual
    tests = len([f for f in os.listdir(os.path.join(AGENT_DIR, "tests"))
                 if f.startswith("test_") and f.endswith(".py")])
    # A static registry count cannot claim every test passed on this host.
    assert f"tests-{tests}%20registered" in readme, "README test badge is stale"
    import mutate_check
    assert f"mutation%20tests-{len(mutate_check.MUTATIONS)}%20registered" in readme, \
        "README mutation badge is stale"
    print(f"[prose] REFERENCE names {n_templates} templates and all {len(kinds)} "
          f"intention kinds; MANUAL and REFERENCE say {n_caps} capabilities; "
          f"the README badges carry {tests} tests and "
          f"{len(mutate_check.MUTATIONS)} mutations")


def main():
    check_doctor_reports_import_failures()
    check_panel_names_a_gate()
    check_invite_posts_no_actor()
    check_subquery_purpose_is_declared()
    check_case_ledger_is_control()
    check_recipes_command()
    check_manifest_tells_the_truth_about_a2a()
    check_prose_matches_the_tree()
    print("PASS test_ledger_defects")


if __name__ == "__main__":
    main()
