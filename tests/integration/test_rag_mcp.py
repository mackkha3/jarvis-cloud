"""
Tests for the MCP server adapter (app/rag/mcp_server.py).

Everything exercised here is the pure, SDK-free surface: the tool schema,
``handle_search``, and ``render_text``. The stdio entrypoint (``build_server`` /
``main``) is a thin wrapper around the ``mcp`` SDK and is intentionally not
imported, so these tests need neither the SDK nor a network — the same stance as
the rest of the suite.
"""

from pathlib import Path

import pytest

from app.rag import RagService
from app.rag.corpus import reindex
from app.rag.mcp_server import (
    SEARCH_TOOL_NAME,
    SEARCH_TOOL_SCHEMA,
    handle_search,
    render_text,
)

CORPUS = str(Path(__file__).resolve().parents[2] / "demo_corpus")


@pytest.fixture
def service(tmp_path):
    db = str(tmp_path / "mcp.db")
    svc = RagService(db_path=db, audit_path=db)
    reindex(CORPUS, store=svc.store, embedder=svc.embedder, activate=True)
    yield svc
    svc.close()


class TestToolSchema:
    def test_schema_is_well_formed(self):
        assert SEARCH_TOOL_SCHEMA["name"] == SEARCH_TOOL_NAME
        props = SEARCH_TOOL_SCHEMA["inputSchema"]["properties"]
        assert "query" in props and "k" in props and "permission_tags" in props
        assert SEARCH_TOOL_SCHEMA["inputSchema"]["required"] == ["query"]


class TestHandleSearch:
    def test_on_topic_returns_cited_results(self, service):
        out = handle_search({"query": "how does the three layer routing escalate to sonnet"},
                            service=service)
        assert out["decision"] == "answer"
        assert out["answerable"] is True
        assert out["results"], "expected at least one hit"
        top = out["results"][0]
        assert top["link"].startswith("https://github.com/")
        assert top["text"]
        assert out["citations"][0]["title"]

    def test_off_topic_abstains_with_no_results(self, service):
        out = handle_search({"query": "recipe for banana bread with walnuts"}, service=service)
        assert out["decision"] == "abstain"
        assert out["answerable"] is False
        assert out["results"] == []
        assert out["citations"] == []
        assert "message" in out

    def test_k_limits_result_count(self, service):
        out = handle_search({"query": "how is retrieval quality measured with recall", "k": 2},
                            service=service)
        assert len(out["results"]) <= 2

    def test_permission_tags_filter(self, service):
        # Nothing in the demo corpus is tagged 'nonexistent', so results are empty
        # -> abstain. Proves the tag filter is actually applied by the adapter.
        out = handle_search(
            {"query": "how does the three layer routing work", "permission_tags": ["nonexistent"]},
            service=service,
        )
        assert out["decision"] == "abstain"

    def test_records_mcp_caller_in_audit(self, service):
        handle_search({"query": "how do versioned collections enable rollback"}, service=service)
        rows = service.audit.recent(5)
        assert rows and rows[0]["caller"] == "mcp"

    def test_missing_query_abstains_not_raises(self, service):
        out = handle_search({}, service=service)
        assert out["decision"] == "abstain"


class TestDefaultService:
    def test_uses_lazy_singleton_when_no_service_passed(self):
        # No service injected -> builds the module singleton on the test's default
        # RAG_DB_PATH (an empty, unindexed store), so retrieval abstains.
        out = handle_search({"query": "anything at all"})
        assert out["decision"] == "abstain"


class TestRenderText:
    def test_renders_numbered_cited_snippets(self, service):
        out = handle_search({"query": "how does data minimisation work in the event store"},
                            service=service)
        text = render_text(out)
        assert "[1]" in text
        assert "score" in text

    def test_renders_abstain_message(self):
        text = render_text({"answerable": False, "message": "nope"})
        assert text == "nope"
