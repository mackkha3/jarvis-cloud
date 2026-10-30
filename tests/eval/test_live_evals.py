"""
Live, model-in-the-loop evals (OPT-IN — never run in CI).

These call the real Anthropic API and assert behavioural invariants on the
actual output: the persona guardrails hold, and a scheduling request produces a
machine-parseable <action> tag (the contract the voice layer depends on).

They are skipped unless BOTH:
  * RUN_LLM_EVALS=1 is set, and
  * a real ANTHROPIC_API_KEY (not the conftest stub) is present.

Run locally with:
    RUN_LLM_EVALS=1 ANTHROPIC_API_KEY=sk-ant-... pytest -m llm -v

Model output is non-deterministic, so these assert robust invariants (a phrase
is absent / a tag is present), never exact strings. Treat them as a smoke eval
against prompt drift, not a unit test.
"""

import os

import pytest

RUN = os.environ.get("RUN_LLM_EVALS") == "1"
REAL_KEY = os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-") and \
    "not-a-real-key" not in os.environ.get("ANTHROPIC_API_KEY", "")

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not (RUN and REAL_KEY),
        reason="live evals: set RUN_LLM_EVALS=1 and a real ANTHROPIC_API_KEY",
    ),
]

FORBIDDEN = ["Certainly!", "Of course!", "Great question!"]


@pytest.fixture(scope="module")
def ai():
    from app.core.claude import JarvisAI
    return JarvisAI()


def test_persona_avoids_forbidden_openers(ai):
    result = ai.respond("give me a quick status update", force_layer=2)
    text = result["response"]
    for phrase in FORBIDDEN:
        assert phrase not in text, f"persona leaked forbidden opener: {phrase!r}"


def test_scheduling_request_emits_action_tag(ai):
    result = ai.respond(
        "schedule a bridal ring fitting tomorrow at 2pm",
        context="Current time: Thursday, October 29, 2026 at 10:00 PM",
    )
    assert "<action>" in result["response"]
    assert "create_calendar_event" in result["response"]
