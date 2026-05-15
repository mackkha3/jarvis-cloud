"""
JARVIS Cloud — Google Integrations

Handles OAuth token management and provides clean interfaces
for Google Calendar, Tasks, and Gmail.

OAuth strategy for cloud deployment:
- Token stored as GOOGLE_TOKEN_JSON environment variable (base64 encoded)
- Falls back to GOOGLE_TOKEN_PATH file for local development
- Auto-refreshes using google-auth library
"""

import json
import logging
import base64
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from app.config import get_config

logger = logging.getLogger("jarvis.google")

# OAuth scopes we need
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _load_credentials() -> Optional[Credentials]:
    """
    Load Google OAuth credentials.

    Priority order:
    1. GOOGLE_TOKEN_JSON env var (base64 encoded) — used in production/Railway
    2. File at GOOGLE_TOKEN_PATH — used in local development

    Returns None if no valid credentials found.
    """
    cfg = get_config()
    creds = None

    # --- Production path: env var ---
    token_json_b64 = os.environ.get("GOOGLE_TOKEN_JSON")
    if token_json_b64:
        try:
            token_json = base64.b64decode(token_json_b64).decode("utf-8")
            token_data = json.loads(token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
            logger.debug("Google credentials loaded from GOOGLE_TOKEN_JSON env var")
        except Exception as e:
            logger.error(f"Failed to load GOOGLE_TOKEN_JSON env var: {e}")
            return None

    # --- Development path: file ---
    if creds is None:
        token_path = Path(cfg.project_root) / cfg.google_token_path
        if token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
                logger.debug(f"Google credentials loaded from {token_path}")
            except Exception as e:
                logger.error(f"Failed to load token file: {e}")
                return None

    if creds is None:
        logger.warning("No Google credentials found — run OAuth setup first")
        return None

    # --- Refresh if expired ---
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("Google credentials refreshed successfully")

            # Save refreshed token back to file if in dev mode
            token_path = Path(cfg.project_root) / cfg.google_token_path
            if token_path.parent.exists():
                token_path.write_text(creds.to_json())

        except Exception as e:
            logger.error(f"Google credentials refresh failed: {e}")
            return None

    if not creds.valid:
        logger.error("Google credentials invalid and could not be refreshed")
        return None

    return creds


class GoogleCalendar:
    """Clean interface for Google Calendar API."""

    def __init__(self):
        self.creds = _load_credentials()
        if self.creds:
            self.service = build("calendar", "v3", credentials=self.creds)
            logger.info("Google Calendar connected")
        else:
            self.service = None
            logger.warning("Google Calendar unavailable — no valid credentials")

    @property
    def available(self) -> bool:
        return self.service is not None

    def get_todays_events(self) -> list[dict]:
        """Fetch all calendar events for today."""
        if not self.available:
            return []

        cfg = get_config()
        now = datetime.now(timezone.utc)

        # Today's range in UTC
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        try:
            result = self.service.events().list(
                calendarId="primary",
                timeMin=start_of_day.isoformat(),
                timeMax=end_of_day.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=20,
            ).execute()

            events = result.get("items", [])
            logger.info(f"Calendar: fetched {len(events)} events for today")
            return self._format_events(events)

        except Exception as e:
            logger.error(f"Calendar fetch error: {e}")
            return []

    def get_upcoming_events(self, days: int = 7) -> list[dict]:
        """Fetch upcoming events for the next N days."""
        if not self.available:
            return []

        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days)

        try:
            result = self.service.events().list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=30,
            ).execute()

            events = result.get("items", [])
            logger.info(f"Calendar: fetched {len(events)} upcoming events")
            return self._format_events(events)

        except Exception as e:
            logger.error(f"Calendar upcoming fetch error: {e}")
            return []

    def _format_events(self, raw_events: list) -> list[dict]:
        """Normalise raw Google Calendar events into clean dicts."""
        formatted = []
        for event in raw_events:
            start = event.get("start", {})
            end = event.get("end", {})

            formatted.append({
                "id": event.get("id", ""),
                "summary": event.get("summary", "Untitled"),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "location": event.get("location", ""),
                "description": event.get("description", "")[:200],
                "attendees": [
                    a.get("email", "") for a in event.get("attendees", [])
                ],
                "all_day": "date" in start and "dateTime" not in start,
            })

        return formatted


