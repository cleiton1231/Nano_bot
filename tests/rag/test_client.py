"""Unit test suite for RAG EmbeddingClient."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from nanobot.rag.markdown import Chunk


class TestEmbeddingClient(unittest.TestCase):
    def setUp(self) -> None:
        from nanobot.rag.client import EmbeddingClient, EmbeddingError

        self.EmbeddingClient = EmbeddingClient
        self.EmbeddingError = EmbeddingError

    def test_embed_texts_success(self) -> None:
        client = self.EmbeddingClient(
            base_url="http://127.0.0.1:8082/v1/embeddings",
            model="Qwen3-Embedding-0.6B-Q8_0.gguf",
            dims=4,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "object": "list",
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
                {"index": 1, "embedding": [0.5, 0.6, 0.7, 0.8]},
            ],
        }

        with patch.object(client._http_client, "post", return_value=mock_resp) as mock_post:
            vectors = client.embed_texts(["Texto 1", "Texto 2"])
            self.assertEqual(len(vectors), 2)
            self.assertEqual(vectors[0], [0.1, 0.2, 0.3, 0.4])
            self.assertEqual(vectors[1], [0.5, 0.6, 0.7, 0.8])
            mock_post.assert_called_once()
        client.close()

    def test_embed_texts_reorders_out_of_order_indices(self) -> None:
        client = self.EmbeddingClient(dims=4)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Return index 1 before index 0
        mock_resp.json.return_value = {
            "object": "list",
            "data": [
                {"index": 1, "embedding": [0.5, 0.6, 0.7, 0.8]},
                {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
            ],
        }

        with patch.object(client._http_client, "post", return_value=mock_resp):
            vectors = client.embed_texts(["Primeiro", "Segundo"])
            self.assertEqual(vectors[0], [0.1, 0.2, 0.3, 0.4])
            self.assertEqual(vectors[1], [0.5, 0.6, 0.7, 0.8])
        client.close()

    def test_embed_chunks_empty_list(self) -> None:
        client = self.EmbeddingClient(dims=4)
        with patch.object(client._http_client, "post") as mock_post:
            res = client.embed_chunks([])
            self.assertEqual(res, [])
            mock_post.assert_not_called()
        client.close()

    def test_embed_chunks_dimension_mismatch(self) -> None:
        client = self.EmbeddingClient(dims=4)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "object": "list",
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},  # 2 dims instead of 4
            ],
        }

        chunk = Chunk(doc_path="a.md", chunk_index=0, heading=None, content="hello", token_count=5)
        with patch.object(client._http_client, "post", return_value=mock_resp):
            with self.assertRaises(self.EmbeddingError):
                client.embed_chunks([chunk])
        client.close()

    def test_embed_texts_network_error_raises_embedding_error(self) -> None:
        import httpx

        client = self.EmbeddingClient(dims=4)
        with patch.object(client._http_client, "post", side_effect=httpx.ConnectError("Connection refused")):
            with self.assertRaises(self.EmbeddingError):
                client.embed_texts(["teste"])
        client.close()

    def test_embed_texts_http_status_error_raises_embedding_error(self) -> None:
        import httpx

        client = self.EmbeddingClient(dims=4)
        req = httpx.Request("POST", "http://test")
        resp = httpx.Response(500, request=req)
        with patch.object(client._http_client, "post", side_effect=httpx.HTTPStatusError("500", request=req, response=resp)):
            with self.assertRaises(self.EmbeddingError):
                client.embed_texts(["teste"])
        client.close()

    def test_batching_partitioning(self) -> None:
        client = self.EmbeddingClient(dims=4, batch_size=2)
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = {
            "object": "list",
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
                {"index": 1, "embedding": [0.5, 0.6, 0.7, 0.8]},
            ],
        }
        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = {
            "object": "list",
            "data": [
                {"index": 0, "embedding": [0.9, 1.0, 1.1, 1.2]},
            ],
        }

        with patch.object(client._http_client, "post", side_effect=[mock_resp1, mock_resp2]) as mock_post:
            vectors = client.embed_texts(["1", "2", "3"])
            self.assertEqual(len(vectors), 3)
            self.assertEqual(mock_post.call_count, 2)
        client.close()


class TestAsyncEmbeddingClient(unittest.IsolatedAsyncioTestCase):
    async def test_async_embed_chunks(self) -> None:
        from nanobot.rag.client import EmbeddingClient

        client = EmbeddingClient(dims=4)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "object": "list",
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
            ],
        }

        async_client = client._get_async_client()
        with patch.object(async_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            chunk = Chunk(doc_path="b.md", chunk_index=0, heading=None, content="async test", token_count=4)
            res = await client.aembed_chunks([chunk])
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0][1], [0.1, 0.2, 0.3, 0.4])

        await client.aclose()
        client.close()


if __name__ == "__main__":
    unittest.main()
