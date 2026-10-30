"""
Unit tests for the pure formatting helpers in app.briefings.morning.

These turn raw Google payloads into the plain-text context block handed to
Claude, and the plain-text fallback briefing used when Claude is unavailable.
They're pure string functions, so they're pinned directly — no Google, no
Claude, no clock dependence beyond what's injected.
"""

from datetime import datetime

from app.briefings import morning
from app.config import get_config


class TestFormatEvents:
    def test_empty_events(self):
        assert morning._format_events_for_context([]) == "No events scheduled for today."

    def test_timed_event_is_humanised(self):
        out = morning._format_events_for_context(
            [{"title": "Standup", "start": "2026-10-30T09:00:00-05:00"}]
        )
        assert "09:00 AM" in out
        assert "Standup" in out

    def test_location_and_attendees_rendered(self):
        out = morning._format_events_for_context(
            [{"title": "Fitting", "start": "2026-10-30T14:00:00-05:00",
              "location": "Kiosk", "attendees": ["a@x.com", "b@x.com"]}]
        )
        assert "@ Kiosk" in out
        assert "2 attendee(s)" in out


class TestFormatTasks:
    def test_empty_tasks(self):
        assert morning._format_tasks_for_context([]) == "No pending tasks."

    def test_due_date_is_rendered(self):
        out = morning._format_tasks_for_context(
            [{"title": "Pick up HDMI cord", "due": "2026-10-30T00:00:00Z"}]
        )
        assert "Pick up HDMI cord" in out
        assert "due Oct 30" in out

    def test_task_without_due(self):
        out = morning._format_tasks_for_context([{"title": "Audit roofing"}])
        assert out.strip() == "• Audit roofing".replace("•", "•")  # no trailing due


class TestFormatEmails:
    def test_unread_count_always_present(self):
        assert "Total unread: 0" in morning._format_emails_for_context([], 0)

    def test_sender_display_name_is_extracted(self):
        out = morning._format_emails_for_context(
            [{"from": '"Marcus Lee" <marcus@acme.com>', "subject": "Re: pitch"}], 1
        )
        assert "Marcus Lee" in out
        assert "marcus@acme.com" not in out  # raw address stripped
        assert "Re: pitch" in out


class TestPlainBriefingFallback:
    def test_fallback_greets_and_summarises(self):
        cfg = get_config()
        now = datetime(2026, 10, 30, 8, 0, 0)  # morning
        out = morning._build_plain_briefing(
            cfg, now,
            events=[{"title": "A"}, {"title": "B"}],
            tasks=[{"title": "ship it"}],
            unread_count=3,
        )
        assert out.startswith("Good morning, Boss.")
        assert "2 calendar events today" in out
        assert "ship it" in out
        assert "3 unread emails" in out

    def test_fallback_handles_empty_day(self):
        cfg = get_config()
        now = datetime(2026, 10, 30, 14, 0, 0)  # afternoon
        out = morning._build_plain_briefing(cfg, now, events=[], tasks=[], unread_count=0)
        assert out.startswith("Good afternoon, Boss.")
        assert "calendar is clear" in out
