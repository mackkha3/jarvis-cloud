"""
JARVIS Cloud — Dashboard API Routes

Endpoints that power the dashboard UI.
Some are fully implemented, some are stubs
pending feature development.
"""

import logging
import os
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
from pathlib import Path

from app.api.auth import require_api_key
from app.config import get_config

logger = logging.getLogger("jarvis.api.dashboard")


def register_dashboard_routes(app: Flask) -> None:
    """Register all dashboard-related routes."""

    cfg = get_config()
    pwa_dir = Path(cfg.project_root) / "pwa" / "public"

    # ====== SERVE THE DASHBOARD ======

    @app.route("/dashboard")
    @app.route("/dashboard/")
    def dashboard():
        """Serve the Iron Man HUD dashboard."""
        return send_from_directory(str(pwa_dir), "index.html")

    # ====== CALENDAR ======

    @app.route("/api/calendar/upcoming", methods=["GET"])
    @require_api_key
    def calendar_upcoming():
        """Upcoming calendar events for the next 7 days."""
        try:
            from app.integrations.google import GoogleCalendar
            cal = GoogleCalendar()
            if not cal.available:
                return jsonify({"events": [], "error": "Calendar unavailable"})
            events = cal.get_upcoming_events(days=7)
            return jsonify({"events": events, "count": len(events)})
        except Exception as e:
            logger.exception(f"Calendar upcoming error: {e}")
            return jsonify({"events": [], "error": str(e)})

    # ====== TASKS ======

    @app.route("/api/tasks", methods=["GET"])
    @require_api_key
    def get_tasks():
        """Fetch pending Google Tasks."""
        try:
            from app.integrations.google import GoogleTasks
            tasks_client = GoogleTasks()
            if not tasks_client.available:
                return jsonify({"tasks": [], "error": "Tasks unavailable"})
            tasks = tasks_client.get_tasks()
            return jsonify({"tasks": tasks, "count": len(tasks)})
        except Exception as e:
            logger.exception(f"Tasks fetch error: {e}")
            return jsonify({"tasks": [], "error": str(e)})

    @app.route("/api/tasks", methods=["POST"])
    @require_api_key
    def create_task():
        """Create a new Google Task."""
        try:
            from app.integrations.google import GoogleTasks
            data = request.get_json(silent=True) or {}
            title = data.get("title", "").strip()
            if not title:
                return jsonify({"error": "title is required"}), 400

            tasks_client = GoogleTasks()
            result = tasks_client.create_task(
                title=title,
                notes=data.get("notes", ""),
                due=data.get("due", ""),
            )
            return jsonify({"task": result, "created": True})
        except Exception as e:
            logger.exception(f"Task creation error: {e}")
            return jsonify({"error": str(e)}), 500

    # ====== DIGEST ======

    @app.route("/api/digest", methods=["GET"])
    @require_api_key
    def digest():
        """
        Digest endpoint — powers the dashboard triage panel, chart, and header.

        Returns:
          emails: list of email objects with category tags for triage display
          events_today: count of today's calendar events
          tasks_pending: count of pending tasks
          tasks_completed: count completed today (stub — 0 until task tracking built)
          emails_unread: raw unread count
          timestamp: ISO timestamp
        """
        try:
            from app.integrations.google import GoogleCalendar, GoogleTasks, GoogleGmail

            cal = GoogleCalendar()
            tasks_client = GoogleTasks()
            gmail = GoogleGmail()

            # Calendar
            events_today = len(cal.get_todays_events()) if cal.available else 0

            # Tasks
            tasks_count = len(tasks_client.get_tasks()) if tasks_client.available else 0

            # Gmail — fetch recent emails and categorize them
            unread_count = 0
            categorized_emails = []

            if gmail.available:
                unread_count = gmail.get_unread_count()
                recent = gmail.get_recent_emails(max_results=20)

                for email in recent:
                    subject = (email.get("subject") or "").lower()
                    snippet = (email.get("snippet") or "").lower()
                    sender  = (email.get("from") or "").lower()
                    text    = subject + " " + snippet

                    # Simple heuristic categorization
                    # In a future build this will use Claude triage
                    if any(w in text for w in [
                        "urgent", "asap", "immediately", "critical",
                        "important", "deadline", "overdue", "action required"
                    ]):
                        category = "urgent"
                    elif any(w in text for w in [
                        "reply", "response", "please respond", "let me know",
                        "following up", "follow up", "can you", "could you",
                        "waiting", "awaiting"
                    ]):
                        category = "reply_needed"
                    elif any(w in text for w in [
                        "fyi", "for your information", "heads up", "update",
                        "newsletter", "notification", "alert", "reminder"
                    ]):
                        category = "fyi"
                    else:
                        category = "clean"

                    categorized_emails.append({
                        "id": email.get("id", ""),
                        "from": email.get("from", ""),
                        "subject": email.get("subject", ""),
                        "snippet": email.get("snippet", ""),
                        "category": category,
                        "tag": category,
                    })

            return jsonify({
                "emails": categorized_emails,
                "emails_unread": unread_count,
                "events_today": events_today,
                "tasks_pending": tasks_count,
                "tasks_completed": 0,
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            })

        except Exception as e:
            logger.exception(f"Digest error: {e}")
            return jsonify({
                "emails": [],
                "emails_unread": 0,
                "events_today": 0,
                "tasks_pending": 0,
                "tasks_completed": 0,
                "timestamp": "—",
                "error": str(e),
            })

    # ====== VOICE STUBS ======
    # Full implementation coming when voice layer is built.
    # Returns safe defaults so dashboard doesn't crash.

    @app.route("/api/voice/status", methods=["GET"])
    @require_api_key
    def voice_status():
        """Voice layer status — stub until voice module is built."""
        return jsonify({
            "status": "offline",
            "message": "Voice layer coming in next build",
            "wake_word": "hey_jarvis",
            "tts": "kokoro",
        })

    @app.route("/api/voice/activate", methods=["POST"])
    @require_api_key
    def voice_activate():
        """Voice activation — stub until voice module is built."""
        return jsonify({
            "activated": False,
            "message": "Voice layer coming in next build",
        })

    # ====== MEMORY STUB ======

    @app.route("/api/memory/conversation", methods=["GET"])
    @require_api_key
    def memory_conversation():
        """Last conversation memory — stub until memory module is built."""
        return jsonify({
            "turns": [],
            "message": "Memory layer coming in next build",
        })

    # ====== LOGS STUB ======

    @app.route("/api/logs/recent", methods=["GET"])
    @require_api_key
    def logs_recent():
        """Recent log lines — reads from actual log file."""
        try:
            source = request.args.get("source", "api")
            lines_count = int(request.args.get("lines", 20))
            log_path = Path(cfg.project_root) / "logs" / "jarvis.log"

            if not log_path.exists():
                return jsonify({"lines": [], "source": source})

            with open(log_path, "r") as f:
                all_lines = f.readlines()

            recent = all_lines[-lines_count:]
            return jsonify({
                "lines": [l.rstrip() for l in recent],
                "source": source,
                "count": len(recent),
            })
        except Exception as e:
            return jsonify({"lines": [], "error": str(e)})

    # ====== RUN JOBS ======

    @app.route("/api/run/<job>", methods=["POST"])
    @require_api_key
    def run_job(job: str):
        """
        Trigger autonomous jobs on demand.
        Currently supported: morning-brief, evening-brief, triage
        """
        allowed_jobs = ["morning-brief", "evening-brief", "triage"]
        if job not in allowed_jobs:
            return jsonify({
                "error": f"Unknown job '{job}'",
                "allowed": allowed_jobs,
            }), 400

        try:
            if job == "morning-brief":
                from app.briefings.morning import generate_morning_briefing
                result = generate_morning_briefing()
                return jsonify({"job": job, "result": result, "triggered": True})
            else:
                # Stubs for evening-brief and triage
                return jsonify({
                    "job": job,
                    "triggered": True,
                    "message": f"{job} coming in next build",
                })
        except Exception as e:
            logger.exception(f"Job run error: {e}")
            return jsonify({"error": str(e), "job": job}), 500

    # ====== FULL BRIEFING PAGES ======

    @app.route("/morning-brief.html", methods=["GET"])
    def morning_brief_page():
        """
        Full morning briefing page — linked from dashboard VIEW FULL BRIEFING.
        Generates fresh HTML with live data on every request.
        No auth required — served as a standalone page.
        """
        try:
            from app.briefings.morning_html import generate_morning_brief_html
            html = generate_morning_brief_html()
            from flask import Response
            return Response(html, mimetype="text/html")
        except Exception as e:
            logger.exception(f"Morning brief page error: {e}")
            return f"<h1>Error generating briefing: {e}</h1>", 500

    @app.route("/evening-debrief.html", methods=["GET"])
    def evening_debrief_page():
        """Evening debrief page — stub until evening briefing is built."""
        from flask import Response
        html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>J.A.R.V.I.S // EVENING DEBRIEF</title>
<style>
body{background:#050811;color:#00d4ff;font-family:monospace;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
.msg{text-align:center;border:1px solid rgba(0,212,255,0.3);padding:3rem;border-radius:4px;}
h1{font-size:1.5rem;margin-bottom:1rem;letter-spacing:.2em;}
p{color:#6c8090;font-size:.85rem;}
</style></head>
<body><div class="msg">
<h1>J.A.R.V.I.S</h1>
<p>EVENING DEBRIEF // COMING IN NEXT BUILD</p>
<p style="margin-top:1rem;color:#00d4ff;">Check back after 23:30</p>
</div></body></html>"""
        return Response(html, mimetype="text/html")

    # ====== SCHEDULE STUB ======

    @app.route("/api/schedule/update", methods=["POST"])
    @require_api_key
    def schedule_update():
        """Schedule update — stub until cron management is built."""
        return jsonify({
            "updated": False,
            "message": "Schedule management coming in next build",
        })
