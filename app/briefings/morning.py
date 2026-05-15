"""
JARVIS Cloud — Morning Briefing

Generates a personalised morning briefing by:
1. Fetching today's calendar events
2. Fetching pending tasks
3. Fetching unread email count + recent senders
4. Building a context package
5. Passing everything to Claude Sonnet for synthesis

The briefing Claude produces follows the JARVIS personality —
tactical, concise, actionable. Not a generic summary dump.
"""

import logging
from datetime import datetime
from typing import Optional

from app.config import get_config
from app.core.claude import JarvisAI
from app.integrations.google import GoogleCalendar, GoogleTasks, GoogleGmail

logger = logging.getLogger("jarvis.briefings.morning")


def _format_events_for_context(events: list[dict]) -> str:
    """Format calendar events into clean text for Claude's context."""
    if not events:
        return "No events scheduled for today."

    lines = []
    for e in events:
        start = e.get("start", "")
        # Strip the timezone offset for readability
        if "T" in start:
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                start = dt.strftime("%I:%M %p")
            except Exception:
                start = start[:16]

        title = e.get("title", "Untitled")
        location = e.get("location", "")
        attendees = e.get("attendees", [])

        line = f"  • {start} — {title}"
        if location:
            line += f" @ {location}"
        if attendees:
            line += f" (with {len(attendees)} attendee(s))"
        lines.append(line)

    return "\n".join(lines)


def _format_tasks_for_context(tasks: list[dict]) -> str:
    """Format pending tasks into clean text for Claude's context."""
    if not tasks:
        return "No pending tasks."

    lines = []
    for t in tasks:
        title = t.get("title", "Untitled")
        due = t.get("due", "")
        if due:
            try:
                dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                due = f" (due {dt.strftime('%b %d')})"
            except Exception:
                due = ""
        lines.append(f"  • {title}{due}")

    return "\n".join(lines)


def _format_emails_for_context(emails: list[dict], unread_count: int) -> str:
    """Format email data into clean text for Claude's context."""
    lines = [f"Total unread: {unread_count}"]

    if emails:
        lines.append("Most recent unread:")
        for e in emails[:5]:
            sender = e.get("from", "Unknown")
            # Strip email address, keep display name only
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            subject = e.get("subject", "No subject")
            lines.append(f"  • From: {sender} — {subject}")

    return "\n".join(lines)


def generate_morning_briefing(
    include_weather: bool = True,
) -> dict:
    """
    Main entry point for morning briefing generation.

    Returns:
        dict with keys:
            briefing (str): The full briefing text
            stats (dict): Counts of events/tasks/emails pulled
            generated_at (str): ISO timestamp
            error (str|None): Error message if something failed
    """
    cfg = get_config()
    logger.info(f"Generating morning briefing for {cfg.owner_name}")

    # ---- Fetch all data ----
    stats = {
        "events_today": 0,
        "tasks_pending": 0,
        "emails_unread": 0,
    }
    errors = []

    # Calendar
    try:
        calendar = GoogleCalendar()
        events = calendar.get_todays_events() if calendar.available else []
        stats["events_today"] = len(events)
    except Exception as e:
        logger.error(f"Calendar fetch failed: {e}")
        events = []
        errors.append("calendar unavailable")

    # Tasks
    try:
        tasks_client = GoogleTasks()
        tasks = tasks_client.get_tasks() if tasks_client.available else []
        stats["tasks_pending"] = len(tasks)
    except Exception as e:
        logger.error(f"Tasks fetch failed: {e}")
        tasks = []
        errors.append("tasks unavailable")

    # Gmail
    try:
        gmail = GoogleGmail()
        if gmail.available:
            unread_count = gmail.get_unread_count()
            recent_emails = gmail.get_recent_emails(max_results=5)
            stats["emails_unread"] = unread_count
        else:
            unread_count = 0
            recent_emails = []
    except Exception as e:
        logger.error(f"Gmail fetch failed: {e}")
        unread_count = 0
        recent_emails = []
        errors.append("gmail unavailable")

    # ---- Build context for Claude ----
    now = datetime.now()
    context = f"""MORNING BRIEFING DATA — {now.strftime('%A, %B %d, %Y')}

TODAY'S CALENDAR ({stats['events_today']} events):
{_format_events_for_context(events)}

PENDING TASKS ({stats['tasks_pending']} items):
{_format_tasks_for_context(tasks)}

EMAIL INBOX ({stats['emails_unread']} unread):
{_format_emails_for_context(recent_emails, unread_count)}
"""

    # ---- Build briefing prompt ----
    prompt = f"""Generate a morning briefing for {cfg.owner_name}.

The briefing should:
- Open with a time-aware greeting using their title ({cfg.owner_title})
- Summarize today's schedule tactically — flag conflicts, back-to-back meetings, anything noteworthy
- Highlight the most important pending tasks
- Give an email inbox status — not every email, just the signal
- Close with a sharp one-line priority for the day
- Be concise — this is read first thing in the morning, not a novel
- Sound like JARVIS briefing Tony Stark — calm authority, not a cheerful assistant

Do NOT use bullet points for the opening or closing. Use them only for the schedule and task sections.
Do NOT start with 'Good morning' if it's after noon."""

    # ---- Call Claude (always Sonnet for briefings — quality matters here) ----
    ai = JarvisAI()
    result = ai.respond(
        query=prompt,
        context=context,
        force_layer=3,
    )

    briefing_text = result.get("response", "Briefing generation failed.")

    logger.info(
        f"Morning briefing generated — "
        f"{stats['events_today']} events, "
        f"{stats['tasks_pending']} tasks, "
        f"{stats['emails_unread']} unread emails"
    )

    return {
        "briefing": briefing_text,
        "stats": stats,
        "generated_at": now.isoformat(),
        "tokens": result.get("tokens", {}),
        "error": ", ".join(errors) if errors else None,
    }