class GoogleTasks:
    """Clean interface for Google Tasks API."""

    def __init__(self):
        self.creds = _load_credentials()
        if self.creds:
            self.service = build("tasks", "v1", credentials=self.creds)
            logger.info("Google Tasks connected")
        else:
            self.service = None
            logger.warning("Google Tasks unavailable — no valid credentials")

    @property
    def available(self) -> bool:
        return self.service is not None

    def get_tasks(self, max_results: int = 20) -> list[dict]:
        """Fetch pending tasks from the primary task list."""
        if not self.available:
            return []

        try:
            # Get the primary task list
            lists = self.service.tasklists().list().execute()
            if not lists.get("items"):
                return []

            primary_list_id = lists["items"][0]["id"]

            result = self.service.tasks().list(
                tasklist=primary_list_id,
                showCompleted=False,
                maxResults=max_results,
            ).execute()

            tasks = result.get("items", [])
            logger.info(f"Tasks: fetched {len(tasks)} pending tasks")

            return [
                {
                    "id": t.get("id", ""),
                    "title": t.get("title", ""),
                    "due": t.get("due", ""),
                    "notes": t.get("notes", ""),
                    "status": t.get("status", ""),
                }
                for t in tasks
            ]

        except Exception as e:
            logger.error(f"Tasks fetch error: {e}")
            return []

    def create_task(self, title: str, notes: str = "", due: str = "") -> Optional[dict]:
        """Create a new task in the primary task list."""
        if not self.available:
            return None

        try:
            lists = self.service.tasklists().list().execute()
            primary_list_id = lists["items"][0]["id"]

            task_body = {"title": title}
            if notes:
                task_body["notes"] = notes
            if due:
                task_body["due"] = due

            result = self.service.tasks().insert(
                tasklist=primary_list_id,
                body=task_body,
            ).execute()

            logger.info(f"Task created: '{title}'")
            return result

        except Exception as e:
            logger.error(f"Task creation error: {e}")
            return None


class GoogleGmail:
    """Clean interface for Gmail API — read-only."""

    def __init__(self):
        self.creds = _load_credentials()
        if self.creds:
            self.service = build("gmail", "v1", credentials=self.creds)
            logger.info("Gmail connected")
        else:
            self.service = None
            logger.warning("Gmail unavailable — no valid credentials")

    @property
    def available(self) -> bool:
        return self.service is not None

    def get_unread_count(self) -> int:
        """Return count of unread emails in inbox."""
        if not self.available:
            return 0

        try:
            result = self.service.users().messages().list(
                userId="me",
                labelIds=["INBOX", "UNREAD"],
                maxResults=1,
            ).execute()
            return result.get("resultSizeEstimate", 0)

        except Exception as e:
            logger.error(f"Gmail unread count error: {e}")
            return 0

    def get_recent_emails(self, max_results: int = 10) -> list[dict]:
        """Fetch recent unread emails with basic metadata."""
        if not self.available:
            return []

        try:
            result = self.service.users().messages().list(
                userId="me",
                labelIds=["INBOX", "UNREAD"],
                maxResults=max_results,
            ).execute()

            messages = result.get("messages", [])
            emails = []

            for msg in messages[:max_results]:
                detail = self.service.users().messages().get(
                    userId="me",
                    id=msg["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()

                headers = {
                    h["name"]: h["value"]
                    for h in detail.get("payload", {}).get("headers", [])
                }

                emails.append({
                    "id": msg["id"],
                    "from": headers.get("From", ""),
                    "subject": headers.get("Subject", ""),
                    "date": headers.get("Date", ""),
                    "snippet": detail.get("snippet", "")[:200],
                })

            logger.info(f"Gmail: fetched {len(emails)} recent emails")
            return emails

        except Exception as e:
            logger.error(f"Gmail fetch error: {e}")
            return []
