"""OpenAI-compatible HTTP client for local embedding server (llama-server)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from nanobot.rag.markdown import Chunk


class EmbeddingError(Exception):
    """Raised when embedding API request fails, times out, or returns invalid vectors."""


class EmbeddingClient:
    """HTTP client for generating text embeddings via local llama-server."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8082/v1/embeddings",
        model: str = "Qwen3-Embedding-0.6B-Q8_0.gguf",
        dims: int = 1024,
        batch_size: int = 32,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.dims = int(dims)
        self.batch_size = max(1, int(batch_size))
        self.timeout = float(timeout)
        self._http_client: httpx.Client = httpx.Client(timeout=self.timeout)
        self._async_http_client: httpx.AsyncClient | None = None

    def __enter__(self) -> "EmbeddingClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close synchronous HTTP client connection pool."""
        self._http_client.close()

    async def aclose(self) -> None:
        """Close asynchronous HTTP client connection pool."""
        if self._async_http_client is not None:
            await self._async_http_client.aclose()
            self._async_http_client = None

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_http_client is None:
            self._async_http_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_http_client

    def _extract_and_validate_vectors(
        self,
        data: dict[str, Any],
        expected_count: int,
    ) -> list[list[float]]:
        """Validate and extract ordered vector list from embedding API response."""
        raw_data = data.get("data", [])
        if not isinstance(raw_data, list):
            raise EmbeddingError("Embedding server response 'data' field is not a list")

        # Sort safely by index to ensure ordering matches input batch
        def _get_index(x: Any) -> int:
            if isinstance(x, dict):
                idx = x.get("index")
                return idx if idx is not None and isinstance(idx, int) else 0
            return 0

        raw_data_sorted = sorted(raw_data, key=_get_index)

        if len(raw_data_sorted) != expected_count:
            raise EmbeddingError(
                f"Embedding server returned {len(raw_data_sorted)} items, expected {expected_count}"
            )

        vectors: list[list[float]] = []
        for item in raw_data_sorted:
            if not isinstance(item, dict):
                raise EmbeddingError("Embedding data item is not a dictionary")
            vec = item.get("embedding", [])
            if not isinstance(vec, list) or len(vec) != self.dims:
                raise EmbeddingError(
                    f"Embedding dimension mismatch: expected {self.dims}, got {len(vec) if isinstance(vec, list) else type(vec)}"
                )
            vectors.append(vec)

        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts in batches."""
        if not texts:
            return []

        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            payload = {
                "model": self.model,
                "input": batch,
            }
            try:
                resp = self._http_client.post(self.base_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                raise EmbeddingError(f"HTTP error {e.response.status_code} from embedding server: {e}") from e
            except httpx.RequestError as e:
                raise EmbeddingError(f"Network error connecting to embedding server: {e}") from e
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                raise EmbeddingError(f"Failed to parse embedding response JSON: {e}") from e

            all_vectors.extend(self._extract_and_validate_vectors(data, len(batch)))

        return all_vectors

    async def aembed_texts(self, texts: list[str]) -> list[list[float]]:
        """Asynchronously generate embeddings for a list of texts in batches."""
        if not texts:
            return []

        client = self._get_async_client()
        all_vectors: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            payload = {
                "model": self.model,
                "input": batch,
            }
            try:
                resp = await client.post(self.base_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                raise EmbeddingError(f"HTTP error {e.response.status_code} from embedding server: {e}") from e
            except httpx.RequestError as e:
                raise EmbeddingError(f"Network error connecting to embedding server: {e}") from e
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                raise EmbeddingError(f"Failed to parse embedding response JSON: {e}") from e

            all_vectors.extend(self._extract_and_validate_vectors(data, len(batch)))

        return all_vectors

    def embed_chunks(self, chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]:
        """Generate embeddings for Chunk objects, returning (Chunk, vector) pairs."""
        if not chunks:
            return []
        texts = [c.content for c in chunks]
        vectors = self.embed_texts(texts)
        return list(zip(chunks, vectors))

    async def aembed_chunks(self, chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]:
        """Asynchronously generate embeddings for Chunk objects."""
        if not chunks:
            return []
        texts = [c.content for c in chunks]
        vectors = await self.aembed_texts(texts)
        return list(zip(chunks, vectors))


class RerankerError(Exception):
    """Raised when reranking API request fails, times out, or returns invalid response."""


class RerankerClient:
    """HTTP client for reranking candidate documents via local llama-server (--rerank)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8081/v1/rerank",
        model: str = "ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF",
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.timeout = float(timeout)
        self._http_client: httpx.Client = httpx.Client(timeout=self.timeout)
        self._async_http_client: httpx.AsyncClient | None = None

    def __enter__(self) -> "RerankerClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close synchronous HTTP client connection pool."""
        self._http_client.close()

    async def aclose(self) -> None:
        """Close asynchronous HTTP client connection pool."""
        if self._async_http_client is not None:
            await self._async_http_client.aclose()
            self._async_http_client = None

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_http_client is None:
            self._async_http_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_http_client

    def _extract_and_validate_results(
        self,
        data: dict[str, Any],
        doc_count: int,
    ) -> list[dict[str, Any]]:
        """Validate and extract ordered result list from rerank API response."""
        if not isinstance(data, dict):
            raise RerankerError("Rerank response is not a JSON object")

        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            raise RerankerError("Rerank response 'results' field is missing or not a list")

        validated: list[dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                raise RerankerError("Rerank result item is not a dictionary")

            if "index" not in item:
                raise RerankerError("Rerank result item missing required 'index' key")
            if "relevance_score" not in item:
                raise RerankerError("Rerank result item missing required 'relevance_score' key")

            idx = item["index"]
            if isinstance(idx, bool) or not isinstance(idx, int):
                raise RerankerError(f"Rerank result 'index' must be integer, got {type(idx)}")
            if idx < 0 or idx >= doc_count:
                raise RerankerError(
                    f"Rerank result index {idx} out of bounds for document pool of size {doc_count}"
                )

            score = item["relevance_score"]
            try:
                score_float = float(score)
            except (ValueError, TypeError) as e:
                raise RerankerError(f"Invalid relevance_score '{score}': {e}") from e

            validated.append({
                "index": idx,
                "relevance_score": score_float,
                "document": item.get("document"),
            })

        return validated

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Rerank documents against a query string.

        Follows fail-fast policy (Rule 13) and short-circuits on empty documents.
        """
        if not documents:
            return []

        effective_top_n = min(top_n, len(documents)) if top_n is not None else len(documents)
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": effective_top_n,
        }

        try:
            resp = self._http_client.post(self.base_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise RerankerError(f"HTTP error {e.response.status_code} from rerank server: {e}") from e
        except httpx.RequestError as e:
            raise RerankerError(f"Network error connecting to rerank server: {e}") from e
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            raise RerankerError(f"Failed to parse rerank response JSON: {e}") from e

        return self._extract_and_validate_results(data, len(documents))

    async def arerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """Asynchronously rerank documents against a query string."""
        if not documents:
            return []

        effective_top_n = min(top_n, len(documents)) if top_n is not None else len(documents)
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": effective_top_n,
        }

        client = self._get_async_client()
        try:
            resp = await client.post(self.base_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            raise RerankerError(f"HTTP error {e.response.status_code} from rerank server: {e}") from e
        except httpx.RequestError as e:
            raise RerankerError(f"Network error connecting to rerank server: {e}") from e
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            raise RerankerError(f"Failed to parse rerank response JSON: {e}") from e

        return self._extract_and_validate_results(data, len(documents))
