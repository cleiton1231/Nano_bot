"""Search study notes tool for university study RAG."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.rag.client import EmbeddingClient, EmbeddingError, RerankerClient, RerankerError
from nanobot.rag.config import StudyRagConfig
from nanobot.rag.retrieval import RetrievalPipeline
from nanobot.rag.store import DimensionMismatchError, RagStore


@tool_parameters(
    tool_parameters_schema(
        query=StringSchema(
            description="Termo de busca ou pergunta para pesquisar nas notas de estudo da faculdade.",
        ),
        folder=StringSchema(
            description="Pasta/disciplina específica para filtrar a busca (opcional, ex: 'calculo_1').",
            nullable=True,
        ),
        top_k=IntegerSchema(
            description="Quantidade máxima de notas/trechos a retornar (opcional, default 10).",
            minimum=1,
            maximum=100,
            nullable=True,
        ),
        required=["query"],
    )
)
class SearchStudyNotesTool(Tool):
    """Semantic search tool over university study notes vault with KNN and reranking."""

    name = "search_study_notes"
    description = (
        "Pesquisa semanticamente no vault de notas de estudo da faculdade, "
        "recuperando os trechos mais relevantes via busca vetorial e reranking."
    )
    read_only = True
    concurrency_safe = True
    config_key = "study_rag"
    _scopes = {"core", "subagent"}


    @classmethod
    def config_cls(cls) -> type[StudyRagConfig]:
        return StudyRagConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return bool(ctx.config.study_rag.enable)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(config=ctx.config.study_rag)

    def __init__(self, config: StudyRagConfig | None = None) -> None:
        self.config = config or StudyRagConfig()

    def _run_search(
        self,
        query: str,
        folder: str | None = None,
        top_k: int | None = None,
    ) -> str:
        """Run synchronous retrieval pipeline with deterministic context manager lifecycle."""
        with RagStore(
            db_path=self.config.db_path,
            embedding_dims=self.config.embedding_dims,
        ) as store, EmbeddingClient(
            base_url=self.config.embedding_url,
            model=self.config.embedding_model,
            dims=self.config.embedding_dims,
            timeout=self.config.embedding_timeout,
        ) as embed_client, RerankerClient(
            base_url=self.config.reranker_url,
            model=self.config.reranker_model,
            timeout=self.config.reranker_timeout,
        ) as rerank_client:
            pipeline = RetrievalPipeline(
                store=store,
                embedding_client=embed_client,
                reranker_client=rerank_client,
                config=self.config,
            )
            results = pipeline.search(
                query=query,
                folder=folder,
                top_k=top_k,
            )
            return pipeline.format_markdown(results)

    async def execute(
        self,
        query: str,
        folder: str | None = None,
        top_k: int | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        """Execute semantic search asynchronously via thread pool to avoid blocking the event loop."""
        norm_folder = str(folder).strip() if folder and str(folder).strip() else None
        norm_top_k = int(top_k) if top_k is not None and int(top_k) > 0 else None

        try:
            formatted_content = await asyncio.to_thread(
                self._run_search,
                query=query,
                folder=norm_folder,
                top_k=norm_top_k,
            )
            return ToolResult(content=formatted_content)
        except RerankerError as err:
            logger.warning("Reranker error during study notes search: {}", err)
            return ToolResult.error(f"Erro no subsistema de reranking: {err}")
        except EmbeddingError as err:
            logger.warning("Embedding error during study notes search: {}", err)
            return ToolResult.error(f"Erro no subsistema de embedding: {err}")
        except DimensionMismatchError as err:
            logger.error("Vector dimension mismatch: {}", err)
            return ToolResult.error(f"Incompatibilidade de dimensões no banco vetorial: {err}")
        except sqlite3.Error as err:
            logger.error("SQLite database error during search: {}", err)
            return ToolResult.error(f"Erro no banco de dados RAG: {err}")
        except Exception as err:
            logger.exception("Unexpected error in search_study_notes tool: {}", err)
            return ToolResult.error(f"Erro inesperado durante busca nas notas de estudo: {err}")

