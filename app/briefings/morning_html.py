"""
JARVIS Cloud — Morning Brief HTML Generator

Generates a full-page HTML briefing using the original JARVIS design.
CSS and SVG copied verbatim from the working original.
"""

import logging
from datetime import datetime
from app.config import get_config
from app.core.claude import JarvisAI
from app.integrations.google import GoogleCalendar, GoogleTasks, GoogleGmail

logger = logging.getLogger("jarvis.briefings.morning_html")


def _format_time(iso_str: str, all_day: bool = False) -> tuple[str, bool]:
    """Returns (formatted_time, is_all_day)."""
    if all_day or not iso_str or "T" not in iso_str:
        return "All Day", True
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%I:%M %p").lstrip("0"), False
    except Exception:
        return iso_str[:10], False


def generate_morning_brief_html() -> str:
    cfg = get_config()
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    date_display = now.strftime("%A, %B %d")

    # ---- Fetch data ----
    calendar = GoogleCalendar()
    tasks_client = GoogleTasks()
    gmail = GoogleGmail()

    events = calendar.get_todays_events() if calendar.available else []
    tasks = tasks_client.get_tasks() if tasks_client.available else []
    unread_count = gmail.get_unread_count() if gmail.available else 0
    recent_emails = gmail.get_recent_emails(max_results=10) if gmail.available else []

    urgent_emails = []
    for email in recent_emails:
        text = ((email.get("subject") or "") + " " + (email.get("snippet") or "")).lower()
        if any(w in text for w in ["urgent", "asap", "immediately", "critical", "action required", "deadline"]):
            urgent_emails.append(email)

    # ---- Claude briefing ----
    events_text = "\n".join([
        f"  - {_format_time(e.get('start',''), e.get('all_day', False))[0]} {e.get('summary','Untitled')}"
        for e in events
    ]) or "  No events today."

    tasks_text = "\n".join([
        f"  - {t.get('title','Untitled')}" + (f" (due {t.get('due','')[:10]})" if t.get('due') else "")
        for t in tasks
    ]) or "  No pending tasks."

    context = f"""MORNING BRIEFING DATA — {now.strftime('%A, %B %d, %Y')}
TODAY'S EVENTS ({len(events)}):
{events_text}
PENDING TASKS ({len(tasks)}):
{tasks_text}
EMAIL: {unread_count} unread, {len(urgent_emails)} urgent"""

    prompt = f"""Generate a morning briefing paragraph for {cfg.owner_name}.
Be tactical, sharp, and concise — JARVIS briefing Tony Stark style.
Reference specific events and tasks by name. Note any risks or conflicts.
Close with a dry wit remark if appropriate. 2-4 sentences maximum.
Do NOT use bullet points. Plain prose only."""

    ai = JarvisAI()
    result = ai.respond(query=prompt, context=context, force_layer=3)
    briefing_text = result.get("response", "Briefing unavailable.").replace('"', '&quot;').replace("'", "&#x27;")

    # ---- Schedule HTML ----
    schedule_items = ""
    for e in events:
        time_str, is_all_day = _format_time(e.get("start", ""), e.get("all_day", False))
        badge_class = "time-badge allday" if is_all_day else "time-badge"
        title = e.get("summary", "Untitled")
        location = e.get("location", "")
        meta_html = f'<div class="event-meta">{location}</div>' if location else ""
        schedule_items += f"""
      <div class="timeline-item">
        <div class="{badge_class}">{time_str}</div>
        <div class="event-info">
          <div class="event-title">{title}</div>
          {meta_html}
        </div>
      </div>"""

    if not schedule_items:
        schedule_items = '<div class="empty-state">No events scheduled today.</div>'

    # ---- Tasks HTML ----
    task_items = ""
    for t in tasks:
        title = t.get("title", "Untitled")
        due = t.get("due", "")[:10] if t.get("due") else ""
        meta = f"[My Tasks]{' &middot; due ' + due if due else ''}"
        task_items += f"""
      <div class="task-item">
        <span class="task-bullet">&rsaquo;</span>
        <div class="task-info">
          <div class="task-title">{title}</div>
          <div class="task-meta">{meta}</div>
        </div>
      </div>"""

    if not task_items:
        task_items = '<div class="empty-state">No pending tasks.</div>'

    # ---- Urgent emails HTML ----
    urgent_section = ""
    if urgent_emails:
        urgent_items = ""
        for e in urgent_emails:
            sender = e.get("from", "Unknown")
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            subject = e.get("subject", "No subject")
            snippet = e.get("snippet", "")[:120]
            urgent_items += f"""
          <div class="urgent-item">
            <div class="urgent-row">
              <span class="tag tag-urgent">URGENT</span>
              <div>
                <div class="urgent-subject">{subject}</div>
                <div class="urgent-meta">From: {sender}</div>
                <div class="urgent-meta">{snippet}</div>
              </div>
            </div>
          </div>"""

        urgent_section = f"""
  <section>
    <details open>
      <summary>Urgent Emails &mdash; {len(urgent_emails)} item(s)</summary>
      {urgent_items}
    </details>
  </section>"""

    # ---- Full HTML — original CSS verbatim ----
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>J.A.R.V.I.S // MORNING BRIEF &mdash; {timestamp}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;0,700;1,400&display=swap" rel="stylesheet">
  <style>
    :root {{
      --fs-hero: 2rem; --fs-section: 0.75rem; --fs-stat: 2.2rem;
      --fs-body: 0.875rem; --fs-meta: 0.7rem;
      --bg: #050811; --bg-panel: #0a1020;
      --cyan: #00d4ff; --cyan-dim: rgba(78,201,255,0.4);
      --amber: #ffb84d; --red: #ff3860; --green: #00ff88;
      --text: #c8d8e8; --text-dim: #6c8090; --border: #1a2a40;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'JetBrains Mono', 'SF Mono', ui-monospace, monospace;
      font-size: var(--fs-body); line-height: 1.6;
      background: var(--bg); color: var(--text);
      padding: 2rem 1.5rem; min-height: 100vh;
      background-image:
        radial-gradient(rgba(0,212,255,0.03) 1px, transparent 1px),
        linear-gradient(rgba(0,212,255,0.015) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,212,255,0.015) 1px, transparent 1px);
      background-size: 30px 30px, 48px 48px, 48px 48px;
    }}
    body::before {{
      content: ''; position: fixed; inset: 0;
      background: repeating-linear-gradient(0deg, transparent, transparent 3px,
        rgba(0,0,0,0.015) 3px, rgba(0,0,0,0.015) 4px);
      pointer-events: none; z-index: 9998;
    }}
    @keyframes scanbeam {{ 0% {{ transform: translateY(-100vh); }} 100% {{ transform: translateY(200vh); }} }}
    body::after {{
      content: ''; position: fixed; left: 0; top: 0; width: 100%; height: 3px;
      background: linear-gradient(transparent, rgba(0,212,255,0.04), transparent);
      animation: scanbeam 15s linear infinite; pointer-events: none; z-index: 9999;
    }}
    .hud-container {{ max-width: 1100px; margin: 0 auto; position: relative; }}
    .hud-container::before {{
      content: ''; position: absolute; top: -4px; left: -4px; width: 24px; height: 24px;
      border-top: 1px solid var(--cyan); border-left: 1px solid var(--cyan);
    }}
    .hud-container::after {{
      content: ''; position: absolute; top: -4px; right: -4px; width: 24px; height: 24px;
      border-top: 1px solid var(--cyan); border-right: 1px solid var(--cyan);
    }}
    .hud-corner-bl, .hud-corner-br {{
      position: absolute; bottom: -4px; width: 24px; height: 24px;
      border-style: solid; border-color: var(--cyan); pointer-events: none;
    }}
    .hud-corner-bl {{ left: -4px; border-width: 0 0 1px 1px; }}
    .hud-corner-br {{ right: -4px; border-width: 0 1px 1px 0; }}
    .hud-header {{
      border: 1px solid var(--cyan-dim); border-top: 2px solid var(--cyan);
      background: linear-gradient(180deg, rgba(0,212,255,0.05) 0%, transparent 100%);
      padding: 1.25rem 1.5rem; margin-bottom: 2rem;
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 1rem;
    }}
    .hud-title {{
      font-family: 'Orbitron', sans-serif; font-size: var(--fs-hero);
      font-weight: 700; line-height: 1.2; color: var(--cyan);
      text-shadow: 0 0 20px rgba(0,212,255,0.45), 0 0 60px rgba(0,212,255,0.12);
      letter-spacing: 0.03em;
    }}
    .hud-subtitle {{
      font-size: var(--fs-meta); color: rgba(78,201,255,0.6);
      letter-spacing: 0.15em; text-transform: uppercase; margin-top: 0.25rem;
    }}
    .hud-meta {{ display: flex; flex-direction: column; align-items: flex-end; gap: 0.5rem; }}
    .hud-meta-row {{ display: flex; gap: 1.5rem; flex-wrap: wrap; justify-content: flex-end; }}
    .hud-meta-item {{ font-size: var(--fs-meta); color: var(--text-dim); letter-spacing: 0.1em; text-transform: uppercase; }}
    .hud-meta-item .val {{ color: var(--cyan); }}
    .hud-core {{ flex-shrink: 0; }}
    .hud-brand {{ flex: 1; min-width: 0; }}
    .jarvis-core {{ width: 80px; height: 80px; flex-shrink: 0; }}
    .ring-outer {{ transform-box: fill-box; transform-origin: center; animation: spin-cw 20s linear infinite; }}
    .ring-mid   {{ transform-box: fill-box; transform-origin: center; animation: spin-ccw 10s linear infinite; }}
    .ring-inner {{ transform-box: fill-box; transform-origin: center; animation: spin-cw 4s linear infinite; }}
    .orb-pulse {{ animation: orb-glow 2s ease-in-out infinite; }}
    @keyframes spin-cw  {{ to {{ transform: rotate(360deg); }} }}
    @keyframes spin-ccw {{ to {{ transform: rotate(-360deg); }} }}
    @keyframes orb-glow {{ 0%, 100% {{ opacity: 0.75; }} 50% {{ opacity: 1; }} }}
    .status-row {{ display: flex; gap: 1.5rem; flex-wrap: wrap; align-items: center; margin-top: 1rem; }}
    .status-item {{ display: flex; align-items: center; gap: 0.4rem; font-size: var(--fs-meta); color: var(--text-dim); letter-spacing: 0.12em; text-transform: uppercase; }}
    .status-dot {{ width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }}
    .dot-green {{ background: #00ff88; box-shadow: 0 0 4px #00ff88; animation: dot-pulse 2s ease-in-out infinite; }}
    .dot-cyan  {{ background: var(--cyan); box-shadow: 0 0 4px var(--cyan); animation: dot-pulse 2.5s ease-in-out infinite 0.4s; }}
    .dot-amber {{ background: var(--amber); box-shadow: 0 0 4px var(--amber); animation: dot-pulse 3s ease-in-out infinite 0.8s; }}
    @keyframes dot-pulse {{ 0%, 100% {{ opacity: 0.6; }} 50% {{ opacity: 1; }} }}
    .sec-label {{
      font-size: var(--fs-section); font-weight: 700; letter-spacing: 0.2em;
      text-transform: uppercase; color: var(--text-dim);
      display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem;
    }}
    .sec-label::after {{ content: ''; flex: 1; height: 1px; background: linear-gradient(90deg, var(--border), transparent); }}
    section {{ margin-bottom: 2.5rem; }}
    .briefing-card {{ border: 1px solid var(--cyan-dim); background: var(--bg-panel); padding: 1.5rem 2rem; position: relative; }}
    .briefing-card::before {{
      content: '// MORNING INTEL';
      position: absolute; top: -0.5rem; left: 1.5rem;
      font-size: var(--fs-meta); letter-spacing: 0.2em; text-transform: uppercase;
      color: var(--cyan); background: var(--bg); padding: 0 0.5rem;
    }}
    .briefing-text {{ font-size: 0.95rem; line-height: 1.75; color: var(--text); font-style: italic; }}
    .stats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }}
    .stat {{ border: 1px solid var(--border); background: var(--bg-panel); padding: 1.25rem; text-align: center; }}
    .stat-n {{ font-size: var(--fs-stat); font-weight: 700; line-height: 1.2; display: block; }}
    .stat-l {{ font-size: var(--fs-section); letter-spacing: 0.2em; text-transform: uppercase; color: var(--text-dim); margin-top: 0.5rem; display: block; }}
    .stat-events {{ border-color: var(--cyan-dim); }}
    .stat-tasks  {{ border-color: rgba(255,184,77,0.35); }}
    .stat-urgent {{ border-color: rgba(255,56,96,0.35); }}
    details {{ margin-bottom: 1rem; }}
    summary {{
      cursor: pointer; list-style: none; -webkit-user-select: none; user-select: none;
      display: flex; align-items: center; gap: 0.75rem;
      padding: 0.75rem 1rem; border-left: 2px solid var(--cyan-dim);
      background: var(--bg-panel); font-size: var(--fs-section); font-weight: 700;
      letter-spacing: 0.2em; text-transform: uppercase; color: var(--text-dim);
      transition: border-color 0.2s, box-shadow 0.2s, color 0.2s; margin-bottom: 0.75rem;
    }}
    summary::-webkit-details-marker, summary::marker {{ display: none; }}
    summary:hover {{ border-left-color: var(--cyan); box-shadow: -3px 0 16px rgba(0,212,255,0.12); color: var(--text); }}
    summary::before {{ content: '›'; font-size: 1.1rem; color: var(--cyan); display: inline-block; transition: transform 0.25s ease; line-height: 1; flex-shrink: 0; }}
    details[open] > summary::before {{ transform: rotate(90deg); }}
    .timeline {{ display: flex; flex-direction: column; gap: 0.5rem; }}
    .timeline-item {{ display: flex; gap: 1rem; align-items: flex-start; border: 1px solid var(--border); background: var(--bg-panel); padding: 0.875rem 1rem; }}
    .time-badge {{ font-size: var(--fs-meta); font-weight: 700; color: var(--cyan); letter-spacing: 0.08em; white-space: nowrap; min-width: 5.5rem; flex-shrink: 0; padding-top: 0.1rem; }}
    .time-badge.allday {{ color: var(--text-dim); }}
    .event-info {{ flex: 1; min-width: 0; }}
    .event-title {{ font-size: var(--fs-body); color: var(--text); font-weight: 500; }}
    .event-meta  {{ font-size: var(--fs-meta); color: var(--text-dim); margin-top: 0.25rem; }}
    .empty-state {{ font-size: var(--fs-meta); color: var(--text-dim); letter-spacing: 0.1em; text-transform: uppercase; padding: 1rem; border: 1px solid var(--border); background: var(--bg-panel); text-align: center; }}
    .task-list {{ display: flex; flex-direction: column; gap: 0.5rem; }}
    .task-item {{ display: flex; gap: 0.75rem; align-items: flex-start; border: 1px solid var(--border); background: var(--bg-panel); padding: 0.75rem 1rem; }}
    .task-bullet {{ color: var(--amber); flex-shrink: 0; margin-top: 0.15rem; }}
    .task-info {{ flex: 1; min-width: 0; }}
    .task-title {{ font-size: var(--fs-body); color: var(--text); }}
    .task-meta  {{ font-size: var(--fs-meta); color: var(--text-dim); margin-top: 0.2rem; }}
    .urgent-item {{ border: 1px solid rgba(255,56,96,0.5); background: var(--bg-panel); padding: 0.875rem 1rem; margin-bottom: 0.5rem; animation: pulse-urgent 2.5s ease-in-out infinite; }}
    @keyframes pulse-urgent {{ 0%, 100% {{ box-shadow: 0 0 10px rgba(255,56,96,0.08); }} 50% {{ box-shadow: 0 0 24px rgba(255,56,96,0.28); }} }}
    .urgent-row {{ display: flex; align-items: flex-start; gap: 0.75rem; }}
    .urgent-subject {{ font-size: var(--fs-body); color: var(--text); font-weight: 500; }}
    .urgent-meta    {{ font-size: var(--fs-meta); color: var(--text-dim); margin-top: 0.25rem; }}
    .tag {{ font-size: var(--fs-meta); font-weight: 700; letter-spacing: 0.12em; padding: 0.15rem 0.5rem; white-space: nowrap; border: 1px solid; display: inline-block; }}
    .tag-urgent {{ border-color: rgba(255,56,96,0.5); color: var(--red); background: rgba(255,56,96,0.08); }}
    .hud-footer {{
      border-top: 1px solid var(--border); padding-top: 1.5rem; margin-top: 2.5rem;
      display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;
      font-size: var(--fs-meta); color: var(--text-dim); letter-spacing: 0.1em; text-transform: uppercase;
    }}
    .hud-footer .ft-val {{ color: var(--cyan); }}
    @media (max-width: 1100px) {{ .hud-container {{ max-width: 100%; }} }}
    @media (max-width: 768px) {{
      body {{ padding: 1rem; }}
      .hud-header {{ flex-direction: column; align-items: flex-start; }}
      .hud-meta {{ align-items: flex-start; }}
      .hud-meta-row {{ justify-content: flex-start; }}
      .hud-title {{ font-size: 1.5rem; }}
    }}
    @media (max-width: 375px) {{
      .stats {{ grid-template-columns: 1fr; }}
      .stat-n {{ font-size: 1.75rem; }}
      .time-badge {{ min-width: 4rem; }}
    }}
  </style>
