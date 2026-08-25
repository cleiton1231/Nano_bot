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


class TestRerankerClient(unittest.TestCase):
    def setUp(self) -> None:
        from nanobot.rag.client import RerankerClient, RerankerError

        self.RerankerClient = RerankerClient
        self.RerankerError = RerankerError

    def test_rerank_success_sync(self) -> None:
        """Verify successful synchronous reranking parsing index and relevance scores."""
        client = self.RerankerClient(
            base_url="http://127.0.0.1:8081/v1/rerank",
            model="ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.998, "document": {"text": "Doc 0"}},
                {"index": 1, "relevance_score": 0.001, "document": {"text": "Doc 1"}},
            ]
        }

        with patch.object(client._http_client, "post", return_value=mock_resp) as mock_post:
            results = client.rerank(
                query="o que é limite",
                documents=["Doc 0", "Doc 1"],
                top_n=2,
            )
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["index"], 0)
            self.assertAlmostEqual(results[0]["relevance_score"], 0.998, places=3)
            self.assertEqual(results[1]["index"], 1)
            self.assertAlmostEqual(results[1]["relevance_score"], 0.001, places=3)
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args.kwargs
            self.assertEqual(call_kwargs["json"]["query"], "o que é limite")
            self.assertEqual(call_kwargs["json"]["documents"], ["Doc 0", "Doc 1"])
            self.assertEqual(call_kwargs["json"]["top_n"], 2)
        client.close()

    def test_rerank_empty_documents_short_circuit(self) -> None:
        """Verify empty documents list short-circuits without triggering HTTP request."""
        client = self.RerankerClient()
        with patch.object(client._http_client, "post") as mock_post:
            results = client.rerank(query="teste", documents=[])
            self.assertEqual(results, [])
            mock_post.assert_not_called()
        client.close()

    def test_rerank_http_status_error_raises_reranker_error(self) -> None:
        """Verify HTTP 500 error from rerank server raises RerankerError."""
        import httpx

        client = self.RerankerClient()
        req = httpx.Request("POST", "http://test")
        resp = httpx.Response(500, request=req)
        with patch.object(client._http_client, "post", side_effect=httpx.HTTPStatusError("500", request=req, response=resp)):
            with self.assertRaises(self.RerankerError):
                client.rerank(query="teste", documents=["doc 1"])
        client.close()

    def test_rerank_network_error_raises_reranker_error(self) -> None:
        """Verify network connection failure raises RerankerError."""
        import httpx

        client = self.RerankerClient()
        with patch.object(client._http_client, "post", side_effect=httpx.ConnectError("Connection refused")):
            with self.assertRaises(self.RerankerError):
                client.rerank(query="teste", documents=["doc 1"])
        client.close()

    def test_rerank_malformed_json_raises_reranker_error(self) -> None:
        """Verify malformed JSON or missing results list raises RerankerError."""
        client = self.RerankerClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"not_results": []}

        with patch.object(client._http_client, "post", return_value=mock_resp):
            with self.assertRaises(self.RerankerError):
                client.rerank(query="teste", documents=["doc 1"])
        client.close()

    def test_rerank_missing_relevance_score_key_raises_reranker_error(self) -> None:
        """Verify response items missing 'relevance_score' trigger RerankerError."""
        client = self.RerankerClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"index": 0, "document": {"text": "conteúdo sem score"}}
            ]
        }

        with patch.object(client._http_client, "post", return_value=mock_resp):
            with self.assertRaises(self.RerankerError) as ctx:
                client.rerank(query="teste", documents=["conteúdo"])
            self.assertIn("relevance_score", str(ctx.exception).lower())
        client.close()

    def test_rerank_missing_index_key_raises_reranker_error(self) -> None:
        """Verify response items missing 'index' trigger RerankerError."""
        client = self.RerankerClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"relevance_score": 0.95, "document": {"text": "conteúdo sem index"}}
            ]
        }

        with patch.object(client._http_client, "post", return_value=mock_resp):
            with self.assertRaises(self.RerankerError) as ctx:
                client.rerank(query="teste", documents=["conteúdo"])
            self.assertIn("index", str(ctx.exception).lower())
        client.close()

    def test_rerank_boolean_index_raises_reranker_error(self) -> None:
        """Verify response items with boolean 'index' (e.g. True/False) trigger RerankerError."""
        client = self.RerankerClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"index": True, "relevance_score": 0.95}
            ]
        }

        with patch.object(client._http_client, "post", return_value=mock_resp):
            with self.assertRaises(self.RerankerError) as ctx:
                client.rerank(query="teste", documents=["doc 0", "doc 1"])
            self.assertIn("integer", str(ctx.exception).lower())
        client.close()

    def test_rerank_index_out_of_bounds_raises_reranker_error(self) -> None:
        """Verify item index out of bounds relative to input documents raises RerankerError."""
        client = self.RerankerClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"index": 5, "relevance_score": 0.95}  # only 1 document provided
            ]
        }


        with patch.object(client._http_client, "post", return_value=mock_resp):
            with self.assertRaises(self.RerankerError) as ctx:
                client.rerank(query="teste", documents=["doc 0"])
            self.assertIn("out of bounds", str(ctx.exception).lower())
        client.close()


class TestAsyncRerankerClient(unittest.IsolatedAsyncioTestCase):
    async def test_async_rerank_success(self) -> None:
        """Verify asynchronous rerank execution."""
        from nanobot.rag.client import RerankerClient

        client = RerankerClient()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"index": 0, "relevance_score": 0.88},
            ]
        }

        async_client = client._get_async_client()
        with patch.object(async_client, "post", new_callable=AsyncMock, return_value=mock_resp):
            res = await client.arerank(query="teste", documents=["doc 0"], top_n=1)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["index"], 0)
            self.assertAlmostEqual(res[0]["relevance_score"], 0.88, places=2)

        await client.aclose()
        client.close()


if __name__ == "__main__":
    unittest.main()

