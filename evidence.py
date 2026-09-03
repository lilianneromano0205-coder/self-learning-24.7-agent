#!/usr/bin/env python3
"""EVIDENCE — why we believe each system works, and where belief runs out.

"All tests passed" is not a claim about the platform. It is a claim about the
tests. This module turns the first into the second honestly: it runs the
suite, captures what each test SAID it proved (every test prints its own
`[section]` sentences), maps those to the six systems, and writes a report
where each system carries:

    verdict     proven / proven except skipped / partly proven /
                FAILING / UNPROVEN
    evidence    the sentences the tests actually printed, from this run
    blind spot  what these tests do not cover, stated plainly

The last column is the point. A system with twelve passing tests and one
untested failure mode is not "green" — it is well covered with a named hole,
and an owner deciding whether to trust it deserves the hole.

Two rules keep it honest:

  * every registered test must be assigned to a system. A new test that
    nobody classified makes this report fail loudly, so coverage cannot
    silently drift away from the map.
  * a system with no tests is printed as UNPROVEN in capitals. Silence is
    never read as success.
  * a test that SKIPS is a third outcome, not a failure and not a proof. It
    is named in the report with the reason it gave, it contributes no
    observations, and a system where everything skipped reads UNPROVEN.

    python evidence.py                 # run the suite and write EVIDENCE.md
    python evidence.py --from run.log  # use a captured run instead
    python evidence.py --json
"""

import argparse
import json
import locale
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# A test's observation label may carry spaces and a few marks ("[phase 1]",
# "[csv->sql]", "[re-exam failure]"); it never carries a colon, which is
# what keeps run_all's "[skipped: ...]" note and a tool's "[UNSAFE developer
# host: ...]" out of the count. The old grammar ([a-z0-9_-] only) silently
# dropped every spaced label, so ~20 observations the suite printed never
# reached this document (docs/DESIGN-P6.1, finding 10).
SECTION_RE = re.compile(r"^\[([a-z0-9][a-z0-9_ .><\-/]{0,39})\]\s+(.*)$", re.I)
TEST_RE = re.compile(r"^=== (test_\w+\.py) ===$")
PASS_RE = re.compile(r"^PASS (\S+)")
# A unittest file ends with a bare "OK" (or "OK (skipped=1)"), never "PASS
# <name>". This parser knew only the hand-rolled convention, so the ~18
# unittest-style files the verified-learning layer added were read as
# FAILURES: EVIDENCE.md announced "118/136 tests passed" and marked five
# systems FAILING off a suite that had just reported 0 failed. A document
# whose job is to say why we believe this works cannot invent red.
UNITTEST_OK_RE = re.compile(r"^OK(\s*\(.*\))?$")
# A test may decline to run and SAY SO — test_shutdown does exactly this on
# Windows, where Popen.terminate() is TerminateProcess and no handler can
# intercept it, so there is no SIGTERM to catch and asserting anything would
# be asserting something false.
#
# Before this, a skip read as a missing PASS and the whole system came out
# **FAILING** on a green suite. That is the worst kind of wrong for a document
# whose entire job is to be trusted: it cries failure where there is none, and
# a reader who checks once and finds the alarm bogus stops reading the alarms.
# The opposite — folding skips silently into "proven" — is worse still, because
# a skipped test proves NOTHING and would be counted as proof.
#
# So a skip is its own outcome, carries its reason into the artifact, and the
# system it belongs to is marked as not fully proven ON THIS RUN.
# The separator accepts ASCII colon/hyphen AND the em/en dashes, because
# test_docker_live writes "SKIP test_docker_live — docker is not..."
# and a skip whose punctuation the parser does not recognise is counted as
# a FAILURE — the exact false alarm this regex exists to prevent.
SKIP_RE = re.compile(r"^SKIP\s+(test_\w+)(?:\.py)?\s*[:\-–—]\s*(.*)$")

