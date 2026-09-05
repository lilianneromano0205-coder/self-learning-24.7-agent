"""Retrospective choice measurement laws; DESIGN-twin-measurement-integrity.md."""
import copy
import os
import sys
import tempfile
import json
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import twin
import twinmath as M
import twinmeasurement as TM


def rows(n=100):
    return [{"id": "ep-" + str(i), "kind": "decision", "at": "2026-01-01T00:00:00",
             "situation": {"text": "offer " + str(i), "features": {"risk": i / n}},
             "options": [{"id": "yes", "text": "yes", "features": {}},
                         {"id": "no", "text": "no", "features": {}}],
             "choice": "yes" if i < n / 2 else "no", "counterpart": "vendor"}
            for i in range(n)]


class Measurement(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="twin-measure-")
        self.addCleanup(self.temp.cleanup)
        self.root = self.temp.name

    def seed(self, n=100):
        twin.consent_grant(self.root, "predict")
        for row in rows(n):
            twin.observe(self.root, row["situation"], row["options"], row["choice"],
                         counterpart=row["counterpart"], origin=row["id"])
        twin.learn(self.root)
        return twin.load_kernel(self.root)

    def test_final_rows_never_select_rules(self):
        data = rows()
        seen = []
        validate = M.validate_rules
        def watched(rules, validation, **kwargs):
            seen.extend(e["id"] for e in validation)
            return validate(rules, validation, **kwargs)
        with patch.object(M, "validate_rules", side_effect=watched):
            fitted = twin._fit_version(data, 0, [])
        final = set(fitted.get("test_ids", [e["id"] for e in data if M.is_holdout(e["id"])]))
        self.assertTrue(final)
        self.assertFalse(final.intersection(seen), "FINAL rows were used to select rules")
        print("[test-purity] actual rule validation received no final-test row")

    def test_final_labels_cannot_change_fit(self):
        data = rows()
        before = twin._fit_version(data, 0, [])
        altered = copy.deepcopy(data)
        for row in altered:
            if TM.partition(row) == "test":
                row["choice"] = "no" if row["choice"] == "yes" else "yes"
                row["why"] = "INJECTED FINAL LABEL"
                row["outcome"] = "good"
        after = twin._fit_version(altered, 0, ["INJECTED FINAL LABEL"])
        self.assertEqual(before, after, "final labels/explanations altered fitted snapshot")
        self.assertNotIn("INJECTED", json.dumps(after))
        print("[label-perturbation] changing every final answer, reason and outcome left the entire fit identical")

    def test_all_fit_paths_only_see_development(self):
        data = rows()
        train_ids = {r["id"] for r in data if TM.partition(r) == "train"}
        val_ids = {r["id"] for r in data if TM.partition(r) == "validation"}
        with patch.object(M, "fit", wraps=M.fit) as fit, \
                patch.object(M, "mine_rules", wraps=M.mine_rules) as mine, \
                patch.object(M, "validate_rules", wraps=M.validate_rules) as validate, \
                patch.object(twin, "_social", wraps=twin._social) as social:
            version = twin._fit_version(data, 0, [])
        for spy in (fit, mine, social):
            self.assertEqual({r["id"] for r in spy.call_args.args[0]}, train_ids)
        self.assertEqual({r["id"] for r in validate.call_args.args[1]}, val_ids)
        self.assertEqual({r["id"] for r in version["neighbors"]}, train_ids)
        print("[all-paths] numerical fit, rule miner, social state and neighbors use train only; rule selection uses validation only")

    def test_group_ignores_answers_and_order(self):
        for row in rows():
            changed = copy.deepcopy(row)
            changed.update(id="retest", choice="other", why="later reason", outcome="bad",
                           at="2099-01-01", source="other", kind="retest")
            changed["options"].reverse()
            self.assertEqual(TM.group(row), TM.group(changed))
            self.assertEqual(TM.partition(row), TM.partition(changed))
        data = rows()
        self.assertEqual(TM.split(data), TM.split(list(reversed(data))))
        duplicate = copy.deepcopy(data[0])
        duplicate["id"] = "explicit-retest"
        parts = TM.split(data + [duplicate])
        self.assertIn(duplicate, parts[TM.partition(data[0])])
        with self.assertRaises(ValueError):
            TM.split(data + [data[0]])
        malformed = copy.deepcopy(data)
        malformed[0]["choice"] = "not-an-option"
        with self.assertRaises(ValueError):
            TM.split(malformed)
        for ids in (("same", "same"), (1, "1")):
            ambiguous = copy.deepcopy(data[0])
            ambiguous["options"][0]["id"], ambiguous["options"][1]["id"] = ids
            ambiguous["choice"] = str(ids[0])
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "duplicate option ID"):
                    TM.split([ambiguous])
                ambiguous["options"].reverse()
        print("[grouping] 100 answer/ID/time/retest permutations kept their inferred partition; duplicates and malformed choices refused")

    def test_frozen_neighbors_and_tampered_fit(self):
        self.seed()
        sample = rows()[0]
        before = twin.predict(self.root, sample["situation"], sample["options"], "vendor")
        # Poison the live ledger with exact copies of the query, opposite answer.
        for i in range(15):
            twin.observe(self.root, sample["situation"], sample["options"], "no",
                         counterpart="vendor", origin="poison-" + str(i))
        after = twin.predict(self.root, sample["situation"], sample["options"], "vendor")
        self.assertEqual(before["probs"], after["probs"], "live rows changed frozen prediction")
        self.assertEqual(before["neighbors"], after["neighbors"])
        kernel = twin.load_kernel(self.root)
        twin.current_version(kernel)["social"] = {"changed": True}
        twin.save_kernel(self.root, kernel)
        with self.assertRaisesRegex(twin.Refused, "hash mismatch"):
            twin.fidelity(self.root)
        print("[frozen] 15 poisoned live neighbors did not change predictions; altered fitted state refused")

    def test_receipt_replay_stale_and_tamper(self):
        self.seed()
        report = twin.fidelity(self.root)
        self.assertFalse(report["generalization_established"])
        self.assertEqual(TM.current_report(self.root), report)
        replayed = TM.replay(self.root, report["receipt"])
        self.assertEqual(replayed["choice_fidelity"], report["choice_fidelity"])
        twin.observe(self.root, "a new event", [], None, origin="new-text")
        self.assertEqual(TM.current_report(self.root)["verdict"], "STALE")
        self.assertIn("STALE", twin.render(self.root))
        self.assertEqual(TM.replay(self.root, report["receipt"]), replayed)
        path = os.path.join(self.root, TM.RECEIPTS, report["receipt"] + ".json")
        with open(path, encoding="utf-8") as stream:
            body = json.load(stream)
        body["report"]["choice_fidelity"] = 1.234
        twin._write_json(path, body)
        with self.assertRaisesRegex(ValueError, "TAMPER"):
            TM.replay(self.root, report["receipt"])
        print("[receipts] unchanged snapshot replayed after live writes; stale display suppressed current score; tampered receipt refused")

    def test_kernel_runtime_and_report_binding(self):
        self.seed()
        report = twin.fidelity(self.root)
        with patch.object(twin, "NEIGHBOR_BONUS", 99):
            self.assertEqual(TM.current_report(self.root)["verdict"], "STALE")
        kernel = twin.load_kernel(self.root)
        kernel["identity"]["principles"] = "new principle"
        twin.save_kernel(self.root, kernel)
        self.assertEqual(twin.status(self.root)["fidelity"]["verdict"], "STALE")
        new = twin.fidelity(self.root)
        self.assertTrue(new["test_groups_reused"])
        new["choice_fidelity"] = 0.999
        twin._write_json(twin._p(self.root, twin.FIDELITY), new)
        self.assertEqual(TM.current_report(self.root)["verdict"], "STALE")
        self.assertNotEqual(report["receipt"], new["receipt"])
        print("[binding] constants, identity and edited report invalidate display; changed candidate reusing test groups is labeled")

    def test_small_and_legacy_are_not_validated(self):
        self.seed(8)
        report = twin.fidelity(self.root)
        self.assertEqual(report["verdict"], "INSUFFICIENT EVIDENCE")
        self.assertIn("retrospective", report["measurement_scope"])
        self.assertFalse(report["generalization_established"])
        kernel = twin.load_kernel(self.root)
        del twin.current_version(kernel)["measurement_schema"]
        twin.save_kernel(self.root, kernel)
        with self.assertRaisesRegex(twin.Refused, "legacy"):
            twin.fidelity(self.root)
        print("[limits] small grouped cohort and legacy fit cannot claim validated human fidelity")

    def test_fidelity_rejects_post_fit_malformed_rows(self):
        self.seed()
        original = twin.episodes(self.root)
        for defect in ("duplicate", "choice"):
            altered = copy.deepcopy(original)
            if defect == "duplicate":
                altered.append(copy.deepcopy(original[0]))
            else:
                altered[0]["choice"] = "not-an-option"
            with patch.object(twin, "episodes", return_value=altered):
                with self.assertRaises((ValueError, twin.Refused)):
                    twin.fidelity(self.root)
        print("[evaluation-validation] post-fit duplicate IDs and invalid choices are refused before scoring")

    def test_fidelity_refuses_intervening_auxiliary_write(self):
        self.seed()
        writing = twin._writing_fidelity
        def interleaved(root, eps):
            result = writing(root, eps)
            twin.observe(root, "concurrent writing", [], None, origin="concurrent")
            return result
        with patch.object(twin, "_writing_fidelity", side_effect=interleaved):
            with self.assertRaisesRegex(twin.Refused, "changed during evaluation"):
                twin.fidelity(self.root)
        self.assertIsNone(TM.current_report(self.root))
        print("[snapshot-race] an intervening writing update refuses archival instead of binding old diagnostics to new inputs")

    def test_novel_losses_do_not_freeze_cold_start(self):
        for i, loss in enumerate([0.1, 0.1, 9.0, 9.0]):
            twin._drift_update(self.root, loss, {"episode": str(i), "novelty": 1.0})
        state = twin._drift_state(self.root)
        self.assertIsNone(state["notice"])
        self.assertEqual(len(state["resolved"]), 4)
        self.assertTrue(all(r["drift_excluded"] == "novel decision" for r in state["resolved"]))
        for i, loss in enumerate([0.1] * 8 + [9.0] * 3):
            twin._drift_update(self.root, loss, {"episode": str(i), "novelty": 0.0})
        self.assertEqual(twin._drift_state(self.root)["notice"]["status"], "open")
        print("[cold-start] unfamiliar losses remain recorded but do not freeze learning; known-policy loss shift still trips drift")


if __name__ == "__main__":
    result = unittest.main(exit=False)
    if not result.result.wasSuccessful():
        raise SystemExit(1)
    print("PASS test_twin_measurement")
