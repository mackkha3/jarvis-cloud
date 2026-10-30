"""
Coverage for the remaining Drive/Gmail read paths: email search, spreadsheet
and binary file export, and the meeting-context assembler that stitches Drive
documents together for a meeting-prep briefing. All mocked at the API boundary.
"""

from unittest.mock import MagicMock

from app.integrations.google import GoogleGmail, GoogleDrive


def _gmail():
    g = GoogleGmail.__new__(GoogleGmail)
    g.service = MagicMock()
    return g


def _drive():
    d = GoogleDrive.__new__(GoogleDrive)
    d.service = MagicMock()
    d.available = True
    return d


class TestGmailSearch:
    def test_search_emails_uses_query(self):
        g = _gmail()
        msgs = g.service.users.return_value.messages.return_value
        msgs.list.return_value.execute.return_value = {"messages": [{"id": "m1"}]}
        msgs.get.return_value.execute.return_value = {
            "snippet": "re: ring",
            "payload": {"headers": [
                {"name": "From", "value": "Jeweler <j@x.com>"},
                {"name": "Subject", "value": "Bridal ring"},
            ]},
        }
        out = g.search_emails("bridal", max_results=3)
        assert msgs.list.call_args.kwargs["q"] == "bridal"
        assert out[0]["subject"] == "Bridal ring"

    def test_search_unavailable_returns_empty(self):
        g = GoogleGmail.__new__(GoogleGmail)
        g.service = None
        assert g.search_emails("x") == []


class TestDriveRead:
    def test_read_spreadsheet_exports_csv(self):
        d = _drive()
        d.service.files.return_value.export.return_value.execute.return_value = b"a,b,c"
        out = d.read_file("f1", "application/vnd.google-apps.spreadsheet")
        assert out == "a,b,c"

    def test_read_binary_uses_get_media(self):
        d = _drive()
        d.service.files.return_value.get_media.return_value.execute.return_value = b"plain bytes"
        out = d.read_file("f1", "text/plain")
        assert out == "plain bytes"


class TestMeetingContext:
    def test_get_meeting_context_stitches_documents(self):
        d = _drive()
        # search_files returns one doc; read_file exports its text.
        d.service.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "f1", "name": "Pyramid proposal",
                       "mimeType": "application/vnd.google-apps.document"}]
        }
        d.service.files.return_value.export.return_value.execute.return_value = b"Scope and pricing"

        ctx = d.get_meeting_context("Pyramid Homes pitch", attendee_names=["Marcus"])
        assert "Pyramid proposal" in ctx
        assert "Scope and pricing" in ctx
