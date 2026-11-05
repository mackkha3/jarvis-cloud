"""Unit tests for observability — the key property is that no content leaks."""

from app.rag.chunker import Chunk
from app.rag.observe import AuditLog, QueryRecord, record_from_result, _qhash
from app.rag.retrieve import Result, Hit


def _result():
    c = Chunk(text="SECRET routing internals", source_id="routing", ordinal=0,
              title="Routing", link="doc://r")
    return Result(query="what are the SECRET routing internals",
                  hits=[Hit(c, 0.42)], decision="answer", elapsed_ms=3.1, index_id="idx1")


class TestRecord:
    def test_record_carries_no_query_text_or_contents(self):
        rec = record_from_result(_result())
        blob = rec.to_json()
        assert "SECRET" not in blob          # chunk text never recorded
        assert "internals" not in blob       # query text never recorded
        assert rec.query_hash == _qhash("what are the SECRET routing internals")
        assert rec.source_ids == ["routing"]  # ids only
        assert rec.decision == "answer"
        assert rec.top_score == 0.42

    def test_qhash_is_stable_and_case_insensitive(self):
        assert _qhash("Hello World") == _qhash("hello world")


class TestAuditLog:
    def test_write_and_recent_roundtrip(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.db"))
        log.write(record_from_result(_result()))
        rows = log.recent(10)
        assert len(rows) == 1
        assert rows[0]["decision"] == "answer"
        assert rows[0]["source_ids"] == ["routing"]
        assert "SECRET" not in str(rows[0])
        log.close()

    def test_stats_counts_and_abstain_rate(self, tmp_path):
        log = AuditLog(str(tmp_path / "audit.db"))
        log.write(record_from_result(_result()))
        abstain = QueryRecord(ts=1.0, query_hash="h", decision="abstain", top_score=0.0,
                              n_hits=0, elapsed_ms=1.0, index_id="idx1")
        log.write(abstain)
        stats = log.stats()
        assert stats["queries"] == 2
        assert stats["abstain_rate"] == 0.5
        assert stats["avg_latency_ms"] >= 0.0
        log.close()
