"""Keyless regression evidence for experiment identity, arms and mastery splits."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark
import capability
import mastery


class MeasurementIntegrity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="measurement-test-")
        self.home = Path(self.tmp.name)
        self.root = self.home / "experts" / "student"
        self.root.mkdir(parents=True)
        (self.root / "settings.toml").write_text('[agent]\nsandbox="host"\nallow_unsafe_host=true\n', encoding="utf8")
        self.pack = "responsive-pricing"
        shutil.copytree(Path(capability.HOME) / "packs" / self.pack, self.home / "packs" / self.pack)

    def tearDown(self):
        self.tmp.cleanup()

    def test_four_disjoint_nonidentical_sets(self):
        groups = [capability._tasks_in(str(self.home / "packs" / self.pack / k))
                  for k in ("baseline", "exercises", "transfer", "retention")]
        self.assertTrue(all(len(g) >= 2 for g in groups), "baseline and retention are missing")
        ids = [t["id"] for g in groups for t in g]
        prompts = [t["goal"] for g in groups for t in g]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(prompts), len(set(prompts)))

    def test_same_content_new_id_rejected(self):
        dst = self.home / "packs" / self.pack / "baseline"
        dst.mkdir(exist_ok=True)
        task = capability.transfer_tasks(str(self.home), self.pack)[0]
        task["id"] = "different-id-same-instance"
        (dst / "duplicate.json").write_text(json.dumps(task), encoding="utf8")
        self.assertTrue(any("overlap" in p or "duplicate" in p for p in capability.validate(str(self.home), self.pack)))

    def test_seal_append_cannot_reauthor_exam(self):
        capability.freeze(str(self.home), self.pack)
        path = self.home / "packs" / self.pack / "pack.json"
        pk = json.loads(path.read_text(encoding="utf8")); pk["domain"] = "modified"
        path.write_text(json.dumps(pk), encoding="utf8")
        with (self.home / capability.SEALS).open("a", encoding="utf8") as f:
            f.write(json.dumps({"pack": self.pack, "hash": capability._content_hash(str(self.home), self.pack)}) + "\n")
        self.assertTrue(capability.verify_pack(str(self.home), self.pack)["tamper"])

    def test_phases_select_disjoint_tasks_and_refuse_reexposure(self):
        capability.freeze(str(self.home), self.pack)
        seen = {}
        def fake(home, expert, pack, task, phase, **kw):
            seen.setdefault(phase, set()).add(task["id"])
            return {"task": task["id"], "passed": False, "competencies": task["competencies"], "failed_checks": ["A1"]}
        with patch.object(mastery, "_run_task", side_effect=fake):
            mastery.pretest(str(self.home), "student", self.pack)
            mastery.exam(str(self.home), "student", self.pack)
            mastery.retest(str(self.home), "student", self.pack)
            self.assertFalse(seen["pretest"] & seen["exam"], "pretest exposes exam")
            self.assertFalse(seen["retest"] & seen["exam"], "retention repeats exam")
            with self.assertRaises(mastery.MasteryError):
                mastery.exam(str(self.home), "student", self.pack)

    def test_corpus_is_separate_twenty_tasks_ten_domains(self):
        self.assertTrue(hasattr(benchmark, "experiment_tasks"), "runner is still the three toy tasks")
        tasks = benchmark.experiment_tasks()
        self.assertGreaterEqual(len(tasks), 20)
        self.assertGreaterEqual(len({t["family"] for t in tasks}), 10)
        self.assertTrue(all(t["split"] == "train" and t["fixture"] for t in tasks))
        self.assertFalse({t["id"] for t in tasks} & {t["id"] for t in benchmark.SUITE})

    def test_missing_metrics_are_unknown_not_free_success(self):
        self.assertTrue(hasattr(benchmark, "summarize_experiment"), "no complete metrics receipt")
        result = benchmark.summarize_experiment([{"arm": "full", "trial": "a", "passed": True, "cost_usd": None}])
        self.assertIsNone(result["arms"]["full"]["verified_work_per_dollar"])
        self.assertIsNone(result["arms"]["full"]["false_accepts"])

    def test_declared_arms(self):
        self.assertTrue(hasattr(benchmark, "ARMS"), "ordinary iterative and no-persistence arms absent")
        self.assertEqual(set(benchmark.ARMS), {"raw", "minimal", "no_persistence", "full", "reference"})


if __name__ == "__main__":
    unittest.main()
