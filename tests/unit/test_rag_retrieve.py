"""Unit tests for the retrieve() read path: thresholding, abstain, citations."""

from app.rag.chunker import Chunk
from app.rag.embedder import HashingEmbedder
from app.rag.retrieve import Result, Hit, retrieve


def _seed(store, specs):
    e = HashingEmbedder()
    idx = store.new_index(e.name)
    chunks = [
        Chunk(text=t, source_id=s, ordinal=o, title=s, link=f"doc://{s}")
        for (t, s, o) in specs
    ]
    store.upsert(idx, chunks, e.embed([c.text for c in chunks]))
    store.activate(idx)
    return e


class TestThreshold:
    def test_on_topic_answers(self, rag_store):
        e = _seed(rag_store, [
            ("three layer routing escalates to sonnet for complex reasoning", "routing", 0),
            ("docker railway gunicorn deployment runtime", "deploy", 0),
        ])
        res = retrieve("how does the three layer routing escalate", store=rag_store, embedder=e)
        assert res.decision == "answer"
        assert res.answerable
        assert res.hits[0].chunk.source_id == "routing"

    def test_off_topic_abstains(self, rag_store):
        e = _seed(rag_store, [
            ("three layer routing escalates to sonnet", "routing", 0),
            ("docker railway gunicorn deployment", "deploy", 0),
        ])
        res = retrieve("recipe for banana bread with walnuts", store=rag_store, embedder=e)
        assert res.decision == "abstain"
        assert not res.answerable

    def test_empty_query_abstains(self, rag_store):
        e = _seed(rag_store, [("routing content", "routing", 0)])
        res = retrieve("   ", store=rag_store, embedder=e)
        assert res.decision == "abstain"
        assert res.hits == []


class TestResult:
    def test_citations_dedup_by_title_and_link(self):
        c1 = Chunk(text="a", source_id="s", ordinal=0, title="T", link="L")
        c2 = Chunk(text="b", source_id="s", ordinal=1, title="T", link="L")  # same doc
        c3 = Chunk(text="c", source_id="u", ordinal=0, title="U", link="M")
        r = Result(query="q", hits=[Hit(c1, 0.9), Hit(c2, 0.8), Hit(c3, 0.5)], decision="answer")
        cites = r.citations
        assert len(cites) == 2  # c1/c2 collapse to one
        assert cites[0] == {"title": "T", "link": "L", "date": ""}

    def test_elapsed_ms_is_populated(self, rag_store):
        e = _seed(rag_store, [("routing content here", "routing", 0)])
        res = retrieve("routing content", store=rag_store, embedder=e)
        assert res.elapsed_ms >= 0.0
        assert res.index_id is not None
