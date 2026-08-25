"""Unit tests for StudyRagConfig configuration schema and defaults."""

import unittest
from pydantic import ValidationError

from nanobot.rag.config import StudyRagConfig


class TestStudyRagConfig(unittest.TestCase):
    """Test defaults and validation bounds of StudyRagConfig."""

    def test_default_values(self) -> None:
        """Verify default configuration parameters for StudyRagConfig."""
        cfg = StudyRagConfig()
        self.assertTrue(cfg.enable)
        self.assertEqual(cfg.notes_dir, "faculdade")
        self.assertEqual(cfg.db_path, "~/.nanobot/data/rag.db")
        self.assertEqual(cfg.embedding_url, "http://127.0.0.1:8082/v1/embeddings")
        self.assertEqual(cfg.embedding_model, "Qwen3-Embedding-0.6B-Q8_0.gguf")
        self.assertEqual(cfg.embedding_dims, 1024)
        self.assertEqual(cfg.embedding_timeout, 30.0)
        self.assertEqual(cfg.reranker_url, "http://127.0.0.1:8081/v1/rerank")
        self.assertEqual(cfg.reranker_model, "ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF")
        self.assertEqual(cfg.reranker_timeout, 30.0)
        self.assertEqual(cfg.candidate_k, 30)
        self.assertEqual(cfg.top_k, 10)
        self.assertEqual(cfg.score_threshold, 0.0)
        self.assertEqual(cfg.chunk_max_tokens, 1500)

    def test_validation_bounds(self) -> None:
        """Verify range constraints on candidate_k, timeouts, and thresholds."""
        # candidate_k must be between 1 and 200
        with self.assertRaises(ValidationError):
            StudyRagConfig(candidate_k=0)
        with self.assertRaises(ValidationError):
            StudyRagConfig(candidate_k=201)

        # score_threshold must be between 0.0 and 1.0
        with self.assertRaises(ValidationError):
            StudyRagConfig(score_threshold=-0.1)
        with self.assertRaises(ValidationError):
            StudyRagConfig(score_threshold=1.1)

        # timeouts must be positive and >= 1.0
        with self.assertRaises(ValidationError):
            StudyRagConfig(embedding_timeout=0.5)
        with self.assertRaises(ValidationError):
            StudyRagConfig(reranker_timeout=0.5)


if __name__ == "__main__":
    unittest.main()
