#!/usr/bin/env python3
"""The capability graph and the amortization metric.

Both are DERIVED views: they must report what the ledgers say, refuse to
invent trust, and stay honest when a ledger is missing or a cost was never
metered. The tests below are written to fail if any of those slip.
"""
import json
import os
from pathlib import Path
import sys
import unittest

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import capability_graph as cg
import fleet
import metrics
import runbook
import skills


def _write(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    Path(p).write_text(text, encoding="utf-8")
    return p


def _state(root, tasks):
    _write(root, "state.json", json.dumps({"tasks": tasks}))


class CapabilityGraphTests(unittest.TestCase):
    def sandbox(self, name):
        return make_sandbox(name, providers={"m": {"script": "s.json"}},
                            roles={"tester": "m"}, scripts={"s.json": []})

    def test_a_missing_ledger_yields_a_partial_map_not_a_crash(self):
        root = self.sandbox("cg-partial")
        # a runbook directory holding something unreadable
        _write(root, "runbooks/broken.json", "{not json")
        graph = cg.build(root)
        self.assertIsInstance(graph["nodes"], dict)
        self.assertIsInstance(graph["partial"], list)
        # the tool scan always contributes, so the map is never empty
        self.assertTrue(graph["counts"]["tool"] >= 1, graph["counts"])

    def test_the_graph_reports_trust_it_never_grants_it(self):
        root = self.sandbox("cg-trust")
        rb = {"name": "p1", "triggers": ["invoice"], "procedure_version": 1,
              "steps": [{"id": "s1", "depends_on": [], "kind": "deterministic",
                         "action": {"tool": "write_file",
                                    "args": {"path": {"input": "path"},
                                             "content": "x"}},
                         "preconditions": [], "effects": [
                             {"predicate": "file_exists",
                              "path": {"input": "path"}}]}],
              "operator": {"inputs": {"path": "path"}, "preconditions": [],
                           "effects": [], "invariants": [], "cost_usd": 0.0,
                           "cost_basis": "t", "latency_seconds": 0.0,
                           "reversibility": "conditional",
                           "authority": ["workspace-write"],
                           "reliability": {"source": "t"}},
              "provenance": {"compiled": True, "trajectory_ids": [],
                             "input_hashes": [], "family": "invoice",
                             "alignment": "t"}}
        _write(root, "runbooks/p1.json", json.dumps(rb))
        # NO trust entry at all -> the ledger's answer is 'candidate'
        graph = cg.build(root)
        self.assertEqual(graph["nodes"]["procedure:p1"]["attrs"]["status"],
                         "candidate")
        support = cg.support_for(root, "handle the invoice", graph)
        self.assertEqual(support["strategy"], "supervised_procedure")
        self.assertIn("CANDIDATE", support["why"])

    def test_a_proven_compiled_procedure_makes_the_strategy_deterministic(self):
        root = self.sandbox("cg-proven")
        rb = {"name": "p2", "triggers": ["invoice"], "procedure_version": 1,
              "steps": [{"id": "s1", "depends_on": [], "kind": "deterministic",
                         "action": {"tool": "write_file",
                                    "args": {"path": {"input": "path"},
                                             "content": "x"}},
                         "preconditions": [], "effects": [
                             {"predicate": "file_exists",
                              "path": {"input": "path"}}]}],
              "operator": {"inputs": {"path": "path"}, "preconditions": [],
                           "effects": [], "invariants": [], "cost_usd": 0.0,
                           "cost_basis": "t", "latency_seconds": 0.0,
                           "reversibility": "conditional",
                           "authority": ["workspace-write"],
                           "reliability": {"source": "t"}},
              "provenance": {"compiled": True, "trajectory_ids": [],
                             "input_hashes": [], "family": "invoice",
                             "alignment": "t"}}
        _write(root, "runbooks/p2.json", json.dumps(rb))
        import procedure
        _write(root, "runbooks/trust.json", json.dumps({"p2": {
            "status": "proven", "wins": 3, "accepted_wins": 3, "losses": 0,
            "streak_losses": 0, "history": [],
            "content_hash": procedure.digest(rb),
            "envelope": {"scope": "observed-inputs-and-environments",
                         "distinct_tasks": 3, "distinct_inputs": 3,
                         "generalization_claim": False, "families": ["invoice"]},
            "reliability": {"accepted": 3, "attempts": 3,
                            "evidence": "observed frequency"}}}))
        graph = cg.build(root)
        node = graph["nodes"]["procedure:p2"]
        self.assertEqual(node["attrs"]["status"], "proven")
        self.assertIs(node["attrs"]["envelope"]["generalization_claim"], False)
        self.assertTrue(any(e["kind"] == "implements" and e["to"] == "family:invoice"
                            for e in graph["edges"]), graph["edges"])
        support = cg.support_for(root, "handle the invoice", graph)
        self.assertEqual(support["strategy"], "deterministic_reuse")
        self.assertEqual(support["proven_procedures"][0]["name"], "p2")

    def test_a_skill_without_ablation_evidence_is_never_reported_causal(self):
        root = self.sandbox("cg-skill")
        _write(root, "skills/audit-thing.md", "KEYWORDS: audit\nsteps\n")
        for i in range(5):
            skills.record_use(root, ["skills/audit-thing.md"], f"t{i}",
                              success=True, verified=True)
        graph = cg.build(root)
        node = graph["nodes"]["skill:audit-thing"]
        self.assertEqual(node["attrs"]["status"], "candidate")
        self.assertIs(node["attrs"]["causal"], False)
        self.assertEqual(node["attrs"]["evidence_basis"], "cooccurrence")
        g = cg.gaps(root, graph)
        self.assertIn("audit-thing", g["skills_without_causal_evidence"])

    def test_novel_work_is_named_as_novel(self):
        root = self.sandbox("cg-novel")
        support = cg.support_for(root, "something nothing here has ever done")
        self.assertEqual(support["strategy"], "novel_reasoning")
        self.assertEqual(support["proven_procedures"], [])

    def test_gaps_names_families_with_no_procedure(self):
        root = self.sandbox("cg-gaps")
        _state(root, [
            {"id": "a", "status": "done", "done_check": "x", "family": "billing",
             "steps": [{}, {}], "cost_usd": 0, "created": "2026-01-01T00:00:00"},
            {"id": "b", "status": "failed", "done_check": "x", "family": "billing",
             "steps": [{}], "cost_usd": 0, "created": "2026-01-02T00:00:00"},
        ])
        g = cg.gaps(root)
        self.assertIn("billing", g["families_without_a_procedure"])


class PlannerSeesItsOwnCompetenceTests(unittest.TestCase):
    """A map nothing consults is a map nobody drew. The planner must
    actually receive it — as a file on disk AND in the plan task's context."""

    def test_pursue_writes_competence_and_puts_it_in_the_plan_context(self):
        import goal as goalmod
        home = make_sandbox("cg-planner", providers={"m": {"script": "s.json"}},
                            roles={"tester": "m"}, scripts={"s.json": []})
        root = fleet.create(home, "Planner", "plans with what it has")
        # a proven compiled procedure this goal's words fire
        rb = {"name": "make-invoice", "triggers": ["invoice"],
              "procedure_version": 1,
              "steps": [{"id": "s1", "depends_on": [], "kind": "deterministic",
                         "action": {"tool": "write_file",
                                    "args": {"path": {"input": "path"},
                                             "content": "x"}},
                         "preconditions": [], "effects": [
                             {"predicate": "file_exists",
                              "path": {"input": "path"}}]}],
              "operator": {"inputs": {"path": "path"}, "preconditions": [],
                           "effects": [], "invariants": [], "cost_usd": 0.0,
                           "cost_basis": "t", "latency_seconds": 0.0,
                           "reversibility": "conditional",
                           "authority": ["workspace-write"],
                           "reliability": {"source": "t"}},
              "provenance": {"compiled": True, "trajectory_ids": [],
                             "input_hashes": [], "family": "invoice",
                             "alignment": "t"}}
        import procedure
        _write(root, "runbooks/make-invoice.json", json.dumps(rb))
        _write(root, "runbooks/trust.json", json.dumps({"make-invoice": {
            "status": "proven", "wins": 3, "accepted_wins": 3, "losses": 0,
            "streak_losses": 0, "history": [],
            "content_hash": procedure.digest(rb)}}))

        gid = "g-competence"
        try:
            goalmod.pursue(home, "planner", "produce the invoice", cycles=1,
                           gid=gid, timeout=20)
        except SystemExit:
            pass                       # the rigged provider never finishes
        note = os.path.join(root, "goals", gid, "competence.md")
        self.assertTrue(os.path.exists(note),
                        "the planner was given no competence map at all")
        text = Path(note).read_text(encoding="utf-8")
        self.assertIn("deterministic_reuse", text)
        self.assertIn("make-invoice", text)
        self.assertIn("not a prediction", text)
        # and it reached the PLAN task's context, not just the disk
        with open(os.path.join(root, "state.json"), encoding="utf-8") as f:
            tasks = json.load(f)["tasks"]
        plan = next((t for t in tasks if "PLAN" in (t.get("goal") or "")), None)
        self.assertIsNotNone(plan, "no plan task was queued")
        self.assertIn(f"goals/{gid}/competence.md", plan.get("memory_files") or [],
                      plan.get("memory_files"))


class AmortizationTests(unittest.TestCase):
    def _home(self, name, tasks):
        home = make_sandbox(name, providers={"m": {"script": "s.json"}},
                            roles={"tester": "m"}, scripts={"s.json": []})
        root = fleet.create(home, "Learner", "gets cheaper")
        _state(root, tasks)
        return home

    @staticmethod
    def _task(i, family, steps, status="done", cost=0.0, routed=None):
        t = {"id": f"t{i:03d}", "status": status, "done_check": "gate",
             "family": family, "cost_usd": cost,
             "created": f"2026-01-{i + 1:02d}T00:00:00",
             "steps": [{"tool": "x"} for _ in range(steps)]}
        if routed:
            t["procedure_routed"] = routed
        return t

    def test_it_measures_a_real_decline_in_model_steps(self):
        # six verified successes: the later three are cheaper
        tasks = [self._task(i, "reports", 6) for i in range(3)] + \
                [self._task(i + 3, "reports", 2) for i in range(3)]
        rep = metrics.amortization(self._home("amort-decline", tasks))
        self.assertTrue(rep["enough"], rep)
        self.assertEqual(rep["value"], 3.0, rep)
        fam = [f for f in rep["families"] if f["family"] == "reports"][0]
        self.assertTrue(fam["cheaper"])
        self.assertEqual(fam["early_steps"], 6.0)
        self.assertEqual(fam["later_steps"], 2.0)

    def test_an_unmetered_fleet_reports_cost_as_unmeasured_never_zero(self):
        tasks = [self._task(i, "reports", 4) for i in range(6)]
        rep = metrics.amortization(self._home("amort-unmetered", tasks))
        self.assertIsNone(rep["spend_measured"])
        self.assertIn("NOT MEASURED", rep["spend_note"])
        fam = [f for f in rep["families"] if f["family"] == "reports"][0]
        self.assertNotIn("cost_ratio", fam)

    def test_one_anecdote_is_not_a_trend(self):
        tasks = [self._task(0, "reports", 9), self._task(1, "reports", 1)]
        rep = metrics.amortization(self._home("amort-anecdote", tasks))
        self.assertFalse(rep["enough"], rep)
        self.assertIsNone(rep["value"])
        self.assertFalse(rep["families"][0]["split"])

    def test_failed_and_ungated_work_cannot_look_like_a_saving(self):
        # a family whose later work "got cheap" only by failing fast, plus
        # ungated work that nothing ever judged
        tasks = [self._task(i, "reports", 8) for i in range(3)] + \
                [self._task(i + 3, "reports", 1, status="failed") for i in range(3)]
        tasks.append({"id": "u1", "status": "done", "family": "reports",
                      "steps": [], "cost_usd": 0,
                      "created": "2026-02-01T00:00:00"})     # no done_check
        rep = metrics.amortization(self._home("amort-honest", tasks))
        fam = [f for f in rep["families"] if f["family"] == "reports"][0]
        self.assertEqual(fam["verified"], 3, "only gated PASSES may count")
        self.assertFalse(fam["split"])

    def test_deterministic_routes_are_reported_separately(self):
        tasks = [self._task(i, "reports", 5) for i in range(3)] + \
                [self._task(i + 3, "reports", 0, routed="proc-reports")
                 for i in range(3)]
        rep = metrics.amortization(self._home("amort-det", tasks))
        self.assertEqual(rep["deterministic_share"], 0.5)
        self.assertIn("no model step at all", rep["also"])
        fam = [f for f in rep["families"] if f["family"] == "reports"][0]
        # later mean is 0 -> the ratio is unbounded and must NOT be faked
        self.assertIsNone(fam["step_ratio"])
        self.assertIn("unbounded", fam["note"])


if __name__ == "__main__":
    unittest.main()
