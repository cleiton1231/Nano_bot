"""Unit test suite for RAG SyncPipeline."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from nanobot.rag.markdown import MarkdownParser
from nanobot.rag.store import RagStore


class TestSyncPipeline(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="rag_sync_test_")
        self.vault_dir = Path(self.temp_dir) / "faculdade"
        self.vault_dir.mkdir()
        self.db_file = Path(self.temp_dir) / "rag.db"

        self.store = RagStore(db_path=self.db_file, embedding_dims=4)
        self.store.init_db()

        self.parser = MarkdownParser()
        self.mock_client = MagicMock()
        # Default mock: returns 4d vector for each chunk
        self.mock_client.dims = 4

        def _embed_chunks_side_effect(chunks):
            return [(c, [0.1, 0.2, 0.3, 0.4]) for c in chunks]

        self.mock_client.embed_chunks.side_effect = _embed_chunks_side_effect

        from nanobot.rag.client import EmbeddingError
        from nanobot.rag.sync import SyncPipeline, SyncStats

        self.SyncPipeline = SyncPipeline
        self.SyncStats = SyncStats
        self.EmbeddingError = EmbeddingError

    def tearDown(self) -> None:
        self.store.close()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sync_fresh_vault(self) -> None:
        subfolder = self.vault_dir / "calculo_1"
        subfolder.mkdir()
        (subfolder / "limites.md").write_text("# Limites\nDefinição formal.", encoding="utf-8")
        (subfolder / "derivadas.md").write_text("# Derivadas\nTaxa de variação.", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        stats = pipeline.sync_notes(self.vault_dir)

        self.assertTrue(stats.is_success)
        self.assertEqual(stats.scanned_files, 2)
        self.assertEqual(stats.synced_docs, 2)
        self.assertEqual(stats.unchanged_docs, 0)
        self.assertEqual(stats.deleted_docs, 0)
        self.assertEqual(stats.failed_docs, 0)
        self.assertEqual(self.store.get_stats().document_count, 2)

    def test_sync_deep_folder_hierarchy(self) -> None:
        deep_dir = self.vault_dir / "2026" / "semestre_1" / "calculo"
        deep_dir.mkdir(parents=True)
        (deep_dir / "integrais.md").write_text("# Integrais\nCalculo de area.", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        stats = pipeline.sync_notes(self.vault_dir)

        self.assertTrue(stats.is_success)
        stored = self.store.get_document_by_path("2026/semestre_1/calculo/integrais.md")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.folder, "2026/semestre_1/calculo")

    def test_sync_incremental_skips_unchanged(self) -> None:
        file_path = self.vault_dir / "nota.md"
        file_path.write_text("# Nota\nConteudo estavel.", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        stats1 = pipeline.sync_notes(self.vault_dir)
        self.assertEqual(stats1.synced_docs, 1)

        # Second sync without touching file
        stats2 = pipeline.sync_notes(self.vault_dir)
        self.assertEqual(stats2.synced_docs, 0)
        self.assertEqual(stats2.unchanged_docs, 1)
        self.assertEqual(stats2.deleted_docs, 0)
        self.assertTrue(stats2.is_success)

    def test_sync_force_reindexes_unchanged(self) -> None:
        file_path = self.vault_dir / "nota.md"
        file_path.write_text("# Nota\nConteudo estavel.", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        stats1 = pipeline.sync_notes(self.vault_dir)
        self.assertEqual(stats1.synced_docs, 1)

        # Force sync should re-index even if checksum is identical
        stats2 = pipeline.sync_notes(self.vault_dir, force=True)
        self.assertEqual(stats2.synced_docs, 1)
        self.assertEqual(stats2.unchanged_docs, 0)
        self.assertTrue(stats2.is_success)

    def test_sync_incremental_updates_modified(self) -> None:
        file_path = self.vault_dir / "nota.md"
        file_path.write_text("# Nota\nVersao 1.", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        pipeline.sync_notes(self.vault_dir)

        # Modify file content
        file_path.write_text("# Nota\nVersao 2 com mudanca.", encoding="utf-8")
        stats = pipeline.sync_notes(self.vault_dir)
        self.assertEqual(stats.synced_docs, 1)
        self.assertEqual(stats.unchanged_docs, 0)

    def test_sync_deletes_removed_files(self) -> None:
        file_path = self.vault_dir / "remover.md"
        file_path.write_text("# Para Remover\nTexto.", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        pipeline.sync_notes(self.vault_dir)
        self.assertEqual(self.store.get_stats().document_count, 1)

        # Remove from disk
        file_path.unlink()
        stats = pipeline.sync_notes(self.vault_dir)
        self.assertEqual(stats.deleted_docs, 1)
        self.assertEqual(self.store.get_stats().document_count, 0)

    def test_sync_ignores_syncthing_conflict_files(self) -> None:
        (self.vault_dir / "calculo.md").write_text("# Calculo\nNormal.", encoding="utf-8")
        (self.vault_dir / "calculo.sync-conflict-20260825-153000-ABCDEF.md").write_text("# Conflito", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        stats = pipeline.sync_notes(self.vault_dir)
        self.assertEqual(stats.scanned_files, 1)
        self.assertEqual(stats.synced_docs, 1)
        self.assertEqual(self.store.get_stats().document_count, 1)

    def test_sync_empty_notes_handled(self) -> None:
        (self.vault_dir / "vazia.md").write_text("", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        stats = pipeline.sync_notes(self.vault_dir)
        self.assertEqual(stats.synced_docs, 1)
        self.assertEqual(stats.failed_docs, 0)
        # Empty note should NOT call embed_chunks
        self.mock_client.embed_chunks.assert_not_called()
        self.assertEqual(self.store.get_stats().document_count, 1)

    def test_sync_skip_and_log_on_embedding_failure(self) -> None:
        (self.vault_dir / "nota1.md").write_text("# Nota 1\nValida.", encoding="utf-8")
        (self.vault_dir / "nota2.md").write_text("# Nota 2\nFalha.", encoding="utf-8")
        (self.vault_dir / "nota3.md").write_text("# Nota 3\nValida.", encoding="utf-8")

        def _side_effect(chunks):
            if chunks and chunks[0].doc_path == "nota2.md":
                raise self.EmbeddingError("500 Server Error")
            return [(c, [0.1, 0.2, 0.3, 0.4]) for c in chunks]

        self.mock_client.embed_chunks.side_effect = _side_effect

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        stats = pipeline.sync_notes(self.vault_dir)

        self.assertFalse(stats.is_success)
        self.assertEqual(stats.scanned_files, 3)
        self.assertEqual(stats.synced_docs, 2)
        self.assertEqual(stats.failed_docs, 1)
        self.assertIn("nota2.md", stats.failed_paths)
        # Store has the 2 successful docs
        self.assertEqual(self.store.get_stats().document_count, 2)

    def test_sync_skip_and_log_on_read_oserror(self) -> None:
        (self.vault_dir / "nota_ok.md").write_text("# OK", encoding="utf-8")
        unreadable = self.vault_dir / "unreadable.md"
        unreadable.write_text("# Unreadable", encoding="utf-8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        with patch.object(Path, "read_text", side_effect=[OSError("Permission denied"), "# OK"]):
            stats = pipeline.sync_notes(self.vault_dir)
            self.assertFalse(stats.is_success)
            self.assertEqual(stats.failed_docs, 1)
            self.assertEqual(stats.synced_docs, 1)

    def test_sync_skip_and_log_on_unicode_decode_error(self) -> None:
        (self.vault_dir / "nota_valida.md").write_text("# Valida", encoding="utf-8")
        corrupted = self.vault_dir / "corrupted.md"
        # Write invalid UTF-8 bytes to disk
        corrupted.write_bytes(b"\x80\x81 invalid utf8")

        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        stats = pipeline.sync_notes(self.vault_dir)
        self.assertFalse(stats.is_success)
        self.assertEqual(stats.failed_docs, 1)
        self.assertIn("corrupted.md", stats.failed_paths)
        self.assertEqual(stats.synced_docs, 1)

    def test_sync_missing_vault_dir_aborts_without_deletion(self) -> None:
        # Pre-populate store
        (self.vault_dir / "nota.md").write_text("# Nota\nValida.", encoding="utf-8")
        pipeline = self.SyncPipeline(store=self.store, client=self.mock_client, parser=self.parser)
        pipeline.sync_notes(self.vault_dir)
        self.assertEqual(self.store.get_stats().document_count, 1)

        # Sync pointing to non-existent directory raises FileNotFoundError and does NOT wipe store
        non_existent = Path(self.temp_dir) / "pasta_fantasma"
        with self.assertRaises(FileNotFoundError):
            pipeline.sync_notes(non_existent)
        self.assertEqual(self.store.get_stats().document_count, 1)


if __name__ == "__main__":
    unittest.main()
