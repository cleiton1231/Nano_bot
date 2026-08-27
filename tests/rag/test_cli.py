"""Unit test suite for nanobot rag CLI commands."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.rag.client import EmbeddingError, RerankerError
from nanobot.rag.sync import SyncStats


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

    # Saída humana de `nanobot rag sync`: imprime duration_seconds e total_chunks
    # (métricas operacionais úteis ao operador local); demais campos de SyncStats
    # também entram no resumo. Não omitir esses dois campos no print do comando.

    def _mock_rag_config(self) -> MagicMock:
        mock_config = MagicMock()
        rag_config = mock_config.tools.study_rag
        rag_config.notes_dir = "/tmp/faculdade"
        rag_config.db_path = "~/.nanobot/data/rag.db"
        rag_config.embedding_dims = 1024
        rag_config.embedding_url = "http://127.0.0.1:8082/v1/embeddings"
        rag_config.embedding_model = "Qwen3-Embedding-0.6B-Q8_0.gguf"
        rag_config.embedding_timeout = 30.0
        return mock_config

    def test_rag_sync_cli_success(self) -> None:
        """Verify successful CLI invocation of nanobot rag sync."""
        stats = SyncStats(
            scanned_files=3,
            synced_docs=2,
            unchanged_docs=1,
            deleted_docs=0,
            failed_docs=0,
            total_chunks=5,
            duration_seconds=1.234,
        )
        mock_pipeline = MagicMock()
        mock_pipeline.sync_notes.return_value = stats

        with patch("nanobot.cli.rag.load_config", return_value=self._mock_rag_config()), \
             patch("nanobot.cli.rag.SyncPipeline", return_value=mock_pipeline, create=True), \
             patch("nanobot.cli.rag.RagStore"), \
             patch("nanobot.cli.rag.EmbeddingClient"):

            result = self.runner.invoke(app, ["rag", "sync"])

            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertIn("Arquivos escaneados: 3", result.output)
            self.assertIn("Documentos sincronizados: 2", result.output)
            self.assertIn("Documentos inalterados: 1", result.output)
            self.assertIn("Documentos removidos: 0", result.output)
            self.assertIn("Documentos com falha: 0", result.output)
            self.assertIn("Chunks indexados: 5", result.output)
            self.assertIn("Duração: 1.234s", result.output)
            mock_pipeline.sync_notes.assert_called_once_with(
                notes_dir="/tmp/faculdade",
                force=False,
            )

    def test_rag_sync_cli_partial_failure_exits_1(self) -> None:
        """Verify partial sync failure exits with code 1 and lists failed paths."""
        stats = SyncStats(
            scanned_files=3,
            synced_docs=2,
            failed_docs=1,
            failed_paths=["calculo_1/quebrada.md"],
        )
        mock_pipeline = MagicMock()
        mock_pipeline.sync_notes.return_value = stats

        with patch("nanobot.cli.rag.load_config", return_value=self._mock_rag_config()), \
             patch("nanobot.cli.rag.SyncPipeline", return_value=mock_pipeline, create=True), \
             patch("nanobot.cli.rag.RagStore"), \
             patch("nanobot.cli.rag.EmbeddingClient"):

            result = self.runner.invoke(app, ["rag", "sync"])

            self.assertEqual(result.exit_code, 1, msg=result.output)
            self.assertIn("Documentos com falha: 1", result.output)
            self.assertIn("calculo_1/quebrada.md", result.output)

    def test_rag_sync_cli_force_flag(self) -> None:
        """Verify --force passes force=True to SyncPipeline.sync_notes."""
        stats = SyncStats(scanned_files=1, synced_docs=1)
        mock_pipeline = MagicMock()
        mock_pipeline.sync_notes.return_value = stats

        with patch("nanobot.cli.rag.load_config", return_value=self._mock_rag_config()), \
             patch("nanobot.cli.rag.SyncPipeline", return_value=mock_pipeline, create=True), \
             patch("nanobot.cli.rag.RagStore"), \
             patch("nanobot.cli.rag.EmbeddingClient"):

            result = self.runner.invoke(app, ["rag", "sync", "--force"])

            self.assertEqual(result.exit_code, 0, msg=result.output)
            mock_pipeline.sync_notes.assert_called_once_with(
                notes_dir="/tmp/faculdade",
                force=True,
            )

    def test_rag_sync_cli_missing_vault_exits_1(self) -> None:
        """Verify missing vault directory exits with code 1 and prints error message."""
        mock_pipeline = MagicMock()
        mock_pipeline.sync_notes.side_effect = FileNotFoundError(
            "Study notes vault directory not found: /tmp/faculdade"
        )

        with patch("nanobot.cli.rag.load_config", return_value=self._mock_rag_config()), \
             patch("nanobot.cli.rag.SyncPipeline", return_value=mock_pipeline, create=True), \
             patch("nanobot.cli.rag.RagStore"), \
             patch("nanobot.cli.rag.EmbeddingClient"):

            result = self.runner.invoke(app, ["rag", "sync"])

            self.assertEqual(result.exit_code, 1, msg=result.output)
            self.assertIn("vault directory not found", result.output)


class TestRagSyncCliIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def _mock_rag_config(self, notes_dir: str, db_path: str = ":memory:") -> MagicMock:
        mock_config = MagicMock()
        rag_config = mock_config.tools.study_rag
        rag_config.notes_dir = notes_dir
        rag_config.db_path = db_path
        rag_config.embedding_dims = 4
        rag_config.embedding_url = "http://127.0.0.1:8082/v1/embeddings"
        rag_config.embedding_model = "Qwen3-Embedding-0.6B-Q8_0.gguf"
        rag_config.embedding_timeout = 30.0
        return mock_config

    def test_rag_sync_cli_initializes_schema_on_fresh_memory_db(self) -> None:
        """First sync must init_db on an uninitialized store and complete without SQL errors."""
        with tempfile.TemporaryDirectory(prefix="rag_sync_cli_int_") as vault_dir:
            vault_path = Path(vault_dir)
            (vault_path / "intro.md").write_text(
                "# Introdução\n\nConteúdo de sanidade para sync CLI.",
                encoding="utf-8",
            )

            mock_embed = MagicMock()
            mock_embed.__enter__.return_value = mock_embed
            mock_embed.__exit__.return_value = False
            mock_embed.embed_chunks.side_effect = (
                lambda chunks: [(chunk, [0.1, 0.2, 0.3, 0.4]) for chunk in chunks]
            )

            with patch(
                "nanobot.cli.rag.load_config",
                return_value=self._mock_rag_config(notes_dir=vault_dir),
            ), patch("nanobot.cli.rag.EmbeddingClient", return_value=mock_embed):
                result = self.runner.invoke(app, ["rag", "sync"])

            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertIn("Arquivos escaneados: 1", result.output)
            self.assertIn("Documentos sincronizados: 1", result.output)
            self.assertIn("Documentos com falha: 0", result.output)
            self.assertNotIn("rag_documents", result.output)


if __name__ == "__main__":
    unittest.main()

