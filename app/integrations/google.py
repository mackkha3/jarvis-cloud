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
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/tasks.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
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

    def create_event(
        self,
        title: str,
        date: str,
        time: str = "",
        duration_minutes: int = 60,
        description: str = "",
    ) -> Optional[dict]:
        """Create a calendar event. date: YYYY-MM-DD, time: HH:MM (24h). Returns created event or None."""
        if not self.available:
            return None
        try:
            import zoneinfo
            cfg = get_config()
            tz = zoneinfo.ZoneInfo(cfg.timezone)

            if time:
                start_dt = datetime.fromisoformat(f"{date}T{time}").replace(tzinfo=tz)
                end_dt = start_dt + timedelta(minutes=duration_minutes)
                event_body = {
                    "summary": title,
                    "description": description,
                    "start": {"dateTime": start_dt.isoformat(), "timeZone": cfg.timezone},
                    "end": {"dateTime": end_dt.isoformat(), "timeZone": cfg.timezone},
                }
            else:
                event_body = {
                    "summary": title,
                    "description": description,
                    "start": {"date": date},
                    "end": {"date": date},
                }

            result = self.service.events().insert(
                calendarId="primary", body=event_body
            ).execute()
            logger.info("Calendar event created: '%s' on %s", title, date)
            try:
                from app.patterns import recorders
                start_iso = result.get("start", {}).get("dateTime") or result.get("start", {}).get("date", "")
                attendees_count = len(result.get("attendees", []))
                recorders.event_created(title, start_iso, attendees_count)
            except Exception:
                pass
            return result
        except Exception as e:
            logger.error(f"Calendar event creation error: {e}")
            return None

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

    def _primary_list_id(self) -> str:
        """Return the ID of the first (primary) task list."""
        lists = self.service.tasklists().list().execute()
        return lists["items"][0]["id"]

    def create_task(self, title: str, notes: str = "", due_date: str = None) -> dict:
        """Create a new task in the primary task list.

        Args:
            title: Task title.
            notes: Optional notes/description.
            due_date: Optional due date in YYYY-MM-DD format.

        Returns dict with success/error keys.
        """
        if not self.available:
            return {"error": "Tasks not available"}

        try:
            tasklist_id = self._primary_list_id()
            task_body: dict = {"title": title}
            if notes:
                task_body["notes"] = notes
            if due_date:
                task_body["due"] = f"{due_date}T00:00:00.000Z"

            result = self.service.tasks().insert(
                tasklist=tasklist_id,
                body=task_body,
            ).execute()

            logger.info("Task created: '%s'", title)
            try:
                from app.patterns import recorders
                recorders.task_created(title, due_date)
            except Exception:
                pass
            return {
                "success": True,
                "task_id": result.get("id"),
                "title": title,
                "due_date": due_date,
            }

        except Exception as e:
            logger.error("Task creation error: %s", e)
            return {"error": str(e)}

    def complete_task(self, task_title: str) -> dict:
        """Find and mark a task complete by fuzzy title match.

        Uses Jaccard similarity on word sets — matches well even when the user
        says "finished the report" and the task is titled "Quarterly report".

        Returns dict with success/error keys.
        """
        if not self.available:
            return {"error": "Tasks not available"}

        try:
            tasklist_id = self._primary_list_id()
            raw = self.service.tasks().list(
                tasklist=tasklist_id,
                showCompleted=False,
            ).execute()

            items = raw.get("items", [])
            if not items:
                return {"error": "no_tasks", "message": "No pending tasks found"}

            query_words = set(task_title.lower().split())
            best_match = None
            best_score = 0.0

            for task in items:
                task_words = set(task.get("title", "").lower().split())
                overlap = len(task_words & query_words)
                total = len(task_words | query_words)
                score = overlap / total if total else 0.0
                if score > best_score:
                    best_score = score
                    best_match = task

            if not best_match or best_score < 0.2:
                return {
                    "error": "no_match",
                    "message": f"No task matching '{task_title}' found",
                    "available_tasks": [t.get("title") for t in items[:5]],
                }

            completed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            best_match["status"] = "completed"
            best_match["completed"] = completed_at

            self.service.tasks().update(
                tasklist=tasklist_id,
                task=best_match["id"],
                body=best_match,
            ).execute()

            logger.info("Task completed: '%s' (score %.2f)", best_match.get("title"), best_score)
            try:
                from app.patterns import recorders
                recorders.task_completed(best_match.get("title", ""))
            except Exception:
                pass
            return {
                "success": True,
                "title": best_match.get("title"),
                "completed_at": completed_at,
            }

        except Exception as e:
            logger.error("Task complete error: %s", e)
            return {"error": str(e)}

    def log_accomplishment(self, text: str, timestamp: str = None) -> dict:
        """Create a pre-completed task as a record for something done without a matching task.

        Returns dict with success/error keys.
        """
        if not self.available:
            return {"error": "Tasks not available"}

        try:
            ts = timestamp or datetime.now().strftime("%I:%M %p")
            tasklist_id = self._primary_list_id()

            task_body = {
                "title": text,
                "notes": f"Logged via JARVIS at {ts}",
                "status": "completed",
            }

            self.service.tasks().insert(
                tasklist=tasklist_id,
                body=task_body,
            ).execute()

            logger.info("Accomplishment logged: '%s'", text)
            return {"success": True, "logged": text, "time": ts}

        except Exception as e:
            logger.error("Accomplishment log error: %s", e)
            return {"error": str(e)}


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
            try:
                from app.patterns import recorders
                for em in emails:
                    recorders.email_received(em.get("from", ""), em.get("subject", ""))
            except Exception:
                pass
            return emails

        except Exception as e:
            logger.error(f"Gmail fetch error: {e}")
            return []

    def search_emails(self, query: str, max_results: int = 5) -> list[dict]:
        """Search emails by keyword (sender name, subject, etc.)."""
        if not self.available:
            return []
        try:
            result = self.service.users().messages().list(
                userId="me",
                q=query,
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
            logger.info(f"Gmail search '{query}': {len(emails)} results")
            return emails
        except Exception as e:
            logger.error(f"Gmail search error: {e}")
            return []


class GoogleDrive:
    """Read-only interface for Google Drive — file search and content export."""

    def __init__(self):
        self.service = None
        self.available = False
        try:
            creds = _load_credentials()
            if creds:
                self.service = build("drive", "v3", credentials=creds)
                self.available = True
                logger.info("Google Drive connected")
            else:
                logger.warning("Google Drive unavailable — no valid credentials")
        except Exception as e:
            logger.error(f"Google Drive connection error: {e}")

    def search_files(self, query: str, max_results: int = 5) -> list[dict]:
        """Search Drive files by keyword."""
        if not self.available:
            return []
        try:
            safe_query = query.replace("'", "\\'")
            results = self.service.files().list(
                q=f"fullText contains '{safe_query}' and trashed=false",
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, webViewLink)",
            ).execute()
            return results.get("files", [])
        except Exception as e:
            logger.error(f"Drive search error: {e}")
            return []

    def read_file(self, file_id: str, mime_type: str) -> str:
        """Read file content — supports Docs, Sheets, and plain text."""
        if not self.available:
            return ""
        try:
            if "document" in mime_type:
                content = self.service.files().export(
                    fileId=file_id,
                    mimeType="text/plain",
                ).execute()
                return content.decode("utf-8")[:3000]
            elif "spreadsheet" in mime_type:
                content = self.service.files().export(
                    fileId=file_id,
                    mimeType="text/csv",
                ).execute()
                return content.decode("utf-8")[:2000]
            else:
                content = self.service.files().get_media(fileId=file_id).execute()
                if isinstance(content, bytes):
                    return content.decode("utf-8", errors="ignore")[:2000]
                return str(content)[:2000]
        except Exception as e:
            logger.error(f"Drive read error: {e}")
            return ""

    def get_meeting_context(self, meeting_title: str, attendee_names: list) -> str:
        """Search Drive for files related to a meeting and its attendees."""
        context_parts = []
        seen_names: set = set()

        keywords = [w for w in meeting_title.split() if len(w) > 3]
        for keyword in keywords[:2]:
            for f in self.search_files(keyword, max_results=3):
                content = self.read_file(f["id"], f["mimeType"])
                if content:
                    context_parts.append(f"Document '{f['name']}': {content[:500]}")
                    seen_names.add(f["name"])

        for name in attendee_names[:2]:
            for f in self.search_files(name, max_results=2):
                if f["name"] not in seen_names:
                    content = self.read_file(f["id"], f["mimeType"])
                    if content:
                        context_parts.append(
                            f"Document '{f['name']}' (related to {name}): {content[:300]}"
                        )
                        seen_names.add(f["name"])

        return "\n\n".join(context_parts[:4])


