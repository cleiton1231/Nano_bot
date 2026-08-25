"""Two-stage retrieval pipeline (KNN + Reranker) for university study notes."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from nanobot.rag.client import EmbeddingClient, RerankerClient
from nanobot.rag.config import StudyRagConfig
from nanobot.rag.store import RagStore


@dataclass
class RetrievedChunk:
    """Represents a retrieved document chunk with vector distance and rerank score."""

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
    relevance_score: float


class RetrievalPipeline:
    """Orchestrates symmetric query embedding, KNN candidate over-fetch, and cross-encoder reranking."""

    def __init__(
        self,
        store: RagStore,
        embedding_client: EmbeddingClient,
        reranker_client: RerankerClient,
        config: StudyRagConfig | None = None,
    ) -> None:
        self.store = store
        self.embedding_client = embedding_client
        self.reranker_client = reranker_client
        self.config = config or StudyRagConfig()

    def search(
        self,
        query: str,
        folder: str | None = None,
        top_k: int | None = None,
        candidate_k: int | None = None,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        """Perform two-stage semantic search: KNN over-fetch followed by fine reranking.

        Follows read-only vault policy (no DDL/init_db), fail-fast reranking (Rule 13),
        and symmetric query embeddings (Rule 14).
        """
        if not query or not query.strip():
            return []

        # Rule 6 / Read-Only Policy: Never trigger DDL/init_db() on search.
        # If database file does not exist on disk, return empty results immediately.
        expanded_db_path = os.path.expanduser(str(self.store.db_path))
        if self.store.db_path != ":memory:" and not os.path.exists(expanded_db_path):
            return []

        effective_candidate_k = candidate_k if candidate_k is not None else self.config.candidate_k
        effective_top_k = top_k if top_k is not None else self.config.top_k
        effective_threshold = score_threshold if score_threshold is not None else self.config.score_threshold

        # 1. Symmetric query embedding (plain text, no instruction prefix)
        query_vectors = self.embedding_client.embed_texts([query])
        if not query_vectors:
            return []
        query_vector = query_vectors[0]

        # 2. Retrieve coarse candidates via KNN in sqlite-vec
        try:
            candidates = self.store.search_knn(
                query_vector=query_vector,
                top_k=effective_candidate_k,
                folder=folder,
            )
        except sqlite3.OperationalError:
            # Table missing or database uninitialized
            return []

        # 3. Short-circuit if no candidates found
        if not candidates:
            return []

        # 4. Rerank candidates using cross-encoder (porta 8081)
        # Clamp top_n to available candidate pool size
        effective_top_n = min(effective_top_k, len(candidates))
        candidate_texts = [c.content for c in candidates]

        # Propagates RerankerError on HTTP/network/timeout failure (fail-fast, Rule 13)
        rerank_results = self.reranker_client.rerank(
            query=query,
            documents=candidate_texts,
            top_n=effective_top_n,
        )

        # 5. Map scores back to relational candidates
        retrieved_items: list[RetrievedChunk] = []
        for item in rerank_results:
            idx = item["index"]
            score = item["relevance_score"]
            c = candidates[idx]
            retrieved_items.append(
                RetrievedChunk(
                    chunk_id=c.chunk_id,
                    doc_path=c.doc_path,
                    chunk_index=c.chunk_index,
                    folder=c.folder,
                    title=c.title,
                    heading=c.heading,
                    content=c.content,
                    token_count=c.token_count,
                    distance=c.distance,
                    similarity=c.similarity,
                    relevance_score=score,
                )
            )

        # 6. Apply score_threshold filter (if configured > 0.0)
        if effective_threshold > 0.0:
            retrieved_items = [r for r in retrieved_items if r.relevance_score >= effective_threshold]

        # 7. Sort by relevance_score descending
        retrieved_items.sort(key=lambda r: r.relevance_score, reverse=True)

        # 8. Limit to top_k
        return retrieved_items[:effective_top_k]

    def format_markdown(self, results: list[RetrievedChunk]) -> str:
        """Format retrieved notes into structured Markdown blocks for agent context (Rule 15)."""
        if not results:
            return "Nenhuma nota de estudo encontrada para a consulta."

        blocks: list[str] = []
        for i, r in enumerate(results, start=1):
            heading_text = r.heading if r.heading else "Introdução"
            blocks.append(
                f"### [{i}] {r.title} ({r.doc_path})\n"
                f"- **Seção**: {heading_text}\n"
                f"- **Relevância**: {r.relevance_score:.3f}\n"
                f"- **Trecho**:\n{r.content}"
            )

        return "\n\n".join(blocks)