# Which tests speak for which system. Every registered test must appear here.
SYSTEMS = {
    "1. Harness & loop": {
        "what": "the engine: context assembly, six tools, gates, brakes, "
                "retries, escalation, policy, effects, compaction",
        "tests": ["test_harness.py", "test_faults.py", "test_stop.py",
                  "test_checkpoint.py", "test_retry.py", "test_compaction.py",
                  "test_resume.py", "test_lock.py", "test_paths.py",
                  "test_shutdown.py",
                  "test_reliability.py", "test_e2e_crash.py", "test_layers.py",
                  "test_subquery.py",
                  "test_json_toolcall.py", "test_guardrails.py",
                  "test_effects.py", "test_sandbox.py",
                  "test_secrets.py", "test_chaos.py", "test_blocked.py",
                  "test_hardening.py",
                  "test_candidates.py",
                  "test_retention.py", "test_context.py",
                  "test_loop_learning_controls.py",
                  "test_use_cases.py", "test_vision_preservation.py"],
        "blind": "every model call in these tests is the scripted mock "
                 "provider. They prove the harness holds around a model; they "
                 "prove nothing about any real provider's behaviour.",
    },
    "2. Fleet & creation lanes": {
        "what": "trained expert, quick specialist, archetype, learner, team",
        "tests": ["test_fleet.py", "test_quick.py", "test_lanes.py",
                  "test_team.py", "test_toolbox.py", "test_local.py"],
        "blind": "the lanes are exercised with scripted providers and small "
                 "briefings; no test covers a multi-hour real ingestion or a "
                 "team larger than three specialists.",
    },
    "3. Work systems": {
        "what": "task, goal engine, team, deterministic workflow, "
                "consultation, prospective intentions, routines, "
                "procedural mastery (sealed capability packs)",
        "tests": ["test_goal.py", "test_contract.py", "test_runbook.py",
                  "test_repair.py", "test_swarm.py", "test_mastery.py",
                  "test_steer.py", "test_contract_model.py",
                  "test_workflows.py", "test_consult.py",
                  "test_prospective.py", "test_routines.py", "test_wake.py",
                  "test_research.py",
                  "test_course.py", "test_exam.py", "test_verify.py",
                  "test_inbox.py", "test_material.py", "test_url.py",
                  "test_curriculum.py",
                  "test_e2e.py",
                  "test_research_discovery.py"],
        "blind": "schedules are tested with tiny intervals inside one run. "
                 "Nothing here proves a month of unattended drift, clock "
                 "changes across daylight saving, or a real cron environment.",
    },
    "4. Memory institution": {
        "what": "courses and atoms, skills graph, commons, failures, gotchas, "
                "premise, competence, recall, sources, conflicts, standards, "
                "self-model",
        "tests": ["test_knowledge.py",
                  "test_memory.py", "test_memcheck.py", "test_skills.py",
                  "test_skillgraph.py", "test_skillmd.py", "test_recall.py",
                  "test_associative.py", "test_memory_kinds.py",
                  "test_conflicts.py", "test_freshness.py",
                  "test_awareness.py", "test_audit.py",
                  "test_cases.py", "test_gotcha_retire.py", "test_discover.py",
                  "test_sources.py",
                  "test_reflector.py",
                  "test_memory_hybrid.py", "test_memory_policy.py", "test_memory_benchmarks.py", "test_skill_attribution.py"],
        "blind": "conflict detection is text-based and conservative by "
                 "design: it finds polarity flips and numeric disagreements "
                 "between claims about the same subject, and has no semantic "
                 "model of any domain. Contradictions phrased outside those "
                 "rules are missed, and no test can enumerate what is missed. "
                 "Gotcha retirement has its own limit, in the other "
                 "direction: a probe names the COMMAND (plus its subcommand "
                 "for a generic runner like git or python), not the "
                 "arguments. So a failure that depends on the input — pandoc "
                 "handling .docx but choking on .odt — is retired by a "
                 "success on a different file, and the warning is withdrawn "
                 "while still true for the case that mattered. It comes back "
                 "the next time it bites, marked UNRETIRED, but it is "
                 "withdrawn in between. Narrowing the probe to the full "
                 "argument list would trade this for the opposite failure: "
                 "almost nothing would ever match, and gotchas would "
                 "accumulate forever again.",
    },
    "5. Improvement & governance": {
        "what": "charter variants with predictions, approvals, replay, "
                "benchmark, promotion gates, the design gate",
        "tests": ["test_variants.py", "test_decisions.py", "test_approvals.py",
                  "test_replay.py", "test_benchmark.py", "test_governance.py",
                  "test_design.py", "test_modelrouter.py",
                  "test_procedural_learning.py", "test_scheduler_verifier.py",
                  "test_advanced_learning.py", "test_tabular.py",
                  "test_operator_runtime.py", "test_verifier_factory.py",
                  "test_procedure_v2.py", "test_capability_signatures.py",
                  "test_git_operators.py", "test_xlsx_operators.py",
                  "test_transactional_contracts.py",
                  "test_correctness_patch.py"],
        "blind": "promotion and routing decisions are proven against seeded "
                 "outcome ledgers, not against months of real measured "
                 "performance. The design gate checks mechanics and the known "
                 "fingerprints of generated filler; it cannot judge beauty.",
    },
    "6. Control plane & interop": {
        "what": "panel, live events, cards, chief, doctor, preflight, backup, "
                "providers, MCP, A2A federation, traces",
        "tests": ["test_ui.py", "test_csrf.py", "test_frontend.py",
                  "test_package.py", "test_panel_v2.py",
                  "test_events.py", "test_uicards.py", "test_remote.py",
                  "test_chief.py", "test_doctor.py", "test_mcp.py",
                  "test_federation.py", "test_providers.py", "test_check.py",
                  "test_trace.py", "test_bootstrap.py", "test_backup.py",
                  "test_preflight.py", "test_ecosystem.py",
                  "test_mcp_hardening.py", "test_ui_auth_hardening.py",
                  "test_ledger_defects.py"],
        "blind": "the panel is driven through its HTTP API and its HTML is "
                 "parsed, but no test renders it in a browser. Layout, "
                 "contrast and touch targets are verified by eye, not by CI.",
    },
    "7. The six authorities": {
        "what": "one mandatory gateway per kind of power — execution, file, "
                "credential, model gateway, effect, control plane — plus the "
                "invariant tests that enumerate every caller of each",
        "tests": ["test_invariants.py", "test_promotion_leakage.py",
                  "test_controlplane.py",
                  "test_execution_containment.py"],
        "blind": "these tests enumerate every path in THIS tree. They cannot "
                 "see a path added by a plugin, an MCP server or a future "
                 "module that does not exist yet — which is why the execution "
                 "audit is a source scan rather than a runtime check, and why "
                 "it fails on a new raw subprocess call rather than warning. "
                 "The Control Plane Authority carries a second, sharper "
                 "limit, stated in its own module: on `sandbox = \"host\"` it "
                 "DETECTS AND REVERTS rather than prevents, because there is "
                 "no filesystem boundary on that backend to prevent with. "
                 "Prevention needs `sandbox = \"docker\"`, where the control "
                 "paths are bound read-only and the boundary is the "
                 "kernel's.",
    },
    "8. Proof, missions and long-horizon work": {
        "what": "capability proof levels derived from hash-bound evidence; "
                "the mission contract that survives context resets, restarts "
                "and model swaps",
        "tests": ["test_proof.py", "test_mission.py", "test_metrics.py",
                  "test_evalsuite.py",
                  "test_measurement_integrity.py"],
        "blind": "no mission here has run longer than a test. The contract is "
                 "proven to survive a simulated reset, not a week of real "
                 "drift, and no capability has ever been observed above level "
                 "2 because that needs a real provider. Three of the manual's "
                 "twelve metrics cannot be computed at all — supervision "
                 "hours, 90-day retention, and anything that would need a "
                 "real workload — and `metrics.py` names them rather than "
                 "approximating them.",
    },
    "9. Computers, capability and organization": {
        "what": "where work runs and why that computer was chosen; how a "
                "capability is acquired without gaining authority; who may do "
                "what, and the trail that records it",
        "tests": ["test_workers.py", "test_acquire.py", "test_org.py",
                  "test_rbac.py", "test_frontier.py", "test_frontier_live.py",
                  "test_acquisition_arena.py", "test_capability_graph.py"],
        "blind": "every worker is a RECORD. Nothing here has started a "
                 "container, installed a package, or measured a real start-up "
                 "time — the acquisition ladder is proven to refuse correctly, "
                 "not to install correctly. And `test_rbac.py` proves "
                 "AUTHORISATION given an identity; the identity itself is a "
                 "bearer token over plain HTTP with no TLS, session or expiry. "
                 "The capability frontier is proved WITHOUT a real install: "
                 "no registry was queried, no package fetched and no hosted "
                 "rail called, so what is proven here is that it refuses, "
                 "seals and reports correctly — not that an acquisition "
                 "completes.",
    },
    "10. Training lab": {
        "what": "sanitised trajectory export, a deterministic non-overlapping "
                "split, an immutable verifier, a promotion threshold and a "
                "mandatory rollback target",
        "tests": ["test_training.py"],
        "blind": "this module performs no gradient updates at all, and says "
                 "so on every export. What is proven is the governance around "
                 "a training run — nothing here has trained anything, and no "
                 "reward-hacking suite exists.",
    },
    "12. The paths that touch something real": {
        "what": "the two code paths that had never been executed by anything "
                "— the live provider HTTP client, and the docker sandbox — "
                "each driven against a real server and a real container",
        "tests": ["test_live_provider.py", "test_docker_live.py",
                  "test_hosted_sandbox.py", "test_first_day.py",
                  "test_endurance.py",
                  "test_release_checks.py"],
        "blind": "the provider tests run against a LOOPBACK SERVER that "
                 "implements the documented OpenAI-compatible shape. They "
                 "prove this platform's HTTP client is correct against that "
                 "shape; they prove nothing about how any real provider "
                 "behaves, and a provider that deviates will still surprise "
                 "us. `python loop.py check` remains the only live probe. "
                 "The docker tests DO start real containers, but on one "
                 "machine, one image and one daemon version — not on the "
                 "hosted backends (E2B, Daytona), whose CLIENT is verified "
                 "against the documented shape while the services themselves "
                 "have never been contacted. The endurance soak drives real "
                 "tasks for minutes, which rules out growth that is O(total "
                 "work) and cannot rule out a leak that needs days.",
    },
    "11. The interface itself": {
        "what": "the UI/UX specification's own acceptance table: that each "
                "flow's information is reachable, that the migration moved "
                "views rather than deleting them, and that no proof level can "
                "be set by hand",
        "tests": ["test_ux.py"],
        "blind": "this proves REACHABILITY, not usability. The spec asks for "
                 "five people completing five flows at 90%; that has not "
                 "happened and nothing in a repository can stand in for it. "
                 "The mobile assertions read CSS source, not rendered layout — "
                 "the two defects they cover were found in a real browser at "
                 "375 px, which no test here runs.",
    },
    "13. The universal agent": {
        "what": "the layer that decides which of these systems a goal needs "
                "before any work starts: that the readiness verdict is EARNED "
                "from mechanical probes rather than asserted, that knowledge "
                "from a weak source does not count as knowledge, that an "
                "AUTHORITY gap stops the run before goal.pursue is ever "
                "reached, that a dry run writes nothing, and that every gap "
                "is classified by the platform's own gap router rather than "
                "by a second opinion",
        "tests": ["test_universal.py", "test_grants.py",
                  "test_experience.py"],
        "blind": "it reads the goal's WORDS to infer what will be needed, so "
                 "a goal that requires a PDF reader without saying anything "
                 "PDF-shaped is not detected — the inference is a keyword "
                 "table, deliberately inspectable rather than a model's "
                 "guess, and it is better at over-asking than under-asking. "
                 "It also decides readiness from what is on disk NOW: an "
                 "expert can be READY and still fail, because ready means "
                 "'nothing known is missing', never 'this will succeed'.",
    },
}
GLOBAL_CAVEAT = (
    "Every model call in every test is the scripted mock provider. A green "
    "suite proves the harness holds; it never proves that any real provider "
    "works. `python loop.py check` is the only live probe."
)


