"""CLI commands for study notes RAG subsystem."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from nanobot.config.loader import load_config
from nanobot.rag.client import EmbeddingClient, EmbeddingError, RerankerClient, RerankerError
from nanobot.rag.config import StudyRagConfig
from nanobot.rag.retrieval import RetrievalPipeline
from nanobot.rag.store import DimensionMismatchError, RagStore

console = Console()
rag_app = typer.Typer(
    name="rag",
    help="Study notes RAG commands.",
    no_args_is_help=True,
)


@rag_app.command("search", help="Search study notes via vector KNN and reranking.")
def search_notes(
    query: str = typer.Argument(..., help="Query string to search in study notes."),
    folder: Optional[str] = typer.Option(
        None,
        "--folder",
        "-f",
        help="Filter by specific folder/discipline (e.g. 'calculo_1').",
    ),
    top_k: Optional[int] = typer.Option(
        None,
        "--top-k",
        "-k",
        help="Number of final reranked results to return.",
    ),
    candidate_k: Optional[int] = typer.Option(
        None,
        "--candidate-k",
        "-c",
        help="Number of coarse vector candidates to retrieve before reranking.",
    ),
    config_file: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Custom configuration file path.",
    ),
) -> None:
    """Execute semantic search against the study notes knowledge base."""
    config = load_config(config_file)
    rag_config: StudyRagConfig = config.tools.study_rag

    try:
        with RagStore(
            db_path=rag_config.db_path,
            embedding_dims=rag_config.embedding_dims,
        ) as store, EmbeddingClient(
            base_url=rag_config.embedding_url,
            model=rag_config.embedding_model,
            dims=rag_config.embedding_dims,
            timeout=rag_config.embedding_timeout,
        ) as embed_client, RerankerClient(
            base_url=rag_config.reranker_url,
            model=rag_config.reranker_model,
            timeout=rag_config.reranker_timeout,
        ) as rerank_client:
            pipeline = RetrievalPipeline(
                store=store,
                embedding_client=embed_client,
                reranker_client=rerank_client,
                config=rag_config,
            )
            results = pipeline.search(
                query=query,
                folder=folder,
                top_k=top_k,
                candidate_k=candidate_k,
            )
            formatted = pipeline.format_markdown(results)
            console.print(formatted)
    except RerankerError as err:
        console.print(f"[red]Erro no subsistema de reranking (porta 8081):[/red] {err}")
        raise typer.Exit(1)
    except EmbeddingError as err:
        console.print(f"[red]Erro no subsistema de embedding (porta 8082):[/red] {err}")
        raise typer.Exit(1)
    except DimensionMismatchError as err:
        console.print(f"[red]Erro de dimensão no banco vetorial:[/red] {err}")
        raise typer.Exit(1)
    except Exception as err:
        console.print(f"[red]Erro inesperado na busca RAG:[/red] {err}")
        raise typer.Exit(1)

