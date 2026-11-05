"""Unit tests for the RAG chunker — pure, deterministic, no I/O."""

import pytest

from app.rag.chunker import Chunk, chunk_document, content_hash


class TestContentHash:
    def test_stable_across_whitespace(self):
        a = content_hash("the  quick\n\nbrown fox")
        b = content_hash("the quick brown fox")
        assert a == b  # whitespace is normalised before hashing

    def test_differs_on_content(self):
        assert content_hash("alpha") != content_hash("beta")


class TestChunkDocument:
    def test_empty_input_yields_no_chunks(self):
        assert chunk_document("   \n\n  ", source_id="s") == []

    def test_short_doc_is_one_chunk_with_metadata(self):
        chunks = chunk_document(
            "A short document about routing.",
            source_id="routing", title="Routing", link="doc://r", date="2026-01-01",
        )
        assert len(chunks) == 1
        c = chunks[0]
        assert c.source_id == "routing"
        assert c.ordinal == 0
        assert c.citation == {"title": "Routing", "link": "doc://r", "date": "2026-01-01"}
        assert c.doc_hash == content_hash("A short document about routing.")

    def test_long_doc_splits_with_overlap(self):
        text = " ".join(f"word{i}" for i in range(400))
        chunks = chunk_document(text, source_id="s", chunk_words=100, overlap_words=20)
        assert len(chunks) > 1
        # ordinals are contiguous from zero
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))
        # consecutive chunks overlap: last words of one reappear in the next
        first_tail = chunks[0].text.split()[-20:]
        assert any(w in chunks[1].text.split() for w in first_tail)

    def test_overlap_not_smaller_than_chunk_raises(self):
        with pytest.raises(ValueError):
            chunk_document("x y z", source_id="s", chunk_words=10, overlap_words=10)

    def test_permission_tag_propagates(self):
        chunks = chunk_document("secret stuff", source_id="s", permission_tag="admin")
        assert chunks[0].permission_tag == "admin"

    def test_chunk_is_frozen(self):
        c = Chunk(text="t", source_id="s", ordinal=0)
        with pytest.raises(Exception):
            c.text = "mutated"  # frozen dataclass
