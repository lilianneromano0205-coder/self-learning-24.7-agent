#!/usr/bin/env python3
"""Run every offline acceptance test. One command: python tests/run_all.py"""

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = ["test_resume.py", "test_lock.py", "test_json_toolcall.py",
         "test_reflector.py", "test_compaction.py", "test_verify.py",
         "test_inbox.py", "test_skills.py", "test_course.py",
         "test_memcheck.py", "test_e2e.py", "test_retry.py",
         "test_blocked.py", "test_exam.py", "test_paths.py",
         "test_reliability.py", "test_check.py", "test_e2e_crash.py",
         "test_local.py", "test_live_provider.py", "test_guardrails.py", "test_url.py",
         "test_hardening.py", "test_csrf.py", "test_invariants.py",
         "test_controlplane.py",
         "test_proof.py", "test_mission.py",
         "test_workers.py", "test_acquire.py",
         "test_org.py", "test_rbac.py", "test_training.py", "test_metrics.py",
         "test_fleet.py", "test_ui.py", "test_remote.py", "test_material.py",
         "test_frontend.py", "test_ux.py", "test_layers.py", "test_team.py", "test_audit.py",
         "test_recall.py", "test_consult.py", "test_quick.py",
         "test_toolbox.py", "test_doctor.py", "test_goal.py",
         "test_universal.py",
         "test_grants.py",
         "test_experience.py",
         "test_shutdown.py",
         "test_evalsuite.py",
         "test_knowledge.py",
         "test_providers.py", "test_federation.py", "test_retention.py",
         "test_memory.py", "test_benchmark.py", "test_skillgraph.py",
         "test_prospective.py", "test_associative.py", "test_variants.py",
         "test_chief.py", "test_ecosystem.py", "test_mcp.py", "test_effects.py",
         "test_replay.py", "test_lanes.py", "test_approvals.py",
         "test_workflows.py", "test_governance.py", "test_harness.py",
         "test_faults.py", "test_stop.py", "test_checkpoint.py",
         "test_wake.py", "test_context.py", "test_memory_kinds.py",
         "test_sandbox.py", "test_docker_live.py", "test_hosted_sandbox.py", "test_skillmd.py", "test_decisions.py",
         "test_modelrouter.py", "test_routines.py", "test_trace.py",
         "test_events.py", "test_uicards.py", "test_panel_v2.py",
         "test_bootstrap.py", "test_first_day.py", "test_secrets.py", "test_conflicts.py",
         "test_awareness.py", "test_design.py", "test_backup.py", "test_package.py",
         "test_preflight.py", "test_chaos.py", "test_endurance.py", "test_candidates.py",
         "test_curriculum.py", "test_research.py", "test_cases.py",
         "test_gotcha_retire.py", "test_discover.py", "test_contract.py",
         "test_runbook.py", "test_repair.py", "test_swarm.py",
         "test_sources.py", "test_mastery.py", "test_steer.py",
         "test_freshness.py", "test_contract_model.py",
         "test_subquery.py", "test_frontier.py", "test_frontier_live.py",
         "test_execution_containment.py", "test_acquisition_arena.py",
         "test_mcp_hardening.py", "test_ui_auth_hardening.py",
         "test_measurement_integrity.py", "test_procedural_learning.py",
         "test_scheduler_verifier.py", "test_memory_hybrid.py",
         "test_memory_benchmarks.py", "test_memory_policy.py",
         "test_skill_attribution.py", "test_advanced_learning.py",
         "test_research_discovery.py", "test_release_checks.py",
         "test_loop_learning_controls.py", "test_capability_graph.py",
         "test_use_cases.py", "test_tabular.py",
         "test_vision_preservation.py", "test_operator_runtime.py",
         "test_verifier_factory.py", "test_procedure_v2.py",
         "test_capability_signatures.py"]


def main():
    # EXPLICIT COUNTS, NEVER ONE GREEN PHRASE. This used to end "ALL TESTS
    # PASSED", which the audit called out precisely: test_shutdown SKIPS on
    # Windows (there is no SIGTERM to catch), so "all passed" was read as
    # "every test file ran", which was false. A skip is a third outcome —
    # not a failure, not a proof — and compressing the three into one word
    # is how a gap hides inside a green line. evidence.py already learned
    # this lesson; the runner now says the same numbers.
    failed, skipped = [], []
    for t in TESTS:
        # flush: to a pipe this print is block-buffered, so without it the
        # header can land long after the test output it labels
        print(f"\n=== {t} ===", flush=True)
        # UTF-8 pinned at BOTH ends, the lesson evidence.py already paid
        # for: a child that sees a pipe encodes with the locale (cp1252 on
        # Windows) while this side decodes utf-8, and every em-dash a test
        # prints becomes U+FFFD in the relayed output.
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        r = subprocess.run([sys.executable, os.path.join(HERE, t)], cwd=HERE,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        sys.stdout.write(r.stdout or "")
        sys.stderr.write(r.stderr or "")
        sys.stdout.flush()
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            failed.append(t)
        elif re.search(rf"^SKIP\s+{re.escape(t[:-3])}\b", out, re.M):
            skipped.append(t)
    passed = len(TESTS) - len(failed) - len(skipped)
    print(f"\n{len(TESTS)} executed: {passed} passed, "
          f"{len(skipped)} skipped, {len(failed)} failed"
          + (f"  [skipped: {', '.join(skipped)}]" if skipped else ""))
    if failed:
        print("FAILED: " + ", ".join(failed))
    elif not skipped:
        print("ALL TESTS PASSED")
    else:
        print("ALL EXECUTED TESTS PASSED — the skipped ones proved nothing "
              "here; their reasons are printed above and counted in "
              "EVIDENCE.md")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
