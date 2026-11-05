"""Unit tests for the embedding backends."""

import numpy as np
import pytest

from app.rag.embedder import (
    Embedder,
    HashingEmbedder,
    OpenAIEmbedder,
    default_embedder,
)


def _cos(a, b):
    a, b = np.array(a), np.array(b)
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


class TestHashingEmbedder:
    def test_satisfies_protocol(self):
        assert isinstance(HashingEmbedder(), Embedder)

    def test_deterministic(self):
        e = HashingEmbedder()
        assert e.embed(["model routing layers"]) == e.embed(["model routing layers"])

    def test_dimension_and_l2_norm(self):
        e = HashingEmbedder(dim=256)
        v = np.array(e.embed(["some text here"])[0])
        assert v.shape == (256,)
        assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-5)

    def test_empty_text_is_zero_vector(self):
        v = np.array(HashingEmbedder().embed([""])[0])
        assert np.allclose(v, 0.0)

    def test_subword_overlap_beats_unrelated(self):
        e = HashingEmbedder()
        route, routing, banana = e.embed(["route"]), e.embed(["routing"]), e.embed(["banana"])
        # morphological variants share subword n-grams -> higher cosine
        assert _cos(route[0], routing[0]) > _cos(route[0], banana[0])

    def test_stopwords_do_not_dominate(self):
        e = HashingEmbedder()
        # two sentences differing only in stopwords embed identically
        assert e.embed(["routing of the layers"]) == e.embed(["routing layers"])


class TestOpenAIEmbedder:
    def test_import_is_lazy_no_network_on_construct(self):
        # Constructing must not import openai or hit the network.
        emb = OpenAIEmbedder(api_key="sk-fake")
        assert emb.name == "openai-text-embedding-3-small"
        assert emb.dim == 1536
        assert emb._client is None


class TestDefaultEmbedder:
    def test_defaults_to_hashing(self, monkeypatch):
        monkeypatch.setenv("RAG_EMBEDDER", "hashing")
        assert isinstance(default_embedder(), HashingEmbedder)

    def test_openai_without_key_falls_back_to_hashing(self, monkeypatch):
        monkeypatch.setenv("RAG_EMBEDDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "")
        assert isinstance(default_embedder(), HashingEmbedder)
