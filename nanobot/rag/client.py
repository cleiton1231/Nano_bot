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
