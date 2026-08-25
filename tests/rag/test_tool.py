"""Unit test suite for SearchStudyNotesTool agent tool."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.rag.client import EmbeddingError, RerankerError
from nanobot.rag.config import StudyRagConfig
from nanobot.rag.retrieval import RetrievedChunk
from nanobot.rag.store import DimensionMismatchError


class TestSearchStudyNotesTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from nanobot.agent.tools.rag import SearchStudyNotesTool

        self.SearchStudyNotesTool = SearchStudyNotesTool
        self.config = StudyRagConfig(
            enable=True,
            notes_dir="faculdade",
            db_path=":memory:",
            embedding_url="http://127.0.0.1:8082/v1/embeddings",
            reranker_url="http://127.0.0.1:8081/v1/rerank",
        )
        self.tool = self.SearchStudyNotesTool(config=self.config)

    def test_tool_schema_and_parameters(self) -> None:
        """Verify tool metadata, read_only safety, and JSON Schema parameters."""
        self.assertEqual(self.tool.name, "search_study_notes")
        self.assertTrue(self.tool.read_only)
        self.assertTrue(self.tool.concurrency_safe)
        self.assertFalse(self.tool.exclusive)

        params = self.tool.parameters
        self.assertEqual(params["type"], "object")
        self.assertIn("query", params["properties"])
        self.assertIn("folder", params["properties"])
        self.assertIn("top_k", params["properties"])
        self.assertEqual(params["required"], ["query"])

    async def test_tool_execution_success(self) -> None:
        """Verify tool execute runs asynchronously via thread pool and returns formatted content."""
        sample_results = [
            RetrievedChunk(
                chunk_id=1,
                doc_path="calc/limites.md",
                chunk_index=0,
                folder="calc",
                title="Limites",
                heading="Definição",
                content="Limite é o valor...",
                token_count=10,
                distance=0.1,
                similarity=0.9,
                relevance_score=0.985,
            )
        ]

        with patch.object(self.tool, "_run_search", return_value="### [1] Limites (calc/limites.md)\n- **Seção**: Definição\n- **Relevância**: 0.985\n- **Trecho**:\nLimite é o valor...") as mock_run:
            result = await self.tool.execute(
                query="o que é limite",
                folder="calc",
                top_k=5,
            )
            self.assertFalse(result.is_error)
            self.assertIn("### [1] Limites", result)
            self.assertIn("**Relevância**: 0.985", result)
            mock_run.assert_called_once_with(
                query="o que é limite",
                folder="calc",
                top_k=5,
            )

    def test_run_search_lifecycle_and_context_managers(self) -> None:
        """Verify _run_search invokes RagStore, EmbeddingClient, and RerankerClient via context managers."""
        mock_store = MagicMock()
        mock_embed_client = MagicMock()
        mock_rerank_client = MagicMock()
        mock_pipeline = MagicMock()
        mock_pipeline.search.return_value = []
        mock_pipeline.format_markdown.return_value = "Nenhuma nota encontrada."

        with patch("nanobot.agent.tools.rag.RagStore", return_value=mock_store) as mock_store_cls, \
             patch("nanobot.agent.tools.rag.EmbeddingClient", return_value=mock_embed_client) as mock_embed_cls, \
             patch("nanobot.agent.tools.rag.RerankerClient", return_value=mock_rerank_client) as mock_rerank_cls, \
             patch("nanobot.agent.tools.rag.RetrievalPipeline", return_value=mock_pipeline) as mock_pipe_cls:

            output = self.tool._run_search(
                query="teste",
                folder="calc",
                top_k=5,
            )
            self.assertEqual(output, "Nenhuma nota encontrada.")
            mock_store_cls.assert_called_once_with(
                db_path=self.config.db_path,
                embedding_dims=self.config.embedding_dims,
            )
            mock_embed_cls.assert_called_once_with(
                base_url=self.config.embedding_url,
                model=self.config.embedding_model,
                dims=self.config.embedding_dims,
                timeout=self.config.embedding_timeout,
            )
            mock_rerank_cls.assert_called_once_with(
                base_url=self.config.reranker_url,
                model=self.config.reranker_model,
                timeout=self.config.reranker_timeout,
            )
            mock_pipe_cls.assert_called_once()
            mock_pipeline.search.assert_called_once_with(
                query="teste",
                folder="calc",
                top_k=5,
            )
            # Verify context manager entry/exit was invoked
            mock_store.__enter__.assert_called_once()
            mock_store.__exit__.assert_called_once()
            mock_embed_client.__enter__.assert_called_once()
            mock_embed_client.__exit__.assert_called_once()
            mock_rerank_client.__enter__.assert_called_once()
            mock_rerank_client.__exit__.assert_called_once()

    async def test_tool_execution_reranker_error_returns_error_result(self) -> None:
        """Verify RerankerError during search is caught and returned as ToolResult.error."""
        with patch.object(self.tool, "_run_search", side_effect=RerankerError("500 Server Error")):
            result = await self.tool.execute(query="teste")
            self.assertTrue(result.is_error)
            self.assertIn("reranking", result.lower())
            self.assertIn("500 server error", result.lower())

    async def test_tool_execution_embedding_error_returns_error_result(self) -> None:
        """Verify EmbeddingError during search is caught and returned as ToolResult.error."""
        with patch.object(self.tool, "_run_search", side_effect=EmbeddingError("Connection timed out")):
            result = await self.tool.execute(query="teste")
            self.assertTrue(result.is_error)
            self.assertIn("embedding", result.lower())
            self.assertIn("connection timed out", result.lower())

    async def test_tool_execution_dimension_mismatch_returns_error_result(self) -> None:
        """Verify DimensionMismatchError is caught and returned as ToolResult.error."""
        with patch.object(self.tool, "_run_search", side_effect=DimensionMismatchError(db_dims=1024, config_dims=768)):
            result = await self.tool.execute(query="teste")
            self.assertTrue(result.is_error)
            self.assertIn("dimensões", result.lower())

    def test_tool_enabled_flag(self) -> None:
        """Verify enabled() class method checks ctx.config.study_rag.enable."""
        ctx_enabled = MagicMock()
        ctx_enabled.config.study_rag.enable = True
        self.assertTrue(self.SearchStudyNotesTool.enabled(ctx_enabled))

        ctx_disabled = MagicMock()
        ctx_disabled.config.study_rag.enable = False
        self.assertFalse(self.SearchStudyNotesTool.enabled(ctx_disabled))

    def test_tool_create_factory(self) -> None:
        """Verify create() class method initializes tool with ctx.config.study_rag."""
        ctx = MagicMock()
        ctx.config.study_rag = self.config
        inst = self.SearchStudyNotesTool.create(ctx)
        self.assertIsInstance(inst, self.SearchStudyNotesTool)
        self.assertEqual(inst.config, self.config)


if __name__ == "__main__":
    unittest.main()

