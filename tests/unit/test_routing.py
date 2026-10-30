"""
Unit tests for the 3-layer routing decision logic in app.core.claude.

Routing is where cost and latency are decided, so it is pinned hard:
  * Layer 1 (local regex) must catch the cheap, deterministic queries
    (time, date, greetings) and must NOT swallow anything that needs a model.
  * The L2-vs-L3 heuristic (_is_complex_query) decides Haiku vs Sonnet, i.e.
    cheap vs 3x-the-price. A regression here quietly inflates the bill.

These functions are pure — no API, no network — so the whole truth table runs
in milliseconds.
"""

from datetime import datetime as real_datetime

import pytest

from app.core import claude
from app.core.claude import JarvisAI, _is_complex_query, _time_of_day


class TestComplexQueryHeuristic:
    """_is_complex_query == True means the query is routed to Sonnet (L3)."""

    @pytest.mark.parametrize(
        "query",
        [
            "plan my week around the three deadlines",
            "compare the two vendor proposals",
            "analyze last quarter's numbers",
            "draft an email to the landlord",
            "what are the pros and cons of leasing",
            "recommend a strategy for the launch",
            "explain how the routing works",
            "brief me on the 3pm meeting",
            "give me the weekly review",
        ],
    )
    def test_complex_queries_route_to_sonnet(self, query):
        assert _is_complex_query(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "what's the weather",
            "add milk to my list",
            "is it going to rain",
            "mark the report as done",
            "what time is my meeting",
        ],
    )
    def test_simple_queries_stay_on_haiku(self, query):
        assert _is_complex_query(query) is False

    def test_long_query_is_treated_as_complex(self):
        long_query = " ".join(["word"] * 31)
        assert _is_complex_query(long_query) is True

    def test_query_at_length_boundary_is_simple(self):
        # 30 words is NOT > 30, so it stays simple.
        assert _is_complex_query(" ".join(["word"] * 30)) is False


class TestTimeOfDay:
    @pytest.mark.parametrize(
        "hour,expected",
        [(0, "morning"), (9, "morning"), (11, "morning"),
         (12, "afternoon"), (16, "afternoon"),
         (17, "evening"), (20, "evening"), (23, "evening")],
    )
    def test_time_of_day_buckets(self, monkeypatch, hour, expected):
        class _FakeDT(real_datetime):
            @classmethod
            def now(cls, tz=None):
                naive = real_datetime(2026, 10, 29, hour, 0, 0)
                return naive.replace(tzinfo=tz) if tz else naive

        monkeypatch.setattr(claude, "datetime", _FakeDT)
        assert _time_of_day() == expected


class TestLayer1LocalPatterns:
    """Layer 1 answers without ever touching the API."""

    @pytest.fixture
    def ai(self):
        # __init__ builds an anthropic client object but makes no network call.
        return JarvisAI()

    def test_time_query_hits_layer1(self, ai):
        out = ai._try_layer1("what time is it")
        assert out is not None and "Chicago time" in out

    def test_date_query_hits_layer1(self, ai):
        out = ai._try_layer1("what's today's date")
        assert out is not None and out.startswith("Today is")

    @pytest.mark.parametrize("greeting", ["hello", "hi", "good morning"])
    def test_greetings_hit_layer1(self, ai, greeting):
        out = ai._try_layer1(greeting)
        assert out is not None and "Boss" in out

    def test_thanks_hits_layer1(self, ai):
        assert ai._try_layer1("thanks") == "Anytime, Boss."

    def test_status_check_hits_layer1(self, ai):
        out = ai._try_layer1("are you online")
        assert out is not None and "operational" in out.lower()

    @pytest.mark.parametrize(
        "query",
        [
            "schedule a meeting tomorrow at 3pm",
            "what's on my calendar",
            "draft a reply to Marcus",
        ],
    )
    def test_real_requests_fall_through_layer1(self, ai, query):
        assert ai._try_layer1(query) is None
