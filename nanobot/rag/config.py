"""Configuration models for study notes RAG subsystem."""

from __future__ import annotations

from pydantic import Field

from nanobot.config_base import Base


class StudyRagConfig(Base):
    """Configuration for study notes RAG pipeline and vector store."""

    enable: bool = True
    notes_dir: str = "faculdade"
    db_path: str = "~/.nanobot/data/rag.db"
    embedding_url: str = "http://127.0.0.1:8082/v1/embeddings"
    embedding_model: str = "Qwen3-Embedding-0.6B-Q8_0.gguf"
    embedding_dims: int = Field(default=1024, ge=1)
    reranker_url: str = "http://127.0.0.1:8081/v1/rerank"
    reranker_model: str = "ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF"
    top_k: int = Field(default=10, ge=1, le=100)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    chunk_max_tokens: int = Field(default=1500, ge=100, le=16384)
