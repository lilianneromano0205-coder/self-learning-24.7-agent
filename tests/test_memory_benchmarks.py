"""Local schema fixtures and baseline comparisons, NOT official benchmark scores."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BenchmarkTests(unittest.TestCase):
    def test_missing_dataset_has_no_fabricated_zero_or_score(self):
        import memory_benchmarks as b
        r = b.run_external("longmemeval_v2", "missing-path")
        self.assertEqual(r["status"], "NOT_RUN")
        self.assertIsNone(r["score"])

    def test_v2_schema_keeps_answers_from_retriever_and_never_evals_code(self):
        import memory_benchmarks as b
        with tempfile.TemporaryDirectory() as root:
            Path(root, "haystacks").mkdir()
            Path(root, "questions.jsonl").write_text(json.dumps(dict(id="q1", domain="web",
                environment="fixture", question_type="workflow_knowledge", question="Where is export?",
                answer="SECRET_GOLD", eval_function="raise RuntimeError('do not execute')", image=None)) + "\n")
            Path(root, "trajectories.jsonl").write_text(json.dumps(dict(id="t1", domain="web",
                environment="fixture", goal="Export invoice", outcome="success", start_url="http://fixture.local",
                states=[dict(state_index=0, accessibility_tree="Press export", action="click")])) + "\n")
            Path(root, "haystacks", "lme_v2_small.json").write_text(json.dumps({"q1": ["t1"]}))
            data = b.load("longmemeval_v2", root)
            self.assertEqual(data["license"], "Apache-2.0")
            self.assertNotIn("SECRET_GOLD", json.dumps(data["cases"][0]["records"]))
            report = b.compare(data)
            self.assertIsNone(report["arms"]["lexical"]["retrieval_accuracy"])
            self.assertEqual(report["arms"]["lexical"]["answer_status"], "NOT_RUN")
            self.assertEqual(report["arms"]["simple_rag"]["status"], "NOT_RUN")

    def test_mab_parallel_lists_and_unknown_split_rejected(self):
        import memory_benchmarks as b
        with tempfile.TemporaryDirectory() as root:
            file = Path(root, "data.json")
            file.write_text(json.dumps([dict(context="current fact", questions=["question"],
                answers=[["gold", "alternative"]], metadata={"source": "fixture"})]))
            data = b.load("memoryagentbench", str(file), split="Conflict_Resolution")
            self.assertEqual(data["cases"][0]["answers"], ["gold", "alternative"])
            self.assertNotIn("gold", json.dumps(data["cases"][0]["records"]))
            with self.assertRaises(ValueError):
                b.load("memoryagentbench", str(file), split="invented")
            file.write_text(json.dumps([dict(context="x", questions=["q"], answers=[])]))
            with self.assertRaises(ValueError):
                b.load("memoryagentbench", str(file), split="Accurate_Retrieval")

    def test_four_arms_seven_dimensions_and_temporal_supersession(self):
        import memory_benchmarks as b
        categories = ["retrieval_accuracy", "temporal_state_updates", "selective_forgetting",
                      "workflow_recall", "environment_gotchas", "premise_awareness", "long_history_retention"]
        cases = [dict(id=str(i), question="car repair", category=cat, relevant_ids=["good"],
                      answers=[], records=[dict(id="bad", text="car repair", superseded_by="good"),
                                          dict(id="good", text="automobile maintenance")])
                 for i, cat in enumerate(categories)]
        def vectors(texts):
            return [[1.0, 0.0] for _ in texts]
        r = b.compare(dict(name="synthetic", cases=cases, fingerprint="fixture", evidence_tier="synthetic_fixture"),
                      embedder=vectors, limit=1)
        self.assertEqual(set(r["arms"]), {"lexical", "hybrid", "no_memory", "simple_rag"})
        self.assertEqual(r["arms"]["hybrid"]["retrieval_accuracy"], 1)
        self.assertEqual(r["arms"]["no_memory"]["retrieval_accuracy"], 0)
        self.assertEqual(set(r["arms"]["hybrid"]["by_category"]), set(categories))
        self.assertEqual(r["external_benchmark_result"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
