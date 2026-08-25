"""Unit test suite for nanobot rag CLI commands."""

import unittest
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.rag.client import EmbeddingError, RerankerError


class TestRagCli(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_rag_search_cli_success(self) -> None:
        """Verify successful CLI invocation of nanobot rag search."""
        mock_pipeline = MagicMock()
        mock_pipeline.search.return_value = ["dummy_result"]
        mock_pipeline.format_markdown.return_value = "### [1] Limites Fundamentais"

        with patch("nanobot.cli.rag.RetrievalPipeline", return_value=mock_pipeline), \
             patch("nanobot.cli.rag.RagStore"), \
             patch("nanobot.cli.rag.EmbeddingClient"), \
             patch("nanobot.cli.rag.RerankerClient"):

            result = self.runner.invoke(
                app,
                ["rag", "search", "o que é limite", "--folder", "calculo_1", "--top-k", "5", "--candidate-k", "20"],
            )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertIn("### [1] Limites Fundamentais", result.output)
            mock_pipeline.search.assert_called_once_with(
                query="o que é limite",
                folder="calculo_1",
                top_k=5,
                candidate_k=20,
            )

    def test_rag_search_cli_reranker_error_exits_1(self) -> None:
        """Verify RerankerError during CLI search exits with code 1 and prints error message."""
        mock_pipeline = MagicMock()
        mock_pipeline.search.side_effect = RerankerError("500 Server Error")

        with patch("nanobot.cli.rag.RetrievalPipeline", return_value=mock_pipeline), \
             patch("nanobot.cli.rag.RagStore"), \
             patch("nanobot.cli.rag.EmbeddingClient"), \
             patch("nanobot.cli.rag.RerankerClient"):

            result = self.runner.invoke(app, ["rag", "search", "query"])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("Erro no subsistema de reranking", result.output)
            self.assertIn("500 Server Error", result.output)

    def test_rag_search_cli_embedding_error_exits_1(self) -> None:
        """Verify EmbeddingError during CLI search exits with code 1 and prints error message."""
        mock_pipeline = MagicMock()
        mock_pipeline.search.side_effect = EmbeddingError("Connection refused")

        with patch("nanobot.cli.rag.RetrievalPipeline", return_value=mock_pipeline), \
             patch("nanobot.cli.rag.RagStore"), \
             patch("nanobot.cli.rag.EmbeddingClient"), \
             patch("nanobot.cli.rag.RerankerClient"):

            result = self.runner.invoke(app, ["rag", "search", "query"])
            self.assertEqual(result.exit_code, 1)
            self.assertIn("Erro no subsistema de embedding", result.output)
            self.assertIn("Connection refused", result.output)

    def test_rag_search_cli_short_options(self) -> None:
        """Verify CLI search using short options (-f, -k, -c)."""
        mock_pipeline = MagicMock()
        mock_pipeline.search.return_value = ["dummy_result"]
        mock_pipeline.format_markdown.return_value = "### [1] Derivadas"

        with patch("nanobot.cli.rag.RetrievalPipeline", return_value=mock_pipeline), \
             patch("nanobot.cli.rag.RagStore"), \
             patch("nanobot.cli.rag.EmbeddingClient"), \
             patch("nanobot.cli.rag.RerankerClient"):

            result = self.runner.invoke(
                app,
                ["rag", "search", "derivada", "-f", "calculo_2", "-k", "3", "-c", "15"],
            )

            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertIn("### [1] Derivadas", result.output)
            mock_pipeline.search.assert_called_once_with(
                query="derivada",
                folder="calculo_2",
                top_k=3,
                candidate_k=15,
            )

    def test_rag_search_cli_missing_query_fails(self) -> None:
        """Verify omitting the required query argument fails with non-zero exit code."""
        result = self.runner.invoke(app, ["rag", "search"])
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()

