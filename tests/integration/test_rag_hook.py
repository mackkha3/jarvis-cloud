"""
Integration tests for the RAG context hook in app/core/claude.py.

These exercise the adapter that injects retrieved context into the system
prompt: the feature-flag gate, citation injection, abstention, and the
fail-safe wrapper. The Claude API itself is never called — the hook is a pure
context transformation.
"""

from pathlib import Path

import pytest

import app.core.claude as claude
from app.rag import RagService
from app.rag.corpus import reindex

CORPUS = str(Path(__file__).resolve().parents[2] / "demo_corpus")


@pytest.fixture
def rag_enabled(monkeypatch, tmp_path):
    """Enable the flag and point the hook at an indexed throwaway service."""
    monkeypatch.setattr("app.config.features.is_enabled", lambda name: name == "rag")
    db = str(tmp_path / "hook.db")
    svc = RagService(db_path=db, audit_path=db)
    reindex(CORPUS, store=svc.store, embedder=svc.embedder, activate=True)
    monkeypatch.setattr(claude, "_rag_service", svc)
    yield svc
    svc.close()


class TestAugment:
    def test_flag_off_is_noop(self, monkeypatch):
        monkeypatch.setattr("app.config.features.is_enabled", lambda name: False)
        assert claude._augment_with_rag("how does routing work", "BASE") == "BASE"

    def test_on_topic_injects_cited_context(self, rag_enabled):
        out = claude._augment_with_rag(
            "how does the three layer routing escalate to sonnet", "BASE CONTEXT"
        )
        assert out.startswith("BASE CONTEXT")           # original context preserved
        assert "RETRIEVED KNOWLEDGE" in out
        assert "github.com/mackkha3" in out             # citation link present
        assert "[1]" in out                             # bracketed, citable

    def test_off_topic_abstains_unchanged(self, rag_enabled):
        out = claude._augment_with_rag("what is the capital of france", "BASE CONTEXT")
        assert out == "BASE CONTEXT"                     # nothing injected

    def test_no_base_context_still_works(self, rag_enabled):
        out = claude._augment_with_rag("how is retrieval quality measured", None)
        assert out is not None
        assert "RETRIEVED KNOWLEDGE" in out

    def test_records_an_audit_entry(self, rag_enabled):
        claude._augment_with_rag("how does routing escalate to sonnet", None)
        rows = rag_enabled.audit.recent(5)
        assert rows and rows[0]["caller"] == "context_hook"

    def test_failure_is_swallowed(self, monkeypatch):
        monkeypatch.setattr("app.config.features.is_enabled", lambda name: name == "rag")

        class Boom:
            def query(self, *a, **k):
                raise RuntimeError("retrieval exploded")

        monkeypatch.setattr(claude, "_rag_service", Boom())
        # must return the original context rather than propagating the error
        assert claude._augment_with_rag("anything", "BASE") == "BASE"
