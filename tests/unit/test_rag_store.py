"""Unit tests for the versioned-collection vector store."""

from app.rag.chunker import Chunk
from app.rag.embedder import HashingEmbedder


def _chunks_and_vectors(embedder, specs):
    """specs: list of (text, source_id, permission_tag)."""
    chunks = [
        Chunk(text=t, source_id=s, ordinal=0, title=s, link=f"doc://{s}", permission_tag=p)
        for t, s, p in specs
    ]
    vectors = embedder.embed([c.text for c in chunks])
    return chunks, vectors


class TestCollections:
    def test_new_index_is_inactive(self, rag_store):
        idx = rag_store.new_index("hashing-v2-subword")
        assert rag_store.active_index() is None  # not active until flipped
        assert rag_store.count(idx) == 0

    def test_activate_flips_pointer(self, rag_store):
        a = rag_store.new_index("e")
        b = rag_store.new_index("e")
        rag_store.activate(a)
        assert rag_store.active_index() == a
        rag_store.activate(b)
        assert rag_store.active_index() == b  # only one active at a time

    def test_rollback_to_previous_collection(self, rag_store):
        e = HashingEmbedder()
        a = rag_store.new_index(e.name)
        c, v = _chunks_and_vectors(e, [("old content", "d", "owner")])
        rag_store.upsert(a, c, v)
        rag_store.activate(a)

        b = rag_store.new_index(e.name)
        c2, v2 = _chunks_and_vectors(e, [("new content", "d", "owner")])
        rag_store.upsert(b, c2, v2)
        rag_store.activate(b)
        assert rag_store.active_index() == b

        # rollback is a single pointer flip; old data is still intact
        rag_store.activate(a)
        assert rag_store.active_index() == a
        assert rag_store.count(a) == 1


class TestSearch:
    def test_topk_orders_by_similarity(self, rag_store):
        e = HashingEmbedder()
        idx = rag_store.new_index(e.name)
        c, v = _chunks_and_vectors(e, [
            ("routing layers escalate to sonnet", "routing", "owner"),
            ("event store data minimisation", "privacy", "owner"),
            ("docker railway deployment gunicorn", "deploy", "owner"),
        ])
        rag_store.upsert(idx, c, v)
        rag_store.activate(idx)

        q = e.embed(["how does routing escalate"])[0]
        hits = rag_store.search(q, k=3)
        assert hits[0][0].source_id == "routing"
        # scores are descending
        scores = [s for _, s in hits]
        assert scores == sorted(scores, reverse=True)

    def test_permission_filter_excludes_other_tags(self, rag_store):
        e = HashingEmbedder()
        idx = rag_store.new_index(e.name)
        c, v = _chunks_and_vectors(e, [
            ("owner visible routing content", "pub", "owner"),
            ("admin only routing content", "sec", "admin"),
        ])
        rag_store.upsert(idx, c, v)
        rag_store.activate(idx)

        q = e.embed(["routing content"])[0]
        owner_hits = rag_store.search(q, k=5, permission_tags=["owner"])
        assert {h[0].source_id for h in owner_hits} == {"pub"}  # admin chunk filtered out

    def test_search_empty_store_returns_empty(self, rag_store):
        assert rag_store.search([0.1] * 10, k=5) == []
