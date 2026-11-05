"""
JARVIS retrieval core — "one core, two adapters".

This package is a self-contained, swappable retrieval asset:

    chunker  -> embedder -> store -> retrieve -> observe

Nothing here imports Flask, the event store, or ``claude.py``; the dependency
arrow points one way, so the same core is consumed unchanged by two adapters: the
JARVIS context hook (``app/core/claude.py``) and a Model Context Protocol server
(``app/rag/mcp_server.py``) that exposes the same ``retrieve()`` path as a
``search`` tool. The public surface is intentionally small: ``build_index`` to
(re)index a corpus into a fresh, inactive collection, and ``RagService`` to query
the active one with citations, abstention and auditing.
"""

from __future__ import annotations

import os

from app.rag.chunker import Chunk, chunk_document, content_hash
from app.rag.embedder import Embedder, HashingEmbedder, OpenAIEmbedder, default_embedder
from app.rag.observe import AuditLog, QueryRecord, record_from_result
from app.rag.retrieve import DEFAULT_MIN_SCORE, Hit, Result, retrieve
from app.rag.store import RagStore

__all__ = [
    "Chunk", "chunk_document", "content_hash",
    "Embedder", "HashingEmbedder", "OpenAIEmbedder", "default_embedder",
    "RagStore", "retrieve", "Result", "Hit", "DEFAULT_MIN_SCORE",
    "AuditLog", "QueryRecord", "record_from_result",
    "build_index", "RagService",
]


def _default_db_path() -> str:
    # Same /app/data convention as the event store and usage tracker.
    return os.environ.get("RAG_DB_PATH", "/app/data/rag.db")


def build_index(
    documents: list[dict],
    *,
    store: RagStore,
    embedder: Embedder | None = None,
    activate: bool = False,
) -> str:
    """
    Index ``documents`` into a NEW collection and return its id.

    Each document is a dict with ``text`` and ``source_id`` plus optional
    ``title``/``link``/``date``/``permission_tag``. The collection is written
    inactive; the caller activates it only after evals pass (safe rollback).
    """
    embedder = embedder or default_embedder()
    index_id = store.new_index(embedder.name)

    all_chunks: list[Chunk] = []
    for doc in documents:
        all_chunks.extend(
            chunk_document(
                doc["text"],
                source_id=doc["source_id"],
                title=doc.get("title", ""),
                link=doc.get("link", ""),
                date=doc.get("date", ""),
                permission_tag=doc.get("permission_tag", "owner"),
            )
        )
    if all_chunks:
        vectors = embedder.embed([c.text for c in all_chunks])
        store.upsert(index_id, all_chunks, vectors)
    if activate:
        store.activate(index_id)
    return index_id


class RagService:
    """
    Thin query facade over the active collection: retrieve + audit in one call.

    Adapters hold one of these. It owns the store, embedder and audit log so a
    caller just does ``svc.query("...")`` and gets a cited, audited ``Result``.
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        embedder: Embedder | None = None,
        audit_path: str | None = None,
    ):
        self.store = RagStore(db_path or _default_db_path())
        self.embedder = embedder or default_embedder()
        self.audit = AuditLog(audit_path or _default_db_path())

    def query(
        self,
        text: str,
        *,
        k: int = 5,
        permission_tags: list[str] | None = None,
        caller: str = "context_hook",
    ) -> Result:
        result = retrieve(
            text, store=self.store, embedder=self.embedder,
            k=k, permission_tags=permission_tags,
        )
        try:
            self.audit.write(record_from_result(result, caller=caller))
        except Exception:
            pass  # observability must never break the request path
        return result

    def close(self) -> None:
        self.store.close()
        self.audit.close()
