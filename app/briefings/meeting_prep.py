"""
JARVIS Cloud — Meeting Prep Briefings

Background scheduler checks every 5 minutes for meetings starting in 25-35 minutes.
When found, generates a context-rich briefing via Claude (using Gmail + Drive context)
and queues it for the frontend to pick up via GET /api/meeting-prep/pending.
"""

import logging
import threading
import time
from datetime import datetime, timedelta

import pytz

logger = logging.getLogger("jarvis.briefings.meeting_prep")

_pending_briefings: list = []
_briefed_events: set = set()
_scheduler_running = False


def get_pending_briefing() -> dict | None:
    """Called by frontend poll — returns and removes the next pending briefing."""
    if _pending_briefings:
        return _pending_briefings.pop(0)
    return None


def queue_meeting_prep(event: dict) -> None:
    """Kick off background briefing generation for a given event dict.

    Safe to call from a request handler — spawns a daemon thread and returns
    immediately. The generated briefing lands in _pending_briefings.
    """
    def _bg():
        briefing_text = _generate_meeting_prep(event)
        _pending_briefings.append({
            "type": "meeting_prep",
            "text": briefing_text,
            "meeting": event.get("summary", "Meeting"),
            "minutes_away": _minutes_until(event),
        })
        logger.info("Meeting prep queued (on-demand): %s", event.get("summary"))

    threading.Thread(target=_bg, daemon=True).start()


def _minutes_until(event: dict) -> int:
    """Return minutes between now and event start; 30 as fallback."""
    try:
        from app.config import get_config
        cfg = get_config()
        tz = pytz.timezone(cfg.timezone)
        now = datetime.now(tz)
        start_str = event.get("start_dt", "")
        if not start_str:
            return 30
        if start_str.endswith("Z"):
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(tz)
        else:
            start_dt = datetime.fromisoformat(start_str).astimezone(tz)
        return max(0, int((start_dt - now).total_seconds() / 60))
    except Exception:
        return 30


def _generate_meeting_prep(event: dict) -> str:
    """Generate a spoken prep briefing for a meeting via Claude."""
    from app.config import get_config
    from app.core.claude import JarvisAI
    from app.integrations.google import GoogleDrive, GoogleGmail

    cfg = get_config()

    title = event.get("summary", "Meeting")
    start_time = event.get("start_time", "")
    attendees = event.get("attendees", [])
    location = event.get("location", "")
    description = event.get("description", "")
    minutes_away = _minutes_until(event)

    attendee_names = [
        a.get("displayName") or a.get("email", "").split("@")[0]
        for a in attendees[:5]
    ]

    gmail_context = ""
    try:
        mail = GoogleGmail()
        if mail.available:
            for name in attendee_names[:2]:
                emails = mail.search_emails(name, max_results=3)
                if emails:
                    gmail_context += f"Recent emails from {name}:\n"
                    for email in emails:
                        gmail_context += f"- {email.get('subject', '')}: {email.get('snippet', '')}\n"
    except Exception as e:
        logger.error("Gmail context error: %s", e)

    drive_context = ""
    try:
        drive = GoogleDrive()
        if drive.available:
            drive_context = drive.get_meeting_context(title, attendee_names)
    except Exception as e:
        logger.error("Drive context error: %s", e)

    prompt = f"""Generate a concise meeting prep briefing for JARVIS to speak aloud.

Meeting: {title}
Starts in: {minutes_away} minutes ({start_time})
Location: {location or 'Not specified'}
Attendees: {', '.join(attendee_names) or 'Not specified'}
Description: {description or 'None'}

Email context:
{gmail_context or 'No recent emails found'}

Drive documents:
{drive_context or 'No related documents found'}

Generate a 3-4 sentence spoken briefing that:
1. States the meeting name and how many minutes away it is
2. Mentions key context from emails or documents if available
3. Suggests one specific talking point or question based on context
4. Asks if there's anything to pull up before the meeting

Keep it concise and conversational — this will be spoken aloud by JARVIS.
Start with "Boss, heads up —"
No markdown, no bullet points, pure spoken prose."""

    try:
        ai = JarvisAI()
        result = ai.respond(prompt, context="", force_layer=3)
        return result.get("response", f"Boss, heads up — {title} starts in {minutes_away} minutes.")
    except Exception as e:
        logger.error("Meeting prep Claude error: %s", e)
        return f"Boss, heads up — {title} starts in {minutes_away} minutes."


def _check_upcoming_meetings() -> None:
    """Check calendar for meetings starting in 25-35 minutes and queue briefings."""
    try:
        from app.config import get_config
        from app.integrations.google import GoogleCalendar

        cfg = get_config()
        tz = pytz.timezone(cfg.timezone)
        now = datetime.now(tz)

        cal = GoogleCalendar()
        if not cal.available:
            return

        time_min = now.isoformat()
        time_max = (now + timedelta(minutes=36)).isoformat()

        events_result = cal.service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        for event in events_result.get("items", []):
            event_id = event.get("id")
            if event_id in _briefed_events:
                continue

            start = event.get("start", {})
            start_dt = start.get("dateTime", start.get("date", ""))
            if not start_dt:
                continue

            if start_dt.endswith("Z"):
                start_time = datetime.fromisoformat(start_dt.replace("Z", "+00:00")).astimezone(tz)
            else:
                start_time = datetime.fromisoformat(start_dt).astimezone(tz)

            minutes_away = (start_time - now).total_seconds() / 60

            if 25 <= minutes_away <= 35:
                logger.info(
                    "Meeting prep triggered: %s in %d min",
                    event.get("summary"),
                    int(minutes_away),
                )
                _briefed_events.add(event_id)

                prep_event = {
                    "summary": event.get("summary", "Meeting"),
                    "start_time": start_time.strftime("%I:%M %p"),
                    "start_dt": start_dt,
                    "location": event.get("location", ""),
                    "description": event.get("description", ""),
                    "attendees": event.get("attendees", []),
                }
                mins_snapshot = int(minutes_away)

                def _bg(ev, mins):
                    briefing_text = _generate_meeting_prep(ev)
                    _pending_briefings.append({
                        "type": "meeting_prep",
                        "text": briefing_text,
                        "meeting": ev["summary"],
                        "minutes_away": mins,
                    })
                    logger.info("Meeting prep queued (scheduler): %s", ev["summary"])

                threading.Thread(target=_bg, args=(prep_event, mins_snapshot), daemon=True).start()

    except Exception as e:
        logger.error("Meeting check error: %s", e)


def start_meeting_prep_scheduler() -> None:
    """Start the background scheduler — idempotent, safe to call multiple times."""
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True

    def _loop():
        logger.info("Meeting prep scheduler started — checking every 5 minutes")
        while _scheduler_running:
            _check_upcoming_meetings()
            time.sleep(300)

    threading.Thread(target=_loop, daemon=True).start()
