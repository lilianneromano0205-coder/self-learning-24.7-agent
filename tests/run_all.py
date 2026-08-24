#!/usr/bin/env python3
"""Run every offline acceptance test. One command: python tests/run_all.py"""

import os
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
         "test_proof.py", "test_mission.py",
         "test_workers.py", "test_acquire.py",
         "test_org.py", "test_rbac.py", "test_training.py", "test_metrics.py",
         "test_fleet.py", "test_ui.py", "test_remote.py", "test_material.py",
         "test_frontend.py", "test_ux.py", "test_layers.py", "test_team.py", "test_audit.py",
         "test_recall.py", "test_consult.py", "test_quick.py",
         "test_toolbox.py", "test_doctor.py", "test_goal.py",
         "test_universal.py",
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
         "test_curriculum.py", "test_research.py", "test_cases.py"]


def main():
    failed = []
    for t in TESTS:
        # flush: to a pipe this print is block-buffered, so without it the
        # header can land long after the test output it labels
        print(f"\n=== {t} ===", flush=True)
        r = subprocess.run([sys.executable, os.path.join(HERE, t)], cwd=HERE)
        if r.returncode != 0:
            failed.append(t)
    print("\n" + ("FAILED: " + ", ".join(failed) if failed else "ALL TESTS PASSED"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
