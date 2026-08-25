"""RAG package for study notes."""

from nanobot.rag.client import EmbeddingClient, EmbeddingError
from nanobot.rag.config import StudyRagConfig
from nanobot.rag.markdown import Chunk, MarkdownParser, ParsedNote, compute_checksum, is_sync_conflict_file
from nanobot.rag.store import (
    DimensionMismatchError,
    RagStore,
    SearchResult,
    StoredChunk,
    StoredDocument,
    StoreStats,
)
from nanobot.rag.sync import SyncPipeline, SyncStats

__all__ = [
    "Chunk",
    "DimensionMismatchError",
    "EmbeddingClient",
    "EmbeddingError",
    "MarkdownParser",
    "ParsedNote",
    "RagStore",
    "SearchResult",
    "StoreStats",
    "StoredChunk",
    "StoredDocument",
    "StudyRagConfig",
    "SyncPipeline",
    "SyncStats",
    "compute_checksum",
    "is_sync_conflict_file",
]