def get_jarvis_context() -> str:
    """
    Return a formatted context string for JARVIS voice chat:
    current time, today's calendar events, open tasks, unread email count.
    Best-effort — individual failures are skipped silently.
    """
    now = datetime.now()
    lines = [f"Current time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}"]

    try:
        cal = GoogleCalendar()
        events = cal.get_todays_events()
        if events:
            lines.append(f"\nToday's calendar ({len(events)} event{'s' if len(events) != 1 else ''}):")
            for e in events:
                start = e.get("start", "")
                if "T" in start:
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        start = dt.strftime("%I:%M %p")
                    except Exception:
                        pass
                lines.append(f"  - {start}: {e.get('summary', 'Untitled')}")
        else:
            lines.append("\nNo events scheduled today.")
    except Exception:
        pass

    try:
        tasks = GoogleTasks()
        task_list = tasks.get_tasks(max_results=5)
        if task_list:
            lines.append(f"\nOpen tasks ({len(task_list)}):")
            for t in task_list:
                lines.append(f"  - {t.get('title', '')}")
        else:
            lines.append("\nNo open tasks.")
    except Exception:
        pass

    try:
        gmail = GoogleGmail()
        unread = gmail.get_unread_count()
        lines.append(f"\nUnread emails in inbox: {unread}")
    except Exception:
        pass

    return "\n".join(lines)
