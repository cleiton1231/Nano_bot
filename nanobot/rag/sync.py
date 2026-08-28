"""Incremental synchronization pipeline for Obsidian study notes vault."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from nanobot.rag.client import EmbeddingClient, EmbeddingError
from nanobot.rag.markdown import (
    MarkdownParser,
    compute_checksum,
    is_sync_conflict_file,
)
from nanobot.rag.store import RagStore

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Summary statistics for vault synchronization."""

    scanned_files: int = 0
    synced_docs: int = 0
    unchanged_docs: int = 0
    deleted_docs: int = 0
    failed_docs: int = 0
    total_chunks: int = 0
    failed_paths: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def is_success(self) -> bool:
        """True if all candidate documents were synchronized without embedding failures."""
        return self.failed_docs == 0


class SyncPipeline:
    """Orchestrates read-only vault scanning, incremental checksum comparison, and embedding."""

    def __init__(
        self,
        store: RagStore,
        client: EmbeddingClient,
        parser: MarkdownParser | None = None,
    ) -> None:
        self.store = store
        self.client = client
        self.parser = parser or MarkdownParser()

    def sync_notes(
        self,
        notes_dir: str | Path,
        force: bool = False,
    ) -> SyncStats:
        """Synchronize notes directory with SQLite vector store.
        
        Follows read-only vault policy (Rule 10) and skip-and-log error policy (Rule 11).
        """
        start_time = time.perf_counter()
        stats = SyncStats()

        notes_path = Path(notes_dir).expanduser().resolve()
        if not notes_path.exists() or not notes_path.is_dir():
            raise FileNotFoundError(f"Study notes vault directory not found: {notes_path}")

        # Scan all .md files in the vault (excluding Syncthing sync-conflict files)
        disk_files: list[Path] = []
        disk_rel_map: dict[str, Path] = {}

        for p in notes_path.rglob("*.md"):
            if not p.is_file():
                continue
            if is_sync_conflict_file(p):
                logger.debug("Skipping Syncthing conflict file: %s", p)
                continue

            resolved = p.resolve()
            if not resolved.is_relative_to(notes_path):
                logger.warning(
                    "Skipping path escaping notes_dir (symlink or traversal): %s -> %s",
                    p,
                    resolved,
                )
                continue

            rel_posix = p.relative_to(notes_path).as_posix()
            disk_files.append(p)
            disk_rel_map[rel_posix] = p

        stats.scanned_files = len(disk_files)

        # 1. Detect and handle deleted documents
        existing_docs = self.store.list_documents()
        for doc in existing_docs:
            if doc.path not in disk_rel_map:
                logger.info("Removing deleted document from index: %s", doc.path)
                if self.store.delete_document(doc.path):
                    stats.deleted_docs += 1

        # 2. Process existing or new disk files
        for rel_path, file_path in disk_rel_map.items():
            try:
                # Strictly read-only file access (Rule 10) and strict UTF-8 decoding
                content = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as err:
                logger.warning("Failed to read/decode file %s: %s", file_path, err)
                stats.failed_paths.append(rel_path)
                stats.failed_docs += 1
                continue

            checksum = compute_checksum(content)

            # Incremental check: skip if file checksum matches database record
            if not force:
                stored_doc = self.store.get_document_by_path(rel_path)
                if stored_doc is not None and stored_doc.checksum == checksum:
                    stats.unchanged_docs += 1
                    continue

            rel_parent = file_path.relative_to(notes_path).parent.as_posix()
            folder = "" if rel_parent == "." else rel_parent

            note, chunks = self.parser.parse_note(
                path=rel_path,
                content=content,
                folder=folder,
            )

            # Short-circuit for empty notes or notes without text chunks
            if not chunks:
                self.store.save_document(note, [])
                stats.synced_docs += 1
                continue

            # Embed chunks with strict skip-and-log error isolation (Rule 11)
            try:
                chunks_with_embeddings = self.client.embed_chunks(chunks)
            except EmbeddingError as err:
                logger.warning("Failed to embed chunks for %s: %s", rel_path, err)
                stats.failed_paths.append(rel_path)
                stats.failed_docs += 1
                continue

            # Save relational metadata and vector embeddings atomically
            self.store.save_document(note, chunks_with_embeddings)
            stats.synced_docs += 1
            stats.total_chunks += len(chunks_with_embeddings)

        stats.duration_seconds = round(time.perf_counter() - start_time, 3)
        return stats
