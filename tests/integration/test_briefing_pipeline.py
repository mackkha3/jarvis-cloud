"""
Integration test for the morning-briefing pipeline (app.briefings.morning).

generate_morning_briefing() sequences Google (calendar/tasks/gmail) and the
Claude call. Here every external is mocked, so the test pins the orchestration:
stats are counted from the fetched data, the AI's text is returned on success,
and the plain-text fallback kicks in when the AI is unavailable — all without a
single network call.
"""

from unittest.mock import MagicMock, patch

from app.briefings import morning


def _patch_google(cal_events, tasks, unread, recent):
    cal = MagicMock(available=True)
    cal.get_todays_events.return_value = cal_events
    tk = MagicMock(available=True)
    tk.get_tasks.return_value = tasks
    gm = MagicMock(available=True)
    gm.get_unread_count.return_value = unread
    gm.get_recent_emails.return_value = recent
    return cal, tk, gm


def test_successful_briefing_returns_ai_text_and_stats():
    cal, tk, gm = _patch_google(
        cal_events=[{"title": "Standup", "start": "2026-10-30T09:00:00-05:00"}],
        tasks=[{"title": "ship it"}, {"title": "audit roofing"}],
        unread=201,
        recent=[{"from": "Marcus <m@x.com>", "subject": "pitch"}],
    )
    ai = MagicMock()
    ai.respond.return_value = {
        "response": "Good morning, Boss. One event today.",
        "tokens": {"input": 500, "output": 120},
        "error": None,
    }

    with patch.object(morning, "GoogleCalendar", return_value=cal), \
         patch.object(morning, "GoogleTasks", return_value=tk), \
         patch.object(morning, "GoogleGmail", return_value=gm), \
         patch.object(morning, "JarvisAI", return_value=ai):
        result = morning.generate_morning_briefing()

    assert result["briefing_text"].startswith("Good morning, Boss.")
    assert result["stats"] == {"events_today": 1, "tasks_pending": 2, "emails_unread": 201}
    assert result["error"] is None
    # Briefings must always use Sonnet (L3) — quality over cost here.
    assert ai.respond.call_args.kwargs["force_layer"] == 3


def test_falls_back_to_plain_briefing_when_ai_unavailable():
    cal, tk, gm = _patch_google([], [], 0, [])
    ai = MagicMock()
    ai.respond.return_value = {"response": "", "tokens": {}, "error": "ai_unavailable"}

    with patch.object(morning, "GoogleCalendar", return_value=cal), \
         patch.object(morning, "GoogleTasks", return_value=tk), \
         patch.object(morning, "GoogleGmail", return_value=gm), \
         patch.object(morning, "JarvisAI", return_value=ai):
        result = morning.generate_morning_briefing()

    # Fallback briefing is deterministic prose assembled from raw data.
    assert "Boss" in result["briefing_text"]
    assert "calendar is clear" in result["briefing_text"]
    assert "ai_unavailable" in result["error"]


def test_calendar_failure_is_isolated():
    cal = MagicMock(available=True)
    cal.get_todays_events.side_effect = RuntimeError("google 500")
    _, tk, gm = _patch_google([], [], 0, [])
    ai = MagicMock()
    ai.respond.return_value = {"response": "ok", "tokens": {}, "error": None}

    with patch.object(morning, "GoogleCalendar", return_value=cal), \
         patch.object(morning, "GoogleTasks", return_value=tk), \
         patch.object(morning, "GoogleGmail", return_value=gm), \
         patch.object(morning, "JarvisAI", return_value=ai):
        result = morning.generate_morning_briefing()

    # One source failing must not sink the whole briefing.
    assert result["stats"]["events_today"] == 0
    assert "calendar unavailable" in result["error"]
