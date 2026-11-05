"""
Corpus loading and reindexing.

Reads a manifest + document files into the plain dicts ``build_index`` expects,
and provides the reindex routine that builds a new collection, evaluates it, and
only then promotes it. This is the "safe rollback" path in one place: build
inactive, gate on evals, flip the pointer.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.rag import RagStore, build_index
from app.rag.embedder import Embedder, default_embedder


def load_manifest(corpus_dir: str) -> list[dict]:
    """Load ``manifest.json`` and attach each document's text from its file."""
    root = Path(corpus_dir)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    documents: list[dict] = []
    for entry in manifest["documents"]:
        text = (root / entry["file"]).read_text(encoding="utf-8")
        documents.append(
            {
                "text": text,
                "source_id": entry["source_id"],
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "date": entry.get("date", ""),
                "permission_tag": entry.get("permission_tag", "owner"),
            }
        )
    return documents


def reindex(
    corpus_dir: str,
    *,
    store: RagStore,
    embedder: Embedder | None = None,
    gate=None,
    activate: bool = True,
) -> dict:
    """
    Build a new collection from ``corpus_dir`` and, if ``gate`` passes, promote it.

    ``gate`` is an optional callable ``(store, index_id) -> (ok: bool, metrics: dict)``.
    When it returns False the new collection is left inactive (the current one keeps
    serving), which is exactly the eval-gated promotion / safe-rollback behaviour.
    """
    embedder = embedder or default_embedder()
    documents = load_manifest(corpus_dir)
    index_id = build_index(documents, store=store, embedder=embedder, activate=False)

    metrics: dict = {}
    ok = True
    if gate is not None:
        ok, metrics = gate(store, index_id)

    promoted = False
    if ok and activate:
        store.activate(index_id)
        promoted = True

    return {
        "index_id": index_id,
        "documents": len(documents),
        "chunks": store.count(index_id),
        "promoted": promoted,
        "gate_passed": ok,
        "metrics": metrics,
    }


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Reindex a corpus into the RAG store.")
    parser.add_argument("corpus_dir")
    parser.add_argument("--db", default=os.environ.get("RAG_DB_PATH", "/app/data/rag.db"))
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args()

    store = RagStore(args.db)
    result = reindex(args.corpus_dir, store=store, activate=not args.no_activate)
    store.close()
    print(json.dumps(result, indent=2))
