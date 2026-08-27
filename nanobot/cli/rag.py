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
from nanobot.rag.sync import SyncPipeline

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


@rag_app.command("sync", help="Incrementally sync study notes vault into the vector store.")
def sync_notes_cmd(
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Re-embed all notes even if checksum matches the database.",
    ),
    config_file: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Custom configuration file path.",
    ),
) -> None:
    """Synchronize the read-only study notes vault into the local vector store."""
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
        ) as embed_client:
            store.init_db()
            pipeline = SyncPipeline(store=store, client=embed_client)
            stats = pipeline.sync_notes(notes_dir=rag_config.notes_dir, force=force)

            # Saída operacional: todos os campos de SyncStats, incluindo
            # total_chunks e duration_seconds (métricas úteis ao operador local).
            console.print(f"Arquivos escaneados: {stats.scanned_files}")
            console.print(f"Documentos sincronizados: {stats.synced_docs}")
            console.print(f"Documentos inalterados: {stats.unchanged_docs}")
            console.print(f"Documentos removidos: {stats.deleted_docs}")
            console.print(f"Documentos com falha: {stats.failed_docs}")
            console.print(f"Chunks indexados: {stats.total_chunks}")
            console.print(f"Duração: {stats.duration_seconds}s")

            for path in stats.failed_paths:
                console.print(path)

            if not stats.is_success:
                raise typer.Exit(1)
    except FileNotFoundError as err:
        console.print(f"[red]{err}[/red]")
        raise typer.Exit(1)
    except EmbeddingError as err:
        console.print(f"[red]Erro no subsistema de embedding (porta 8082):[/red] {err}")
        raise typer.Exit(1)
    except DimensionMismatchError as err:
        console.print(f"[red]Erro de dimensão no banco vetorial:[/red] {err}")
        raise typer.Exit(1)
    except Exception as err:
        console.print(f"[red]Erro inesperado na sincronização RAG:[/red] {err}")
        raise typer.Exit(1)