def registered_tests():
    try:
        import ast
        src = open(os.path.join(HERE, "tests", "run_all.py"),
                   encoding="utf-8").read()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Assign) and \
                    getattr(node.targets[0], "id", "") == "TESTS":
                return [el.value for el in node.value.elts]
    except Exception:
        pass
    return []


def run_suite(capture_path=None):
    """Run each registered test as its own captured process.

    Deliberately NOT `run_all.py` under one pipe: a parent's prints and its
    children's are buffered independently, so the `=== test ===` headers can
    flush long after the output they label and every observation is attributed
    to the wrong test (or to none). Running them here means attribution is by
    construction, and a crashed test still gets its own section.
    """
    tests = registered_tests()
    parts, failed = [], 0
    tdir = os.path.join(HERE, "tests")
    for name in tests:
        parts.append(f"=== {name} ===")
        # UTF-8 IN THE CHILDREN, EXPLICITLY.
        #
        # `text=True` alone decodes with the locale encoding, which on Windows
        # is cp1252 — and the child, seeing a pipe, ENCODES with cp1252 too.
        # The two cancel out for characters cp1252 happens to have (the
        # em-dashes these tests are full of) and lose everything else: a test
        # printing an arrow or a non-Latin name would either mangle it or die
        # of UnicodeEncodeError while its assertions were all passing. Pinning
        # both ends to UTF-8 makes the round-trip lossless whatever a test
        # prints, on every platform.
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        r = subprocess.run([sys.executable, os.path.join(tdir, name)],
                           capture_output=True, text=True, cwd=tdir,
                           encoding="utf-8", errors="replace", env=env)
        parts.append((r.stdout or "") + (r.stderr or ""))
        if r.returncode != 0:
            failed += 1
            parts.append(f"[FAILED] exit {r.returncode}")
        print(f"  {'ok  ' if r.returncode == 0 else 'FAIL'} {name}", flush=True)
    out = "\n".join(parts)
    if capture_path:
        with open(capture_path, "w", encoding="utf-8") as f:
            f.write(out)
    return out, failed


