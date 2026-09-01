"""Actual file-action compiler, independent graders and generalization regressions."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fileauth
import runbook


class ProceduralLearning(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="procedure-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name
        # Explicitly unsafe disposable host fixture; no provider calls.
        Path(self.root, "settings.toml").write_text(
            '[agent]\nsandbox="host"\nallow_unsafe_host=true\n', encoding="utf-8")

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("procedure"),
                             "missing cross-trajectory procedural compiler")
        import procedure
        return procedure

    def train(self, module, suffix, value):
        inputs = {"destination": f"out/{suffix}.txt", "value": value}
        module.seal_judge(self.root, suffix, [
            {"predicate": "file_equals", "path": inputs["destination"], "value": value}])
        module.begin_trajectory(self.root, suffix, suffix, inputs, family="report")
        module.perform(self.root, suffix, {"tool": "write_file", "args": {
            "path": inputs["destination"], "content": value}})
        self.assertTrue(module.finish_trajectory(self.root, suffix)["accepted"])
        return suffix

    def candidate(self):
        p = self.module()
        ids = [self.train(p, "alpha", "one"), self.train(p, "beta", "two")]
        p.compile(self.root, "report", ids, ["report"])
        return p

    def suite(self, p, name="fresh", bad=False):
        p.seal_suite(self.root, name, {
            "family": "report", "cases": [
                {"id": "ordinary", "inputs": {"destination": "out/new.txt", "value": "three"}},
                {"id": "empty", "edge": True, "inputs": {"destination": "out/empty.txt", "value": ""}},
                {"id": "unicode", "edge": True, "inputs": {"destination": "out/space name.txt", "value": "été 東京"}}],
            "checks": [{"predicate": "file_equals", "path": {"input": "destination"},
                        "value": "WRONG" if bad else {"input": "value"}}]})

    def gate_run(self, module, tid, path, value, gate="check.py out", passed=True):
        """A trajectory captured the way ORDINARY work is: no sealed judge and
        no typed inputs, accepted by the task's own mechanical gate."""
        module.begin_trajectory(self.root, tid, None, None, family="weekly", gate=gate)
        module.perform(self.root, tid, {"tool": "write_file",
                                        "args": {"path": path, "content": value}})
        return module.finish_trajectory(self.root, tid, gate_passed=passed)

    def test_ordinary_gated_work_induces_a_candidate_and_names_what_it_invented(self):
        """The economics only exist if the loop learns from work nobody staged.

        Requiring a sealed judge and typed inputs per task meant nothing from
        the panel, a goal, a mission or a routine was ever captured, so the
        compiler was reachable only from a demo. Gate-captured work now
        compiles — and because such tasks declare no inputs, the compiler has
        to NAME what varied itself.
        """
        p = self.module()
        self.assertTrue(self.gate_run(p, "wk1", "out/r-w1.md", "revenue w1")["accepted"])
        self.assertTrue(self.gate_run(p, "wk2", "out/r-w2.md", "revenue w2")["accepted"])
        rb = p.compile(self.root, "weekly", ["wk1", "wk2"], ["weekly"])
        self.assertEqual(rb["operator"]["inputs"], {"path": "path", "content": "string"})
        self.assertEqual(sorted(rb["provenance"]["inferred_parameters"]),
                         ["content", "path"])
        self.assertEqual(rb["provenance"]["acceptance_basis"], "harness_gate")
        self.assertEqual([s["kind"] for s in rb["steps"]], ["deterministic"])
        # AND IT IS NOT TRUSTED. Automatic induction buys a candidate and
        # nothing else; only a sealed suite of fresh instances can promote.
        self.assertEqual(runbook.status(self.root, "weekly"), "candidate")

    def test_a_failed_gate_and_repeated_identical_work_teach_nothing(self):
        """Two ways for automatic capture to become superstition, both shut.

        A gate that did not pass is not evidence, and the same work repeated
        is one observation however many times it ran — otherwise a routine
        firing nightly would 'prove' itself by monotony.
        """
        p = self.module()
        self.assertFalse(self.gate_run(p, "bad1", "out/x.md", "x", passed=False)["accepted"])
        self.assertFalse(self.gate_run(p, "bad2", "out/y.md", "y", passed=None)["accepted"])
        with self.assertRaises(p.ProcedureError):
            p.compile(self.root, "weekly", ["bad1", "bad2"], ["weekly"])
        self.gate_run(p, "same1", "out/same.md", "identical")
        self.gate_run(p, "same2", "out/same.md", "identical")
        with self.assertRaises(p.ProcedureError) as caught:
            p.compile(self.root, "weekly", ["same1", "same2"], ["weekly"])
        self.assertIn("identical work", str(caught.exception))

    def test_invented_parameters_refuse_values_that_are_not_one_clean_thing(self):
        """Minting is narrow on purpose: it names a variation, never guesses.

        A value that varies but repeats across runs is not explained by one
        argument per run, and mixed types are not one argument at all.
        """
        p = self.module()
        self.gate_run(p, "m1", "out/a.md", "same-content")
        self.gate_run(p, "m2", "out/b.md", "same-content")
        rb = p.compile(self.root, "weekly", ["m1", "m2"], ["weekly"])
        # content did not vary, so it stayed a CONSTANT and only path was named
        self.assertEqual(rb["provenance"]["inferred_parameters"], ["path"])
        self.assertEqual(rb["steps"][0]["action"]["args"]["content"], "same-content")

    def test_compiles_real_actions_infers_inputs_and_executes_fresh_values(self):
        p = self.candidate()
        rb = runbook.load(self.root, "report")
        self.assertEqual(rb["operator"]["inputs"], {"destination": "path", "value": "string"})
        self.assertEqual(rb["steps"][0]["kind"], "deterministic")
        self.assertEqual(runbook.status(self.root, "report"), "candidate")
        self.assertFalse(runbook.run(self.root, "report", inputs={"destination": "out/x", "value": "x"})["ok"])
        result = runbook.run(self.root, "report", allow_candidate=True,
                            inputs={"destination": "out/fresh", "value": "hello"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(Path(self.root, "out/fresh").read_text(), "hello")
        self.assertEqual(runbook.status(self.root, "report"), "candidate")

    def test_rejects_claimed_success_or_unsealed_grader(self):
        p = self.module()
        with self.assertRaises(p.ProcedureError):
            p.begin_trajectory(self.root, "fake", "missing", {})
        with self.assertRaises(p.ProcedureError):
            p.compile(self.root, "fake", [{"accepted": True}, {"accepted": True}], ["fake"])
        p.seal_judge(self.root, "judge", [{"predicate": "file_exists", "path": "out/missing"}])
        p.begin_trajectory(self.root, "empty", "judge", {})
        self.assertFalse(p.finish_trajectory(self.root, "empty")["accepted"])

    def test_seal_is_immutable_and_actor_cannot_author_judge(self):
        p = self.module()
        checks = [{"predicate": "file_exists", "path": "out/a"}]
        with self.assertRaises(p.ProcedureError):
            p.seal_judge(self.root, "x", checks, actor="agent")
        p.seal_judge(self.root, "x", checks)
        with self.assertRaises(p.ProcedureError):
            p.seal_judge(self.root, "x", [{"predicate": "file_exists", "path": "out/b"}])
        with self.assertRaises(fileauth.Denied):
            fileauth.write_text(self.root, "org/procedures/forged.json", "{}")

    def test_fresh_edge_cases_promote_but_duplicate_evidence_does_not(self):
        p = self.candidate()
        self.suite(p)
        result = p.evaluate(self.root, "report", "fresh")
        self.assertTrue(result["accepted"], result)
        self.assertEqual(runbook.status(self.root, "report"), "proven")
        trust = runbook._trust(self.root)["report"]
        self.assertEqual(trust["accepted_wins"], 3)
        self.assertEqual(trust["envelope"]["distinct_inputs"], 3)
        self.assertEqual(trust["envelope"]["scope"], "observed-inputs-and-environments")
        p.evaluate(self.root, "report", "fresh")
        self.assertEqual(runbook._trust(self.root)["report"]["accepted_wins"], 3)

    def test_training_instance_reuse_is_rejected_and_failed_grader_quarantines(self):
        p = self.candidate()
        p.seal_suite(self.root, "leaked", {"family": "report", "cases": [
            {"id": "alpha", "edge": True, "inputs": {"destination": "out/alpha.txt", "value": "one"}}],
            "checks": [{"predicate": "file_exists", "path": {"input": "destination"}}]})
        with self.assertRaises(p.ProcedureError):
            p.evaluate(self.root, "report", "leaked")
        self.suite(p, "bad", bad=True)
        self.assertFalse(p.evaluate(self.root, "report", "bad")["accepted"])
        self.assertEqual(runbook.status(self.root, "report"), "quarantined")

    def test_changed_bytes_invalidate_trust_and_untrusted_receipt_cannot_promote(self):
        p = self.candidate()
        for _ in range(4):
            runbook.record(self.root, "report", True, accepted=True)
        self.assertEqual(runbook.status(self.root, "report"), "candidate")
        self.suite(p)
        p.evaluate(self.root, "report", "fresh")
        rb = runbook.load(self.root, "report")
        rb["steps"][0]["action"]["args"]["content"] = "changed"
        Path(runbook.path(self.root, "report")).write_text(json.dumps(rb))
        self.assertEqual(runbook.status(self.root, "report"), "candidate")

    def test_types_authority_and_path_traversal_fail_before_any_write(self):
        self.candidate()
        for inputs in ({"destination": "../escape", "value": "x"},
                       {"destination": "settings.toml", "value": "x"},
                       {"destination": "out/typed", "value": 42}):
            self.assertFalse(runbook.run(self.root, "report", allow_candidate=True, inputs=inputs)["ok"])
        denied = runbook.run(self.root, "report", allow_candidate=True,
                             inputs={"destination": "out/denied", "value": "x"}, authority=[])
        self.assertFalse(denied["ok"])
        self.assertFalse(Path(self.root, "out/denied").exists())

    def test_model_steps_never_replay_as_deterministic_and_bad_dag_is_rejected(self):
        p = self.module()
        ids = []
        for suffix, value in (("a", "one"), ("b", "two")):
            tid = self.train(p, suffix, value)
            ids.append(tid)
        rb = p.compile(self.root, "withmodel", ids, ["report"])
        rb["steps"].insert(0, {"id": "judgment", "kind": "model", "depends_on": [],
                                "tool": "subquery", "reason": "requires judgment"})
        Path(runbook.path(self.root, "withmodel")).write_text(json.dumps(rb))
        rr = runbook.run(self.root, "withmodel", allow_candidate=True,
                         inputs={"destination": "out/model", "value": "z"})
        self.assertFalse(rr["ok"])
        self.assertFalse(Path(self.root, "out/model").exists())
        rb["steps"][1]["depends_on"] = [rb["steps"][1]["id"]]
        self.assertTrue(runbook.validate(rb))

    def test_loop_capture_requires_active_trajectory_and_disk_readback(self):
        p = self.module()
        self.assertFalse(hasattr(p, "active_trajectory") and p.active_trajectory(self.root, "task"),
                         "unexpected open trajectory")
        self.assertTrue(hasattr(p, "active_trajectory"), "loop lacks safe opt-in capture API")
        p.seal_judge(self.root, "judge", [{"predicate": "file_exists", "path": "out/missing"}])
        p.begin_trajectory(self.root, "task", "judge", {})
        token = p.begin_action(self.root, "task", "write_file", {"path": "out/missing", "content": "x"})
        self.assertFalse(p.finish_action(self.root, "task", token, True),
                         "success prose substituted for actual file output")
        self.assertFalse(p.finish_trajectory(self.root, "task")["accepted"])
        self.assertFalse(p.active_trajectory(self.root, "task"))

    def test_copy_operator_composes_with_writer_and_observes_actual_effects(self):
        p = self.candidate()
        self.suite(p)
        p.evaluate(self.root, "report", "fresh")
        ids = []
        for key, value in (("copy-a", "a"), ("copy-b", "b")):
            inputs = {"source": f"out/{key}-source", "destination": f"out/{key}-dest", "value": value}
            fileauth.write_text(self.root, inputs["source"], value)
            p.seal_judge(self.root, key, [{"predicate": "file_equals", "path": inputs["destination"], "value": value}])
            p.begin_trajectory(self.root, key, key, inputs, family="report")
            p.perform(self.root, key, {"tool": "copy_file", "args": {
                "source": inputs["source"], "path": inputs["destination"]}})
            p.finish_trajectory(self.root, key)
            ids.append(key)
        p.compile(self.root, "copy", ids, ["copy"])
        p.seal_suite(self.root, "copy-fresh", {"family": "report", "cases": [
            {"id": str(i), "edge": i > 0, "inputs": {
                "source": f"out/src{i}", "destination": f"out/dest{i}", "value": value}}
            for i, value in enumerate(("plain", "", "東京"))],
            "initial_files": [{"path": {"input": "source"}, "content": {"input": "value"}}],
            "checks": [{"predicate": "file_equals", "path": {"input": "destination"}, "value": {"input": "value"}}]})
        self.assertTrue(p.evaluate(self.root, "copy", "copy-fresh")["accepted"])
        import operators
        goal = [{"predicate": "file_exists", "path": "out/final"}]
        bindings = [{"name": "copy", "inputs": {"source": "out/stage", "destination": "out/final", "value": "assembled"}},
                    {"name": "report", "inputs": {"destination": "out/stage", "value": "assembled"}}]
        plan = operators.plan(self.root, goal, bindings)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual([item["name"] for item in plan["steps"]], ["report", "copy"])
        self.assertFalse(Path(self.root, "out/stage").exists(), "planning changed world state")
        result = operators.execute_plan(self.root, plan, goal)
        self.assertTrue(result["ok"], result)
        self.assertEqual(Path(self.root, "out/final").read_text(), "assembled")
        self.assertFalse(operators.plan(self.root, [{"predicate": "file_exists", "path": "out/denied"}],
            [{"name": "report", "inputs": {"destination": "out/denied", "value": "x"}}], authority=[])["ok"])

    def test_failed_actions_and_unaligned_mutations_do_not_become_procedures(self):
        p = self.module()
        ids = [self.train(p, "one", "one")]
        p.seal_judge(self.root, "two", [{"predicate": "file_equals", "path": "out/two.txt", "value": "two"}])
        p.begin_trajectory(self.root, "two", "two", {"destination": "out/two.txt", "value": "two"}, family="report")
        p.perform(self.root, "two", {"tool": "write_file", "args": {"path": "out/extra", "content": "extra"}})
        p.perform(self.root, "two", {"tool": "write_file", "args": {"path": "out/two.txt", "content": "two"}})
        self.assertTrue(p.finish_trajectory(self.root, "two")["accepted"])
        with self.assertRaises(p.ProcedureError):
            p.compile(self.root, "mismatch", ids + ["two"], ["report"])

    def test_promotion_requires_edge_and_distinct_inputs_not_repeated_case_names(self):
        p = self.candidate()
        p.seal_suite(self.root, "duplicates", {"family": "report", "cases": [
            {"id": str(i), "edge": True, "inputs": {"destination": "out/same", "value": "same"}} for i in range(3)],
            "checks": [{"predicate": "file_equals", "path": {"input": "destination"}, "value": {"input": "value"}}]})
        p.evaluate(self.root, "report", "duplicates")
        self.assertEqual(runbook.status(self.root, "report"), "candidate")
        self.assertEqual(runbook._trust(self.root)["report"]["envelope"]["distinct_inputs"], 1)


if __name__ == "__main__":
    unittest.main()
