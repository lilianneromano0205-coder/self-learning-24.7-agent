"""Offline retrieval regressions; synthetic vectors are not model-quality proof."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import recall


class HybridTests(unittest.TestCase):
    def test_retracted_atom_not_returned_as_valid(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root, "courses", "net")
            base.mkdir(parents=True)
            (base / "notes.md").write_text("- C-001 Redis migration completed\n", encoding="utf-8")
            (base / "retractions.md").write_text("- C-001 retracted: migration cancelled\n", encoding="utf-8")
            hits = recall.search(root, "Redis migration")
            self.assertFalse(any("completed" in h[2] for h in hits))

    def test_paraphrase_and_metadata_floor(self):
        import retrieval
        rows = [dict(id="a", text="The automobile needs repair", source_tier=2,
                     provenance="manual:4", observed_at=100, valid=True, kind="gotchas"),
                dict(id="bad", text="car broken", source_tier=1, valid=False),
                dict(id="old", text="car broken", source_tier=1, superseded_by="a"),
                dict(id="other", text="car broken", source_tier=1, kind="skills")]
        def local_vectors(texts):
            return [[1, 0] if ("automobile" in s or "car" in s) else [0, 1] for s in texts]
        self.assertEqual(retrieval.rank(rows, "car broken", kinds=["gotchas"], mode="lexical"), [])
        hits = retrieval.rank(rows, "car broken", kinds=["gotchas"], embedder=local_vectors, now=200)
        self.assertEqual([h["id"] for h in hits], ["a"])
        self.assertEqual(hits[0]["provenance"], "manual:4")
        self.assertEqual(hits[0]["source_tier"], 2)
        self.assertEqual(hits[0]["observed_at"], 100)

    def test_validity_temporal_and_conflict_filters(self):
        import retrieval
        rows = [dict(id="new", text="endpoint server", source_tier=2, valid_from=50, valid_until=150),
                dict(id="expired", text="endpoint server", source_tier=1, valid_until=40),
                dict(id="contradicted", text="endpoint server", contradiction="unresolved"),
                dict(id="retracted", text="endpoint server", retracted=True)]
        self.assertEqual([h["id"] for h in retrieval.rank(rows, "endpoint", now=100)], ["new"])
        history = retrieval.rank(rows, "endpoint", now=100, include_invalid=True)
        self.assertEqual(len(history), 4)
        self.assertFalse(next(h for h in history if h["id"] == "expired")["valid"])

    def test_link_expansion_cannot_resurrect_retraction_or_escape(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root, "courses", "net")
            base.mkdir(parents=True)
            (base / "notes.md").write_text("anchor links C-001\n- C-001 obsolete procedure\n", encoding="utf-8")
            (base / "retractions.md").write_text("- C-001 retracted: wrong\n", encoding="utf-8")
            self.assertFalse(any("obsolete" in h[2] for h in recall.search(root, "anchor")))

    def test_router_applies_before_semantic_ranking(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "skills").mkdir()
            Path(root, "skills", "secret.md").write_text("exam solution", encoding="utf-8")
            records = recall.search_records(root, "exam", task={"role": "student"})
            self.assertEqual(records, [])

    def test_bad_embedding_falls_back_and_nonlocal_model_refused(self):
        import retrieval
        rows = [dict(id="a", text="car")]
        def invalid(texts):
            return [[float("nan")]] * len(texts)
        self.assertEqual(retrieval.rank(rows, "car", embedder=invalid)[0]["retrieval_mode"], "lexical_fallback")
        with self.assertRaises(ValueError):
            retrieval.LocalEmbeddings("remote/model")


if __name__ == "__main__":
    unittest.main()