FAILED_LINE_RE = re.compile(r"^FAILED: (test_\w+\.py)\b")
RUNALL_TAIL_RE = re.compile(r"^\d+ executed: \d+ passed, \d+ skipped, "
                            r"(\d+) failed")


def parse(output):
    """-> {test file: {"sections": [...], "passed": bool}}

    A `--from` log produced by run_all.py under ONE pipe is exactly the
    shape run_suite()'s docstring warns about: the parent's `=== test ===`
    headers and each child's stdout/stderr flush independently, so a
    passing test's own OK line can land under the NEXT header, leaving its
    section empty. Parsed naively, that reported a green test as FAILING —
    the inverse of the UNITTEST_OK_RE bug, and just as corrosive: a report
    that can cry wolf teaches its reader to ignore wolves.

    run_all's tail is authoritative — it counts EXIT CODES and names every
    failed file in a `FAILED: <name>` line. So when that tail is present,
    a test with no recognized pass marker and no skip is failed ONLY if
    the tail names it; otherwise its verdict is the exit code's (passed)
    and only its observations are lost to the interleaving, which the
    report can afford — verdicts cannot."""
    per, current = {}, None
    named_failed, tail_seen = set(), False
    for line in output.splitlines():
        line = line.strip()
        m = TEST_RE.match(line)
        if m:
            current = m.group(1)
            per.setdefault(current, {"sections": [], "passed": False,
                                     "skipped": None})
            continue
        m = FAILED_LINE_RE.match(line)
        if m:
            named_failed.add(m.group(1))
            continue
        if RUNALL_TAIL_RE.match(line):
            tail_seen = True
            continue
        if current is None:
            continue
        m = SECTION_RE.match(line)
        if m:
            per[current]["sections"].append((m.group(1), m.group(2).strip()))
            continue
        if PASS_RE.match(line) or UNITTEST_OK_RE.match(line):
            per[current]["passed"] = True
            continue
        m = SKIP_RE.match(line)
        if m:
            per[current]["skipped"] = m.group(2).strip() or "no reason given"
    if tail_seen:
        for name, rec in per.items():
            if not rec["passed"] and not rec["skipped"] \
                    and name not in named_failed:
                rec["passed"] = True
        # the authority cuts BOTH ways: a test the tail names failed is
        # failed, however green a stray PASS line inside its section looks
        # (a test can print PASS and then die in teardown — the exit code
        # saw it, the prose did not)
        for name in named_failed:
            if name in per:
                per[name]["passed"] = False
                per[name]["skipped"] = None
    return per


