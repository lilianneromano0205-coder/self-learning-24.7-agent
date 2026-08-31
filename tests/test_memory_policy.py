"""Experimental manager must never rewrite institutional evidence."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class PolicyTests(unittest.TestCase):
    def test_disabled_by_default_and_no_authority_write(self):
        import memory_policy
        p = memory_policy.MemoryPolicy([])
        with self.assertRaises(PermissionError):
            p.apply("store", id="x", text="x")
        p = memory_policy.MemoryPolicy([], enabled=True)
        with self.assertRaises(ValueError):
            p.apply("store", id="x", text="x", source_tier=1)

    def test_evidence_retraction_and_original_provenance_survive_all_actions(self):
        import memory_policy
        original = [dict(id="proof", text="receipt 123", source_tier=1, protected=True,
                         provenance="sealed:judge", retracted=True)]
        p = memory_policy.MemoryPolicy(original, enabled=True)
        for action in ("update", "discard"):
            with self.assertRaises(PermissionError):
                p.apply(action, id="proof", text="changed") if action == "update" else p.apply(action, id="proof")
        with self.assertRaises(PermissionError):
            p.apply("summarize", ids=["proof"], id="summary")
        self.assertEqual(p.snapshot()[0], original[0])
        p.apply("store", id="note", text="inspect retry header")
        p.apply("update", id="note", text="inspect retry header before retry")
        p.apply("summarize", ids=["note"], id="summary")
        self.assertEqual(p.apply("retrieve", query="retry")[0]["source_tier"], 4)
        p.apply("discard", id="note")
        stored = next(r for r in p.snapshot() if r["id"] == "note")
        self.assertFalse(stored["valid"])
        self.assertEqual(stored["versions"][0]["text"], "inspect retry header")
        self.assertEqual(original[0]["provenance"], "sealed:judge")

    def test_learning_only_selects_allowed_actions_and_requires_receipt(self):
        import memory_policy
        p = memory_policy.MemoryPolicy([], enabled=True)
        with self.assertRaises(ValueError):
            p.observe("invented-receipt", 1)
        p.apply("store", id="n", text="learned hint")
        p.observe(p.receipts[-1]["id"], 0.8)
        self.assertEqual(p.choose(["store", "retrieve"]), "store")
        self.assertEqual(p.choose(["retrieve"]), "retrieve")
        with self.assertRaises(ValueError):
            p.choose(["erase_evidence"])


if __name__ == "__main__":
    unittest.main()
