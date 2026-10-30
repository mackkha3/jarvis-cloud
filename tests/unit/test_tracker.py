"""
Unit tests for app.usage.tracker — the spend tracker behind the dashboard's
dollar figure.

Two things matter and both are pure arithmetic once the file I/O is pointed at
a temp path:
  * _resolve_rates must map a model ID to a price, including the PREFIX match
    that handles versioned IDs like ``claude-haiku-4-5-20251001`` and must
    return None (don't silently bill at $0) for an unknown model.
  * record_claude / record_openai_tts / get_summary must agree on the money.
"""

import pytest

from app.usage import tracker


@pytest.fixture
def temp_usage(tmp_path, monkeypatch):
    """Point the tracker's JSON store at an isolated temp file per test."""
    store = tmp_path / "usage.json"
    monkeypatch.setattr(tracker, "USAGE_FILE", store)
    return store


class TestResolveRates:
    def test_exact_model_match(self):
        rates = tracker._resolve_rates("claude-sonnet-4-5")
        assert rates == {"input": 3.00, "output": 15.00}

    def test_versioned_id_matches_by_prefix(self):
        # Not an exact key, but starts with a known one.
        rates = tracker._resolve_rates("claude-sonnet-4-5-20260101")
        assert rates == {"input": 3.00, "output": 15.00}

    def test_haiku_rates(self):
        assert tracker._resolve_rates("claude-haiku-4-5")["output"] == 5.00

    def test_unknown_model_returns_none(self):
        assert tracker._resolve_rates("gpt-4o") is None

    def test_openai_tts_entry_is_not_a_rate_dict(self):
        # "openai-tts" is a flat per-char price, not an input/output dict, so it
        # must never be returned as a Claude rate table.
        assert tracker._resolve_rates("openai-tts") is None


class TestRecordAndSummarise:
    def test_claude_cost_math(self, temp_usage):
        # Haiku: $1/M in, $5/M out. 1000 in + 1000 out = 0.001 + 0.005 = 0.006.
        tracker.record_claude("claude-haiku-4-5", input_tokens=1000, output_tokens=1000)
        summary = tracker.get_summary()
        assert summary["today"]["claude"] == pytest.approx(0.006)
        assert summary["today"]["claude_tokens_in"] == 1000
        assert summary["today"]["claude_tokens_out"] == 1000

    def test_tts_cost_math(self, temp_usage):
        # $15 / 1M chars. 1000 chars = 0.015.
        tracker.record_openai_tts(1000)
        summary = tracker.get_summary()
        assert summary["today"]["openai_tts"] == pytest.approx(0.015)
        assert summary["today"]["tts_chars"] == 1000

    def test_costs_accumulate_across_calls(self, temp_usage):
        tracker.record_claude("claude-haiku-4-5", 1000, 0)
        tracker.record_claude("claude-haiku-4-5", 1000, 0)
        summary = tracker.get_summary()
        assert summary["today"]["claude"] == pytest.approx(0.002)

    def test_unknown_model_records_nothing(self, temp_usage):
        tracker.record_claude("gpt-4o", 1000, 1000)
        summary = tracker.get_summary()
        assert summary["today"]["total"] == 0.0

    def test_month_to_date_includes_today(self, temp_usage):
        tracker.record_claude("claude-sonnet-4-5", 1000, 1000)  # 0.003 + 0.015
        summary = tracker.get_summary()
        assert summary["month_to_date"]["total"] == pytest.approx(0.018)

    def test_summary_shape_is_stable(self, temp_usage):
        summary = tracker.get_summary()
        assert set(summary) == {"today", "month_to_date", "as_of"}
        assert set(summary["today"]) >= {"total", "claude", "openai_tts"}
