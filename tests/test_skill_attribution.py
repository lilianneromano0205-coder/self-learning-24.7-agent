"""Co-occurrence cannot become causal authority; matched mechanical ablations can."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import skills


class AttributionTests(unittest.TestCase):
    def test_loaded_success_never_promotes_and_duplicates_do_not_count(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "skills").mkdir()
            for i in range(10):
                skills.record_use(root, ["skills/a.md", "skills/b.md"], str(i), True, True)
            self.assertEqual(skills.status_of(root, "a"), "candidate")
            skills.record_use(root, ["skills/a.md"], "0", True, True)
            self.assertEqual(skills.load_graph(root)["a"]["wins"], 10)

    def test_cooccurrence_losses_do_not_quarantine(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "skills").mkdir()
            for i in range(10):
                skills.record_use(root, ["skills/a.md", "skills/b.md"], str(i), False)
            self.assertEqual(skills.status_of(root, "a"), "candidate")

    def test_trace_requires_injection_and_reference_before_influence(self):
        task = {"id": "trace1"}
        skills.trace_event(task, "retrieved", ["skills/a.md", "skills/b.md"])
        skills.trace_event(task, "injected", ["skills/a.md"])
        with self.assertRaises(ValueError):
            skills.trace_event(task, "influenced", ["skills/b.md"], step=3, evidence="tool-call:3")
        skills.trace_event(task, "referenced", ["skills/a.md"], step=2, evidence="read_file:2")
        skills.trace_event(task, "influenced", ["skills/a.md"], step=3, evidence="explicit-skill-link:3")
        self.assertEqual(task["skill_trace"][-1]["evidence"], "explicit-skill-link:3")

    def test_matched_ablation_uses_fresh_roots_hidden_grader_and_pins_skill(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "skills").mkdir()
            Path(root, "skills", "a.md").write_text("multiply by two", encoding="utf-8")
            cases = [dict(id=f"held-{i}", input={"x": i}, expected=i * 2) for i in range(1, 7)]
            observed = []
            def runner(case, workdir, injected, seed):
                self.assertNotIn("expected", case)
                self.assertEqual(list(Path(workdir).iterdir()), [])
                observed.append((case["id"], seed, workdir))
                return case["input"]["x"] * (2 if injected else 1)
            result = skills.run_ablation(root, "skills/a.md", cases, runner,
                                        lambda case, output: output == case["expected"], seed=7)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["pairs"], 6)
            self.assertEqual(result["delta"], 1)
            self.assertEqual(skills.status_of(root, "a"), "proven")
            self.assertEqual(len(set(x[2] for x in observed)), 12)
            for i in range(0, len(observed), 2):
                self.assertEqual(observed[i][:2], observed[i + 1][:2])
            Path(root, "skills", "a.md").write_text("changed skill", encoding="utf-8")
            self.assertEqual(skills.status_of(root, "a"), "candidate")

    def test_ablation_rejects_training_overlap_duplicate_tasks_and_boolean_lies(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "skills").mkdir()
            Path(root, "skills", "a.md").write_text("x", encoding="utf-8")
            cases = [dict(id="seen", input={}, expected=1)]
            skills.record_use(root, ["skills/a.md"], "seen", True, True)
            with self.assertRaises(ValueError):
                skills.run_ablation(root, "skills/a.md", cases, lambda *a: 1, lambda *a: True)
            with self.assertRaises(ValueError):
                skills.run_ablation(root, "skills/a.md", cases * 2, lambda *a: 1, lambda *a: True)
            result = skills.run_ablation(root, "skills/a.md", [dict(id="fresh", input={}, expected=1)],
                                        lambda *a: {"success": True}, lambda *a: "yes")
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(skills.status_of(root, "a"), "candidate")


if __name__ == "__main__":
    unittest.main()
