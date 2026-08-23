#!/usr/bin/env python3
"""EVIDENCE — why we believe each system works, and where belief runs out.

"All tests passed" is not a claim about the platform. It is a claim about the
tests. This module turns the first into the second honestly: it runs the
suite, captures what each test SAID it proved (every test prints its own
`[section]` sentences), maps those to the six systems, and writes a report
where each system carries:

    verdict     proven / partly proven / UNPROVEN
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

    python evidence.py                 # run the suite and write EVIDENCE.md
    python evidence.py --from run.log  # use a captured run instead
    python evidence.py --json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SECTION_RE = re.compile(r"^\[([a-z0-9_-]+)\]\s+(.*)$", re.I)
TEST_RE = re.compile(r"^=== (test_\w+\.py) ===$")
PASS_RE = re.compile(r"^PASS (\S+)")

# Which tests speak for which system. Every registered test must appear here.
SYSTEMS = {
    "1. Harness & loop": {
        "what": "the engine: context assembly, five tools, gates, brakes, "
                "retries, escalation, policy, effects, compaction",
        "tests": ["test_harness.py", "test_faults.py", "test_stop.py",
                  "test_checkpoint.py", "test_retry.py", "test_compaction.py",
                  "test_resume.py", "test_lock.py", "test_paths.py",
                  "test_reliability.py", "test_e2e_crash.py", "test_layers.py",
                  "test_json_toolcall.py", "test_guardrails.py",
                  "test_effects.py", "test_sandbox.py",
                  "test_secrets.py", "test_chaos.py", "test_blocked.py",
                  "test_hardening.py",
                  "test_candidates.py",
                  "test_retention.py", "test_context.py"],
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
                "consultation, prospective intentions, routines",
        "tests": ["test_goal.py", "test_workflows.py", "test_consult.py",
                  "test_prospective.py", "test_routines.py", "test_wake.py",
                  "test_research.py",
                  "test_course.py", "test_exam.py", "test_verify.py",
                  "test_inbox.py", "test_material.py", "test_url.py",
                  "test_curriculum.py",
                  "test_e2e.py"],
        "blind": "schedules are tested with tiny intervals inside one run. "
                 "Nothing here proves a month of unattended drift, clock "
                 "changes across daylight saving, or a real cron environment.",
    },
    "4. Memory institution": {
        "what": "courses and atoms, skills graph, commons, failures, gotchas, "
                "premise, competence, recall, sources, conflicts, standards, "
                "self-model",
        "tests": ["test_memory.py", "test_memcheck.py", "test_skills.py",
                  "test_skillgraph.py", "test_skillmd.py", "test_recall.py",
                  "test_associative.py", "test_memory_kinds.py",
                  "test_conflicts.py", "test_awareness.py", "test_audit.py",
                  "test_cases.py",
                  "test_reflector.py"],
        "blind": "conflict detection is text-based and conservative by "
                 "design: it finds polarity flips and numeric disagreements "
                 "between claims about the same subject, and has no semantic "
                 "model of any domain. Contradictions phrased outside those "
                 "rules are missed, and no test can enumerate what is missed.",
    },
    "5. Improvement & governance": {
        "what": "charter variants with predictions, approvals, replay, "
                "benchmark, promotion gates, the design gate",
        "tests": ["test_variants.py", "test_decisions.py", "test_approvals.py",
                  "test_replay.py", "test_benchmark.py", "test_governance.py",
                  "test_design.py", "test_modelrouter.py"],
        "blind": "promotion and routing decisions are proven against seeded "
                 "outcome ledgers, not against months of real measured "
                 "performance. The design gate checks mechanics and the known "
                 "fingerprints of generated filler; it cannot judge beauty.",
    },
    "6. Control plane & interop": {
        "what": "panel, live events, cards, chief, doctor, preflight, backup, "
                "providers, MCP, A2A federation, traces",
        "tests": ["test_ui.py", "test_csrf.py", "test_frontend.py", "test_panel_v2.py",
                  "test_events.py", "test_uicards.py", "test_remote.py",
                  "test_chief.py", "test_doctor.py", "test_mcp.py",
                  "test_federation.py", "test_providers.py", "test_check.py",
                  "test_trace.py", "test_bootstrap.py", "test_backup.py",
                  "test_preflight.py", "test_ecosystem.py"],
        "blind": "the panel is driven through its HTTP API and its HTML is "
                 "parsed, but no test renders it in a browser. Layout, "
                 "contrast and touch targets are verified by eye, not by CI.",
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
        r = subprocess.run([sys.executable, os.path.join(tdir, name)],
                           capture_output=True, text=True, cwd=tdir)
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


def parse(output):
    """-> {test file: {"sections": [...], "passed": bool}}"""
    per, current = {}, None
    for line in output.splitlines():
        line = line.strip()
        m = TEST_RE.match(line)
        if m:
            current = m.group(1)
            per.setdefault(current, {"sections": [], "passed": False})
            continue
        if current is None:
            continue
        m = SECTION_RE.match(line)
        if m:
            per[current]["sections"].append((m.group(1), m.group(2).strip()))
            continue
        if PASS_RE.match(line):
            per[current]["passed"] = True
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
        failed = [t for t in tests if not per[t]["passed"]]
        sections = [(t, k, s) for t in ran for k, s in per[t]["sections"]]
        if not tests:
            verdict = "UNPROVEN"
        elif failed:
            verdict = "FAILING"
        elif len(ran) < len(spec["tests"]):
            verdict = "partly proven"
        else:
            verdict = "proven"
        systems.append({
            "system": name, "what": spec["what"], "verdict": verdict,
            "tests_declared": len(spec["tests"]), "tests_ran": len(ran),
            "tests_failed": failed, "observations": len(sections),
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
        with open(a.src, encoding="utf-8", errors="replace") as f:
            output = f.read()
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
