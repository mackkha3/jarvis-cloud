"""
Regression test for the "tomorrow's events in today's briefing" bug.

THE BUG (fixed in app/integrations/google.py):
    get_todays_events() built the day window from UTC midnight:
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, ...)
    Central time is UTC-5/-6, so any time after ~6-7pm Central the UTC clock
    had already rolled into the next calendar day. The "today" window was then
    tomorrow in UTC — so tomorrow's events showed up in tonight's briefing and
    the brief announced the wrong date.

THE FIX:
    Anchor the window to the OWNER's timezone (cfg.timezone), then let the
    tz-aware isoformat carry the offset to the Calendar API.

This test freezes "now" at 22:00 America/Chicago on 2026-10-29 and asserts the
window the API is asked for is the *Central* day (Oct 29 -> Oct 30), not the
UTC day (Oct 30 -> Oct 31) the old code would have produced. If anyone
reintroduces the UTC anchor, this fails.
"""

from datetime import datetime as real_datetime
from unittest.mock import MagicMock

import pytest

from app.integrations import google
from app.integrations.google import GoogleCalendar


@pytest.fixture
def calendar_at_10pm_central(monkeypatch):
    """A GoogleCalendar whose clock is pinned to 22:00 America/Chicago and whose
    Google service is a mock that records the list() call arguments."""

    class _FakeDT(real_datetime):
        @classmethod
        def now(cls, tz=None):
            naive = real_datetime(2026, 10, 29, 22, 0, 0)
            return naive.replace(tzinfo=tz) if tz is not None else naive

    monkeypatch.setattr(google, "datetime", _FakeDT)

    cal = GoogleCalendar.__new__(GoogleCalendar)  # skip cred-loading __init__
    cal.service = MagicMock()
    cal.service.events.return_value.list.return_value.execute.return_value = {"items": []}
    return cal


def _list_kwargs(cal):
    return cal.service.events.return_value.list.call_args.kwargs


class TestTodaysEventsWindow:
    def test_window_is_the_central_day_not_the_utc_day(self, calendar_at_10pm_central):
        calendar_at_10pm_central.get_todays_events()
        kwargs = _list_kwargs(calendar_at_10pm_central)

        # Central day: Oct 29 00:00 -> Oct 30 00:00
        assert kwargs["timeMin"].startswith("2026-10-29T00:00:00")
        assert kwargs["timeMax"].startswith("2026-10-30T00:00:00")

        # And NOT the UTC day the old bug produced (Oct 30 -> Oct 31).
        assert not kwargs["timeMin"].startswith("2026-10-30")

    def test_window_carries_a_timezone_offset(self, calendar_at_10pm_central):
        calendar_at_10pm_central.get_todays_events()
        kwargs = _list_kwargs(calendar_at_10pm_central)
        # tz-aware isoformat -> ends with an offset, not a bare naive string.
        assert kwargs["timeMin"].endswith(("-05:00", "-06:00"))

    def test_unavailable_calendar_returns_empty(self):
        cal = GoogleCalendar.__new__(GoogleCalendar)
        cal.service = None
        assert cal.get_todays_events() == []
