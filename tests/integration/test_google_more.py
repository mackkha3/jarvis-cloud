"""
Further integration tests for app.integrations.google — Gmail, Drive, Tasks
creation, credential loading, and the voice-context assembler.

Everything is mocked at the googleapiclient / google-auth boundary; no OAuth
and no network. Together with test_google.py and test_dates.py these cover the
request-building and parsing logic across all four Google wrappers.
"""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from app.integrations import google
from app.integrations.google import (
    GoogleCalendar,
    GoogleTasks,
    GoogleGmail,
    GoogleDrive,
    SCOPES,
    get_jarvis_context,
)


# --------------------------------------------------------------------------- #
# Credential loading
# --------------------------------------------------------------------------- #
class TestLoadCredentials:
    def test_loads_from_env_var_when_present(self, monkeypatch):
        token = base64.b64encode(json.dumps({"token": "x"}).encode()).decode()
        monkeypatch.setenv("GOOGLE_TOKEN_JSON", token)
        fake = MagicMock(expired=False, valid=True)
        monkeypatch.setattr(
            google.Credentials, "from_authorized_user_info",
            classmethod(lambda cls, info, scopes: fake),
        )
        assert google._load_credentials() is fake

    def test_returns_none_when_no_credentials(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_TOKEN_JSON", raising=False)
        # No token file exists in the test checkout, so this is the "unconfigured"
        # path that must fail safe to None rather than raise.
        assert google._load_credentials() is None

    def test_bad_env_token_returns_none(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_TOKEN_JSON", "not-valid-base64-json!!")
        assert google._load_credentials() is None


# --------------------------------------------------------------------------- #
# Calendar — upcoming
# --------------------------------------------------------------------------- #
class TestUpcomingEvents:
    def test_upcoming_events_are_formatted(self):
        cal = GoogleCalendar.__new__(GoogleCalendar)
        cal.service = MagicMock()
        cal.service.events.return_value.list.return_value.execute.return_value = {
            "items": [{"summary": "Launch", "start": {"dateTime": "2026-11-02T10:00:00-06:00"},
                       "end": {"dateTime": "2026-11-02T11:00:00-06:00"}}]
        }
        out = cal.get_upcoming_events(days=7)
        assert out[0]["summary"] == "Launch"

    def test_upcoming_unavailable_returns_empty(self):
        cal = GoogleCalendar.__new__(GoogleCalendar)
        cal.service = None
        assert cal.get_upcoming_events() == []


# --------------------------------------------------------------------------- #
# Tasks — create + log
# --------------------------------------------------------------------------- #
class TestTasksWrite:
    def _tasks(self):
        t = GoogleTasks.__new__(GoogleTasks)
        t.service = MagicMock()
        t.service.tasklists.return_value.list.return_value.execute.return_value = {
            "items": [{"id": "list1"}]
        }
        return t

    def test_create_task_with_due_date_sets_rfc3339_due(self):
        t = self._tasks()
        t.service.tasks.return_value.insert.return_value.execute.return_value = {"id": "t9"}
        result = t.create_task("Pick up vitamins", due_date="2026-10-30")
        body = t.service.tasks.return_value.insert.call_args.kwargs["body"]
        assert body["title"] == "Pick up vitamins"
        assert body["due"] == "2026-10-30T00:00:00.000Z"
        assert result["success"] is True

    def test_create_task_without_due(self):
        t = self._tasks()
        t.service.tasks.return_value.insert.return_value.execute.return_value = {"id": "t9"}
        t.create_task("Call landlord")
        body = t.service.tasks.return_value.insert.call_args.kwargs["body"]
        assert "due" not in body

    def test_log_accomplishment_creates_completed_task(self):
        t = self._tasks()
        t.service.tasks.return_value.insert.return_value.execute.return_value = {"id": "t9"}
        result = t.log_accomplishment("submitted the pitch")
        body = t.service.tasks.return_value.insert.call_args.kwargs["body"]
        assert body["status"] == "completed"
        assert result["success"] is True

    def test_create_task_unavailable(self):
        t = GoogleTasks.__new__(GoogleTasks)
        t.service = None
        assert "error" in t.create_task("x")


# --------------------------------------------------------------------------- #
# Gmail
# --------------------------------------------------------------------------- #
class TestGmail:
    def _gmail(self):
        g = GoogleGmail.__new__(GoogleGmail)
        g.service = MagicMock()
        return g

    def test_unread_count(self):
        g = self._gmail()
        g.service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "resultSizeEstimate": 201
        }
        assert g.get_unread_count() == 201

    def test_recent_emails_parse_headers(self):
        g = self._gmail()
        msgs = g.service.users.return_value.messages.return_value
        msgs.list.return_value.execute.return_value = {"messages": [{"id": "m1"}]}
        msgs.get.return_value.execute.return_value = {
            "snippet": "hello there",
            "payload": {"headers": [
                {"name": "From", "value": "Marcus <m@x.com>"},
                {"name": "Subject", "value": "Pitch deck"},
                {"name": "Date", "value": "Thu, 29 Oct 2026"},
            ]},
        }
        emails = g.get_recent_emails(max_results=5)
        assert emails[0]["from"] == "Marcus <m@x.com>"
        assert emails[0]["subject"] == "Pitch deck"
        assert emails[0]["snippet"] == "hello there"

    def test_unread_count_unavailable(self):
        g = GoogleGmail.__new__(GoogleGmail)
        g.service = None
        assert g.get_unread_count() == 0


# --------------------------------------------------------------------------- #
# Drive
# --------------------------------------------------------------------------- #
class TestDrive:
    def _drive(self):
        d = GoogleDrive.__new__(GoogleDrive)
        d.service = MagicMock()
        d.available = True
        return d

    def test_search_files_escapes_quotes(self):
        d = self._drive()
        d.service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "f1", "name": "Roof plan", "mimeType": "application/vnd.google-apps.document"}]
        }
        files = d.search_files("O'Brien")
        q = d.service.files.return_value.list.call_args.kwargs["q"]
        assert "O\\'Brien" in q  # single quote escaped for the Drive query
        assert files[0]["name"] == "Roof plan"

    def test_read_document_exports_plain_text(self):
        d = self._drive()
        d.service.files.return_value.export.return_value.execute.return_value = b"Doc body text"
        out = d.read_file("f1", "application/vnd.google-apps.document")
        assert out == "Doc body text"

    def test_unavailable_drive_returns_empty(self):
        d = GoogleDrive.__new__(GoogleDrive)
        d.service = None
        d.available = False
        assert d.search_files("x") == []
        assert d.read_file("f1", "text/plain") == ""