def build(output):
    per = parse(output)
    registered = registered_tests()
    mapped = {t for s in SYSTEMS.values() for t in s["tests"]}
    unclassified = [t for t in registered if t not in mapped]
    missing = [t for t in mapped if registered and t not in registered]

    systems = []
    for name, spec in SYSTEMS.items():
        tests = [t for t in spec["tests"] if t in per]
        ran = [t for t in tests if per[t]["passed"]]
        skipped = [(t, per[t]["skipped"]) for t in tests
                   if not per[t]["passed"] and per[t]["skipped"]]
        failed = [t for t in tests
                  if not per[t]["passed"] and not per[t]["skipped"]]
        sections = [(t, k, s) for t in ran for k, s in per[t]["sections"]]
        if not tests or not ran:
            verdict = "UNPROVEN"
        elif failed:
            verdict = "FAILING"
        elif skipped:
            # NOT "proven": a test that declined to run proved nothing, and
            # the reader is entitled to know which claim is unbacked here.
            verdict = "proven except skipped"
        elif len(ran) < len(spec["tests"]):
            verdict = "partly proven"
        else:
            verdict = "proven"
        systems.append({
            "system": name, "what": spec["what"], "verdict": verdict,
            "tests_declared": len(spec["tests"]), "tests_ran": len(ran),
            "tests_failed": failed, "tests_skipped": skipped,
            "observations": len(sections),
            "evidence": sections, "blind_spot": spec["blind"],
        })
    return {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tests_seen": len(per),
        "tests_passed": sum(1 for v in per.values() if v["passed"]),
        "observations": sum(len(v["sections"]) for v in per.values()),
        "unclassified_tests": unclassified,
        "declared_but_unregistered": missing,
        "systems": systems, "caveat": GLOBAL_CAVEAT,
    }


