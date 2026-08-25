"""RAG package for study notes."""

from nanobot.rag.config import StudyRagConfig
from nanobot.rag.markdown import Chunk, MarkdownParser, ParsedNote
from nanobot.rag.store import (
    DimensionMismatchError,
    RagStore,
    SearchResult,
    StoredChunk,
    StoredDocument,
    StoreStats,
)

__all__ = [
    "Chunk",
    "DimensionMismatchError",
    "MarkdownParser",
    "ParsedNote",
    "RagStore",
    "SearchResult",
    "StoreStats",
    "StoredChunk",
    "StoredDocument",
    "StudyRagConfig",
]
