"""
Retrieval: the one public entry point the adapters call.

``retrieve(query)`` embeds the query, runs cosine top-k over the active
collection (filtered to the caller's permission tags), and applies a confidence
threshold. Below threshold it returns an explicit *abstain* decision — the
"I don't know" path — rather than low-relevance chunks, so the assistant never
answers off weak matches. Every result carries its chunks' citations and a
timing so the caller can log and display provenance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.rag.chunker import Chunk
from app.rag.embedder import Embedder, default_embedder
from app.rag.store import RagStore

# Below this cosine score the top hit is treated as "no real match" and the
# retriever abstains. Calibrated for the offline HashingEmbedder against the
# demo corpus (off-topic queries score ~0.05–0.10, on-topic ~0.3+); the
# retrieval eval in CI is what keeps this honest when the corpus changes.
DEFAULT_MIN_SCORE = 0.175


@dataclass
class Hit:
    chunk: Chunk
    score: float


@dataclass
class Result:
    query: str
    hits: list[Hit] = field(default_factory=list)
    decision: str = "answer"          # "answer" | "abstain"
    elapsed_ms: float = 0.0
    index_id: str | None = None

    @property
    def answerable(self) -> bool:
        return self.decision == "answer" and bool(self.hits)

    @property
    def citations(self) -> list[dict]:
        """De-duplicated citations, best score first, for display."""
        seen: set = set()
        out: list[dict] = []
        for h in self.hits:
            key = (h.chunk.title, h.chunk.link)
            if key in seen:
                continue
            seen.add(key)
            out.append(h.chunk.citation)
        return out


def retrieve(
    query: str,
    *,
    store: RagStore,
    embedder: Embedder | None = None,
    k: int = 5,
    min_score: float = DEFAULT_MIN_SCORE,
    permission_tags: list[str] | None = None,
    index_id: str | None = None,
) -> Result:
    """Embed, search, threshold. Pure read path — never mutates the store.

    ``index_id`` defaults to the active collection; pass one to query a specific
    (e.g. not-yet-promoted) collection, which is how the eval gate scores a new
    index before it goes live.
    """
    embedder = embedder or default_embedder()
    started = time.perf_counter()

    if not query or not query.strip():
        return Result(query=query, decision="abstain",
                      elapsed_ms=(time.perf_counter() - started) * 1000)

    index_id = index_id or store.active_index()
    qvec = embedder.embed([query])[0]
    raw = store.search(qvec, k=k, index_id=index_id, permission_tags=permission_tags)
    hits = [Hit(chunk=c, score=s) for c, s in raw]

    decision = "answer" if hits and hits[0].score >= min_score else "abstain"
    elapsed_ms = (time.perf_counter() - started) * 1000
    return Result(query=query, hits=hits, decision=decision,
                  elapsed_ms=elapsed_ms, index_id=index_id)