def render(rep):
    L = ["# Evidence — why we believe this works", "",
         f"Generated {rep['at']} from an actual suite run: "
         f"**{rep['tests_passed']}/{rep['tests_seen']} tests passed**, "
         f"**{rep['observations']} observations** recorded.", "",
         "Each test below prints its own sentence describing what it proved; "
         "those sentences are quoted verbatim, not summarised. Every system "
         "also carries a **blind spot** — what these tests do not cover.", "",
         f"> {rep['caveat']}", ""]
    if rep["unclassified_tests"]:
        L += ["## Coverage drift", "",
              "These registered tests are not assigned to any system, so their "
              "evidence is not counted anywhere. Classify them in "
              "`evidence.py`:", ""]
        L += [f"- `{t}`" for t in rep["unclassified_tests"]] + [""]
    if rep["declared_but_unregistered"]:
        L += ["These are claimed as evidence but are not in the suite:", ""]
        L += [f"- `{t}`" for t in rep["declared_but_unregistered"]] + [""]
    L += ["## Verdict by system", "",
          "| system | verdict | tests | observations |", "|---|---|---|---|"]
    for s in rep["systems"]:
        L.append(f"| {s['system']} | **{s['verdict']}** | "
                 f"{s['tests_ran']}/{s['tests_declared']} | {s['observations']} |")
    L.append("")
    for s in rep["systems"]:
        L += [f"## {s['system']}", "", f"*{s['what']}*", "",
              f"**Verdict: {s['verdict']}** — {s['tests_ran']} of "
              f"{s['tests_declared']} declared tests ran and passed, "
              f"producing {s['observations']} observations."]
        if s["tests_failed"]:
            L.append(f"**FAILING:** {', '.join(s['tests_failed'])}")
        for t, why in s.get("tests_skipped") or []:
            L.append(f"**NOT RUN HERE — {t}:** {why}")
        L += ["", "<details><summary>What the tests observed "
              f"({s['observations']})</summary>", ""]
        for t, kind, sentence in s["evidence"]:
            L.append(f"- `{t}` **[{kind}]** {sentence}")
        L += ["", "</details>", "",
              f"**Blind spot.** {s['blind_spot']}", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", help="parse a captured suite run")
    ap.add_argument("--out", default=os.path.join(HERE, "EVIDENCE.md"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.src:
        # A captured run is whatever the capturing shell wrote. On Windows a
        # plain `python tests/run_all.py > run.txt` writes cp1252, and reading
        # that as UTF-8 with errors="replace" silently turned every em-dash
        # into U+FFFD — 84 of them in one artifact, in the sentences this
        # document exists to quote VERBATIM. Replacement characters are the
        # failure mode that looks like a font problem and is actually lost
        # evidence, so decode strictly and fall back rather than guess:
        # a cp1252 byte like 0x97 is not valid UTF-8, which makes the choice
        # deterministic rather than a heuristic.
        # Deliberately NOT falling back to latin-1: it never raises, so it
        # would win every contest and decode a Windows em-dash (0x97) into a
        # C1 control character instead — silently, and looking like success.
        # A captured Windows run is cp1252, and the residue after that is a
        # genuinely mixed file (a test that re-emits a subprocess's already
        # decoded output can double-encode a few bytes), which no single codec
        # can read. Those get U+FFFD and nothing else does.
        raw = open(a.src, "rb").read()
        for enc in ("utf-8", locale.getpreferredencoding(False), "cp1252"):
            try:
                output = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            output = raw.decode("cp1252", errors="replace")
        code = 0
    else:
        print("running the suite (this takes a few minutes)...", flush=True)
        output, code = run_suite()
    rep = build(output)
    if a.json:
        print(json.dumps(rep, indent=1))
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(render(rep))
        print(f"{a.out}\n  {rep['tests_passed']}/{rep['tests_seen']} tests, "
              f"{rep['observations']} observations")
        for s in rep["systems"]:
            print(f"  {s['verdict']:<14} {s['system']}")
        if rep["unclassified_tests"]:
            print(f"  UNCLASSIFIED: {', '.join(rep['unclassified_tests'])}")
    bad = (code != 0 or rep["unclassified_tests"]
           or any(s["verdict"] in ("UNPROVEN", "FAILING") for s in rep["systems"]))
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
