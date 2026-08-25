"""Unit test suite for SQLite vector store with sqlite-vec extension."""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from nanobot.rag.markdown import Chunk, ParsedNote


class TestRagStore(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="rag_store_test_")
        self.db_file = Path(self.temp_dir) / "test_rag.db"
        from nanobot.rag.store import (
            DimensionMismatchError,
            RagStore,
            SearchResult,
            StoredChunk,
            StoredDocument,
            StoreStats,
        )

        self.RagStore = RagStore
        self.DimensionMismatchError = DimensionMismatchError

    def tearDown(self) -> None:
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _sample_note(
        self,
        path: str = "calculo_1/limites.md",
        folder: str = "calculo_1",
        title: str = "Limites e Continuidade",
        content: str = "Definição formal de limites.",
        checksum: str = "a" * 64,
    ) -> ParsedNote:
        return ParsedNote(
            path=path,
            folder=folder,
            title=title,
            updated_at=datetime.now(timezone.utc).isoformat(),
            checksum=checksum,
            frontmatter={"tags": ["matematica", "calculo"]},
            raw_content=content,
            clean_content=content,
        )

    def _sample_chunks(
        self,
        doc_path: str = "calculo_1/limites.md",
        dims: int = 1024,
    ) -> list[tuple[Chunk, list[float]]]:
        c1 = Chunk(
            doc_path=doc_path,
            chunk_index=0,
            heading="Definição de Limite",
            content="Texto sobre definição de limite e vizinhanças.",
            token_count=50,
        )
        c2 = Chunk(
            doc_path=doc_path,
            chunk_index=1,
            heading="Teorema do Confronto",
            content="Texto sobre teorema do confronto ou sanduíche.",
            token_count=60,
        )
        vec1 = [0.0] * dims
        vec1[0] = 1.0
        vec2 = [0.0] * dims
        vec2[1] = 1.0
        return [(c1, vec1), (c2, vec2)]

    def test_init_db_creates_schema_and_meta(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store:
            store.init_db()
            stats = store.get_stats()
            self.assertEqual(stats.document_count, 0)
            self.assertEqual(stats.chunk_count, 0)
            self.assertEqual(stats.embedding_dims, 1024)

    def test_init_db_in_memory(self) -> None:
        with self.RagStore(db_path=":memory:", embedding_dims=1024) as store:
            store.init_db()
            stats = store.get_stats()
            self.assertEqual(stats.document_count, 0)
            self.assertEqual(stats.embedding_dims, 1024)

    def test_save_document_atomic_upsert(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store:
            store.init_db()
            note = self._sample_note()
            chunks = self._sample_chunks()

            doc_id = store.save_document(note, chunks)
            self.assertIsInstance(doc_id, int)
            self.assertGreater(doc_id, 0)

            stats = store.get_stats()
            self.assertEqual(stats.document_count, 1)
            self.assertEqual(stats.chunk_count, 2)

            stored_doc = store.get_document_by_path("calculo_1/limites.md")
            self.assertIsNotNone(stored_doc)
            assert stored_doc is not None
            self.assertEqual(stored_doc.title, "Limites e Continuidade")
            self.assertEqual(stored_doc.folder, "calculo_1")
            self.assertIsNotNone(stored_doc.chunks)
            assert stored_doc.chunks is not None
            self.assertEqual(len(stored_doc.chunks), 2)

    def test_save_document_replaces_old_chunks_without_orphans(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store:
            store.init_db()
            note = self._sample_note()
            chunks = self._sample_chunks()

            store.save_document(note, chunks)
            stats1 = store.get_stats()
            self.assertEqual(stats1.chunk_count, 2)

            # Update note with only 1 new chunk
            new_chunk = Chunk(
                doc_path="calculo_1/limites.md",
                chunk_index=0,
                heading="Novo Cabeçalho Único",
                content="Apenas um chunk atualizado.",
                token_count=30,
            )
            new_vec = [0.0] * 1024
            new_vec[2] = 1.0
            note.checksum = "b" * 64

            store.save_document(note, [(new_chunk, new_vec)])
            stats2 = store.get_stats()
            self.assertEqual(stats2.document_count, 1)
            self.assertEqual(stats2.chunk_count, 1)

            # Directly query virtual table to ensure no orphan vector remains
            conn = store._get_connection()
            vec_count = conn.execute("SELECT count(*) FROM rag_vec_chunks").fetchone()[0]
            self.assertEqual(vec_count, 1)

    def test_delete_document_removes_relational_and_vector_data(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store:
            store.init_db()
            note = self._sample_note()
            chunks = self._sample_chunks()
            store.save_document(note, chunks)

            deleted = store.delete_document("calculo_1/limites.md")
            self.assertTrue(deleted)

            stats = store.get_stats()
            self.assertEqual(stats.document_count, 0)
            self.assertEqual(stats.chunk_count, 0)

            # Confirm vec0 virtual table has 0 rows
            conn = store._get_connection()
            vec_count = conn.execute("SELECT count(*) FROM rag_vec_chunks").fetchone()[0]
            self.assertEqual(vec_count, 0)

            # Deleting non-existent document returns False
            self.assertFalse(store.delete_document("nao_existe.md"))

    def test_search_knn_cosine_similarity(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store:
            store.init_db()
            note = self._sample_note()
            chunks = self._sample_chunks()
            store.save_document(note, chunks)

            # Query identical to c1 vector (dimension 0 = 1.0)
            query_vec = [0.0] * 1024
            query_vec[0] = 1.0

            results = store.search_knn(query_vec, top_k=5)
            self.assertEqual(len(results), 2)
            # Top-1 result should be chunk 0 with similarity ≈ 1.0 (distance ≈ 0.0)
            self.assertEqual(results[0].chunk_index, 0)
            self.assertEqual(results[0].heading, "Definição de Limite")
            self.assertAlmostEqual(results[0].similarity, 1.0, places=4)
            self.assertAlmostEqual(results[0].distance, 0.0, places=4)

            # Top-2 result is orthogonal (dim 1 = 1.0), similarity ≈ 0.0 (distance ≈ 1.0)
            self.assertEqual(results[1].chunk_index, 1)
            self.assertAlmostEqual(results[1].similarity, 0.0, places=4)
            self.assertAlmostEqual(results[1].distance, 1.0, places=4)

    def test_search_knn_with_folder_filter(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store:
            store.init_db()
            note1 = self._sample_note(path="calculo/nota1.md", folder="calculo")
            note2 = self._sample_note(path="fisica/nota2.md", folder="fisica")

            vec = [0.0] * 1024
            vec[0] = 1.0
            c1 = Chunk(doc_path="calculo/nota1.md", chunk_index=0, heading="C1", content="Calculo", token_count=10)
            c2 = Chunk(doc_path="fisica/nota2.md", chunk_index=0, heading="F1", content="Fisica", token_count=10)

            store.save_document(note1, [(c1, vec)])
            store.save_document(note2, [(c2, vec)])

            # Search with folder filter
            results_calculo = store.search_knn(vec, top_k=5, folder="calculo")
            self.assertEqual(len(results_calculo), 1)
            self.assertEqual(results_calculo[0].folder, "calculo")
            self.assertEqual(results_calculo[0].doc_path, "calculo/nota1.md")

            results_fisica = store.search_knn(vec, top_k=5, folder="fisica")
            self.assertEqual(len(results_fisica), 1)
            self.assertEqual(results_fisica[0].folder, "fisica")

    def test_dimension_mismatch_raises_error(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store1024:
            store1024.init_db()

        # Opening same DB expecting 2560 dims must raise DimensionMismatchError
        with self.RagStore(db_path=self.db_file, embedding_dims=2560) as store2560:
            with self.assertRaises(self.DimensionMismatchError):
                store2560.init_db()

    def test_recreate_schema_resets_database(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store1024:
            store1024.init_db()
            note = self._sample_note()
            chunks = self._sample_chunks()
            store1024.save_document(note, chunks)
            self.assertEqual(store1024.get_stats().document_count, 1)

        # Recreate DB with new dimensions
        with self.RagStore(db_path=self.db_file, embedding_dims=2560) as store2560:
            store2560.init_db(recreate=True)
            stats = store2560.get_stats()
            self.assertEqual(stats.document_count, 0)
            self.assertEqual(stats.embedding_dims, 2560)

    def test_list_documents(self) -> None:
        with self.RagStore(db_path=self.db_file, embedding_dims=1024) as store:
            store.init_db()
            note1 = self._sample_note(path="c1/n1.md", folder="c1")
            note2 = self._sample_note(path="c2/n2.md", folder="c2")
            chunks = self._sample_chunks()

            store.save_document(note1, chunks)
            store.save_document(note2, chunks)

            all_docs = store.list_documents()
            self.assertEqual(len(all_docs), 2)
            self.assertIsNone(all_docs[0].chunks)

            c1_docs = store.list_documents(folder="c1")
            self.assertEqual(len(c1_docs), 1)
            self.assertEqual(c1_docs[0].path, "c1/n1.md")


if __name__ == "__main__":
    unittest.main()