# --------------------------------------------------------------------------- #
# Voice context assembler
# --------------------------------------------------------------------------- #
class TestJarvisContext:
    def test_context_assembles_from_all_sources(self):
        cal = MagicMock()
        cal.get_todays_events.return_value = [
            {"summary": "Standup", "start": "2026-10-30T09:00:00-05:00"}
        ]
        tk = MagicMock()
        tk.get_tasks.return_value = [{"title": "ship it"}]
        gm = MagicMock()
        gm.get_unread_count.return_value = 3

        with patch.object(google, "GoogleCalendar", return_value=cal), \
             patch.object(google, "GoogleTasks", return_value=tk), \
             patch.object(google, "GoogleGmail", return_value=gm):
            ctx = get_jarvis_context()

        assert "Standup" in ctx
        assert "ship it" in ctx
        assert "Unread emails in inbox: 3" in ctx

    def test_context_handles_empty_sources(self):
        cal = MagicMock(); cal.get_todays_events.return_value = []
        tk = MagicMock(); tk.get_tasks.return_value = []
        gm = MagicMock(); gm.get_unread_count.return_value = 0
        with patch.object(google, "GoogleCalendar", return_value=cal), \
             patch.object(google, "GoogleTasks", return_value=tk), \
             patch.object(google, "GoogleGmail", return_value=gm):
            ctx = get_jarvis_context()
        assert "No events scheduled today." in ctx
        assert "No open tasks." in ctx


def test_scopes_are_the_six_expected():
    # The invalid_scope outage traced back to scope drift; pin the exact set.
    assert len(SCOPES) == 6
    assert "https://www.googleapis.com/auth/calendar.events" in SCOPES
    assert "https://www.googleapis.com/auth/gmail.readonly" in SCOPES
