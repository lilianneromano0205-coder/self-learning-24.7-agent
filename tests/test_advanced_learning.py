"""Offline authority/adaptation fixtures; no provider or trainer execution."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proof
import training
import variants


class AdvancedLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "experts" / "test"
        self.root.mkdir(parents=True)

    def seed(self):
        for i in range(40):
            training.capture(str(self.root), {"id": str(i), "goal": "token=planted",
                "steps": [{"tool": "write", "result": "safe"}]}, "done", True,
                evidence="Bearer planted-fixture")
        return training.export(str(self.root), "fixture")

    def test_export_redacts_every_field_and_hides_holdout(self):
        man = self.seed()
        data = (self.root / training.RUNS / man["id"] / "train.jsonl").read_text()
        self.assertNotIn("planted", data)
        self.assertFalse((self.root / training.RUNS / man["id"] / "holdout.jsonl").exists())

    def test_direct_owner_api_guard(self):
        with patch.dict(os.environ, {"AGENT_TASK_ID": "fixture"}):
            for call in (lambda: training.register(str(self.root), "missing", "c", 1, "v"),
                         lambda: training.promote(str(self.root), "c", 0),
                         lambda: training.rollback(str(self.root)),
                         lambda: variants.promote(str(self.root), "missing"),
                         lambda: variants.rollback(str(self.root), "missing")):
                with self.assertRaisesRegex(SystemExit, "OWNER"):
                    call()

    def test_two_task_variant_cannot_promote(self):
        variants.spawn(str(self.root), "v", "tester", "candidate")
        m = variants.load_manifest(str(self.root))
        m["v"]["trials"] = {"base": {"tasks": 2, "passes": 0},
                                  "variant": {"tasks": 2, "passes": 2}}
        variants.save_manifest(str(self.root), m)
        with self.assertRaisesRegex(SystemExit, "sealed|hidden|promotion battery"):
            variants.promote(str(self.root), "v")

    def test_latest_failure_downgrades_proof(self):
        proof.observe(str(self.root), "proof-system", "offline", True)
        proof.observe(str(self.root), "proof-system", "offline", False)
        self.assertEqual(proof.evaluate(str(self.root), "proof-system")["level"], proof.IMPLEMENTED)

    def test_ci_cannot_prove_intelligence(self):
        for kind in ("offline", "live", "stress", "production"):
            proof.observe(str(self.root), "training-lab", kind, True)
        result = proof.evaluate(str(self.root), "training-lab")
        self.assertEqual(result["badge"], "OFFLINE VERIFIED")
        self.assertFalse(result["intelligence_claims_proven"])

    def test_learning_authority_immutable_and_conflicting_seal_rejected(self):
        self.assertIsNotNone(importlib.util.find_spec("learning_authority"), "missing sealed learning authority")
        auth = importlib.import_module("learning_authority")
        auth.store(str(self.root), "fixture", "one", {"a": 1})
        self.assertEqual(auth.load(str(self.root), "fixture", "one"), {"a": 1})
        with self.assertRaises(auth.Refused):
            auth.store(str(self.root), "fixture", "one", {"a": 2})
        ledger = auth.directory(str(self.root)) / "seals.jsonl"
        rows = ledger.read_text().splitlines()
        row = json.loads(rows[0]); row["sha256"] = "0" * 64
        with ledger.open("a") as f:
            f.write(json.dumps(row) + "\n")
        with self.assertRaisesRegex(auth.Refused, "TAMPER"):
            auth.load(str(self.root), "fixture", "one")

    def test_local_logit_adaptation_is_explicit_and_verification_bounded(self):
        self.assertIsNotNone(importlib.util.find_spec("adaptation"), "missing experimental adaptation")
        a = importlib.import_module("adaptation")
        rows = [{"id": "a", "state": "build package", "action": "build", "reward": 1, "verified": True},
                {"id": "b", "state": "build package", "action": "delete", "reward": 0, "verified": True}]
        with self.assertRaises(a.Refused):
            a.local_logits("build package", {"build": 0, "delete": 0}, rows)
        with self.assertRaises(a.Refused):
            a.local_logits("build package", {"build": 0}, rows, enabled=True, logits_accessible=False)
        result = a.local_logits("build package", {"build": 0, "delete": 0}, rows,
                                enabled=True, logits_accessible=True)
        self.assertGreater(result["logits"]["build"], result["logits"]["delete"])
        self.assertFalse(result["exact_jitrl"])
        selected = a.closed_api_rerank("build package", ["delete", "build"], rows,
                lambda action: action == "build", enabled=True)
        self.assertEqual(selected["action"], "build")
        self.assertEqual(selected["mode"], "closed_api_approximation")

    def test_external_trainer_exports_no_eval_and_does_not_execute(self):
        self.assertIsNotNone(importlib.util.find_spec("trainer_integration"), "missing external trainer adapter")
        trainer = importlib.import_module("trainer_integration")
        man = self.seed()
        for recipe in ("lora", "qlora", "sft", "preference", "rlvr", "verifier"):
            config = trainer.recipe(recipe, base_model="local/base", revision="a" * 40)
            self.assertTrue(config["external_only"])
        stage = Path(self.temp.name) / "external"
        result = trainer.prepare(str(self.root), man["id"], str(stage), "sft",
                                 base_model="local/base", revision="a" * 40)
        self.assertEqual(result["execution"], "NOT_RUN")
        self.assertEqual(set(p.name for p in stage.iterdir()), {"train.jsonl", "recipe.json"})
        self.assertNotIn("holdout", (stage / "recipe.json").read_text())


if __name__ == "__main__":
    unittest.main()