</head>
<body>
<div class="hud-container">
  <span class="hud-corner-bl"></span>
  <span class="hud-corner-br"></span>

  <header>
    <div class="hud-header">
      <div class="hud-core">
        <svg viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg" class="jarvis-core" aria-hidden="true">
          <defs>
            <radialGradient id="jc-halo" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="#00d4ff" stop-opacity="0.18"/>
              <stop offset="70%"  stop-color="#00d4ff" stop-opacity="0.04"/>
              <stop offset="100%" stop-color="#00d4ff" stop-opacity="0"/>
            </radialGradient>
            <radialGradient id="jc-orb" cx="50%" cy="50%" r="50%">
              <stop offset="0%"   stop-color="#ffffff" stop-opacity="1"/>
              <stop offset="35%"  stop-color="#00d4ff" stop-opacity="0.9"/>
              <stop offset="100%" stop-color="#00d4ff" stop-opacity="0"/>
            </radialGradient>
            <filter id="jc-glow" x="-50%" y="-50%" width="200%" height="200%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="2" result="blur"/>
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          <circle cx="40" cy="40" r="38" fill="url(#jc-halo)"/>
          <g class="ring-outer">
            <circle cx="40" cy="40" r="35" fill="none" stroke="#00d4ff" stroke-width="1"   stroke-opacity="0.35" stroke-dasharray="8 5"  stroke-linecap="round"/>
          </g>
          <g class="ring-mid">
            <circle cx="40" cy="40" r="27" fill="none" stroke="#00d4ff" stroke-width="1.5" stroke-opacity="0.55" stroke-dasharray="4 3"  stroke-linecap="round"/>
          </g>
          <g class="ring-inner">
            <circle cx="40" cy="40" r="18" fill="none" stroke="#00d4ff" stroke-width="2"   stroke-opacity="0.8"  stroke-dasharray="3 2"  stroke-linecap="round"/>
          </g>
          <circle cx="40" cy="40" r="10" fill="url(#jc-orb)" class="orb-pulse" filter="url(#jc-glow)"/>
          <circle cx="40" cy="40" r="3"  fill="#ffffff" opacity="0.95" class="orb-pulse"/>
        </svg>
      </div>
      <div class="hud-brand">
        <div class="hud-title">J.A.R.V.I.S</div>
        <div class="hud-subtitle">Morning Brief // {date_display}</div>
        <div class="status-row">
          <span class="status-item"><span class="status-dot dot-green"></span>Sys_Online</span>
          <span class="status-item"><span class="status-dot dot-cyan"></span>{len(events)} Events</span>
          <span class="status-item"><span class="status-dot dot-amber"></span>{len(tasks)} Tasks</span>
        </div>
      </div>
      <div class="hud-meta">
        <div class="hud-meta-row">
          <span class="hud-meta-item">Timestamp&ensp;<span class="val">{timestamp}</span></span>
          <span class="hud-meta-item">Channel&ensp;<span class="val">02 // MORNING</span></span>
        </div>
      </div>
    </div>
  </header>

  <section>
    <div class="briefing-card">
      <p class="briefing-text">&#8220;{briefing_text}&#8221;</p>
    </div>
  </section>

  <section>
    <div class="sec-label">Status Overview</div>
    <div class="stats">
      <div class="stat stat-events"><span class="stat-n" style="color:var(--cyan)">{len(events)}</span><span class="stat-l">Events Today</span></div>
      <div class="stat stat-tasks"><span class="stat-n" style="color:var(--amber)">{len(tasks)}</span><span class="stat-l">Open Tasks</span></div>
      <div class="stat stat-urgent"><span class="stat-n" style="color:var(--red)">{len(urgent_emails)}</span><span class="stat-l">Urgent Emails</span></div>
    </div>
  </section>

  <section>
    <details open>
      <summary>Today&#x27;s Schedule &mdash; {len(events)} event(s)</summary>
      <div class="timeline">{schedule_items}</div>
    </details>
  </section>

  <section>
    <details open>
      <summary>Open Tasks &mdash; {len(tasks)} item(s)</summary>
      <div class="task-list">{task_items}</div>
    </details>
  </section>

  {urgent_section}

  <footer>
    <div class="hud-footer">
      <span>J.A.R.V.I.S Morning Brief&ensp;<span class="ft-val">v2.0</span></span>
      <span>Generated&ensp;<span class="ft-val">{timestamp}</span></span>
      <span>Source&ensp;<span class="ft-val">Calendar + Tasks + Intel</span></span>
    </div>
  </footer>

</div>
</body>
</html>"""
