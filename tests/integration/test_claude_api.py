"""
Integration tests for JarvisAI.respond() — the full L1->L2->L3 path with the
Anthropic client mocked at the boundary.

No real network call is ever made: the test swaps ai.client for a mock whose
messages.create() returns a canned response (or raises a canned error). What's
verified is JARVIS's own behaviour around the SDK:
  * the correct model is selected for the layer,
  * usage tokens are parsed into the response dict,
  * conversation history grows and is trimmed,
  * each SDK error maps to a graceful, structured fallback (never a 500).
"""

from unittest.mock import MagicMock

import anthropic
import pytest

from app.core.claude import JarvisAI


def _fake_response(text="Acknowledged, Boss.", tokens_in=120, tokens_out=40):
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    resp.usage.input_tokens = tokens_in
    resp.usage.output_tokens = tokens_out
    return resp


@pytest.fixture
def ai():
    agent = JarvisAI()
    agent.client = MagicMock()
    agent.client.messages.create.return_value = _fake_response()
    return agent


class TestModelRouting:
    def test_simple_query_uses_haiku_layer2(self, ai):
        result = ai.respond("what's the weather looking like")
        assert result["layer"] == 2
        assert result["model"] == ai.cfg.claude_model_default
        assert ai.client.messages.create.call_args.kwargs["model"] == ai.cfg.claude_model_default

    def test_complex_query_uses_sonnet_layer3(self, ai):
        result = ai.respond("analyze the quarterly pipeline and recommend next steps")
        assert result["layer"] == 3
        assert result["model"] == ai.cfg.claude_model_complex

    def test_force_layer_overrides_heuristic(self, ai):
        result = ai.respond("hi there friend", force_layer=3)
        assert result["layer"] == 3
        assert result["model"] == ai.cfg.claude_model_complex

    def test_layer1_query_never_calls_the_api(self, ai):
        result = ai.respond("what time is it")
        assert result["layer"] == 1
        assert result["model"] == "local"
        ai.client.messages.create.assert_not_called()


class TestResponseShape:
    def test_tokens_are_parsed_from_usage(self, ai):
        result = ai.respond("draft a short note to the team")
        assert result["tokens"] == {"input": 120, "output": 40}

    def test_response_text_is_returned(self, ai):
        ai.client.messages.create.return_value = _fake_response(text="Done, Boss.")
        assert ai.respond("plan the week")["response"] == "Done, Boss."


class TestConversationHistory:
    def test_history_grows_by_two_per_turn(self, ai):
        ai.respond("compare option A and option B")
        assert len(ai._conversation_history) == 2  # user + assistant

    def test_history_is_trimmed_to_last_10(self, ai):
        for _ in range(7):  # 7 turns * 2 = 14 messages
            ai.respond("analyze this scenario in detail")
        assert len(ai._conversation_history) == 10

    def test_clear_history_empties_it(self, ai):
        ai.respond("plan something")
        ai.clear_history()
        assert ai._conversation_history == []


class TestErrorHandling:
    def test_auth_error_maps_to_graceful_fallback(self, ai):
        ai.client.messages.create.side_effect = anthropic.AuthenticationError.__new__(
            anthropic.AuthenticationError
        )
        result = ai.respond("plan the launch")
        assert result["error"] == "auth_failed"
        assert "Authentication error" in result["response"]
        assert result["tokens"] == {"input": 0, "output": 0}

    def test_rate_limit_maps_to_graceful_fallback(self, ai):
        ai.client.messages.create.side_effect = anthropic.RateLimitError.__new__(
            anthropic.RateLimitError
        )
        result = ai.respond("analyze everything at once")
        assert result["error"] == "rate_limited"
        assert "Rate limit" in result["response"]

    def test_unexpected_error_is_caught_and_reported(self, ai):
        ai.client.messages.create.side_effect = RuntimeError("socket exploded")
        result = ai.respond("compare the vendors")
        assert result["error"] == "socket exploded"
        assert result["tokens"] == {"input": 0, "output": 0}
