"""Unit test suite for RAG two-stage RetrievalPipeline and formatting."""

import os
import sqlite3
import unittest
from unittest.mock import MagicMock

from nanobot.rag.client import RerankerError
from nanobot.rag.config import StudyRagConfig
from nanobot.rag.store import SearchResult


def _make_search_result(
    chunk_id: int,
    doc_path: str,
    folder: str,
    title: str,
    heading: str | None,
    content: str,
    distance: float = 0.2,
) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        doc_path=doc_path,
        chunk_index=0,
        folder=folder,
        title=title,
        heading=heading,
        content=content,
        token_count=len(content.split()),
        distance=distance,
        similarity=1.0 - distance,
    )


class TestRetrievalPipeline(unittest.TestCase):
    def setUp(self) -> None:
        from nanobot.rag.retrieval import RetrievalPipeline, RetrievedChunk

        self.RetrievalPipeline = RetrievalPipeline
        self.RetrievedChunk = RetrievedChunk

        self.mock_store = MagicMock()
        self.mock_store.db_path = ":memory:"
        self.mock_embed_client = MagicMock()
        self.mock_embed_client.embed_texts.return_value = [[0.1] * 1024]
        self.mock_rerank_client = MagicMock()
        self.config = StudyRagConfig(
            candidate_k=30,
            top_k=10,
            score_threshold=0.0,
        )

        self.pipeline = self.RetrievalPipeline(
            store=self.mock_store,
            embedding_client=self.mock_embed_client,
            reranker_client=self.mock_rerank_client,
            config=self.config,
        )

    def test_search_end_to_end_flow(self) -> None:
        """Verify full embed -> KNN -> rerank flow and descending relevance sorting."""
        c0 = _make_search_result(1, "calc/derivada.md", "calc", "Derivadas", "Definição", "Texto sobre derivada")
        c1 = _make_search_result(2, "calc/integral.md", "calc", "Integrais", "Teorema Fundamental", "Texto sobre integral")
        c2 = _make_search_result(3, "calc/limite.md", "calc", "Limites", "Noção Intuitiva", "Texto sobre limite")

        self.mock_store.search_knn.return_value = [c0, c1, c2]
        self.mock_rerank_client.rerank.return_value = [
            {"index": 2, "relevance_score": 0.985},
            {"index": 0, "relevance_score": 0.750},
            {"index": 1, "relevance_score": 0.120},
        ]

        results = self.pipeline.search(query="o que é limite", folder="calc")

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].doc_path, "calc/limite.md")
        self.assertAlmostEqual(results[0].relevance_score, 0.985, places=3)
        self.assertEqual(results[1].doc_path, "calc/derivada.md")
        self.assertAlmostEqual(results[1].relevance_score, 0.750, places=3)
        self.assertEqual(results[2].doc_path, "calc/integral.md")
        self.assertAlmostEqual(results[2].relevance_score, 0.120, places=3)

        self.mock_embed_client.embed_texts.assert_called_once_with(["o que é limite"])
        self.mock_store.search_knn.assert_called_once_with(
            query_vector=[0.1] * 1024,
            top_k=30,
            folder="calc",
        )
        self.mock_rerank_client.rerank.assert_called_once_with(
            query="o que é limite",
            documents=["Texto sobre derivada", "Texto sobre integral", "Texto sobre limite"],
            top_n=3,
        )

    def test_search_candidate_k_overfetch(self) -> None:
        """Verify KNN is called with candidate_k and reranker is called with top_k."""
        candidates = [_make_search_result(i, f"doc_{i}.md", "calc", f"Doc {i}", None, f"Content {i}") for i in range(25)]
        self.mock_store.search_knn.return_value = candidates
        self.mock_rerank_client.rerank.return_value = [
            {"index": i, "relevance_score": 1.0 - (i * 0.03)} for i in range(10)
        ]

        results = self.pipeline.search(query="query", top_k=10, candidate_k=30)
        self.assertEqual(len(results), 10)
        self.mock_store.search_knn.assert_called_once_with(
            query_vector=[0.1] * 1024,
            top_k=30,
            folder=None,
        )
        self.mock_rerank_client.rerank.assert_called_once_with(
            query="query",
            documents=[c.content for c in candidates],
            top_n=10,
        )

    def test_search_partial_candidates(self) -> None:
        """Verify small candidate pool (< top_k) returns all available items without error."""
        c0 = _make_search_result(1, "a.md", "calc", "A", None, "Content A")
        c1 = _make_search_result(2, "b.md", "calc", "B", None, "Content B")
        self.mock_store.search_knn.return_value = [c0, c1]
        self.mock_rerank_client.rerank.return_value = [
            {"index": 0, "relevance_score": 0.9},
            {"index": 1, "relevance_score": 0.8},
        ]

        results = self.pipeline.search(query="query", top_k=10)
        self.assertEqual(len(results), 2)
        self.mock_rerank_client.rerank.assert_called_once_with(
            query="query",
            documents=["Content A", "Content B"],
            top_n=2,
        )

    def test_search_candidate_k_less_than_top_k(self) -> None:
        """Verify candidate_k < top_k clamps top_n to min(top_k, len(candidates)) independently of client."""
        candidates = [_make_search_result(i, f"doc_{i}.md", "calc", f"Doc {i}", None, f"Content {i}") for i in range(5)]
        self.mock_store.search_knn.return_value = candidates
        self.mock_rerank_client.rerank.return_value = [
            {"index": i, "relevance_score": 0.9 - (i * 0.1)} for i in range(5)
        ]

        # Config mismatch: candidate_k=5 < top_k=10
        results = self.pipeline.search(query="query", top_k=10, candidate_k=5)
        self.assertEqual(len(results), 5)
        self.mock_store.search_knn.assert_called_once_with(
            query_vector=[0.1] * 1024,
            top_k=5,
            folder=None,
        )
        self.mock_rerank_client.rerank.assert_called_once_with(
            query="query",
            documents=[c.content for c in candidates],
            top_n=5,  # Clamped to min(10, 5)
        )

    def test_search_uninitialized_db_returns_empty_without_ddl(self) -> None:
        """Verify non-existent database file returns empty list immediately without calling init_db."""
        non_existent_path = "/tmp/rag_test_uninitialized_db_non_existent_12345.db"
        if os.path.exists(non_existent_path):
            os.remove(non_existent_path)

        store_mock = MagicMock()
        store_mock.db_path = non_existent_path

        pipeline = self.RetrievalPipeline(
            store=store_mock,
            embedding_client=self.mock_embed_client,
            reranker_client=self.mock_rerank_client,
            config=self.config,
        )

        results = pipeline.search(query="teste")
        self.assertEqual(results, [])
        store_mock.init_db.assert_not_called()
        store_mock.search_knn.assert_not_called()
        self.assertFalse(os.path.exists(non_existent_path))

    def test_search_uninitialized_db_operational_error_returns_empty(self) -> None:
        """Verify sqlite3.OperationalError from missing tables returns empty list."""
        self.mock_store.search_knn.side_effect = sqlite3.OperationalError("no such table: rag_vec_chunks")
        results = self.pipeline.search(query="teste")
        self.assertEqual(results, [])
        self.mock_rerank_client.rerank.assert_not_called()

    def test_search_empty_knn_returns_empty(self) -> None:
        """Verify empty KNN search returns [] without invoking reranker."""
        self.mock_store.search_knn.return_value = []
        results = self.pipeline.search(query="teste")
        self.assertEqual(results, [])
        self.mock_rerank_client.rerank.assert_not_called()

    def test_search_reranker_failure_propagates_reranker_error(self) -> None:
        """Verify RerankerError fails fast and is propagated without silent catch (Rule 13)."""
        c0 = _make_search_result(1, "a.md", "calc", "A", None, "Content A")
        self.mock_store.search_knn.return_value = [c0]
        self.mock_rerank_client.rerank.side_effect = RerankerError("500 Internal Server Error")

        with self.assertRaises(RerankerError):
            self.pipeline.search(query="teste")

    def test_search_score_threshold_filtering(self) -> None:
        """Verify score_threshold discards items below threshold when > 0.0 and keeps all when 0.0."""
        c0 = _make_search_result(1, "a.md", "calc", "A", None, "Content A")
        c1 = _make_search_result(2, "b.md", "calc", "B", None, "Content B")
        c2 = _make_search_result(3, "c.md", "calc", "C", None, "Content C")
        self.mock_store.search_knn.return_value = [c0, c1, c2]

        self.mock_rerank_client.rerank.return_value = [
            {"index": 0, "relevance_score": 0.95},
            {"index": 1, "relevance_score": 0.60},
            {"index": 2, "relevance_score": 0.40},
        ]

        # With score_threshold=0.50 -> 2 items
        res_threshold = self.pipeline.search(query="teste", score_threshold=0.50)
        self.assertEqual(len(res_threshold), 2)
        self.assertEqual(res_threshold[0].doc_path, "a.md")
        self.assertEqual(res_threshold[1].doc_path, "b.md")

        # With score_threshold=0.0 -> all 3 items
        res_permissive = self.pipeline.search(query="teste", score_threshold=0.0)
        self.assertEqual(len(res_permissive), 3)

    def test_format_markdown_formatting(self) -> None:
        """Verify markdown block layout matching Rule 15 and empty message handling."""
        chunk1 = self.RetrievedChunk(
            chunk_id=1,
            doc_path="calculo_1/limites.md",
            chunk_index=0,
            folder="calculo_1",
            title="Limites Fundamentais",
            heading="Teorema do Confronto",
            content="Se f(x) <= g(x) <= h(x)...",
            token_count=20,
            distance=0.1,
            similarity=0.9,
            relevance_score=0.9854,
        )
        chunk2 = self.RetrievedChunk(
            chunk_id=2,
            doc_path="calculo_1/continuidade.md",
            chunk_index=0,
            folder="calculo_1",
            title="Continuidade",
            heading=None,  # Fallback to Introdução
            content="Uma função é contínua se...",
            token_count=15,
            distance=0.3,
            similarity=0.7,
            relevance_score=0.7501,
        )

        md = self.pipeline.format_markdown([chunk1, chunk2])

        self.assertIn("### [1] Limites Fundamentais (calculo_1/limites.md)", md)
        self.assertIn("- **Seção**: Teorema do Confronto", md)
        self.assertIn("- **Relevância**: 0.985", md)
        self.assertIn("- **Trecho**:\nSe f(x) <= g(x) <= h(x)...", md)

        self.assertIn("### [2] Continuidade (calculo_1/continuidade.md)", md)
        self.assertIn("- **Seção**: Introdução", md)
        self.assertIn("- **Relevância**: 0.750", md)
        self.assertIn("- **Trecho**:\nUma função é contínua se...", md)

        # Empty results formatting
        empty_md = self.pipeline.format_markdown([])
        self.assertEqual(empty_md, "Nenhuma nota de estudo encontrada para a consulta.")

    def test_search_empty_query_returns_empty(self) -> None:
        """Verify empty or whitespace-only query returns [] without embedding call."""
        res1 = self.pipeline.search("")
        self.assertEqual(res1, [])
        res2 = self.pipeline.search("   \n\t  ")
        self.assertEqual(res2, [])
        self.mock_embed_client.embed_texts.assert_not_called()


if __name__ == "__main__":
    unittest.main()

