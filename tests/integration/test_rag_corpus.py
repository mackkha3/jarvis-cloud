"""Integration tests for corpus loading and eval-gated reindexing/rollback."""

from pathlib import Path

from app.rag.corpus import load_manifest, reindex

CORPUS = str(Path(__file__).resolve().parents[2] / "demo_corpus")


class TestLoadManifest:
    def test_loads_documents_with_text_and_metadata(self):
        docs = load_manifest(CORPUS)
        assert len(docs) >= 10
        d = {x["source_id"]: x for x in docs}
        assert "routing" in d
        assert d["routing"]["text"].strip()            # file contents attached
        assert d["routing"]["link"].startswith("https://github.com/")


class TestReindex:
    def test_reindex_builds_and_promotes(self, rag_store):
        result = reindex(CORPUS, store=rag_store, activate=True)
        assert result["documents"] >= 10
        assert result["chunks"] >= result["documents"]
        assert result["promoted"] is True
        assert rag_store.active_index() == result["index_id"]

    def test_failing_gate_leaves_new_index_inactive(self, rag_store):
        # First good index, promoted.
        first = reindex(CORPUS, store=rag_store, activate=True)
        assert rag_store.active_index() == first["index_id"]

        # Second build with a gate that always fails -> must NOT be promoted,
        # and the previously-active index keeps serving (safe rollback).
        def failing_gate(store, index_id):
            return False, {"recall_at_5": 0.0}

        second = reindex(CORPUS, store=rag_store, gate=failing_gate, activate=True)
        assert second["gate_passed"] is False
        assert second["promoted"] is False
        assert rag_store.active_index() == first["index_id"]  # unchanged

    def test_passing_gate_promotes(self, rag_store):
        first = reindex(CORPUS, store=rag_store, activate=True)

        def passing_gate(store, index_id):
            return True, {"recall_at_5": 1.0}

        second = reindex(CORPUS, store=rag_store, gate=passing_gate, activate=True)
        assert second["promoted"] is True
        assert rag_store.active_index() == second["index_id"]
        assert second["index_id"] != first["index_id"]
