"""SQLite vector store with sqlite-vec extension for university study notes."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlite_vec

from nanobot.rag.markdown import Chunk, ParsedNote


class DimensionMismatchError(Exception):
    """Raised when existing database vector dimensions mismatch the configured dimensions."""

    def __init__(self, db_dims: int, config_dims: int) -> None:
        super().__init__(
            f"Embedding dimension mismatch: SQLite store has {db_dims} dimensions, "
            f"but config requires {config_dims}. Reindex with recreate=True to reset schema."
        )
        self.db_dims = db_dims
        self.config_dims = config_dims


@dataclass
class StoredChunk:
    id: int
    doc_id: int
    chunk_index: int
    heading: str | None
    content: str
    token_count: int


@dataclass
class StoredDocument:
    id: int
    path: str
    folder: str
    title: str
    updated_at: str
    checksum: str
    frontmatter: dict[str, Any]
    created_at: str
    chunks: list[StoredChunk] | None = None


@dataclass
class SearchResult:
    chunk_id: int
    doc_path: str
    chunk_index: int
    folder: str
    title: str
    heading: str | None
    content: str
    token_count: int
    distance: float
    similarity: float


@dataclass
class StoreStats:
    document_count: int
    chunk_count: int
    embedding_dims: int
    db_size_bytes: int


class RagStore:
    """SQLite vector store managing relational metadata and sqlite-vec embeddings."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        embedding_dims: int = 1024,
    ) -> None:
        if str(db_path) == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = str(Path(db_path).expanduser().resolve())
        self.embedding_dims = int(embedding_dims)
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> "RagStore":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _connect(self) -> sqlite3.Connection:
        """Create and configure a new SQLite connection with sqlite-vec and WAL pragmas."""
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)

        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _get_connection(self) -> sqlite3.Connection:
        """Get or open active database connection."""
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _safe_rollback(self, conn: sqlite3.Connection) -> None:
        """Attempt transaction rollback without masking original exceptions."""
        try:
            conn.execute("ROLLBACK;")
        except sqlite3.Error:
            pass

    def init_db(self, recreate: bool = False) -> None:
        """Initialize database schema, tables, and virtual vec0 vector table."""
        conn = self._get_connection()

        if recreate:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DROP TABLE IF EXISTS rag_vec_chunks;")
                conn.execute("DROP TABLE IF EXISTS rag_chunks;")
                conn.execute("DROP TABLE IF EXISTS rag_documents;")
                conn.execute("DROP TABLE IF EXISTS rag_meta;")
                conn.execute("COMMIT")
            except Exception:
                self._safe_rollback(conn)
                raise

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE,
                    folder TEXT NOT NULL,
                    title TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    frontmatter_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_docs_checksum ON rag_documents(checksum);"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_docs_folder ON rag_documents(folder);"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id INTEGER NOT NULL REFERENCES rag_documents(id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    heading TEXT,
                    content TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    UNIQUE(doc_id, chunk_index)
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_id ON rag_chunks(doc_id);"
            )
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS rag_vec_chunks USING vec0(
                    chunk_id INTEGER PRIMARY KEY,
                    embedding FLOAT[{self.embedding_dims}] distance_metric=cosine
                );
                """
            )

            # Check and persist embedding dimension metadata
            row = conn.execute(
                "SELECT value FROM rag_meta WHERE key = 'embedding_dims';"
            ).fetchone()
            if row is not None:
                stored_dims = int(row["value"])
                if stored_dims != self.embedding_dims:
                    raise DimensionMismatchError(stored_dims, self.embedding_dims)
            else:
                conn.execute(
                    "INSERT INTO rag_meta(key, value) VALUES ('embedding_dims', ?);",
                    [str(self.embedding_dims)],
                )
                conn.execute(
                    "INSERT INTO rag_meta(key, value) VALUES ('schema_version', '1');"
                )

            conn.execute("COMMIT")
        except Exception:
            self._safe_rollback(conn)
            raise

    def save_document(
        self,
        doc: ParsedNote,
        chunks_with_embeddings: list[tuple[Chunk, list[float]]],
    ) -> int:
        """Atomically upsert document, relational chunks, and vector embeddings."""
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            frontmatter_json = json.dumps(doc.frontmatter, ensure_ascii=False)
            now_iso = datetime.now(timezone.utc).isoformat()

            existing = conn.execute(
                "SELECT id FROM rag_documents WHERE path = ?;", [doc.path]
            ).fetchone()

            if existing is not None:
                doc_id = int(existing["id"])
                conn.execute(
                    """
                    UPDATE rag_documents
                    SET folder = ?, title = ?, updated_at = ?, checksum = ?, frontmatter_json = ?
                    WHERE id = ?;
                    """,
                    [doc.folder, doc.title, doc.updated_at, doc.checksum, frontmatter_json, doc_id],
                )
                # Chesterton's Fence: SQLite virtual tables (vec0) do NOT support foreign keys
                # or ON DELETE CASCADE. We must delete rag_vec_chunks explicitly before
                # deleting relational chunks to prevent leaving orphan vector embeddings.
                conn.execute(
                    "DELETE FROM rag_vec_chunks WHERE chunk_id IN (SELECT id FROM rag_chunks WHERE doc_id = ?);",
                    [doc_id],
                )
                conn.execute("DELETE FROM rag_chunks WHERE doc_id = ?;", [doc_id])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO rag_documents(path, folder, title, updated_at, checksum, frontmatter_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    [doc.path, doc.folder, doc.title, doc.updated_at, doc.checksum, frontmatter_json, now_iso],
                )
                doc_id = int(cursor.lastrowid)

            for chunk, vec in chunks_with_embeddings:
                c_cursor = conn.execute(
                    """
                    INSERT INTO rag_chunks(doc_id, chunk_index, heading, content, token_count)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    [doc_id, chunk.chunk_index, chunk.heading, chunk.content, chunk.token_count],
                )
                chunk_id = int(c_cursor.lastrowid)
                conn.execute(
                    "INSERT INTO rag_vec_chunks(chunk_id, embedding) VALUES (?, ?);",
                    [chunk_id, sqlite_vec.serialize_float32(vec)],
                )

            conn.execute("COMMIT")
            return doc_id
        except Exception:
            self._safe_rollback(conn)
            raise

    def delete_document(self, path: str) -> bool:
        """Atomically delete a document, its chunks, and its vector embeddings."""
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT id FROM rag_documents WHERE path = ?;", [path]
            ).fetchone()
            if existing is None:
                self._safe_rollback(conn)
                return False

            doc_id = int(existing["id"])
            # Chesterton's Fence: SQLite virtual tables (vec0) do NOT support foreign keys
            # or ON DELETE CASCADE. We must delete rag_vec_chunks explicitly before
            # deleting relational chunks to prevent leaving orphan vector embeddings.
            conn.execute(
                "DELETE FROM rag_vec_chunks WHERE chunk_id IN (SELECT id FROM rag_chunks WHERE doc_id = ?);",
                [doc_id],
            )
            conn.execute("DELETE FROM rag_chunks WHERE doc_id = ?;", [doc_id])
            conn.execute("DELETE FROM rag_documents WHERE id = ?;", [doc_id])
            conn.execute("COMMIT")
            return True
        except Exception:
            self._safe_rollback(conn)
            raise

    def get_document_by_path(self, path: str) -> StoredDocument | None:
        """Retrieve stored document metadata and associated chunks."""
        conn = self._get_connection()
        doc_row = conn.execute(
            "SELECT * FROM rag_documents WHERE path = ?;", [path]
        ).fetchone()
        if doc_row is None:
            return None

        doc_id = int(doc_row["id"])
        chunk_rows = conn.execute(
            "SELECT * FROM rag_chunks WHERE doc_id = ? ORDER BY chunk_index ASC;",
            [doc_id],
        ).fetchall()

        chunks = [
            StoredChunk(
                id=int(r["id"]),
                doc_id=int(r["doc_id"]),
                chunk_index=int(r["chunk_index"]),
                heading=r["heading"],
                content=r["content"],
                token_count=int(r["token_count"]),
            )
            for r in chunk_rows
        ]

        try:
            frontmatter = json.loads(doc_row["frontmatter_json"] or "{}")
        except json.JSONDecodeError:
            frontmatter = {}

        return StoredDocument(
            id=doc_id,
            path=doc_row["path"],
            folder=doc_row["folder"],
            title=doc_row["title"],
            updated_at=doc_row["updated_at"],
            checksum=doc_row["checksum"],
            frontmatter=frontmatter,
            created_at=doc_row["created_at"],
            chunks=chunks,
        )

    def list_documents(self, folder: str | None = None) -> list[StoredDocument]:
        """List stored document metadata (without loading chunk bodies)."""
        conn = self._get_connection()
        if folder is not None:
            rows = conn.execute(
                "SELECT * FROM rag_documents WHERE folder = ? ORDER BY path ASC;",
                [folder],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM rag_documents ORDER BY path ASC;"
            ).fetchall()

        documents: list[StoredDocument] = []
        for r in rows:
            try:
                frontmatter = json.loads(r["frontmatter_json"] or "{}")
            except json.JSONDecodeError:
                frontmatter = {}
            documents.append(
                StoredDocument(
                    id=int(r["id"]),
                    path=r["path"],
                    folder=r["folder"],
                    title=r["title"],
                    updated_at=r["updated_at"],
                    checksum=r["checksum"],
                    frontmatter=frontmatter,
                    created_at=r["created_at"],
                    chunks=None,
                )
            )
        return documents

    def search_knn(
        self,
        query_vector: list[float],
        top_k: int = 10,
        folder: str | None = None,
    ) -> list[SearchResult]:
        """Perform KNN vector similarity search with cosine distance."""
        conn = self._get_connection()
        serialized_query = sqlite_vec.serialize_float32(query_vector)

        # Base query joining vector virtual table with relational chunks and documents
        sql = """
            SELECT
                v.chunk_id,
                v.distance,
                c.doc_id,
                c.chunk_index,
                c.heading,
                c.content,
                c.token_count,
                d.path AS doc_path,
                d.folder,
                d.title
            FROM rag_vec_chunks v
            JOIN rag_chunks c ON v.chunk_id = c.id
            JOIN rag_documents d ON c.doc_id = d.id
            WHERE v.embedding MATCH ?
              AND k = ?
        """
        params: list[Any] = [serialized_query]

        if folder is not None:
            # Over-fetch candidate pool to guarantee top_k after relational folder post-filtering
            fetch_k = max(top_k * 5, 50)
            sql += " AND d.folder = ? ORDER BY v.distance ASC LIMIT ?;"
            params.extend([fetch_k, folder, top_k])
        else:
            sql += " ORDER BY v.distance ASC;"
            params.append(top_k)

        rows = conn.execute(sql, params).fetchall()

        results: list[SearchResult] = []
        for r in rows:
            dist = float(r["distance"])
            similarity = max(0.0, min(1.0, 1.0 - dist))
            results.append(
                SearchResult(
                    chunk_id=int(r["chunk_id"]),
                    doc_path=r["doc_path"],
                    chunk_index=int(r["chunk_index"]),
                    folder=r["folder"],
                    title=r["title"],
                    heading=r["heading"],
                    content=r["content"],
                    token_count=int(r["token_count"]),
                    distance=dist,
                    similarity=similarity,
                )
            )
        return results

    def get_stats(self) -> StoreStats:
        """Compute summary statistics for the database."""
        conn = self._get_connection()
        doc_count = int(
            conn.execute("SELECT count(*) FROM rag_documents;").fetchone()[0]
        )
        chunk_count = int(
            conn.execute("SELECT count(*) FROM rag_chunks;").fetchone()[0]
        )

        db_size = 0
        if self.db_path != ":memory:" and os.path.exists(self.db_path):
            db_size = os.path.getsize(self.db_path)

        return StoreStats(
            document_count=doc_count,
            chunk_count=chunk_count,
            embedding_dims=self.embedding_dims,
            db_size_bytes=db_size,
        )

    def close(self) -> None:
        """Close active database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
