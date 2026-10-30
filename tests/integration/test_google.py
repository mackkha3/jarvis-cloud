"""
Integration tests for the Google Calendar / Tasks wrappers with the
googleapiclient service mocked.

These pin the request bodies JARVIS builds (timed vs all-day events) and the
fuzzy task matcher's behaviour, without any OAuth or network. Credentials are
never loaded — instances are built with __new__ and a mock service attached.
"""

from unittest.mock import MagicMock

import pytest

from app.integrations.google import GoogleCalendar, GoogleTasks


def _calendar_with_service():
    cal = GoogleCalendar.__new__(GoogleCalendar)
    cal.service = MagicMock()
    return cal


def _tasks_with_service():
    t = GoogleTasks.__new__(GoogleTasks)
    t.service = MagicMock()
    return t


class TestCreateEvent:
    def test_timed_event_body_uses_datetime_and_timezone(self):
        cal = _calendar_with_service()
        cal.service.events.return_value.insert.return_value.execute.return_value = {
            "id": "evt1",
            "start": {"dateTime": "2026-10-30T14:30:00-05:00"},
        }
        cal.create_event("Bridal ring fitting", "2026-10-30", "14:30", duration_minutes=45)

        body = cal.service.events.return_value.insert.call_args.kwargs["body"]
        assert body["summary"] == "Bridal ring fitting"
        assert "dateTime" in body["start"]
        assert body["start"]["timeZone"] == "America/Chicago"

    def test_all_day_event_body_uses_date(self):
        cal = _calendar_with_service()
        cal.service.events.return_value.insert.return_value.execute.return_value = {
            "id": "evt2", "start": {"date": "2026-10-30"},
        }
        cal.create_event("Day off", "2026-10-30")  # no time -> all-day

        body = cal.service.events.return_value.insert.call_args.kwargs["body"]
        assert body["start"] == {"date": "2026-10-30"}
        assert "dateTime" not in body["start"]

    def test_unavailable_calendar_returns_none(self):
        cal = GoogleCalendar.__new__(GoogleCalendar)
        cal.service = None
        assert cal.create_event("x", "2026-10-30") is None


class TestFormatEvents:
    def test_all_day_flag_and_defaults(self):
        cal = _calendar_with_service()
        formatted = cal._format_events([
            {"summary": "Standup", "start": {"dateTime": "2026-10-30T09:00:00-05:00"},
             "end": {"dateTime": "2026-10-30T09:15:00-05:00"}},
            {"start": {"date": "2026-10-30"}, "end": {"date": "2026-10-31"}},
        ])
        assert formatted[0]["summary"] == "Standup"
        assert formatted[0]["all_day"] is False
        assert formatted[1]["summary"] == "Untitled"  # missing summary -> default
        assert formatted[1]["all_day"] is True


class TestCompleteTaskFuzzyMatch:
    def _wire_tasks(self, titles):
        t = _tasks_with_service()
        t.service.tasklists.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "list1"}]
        }
        t.service.tasks.return_value.list.return_value.execute.return_value = {
            "items": [{"id": f"t{i}", "title": title} for i, title in enumerate(titles)]
        }
        return t

    def test_fuzzy_match_completes_the_right_task(self):
        t = self._wire_tasks(["Quarterly report", "Pick up HDMI cord", "Call landlord"])
        result = t.complete_task("finished the report")
        assert result["success"] is True
        assert result["title"] == "Quarterly report"
        t.service.tasks.return_value.update.assert_called_once()

    def test_no_reasonable_match_returns_error(self):
        t = self._wire_tasks(["Pick up HDMI cord", "Call landlord"])
        result = t.complete_task("renew passport")
        assert result.get("error") == "no_match"
        assert "available_tasks" in result

    def test_empty_task_list_reports_no_tasks(self):
        t = self._wire_tasks([])
        result = t.complete_task("anything")
        assert result.get("error") == "no_tasks"


class TestGetTasks:
    def test_returns_normalised_task_dicts(self):
        t = _tasks_with_service()
        t.service.tasklists.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "list1"}]
        }
        t.service.tasks.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "t1", "title": "Audit Sky High roofing", "status": "needsAction"}]
        }
        tasks = t.get_tasks()
        assert tasks[0]["title"] == "Audit Sky High roofing"
        assert tasks[0]["id"] == "t1"

    def test_unavailable_returns_empty(self):
        t = GoogleTasks.__new__(GoogleTasks)
        t.service = None
        assert t.get_tasks() == []
