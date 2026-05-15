"""
JARVIS Cloud — Evening Debrief Generator

Same data pipeline as morning briefing but different Claude prompt.
Tone: end-of-day recap, carry-overs, tomorrow preview.
"""

import logging
from datetime import datetime, timezone, timedelta
from app.config import get_config
from app.core.claude import JarvisAI
from app.integrations.google import GoogleCalendar, GoogleTasks, GoogleGmail

logger = logging.getLogger("jarvis.briefings.evening")


def generate_evening_debrief() -> dict:
    """
    Generates evening debrief data (JSON — for dashboard panel).
    """
    cfg = get_config()
    now = datetime.now()
    logger.info(f"Generating evening debrief for {cfg.owner_name}")

    # ---- Fetch data ----
    stats = {"events_today": 0, "tasks_pending": 0, "emails_unread": 0}
    errors = []

    try:
        calendar = GoogleCalendar()
        events_today = calendar.get_todays_events() if calendar.available else []
        tomorrow_start = now + timedelta(days=1)
        events_tomorrow = calendar.get_upcoming_events(days=2) if calendar.available else []
        events_tomorrow = [
            e for e in events_tomorrow
            if e.get("start", "").startswith(tomorrow_start.strftime("%Y-%m-%d"))
        ]
        stats["events_today"] = len(events_today)
    except Exception as e:
        logger.error(f"Calendar error: {e}")
        events_today = []
        events_tomorrow = []
        errors.append("calendar unavailable")

    try:
        tasks_client = GoogleTasks()
        tasks = tasks_client.get_tasks() if tasks_client.available else []
        stats["tasks_pending"] = len(tasks)
    except Exception as e:
        logger.error(f"Tasks error: {e}")
        tasks = []
        errors.append("tasks unavailable")

    try:
        gmail = GoogleGmail()
        unread_count = gmail.get_unread_count() if gmail.available else 0
        recent_emails = gmail.get_recent_emails(max_results=5) if gmail.available else []
        stats["emails_unread"] = unread_count
    except Exception as e:
        logger.error(f"Gmail error: {e}")
        unread_count = 0
        recent_emails = []
        errors.append("gmail unavailable")

    # ---- Build context ----
    events_today_text = "\n".join([
        f"  - {e.get('summary','Untitled')}"
        for e in events_today
    ]) or "  No events today."

    events_tomorrow_text = "\n".join([
        f"  - {e.get('summary','Untitled')}"
        for e in events_tomorrow
    ]) or "  Nothing scheduled yet."

    tasks_text = "\n".join([
        f"  - {t.get('title','Untitled')}"
        for t in tasks
    ]) or "  No pending tasks."

    context = f"""EVENING DEBRIEF DATA — {now.strftime('%A, %B %d, %Y at %I:%M %p')}

TODAY'S EVENTS ({len(events_today)} total):
{events_today_text}

TOMORROW'S EVENTS ({len(events_tomorrow)} scheduled):
{events_tomorrow_text}

PENDING TASKS CARRYING OVER ({len(tasks)}):
{tasks_text}

EMAIL STATUS: {unread_count} unread"""

    prompt = f"""Generate an evening debrief for {cfg.owner_name}.

Tone: end of day, closing out the war room. JARVIS wrapping up the day shift.
- Acknowledge what the day held (reference actual events)
- Flag any tasks still pending — carry-over items
- Preview tomorrow briefly
- Close with a sharp one-liner — could be motivating, dry, or both
- 3-5 sentences maximum. Prose only, no bullet points.
- Sound like JARVIS at end of day — not cheerful, not somber. Professional with edge."""

    ai = JarvisAI()
    result = ai.respond(query=prompt, context=context, force_layer=3)
    briefing_text = result.get("response", "Debrief unavailable.")

    logger.info(
        f"Evening debrief generated — "
        f"{stats['events_today']} events today, "
        f"{stats['tasks_pending']} tasks pending, "
        f"{unread_count} unread emails"
    )

    return {
        "briefing_text": briefing_text,
        "stats": stats,
        "events_tomorrow": len(events_tomorrow),
        "generated_at": now.isoformat(),
        "tokens": result.get("tokens", {}),
        "error": ", ".join(errors) if errors else None,
    }
