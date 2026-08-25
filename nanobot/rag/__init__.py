"""RAG package for study notes."""

from nanobot.rag.client import EmbeddingClient, EmbeddingError, RerankerClient, RerankerError
from nanobot.rag.config import StudyRagConfig
from nanobot.rag.markdown import Chunk, MarkdownParser, ParsedNote, compute_checksum, is_sync_conflict_file
from nanobot.rag.retrieval import RetrievalPipeline, RetrievedChunk
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
    "RerankerClient",
    "RerankerError",
    "RetrievalPipeline",
    "RetrievedChunk",
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

