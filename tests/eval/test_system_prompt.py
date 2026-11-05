"""
Prompt-invariant evals (CI-safe, zero API calls).

The system prompt is JARVIS's behaviour contract. Its rules — the persona
guardrails, the action-tag schemas the voice layer parses, the owner
personalisation — are exactly the kind of thing that gets silently broken by a
careless edit and only noticed in production. These tests assert the invariants
are present in the constructed prompt, so a regression fails the build instead
of shipping.

This is the deterministic half of the eval strategy. The live, model-in-the-loop
half lives in test_live_evals.py and is opt-in.
"""

import pytest

from app.core.claude import JarvisAI


@pytest.fixture
def prompt():
    return JarvisAI()._build_system_prompt()


class TestPersonalisation:
    def test_owner_name_and_title_are_injected(self, prompt):
        assert "TestBoss" in prompt
        assert "Boss" in prompt

    def test_timezone_and_date_line_present(self, prompt):
        assert "America/Chicago" in prompt


class TestPersonaGuardrails:
    @pytest.mark.parametrize("banned", ["Certainly!", "Of course!", "Great question!"])
    def test_forbidden_phrases_are_named_as_forbidden(self, prompt, banned):
        # The prompt instructs the model to NEVER say these, so the string must
        # appear (inside the 'Never say ...' instruction).
        assert banned in prompt

    def test_infrastructure_identity_present(self, prompt):
        assert "You are not a chatbot" in prompt


class TestActionSchemas:
    @pytest.mark.parametrize(
        "action_type",
        ["create_calendar_event", "create_task", "complete_task", "schedule_meeting_prep"],
    )
    def test_action_tag_schemas_are_documented(self, prompt, action_type):
        assert action_type in prompt

    def test_action_tag_envelope_present(self, prompt):
        assert "<action>" in prompt


class TestContextInjection:
    def test_context_block_is_appended_when_provided(self):
        p = JarvisAI()._build_system_prompt(context="UNREAD: 3 emails from Marcus")
        assert "CONTEXT FOR THIS REQUEST" in p
        assert "UNREAD: 3 emails from Marcus" in p

    def test_no_context_block_when_absent(self):
        p = JarvisAI()._build_system_prompt()
        assert "CONTEXT FOR THIS REQUEST" not in p
