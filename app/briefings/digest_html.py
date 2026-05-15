"""
JARVIS Cloud — Email Digest HTML Generator

Generates a full-page HUD email intelligence briefing.
Design ported from ~/jarvis/email-triage/digest.html.
"""

import html
import logging
from datetime import datetime
from app.config import get_config
from app.core.claude import JarvisAI
from app.integrations.google import GoogleGmail

logger = logging.getLogger("jarvis.briefings.digest_html")

_URGENT_WORDS = [
    "urgent", "asap", "immediately", "critical",
    "important", "deadline", "overdue", "action required",
]
_REPLY_WORDS = [
    "reply", "response", "please respond", "let me know",
    "following up", "follow up", "can you", "could you",
    "waiting", "awaiting",
]
_FYI_WORDS = [
    "fyi", "for your information", "heads up", "update",
    "newsletter", "notification", "alert", "reminder",
]

_SCORES = {"urgent": 9, "reply_needed": 7, "fyi": 5, "clean": 2}

_TAG_HTML = {
    "urgent":       '<span class="tag tag-urgent">URGENT</span>',
    "reply_needed": '<span class="tag tag-reply">REPLY NEEDED</span>',
    "fyi":          '<span class="tag tag-fyi">FYI</span>',
    "clean":        '<span class="tag tag-ignore">IGNORE</span>',
}

_SCORE_COLORS = {
    "urgent": "var(--red)",
    "reply_needed": "var(--amber)",
    "fyi": "var(--cyan)",
    "clean": "var(--text-dim)",
}


def _categorize(email: dict) -> str:
    subject = (email.get("subject") or "").lower()
    snippet = (email.get("snippet") or "").lower()
    text = subject + " " + snippet
    if any(w in text for w in _URGENT_WORDS):
        return "urgent"
    if any(w in text for w in _REPLY_WORDS):
        return "reply_needed"
    if any(w in text for w in _FYI_WORDS):
        return "fyi"
    return "clean"


def _sender_name(raw: str) -> str:
    raw = (raw or "").strip()
    if "<" in raw:
        return raw.split("<")[0].strip().strip('"').strip("'") or raw
    return raw


def _email_card(email: dict, category: str) -> str:
    subject = html.escape(email.get("subject") or "No subject")
    sender = html.escape(_sender_name(email.get("from", "")))
    snippet = html.escape((email.get("snippet") or "")[:160])
    score = _SCORES.get(category, 2)
    tag_html = _TAG_HTML.get(category, "")
    card_class = {
        "urgent": "email-card email-card-urgent",
        "reply_needed": "email-card email-card-reply",
        "fyi": "email-card email-card-fyi",
        "clean": "email-card email-card-ignore",
    }.get(category, "email-card")

    return f"""
    <div class="{card_class}">
      <div class="card-header">
        <div class="email-subject">{subject}</div>
        {tag_html}
        <span class="score-num">Score: {score}</span>
      </div>
      <div class="card-body">
        <div class="email-sender">From: {sender}</div>
        <div class="email-reason">{snippet}</div>
      </div>
    </div>"""


def _intel_row(email: dict, category: str) -> str:
    subject = html.escape((email.get("subject") or "No subject")[:80])
    sender = html.escape(email.get("from") or "")
    snippet = html.escape((email.get("snippet") or "")[:120])
    score = _SCORES.get(category, 2)
    color = _SCORE_COLORS.get(category, "var(--text-dim)")
    tag_html = _TAG_HTML.get(category, "")

    return f"""
          <tr>
            <td class="td-score" style="color:{color}">{score}</td>
            <td>{subject} {tag_html}</td>
            <td class="td-sender">{sender}</td>
            <td class="td-reason">{snippet}</td>
          </tr>"""


def generate_digest_html() -> str:
    cfg = get_config()
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M")

    # ---- Fetch Gmail data ----
    gmail = GoogleGmail()
    raw_emails = gmail.get_recent_emails(max_results=30) if gmail.available else []
    unread_count = gmail.get_unread_count() if gmail.available else 0

    categorized = [(e, _categorize(e)) for e in raw_emails]

    by_cat = {"urgent": [], "reply_needed": [], "fyi": [], "clean": []}
    for email, cat in categorized:
        by_cat[cat].append(email)

    n_urgent = len(by_cat["urgent"])
    n_reply  = len(by_cat["reply_needed"])
    n_fyi    = len(by_cat["fyi"])
    n_ignore = len(by_cat["clean"])

    # ---- Claude intelligence summary ----
    summary_lines = []
    for email, cat in categorized[:15]:
        subj = email.get("subject", "No subject")[:60]
        snip = email.get("snippet", "")[:80]
        summary_lines.append(f"  [{cat.upper()}] {subj} — {snip}")
    email_summary = "\n".join(summary_lines) or "  No emails."

    context = f"""EMAIL DIGEST — {now.strftime('%A, %B %d, %Y at %H:%M')}
INBOX STATS: {unread_count} unread, {n_urgent} urgent, {n_reply} reply-needed, {n_fyi} fyi, {n_ignore} ignore
RECENT EMAILS (top 15):
{email_summary}"""

    prompt = f"""Generate a concise email intelligence summary for {cfg.owner_name}.
Identify patterns, flag anything that needs immediate attention, note what can be safely ignored.
JARVIS voice — sharp, tactical, slightly dry. 2-4 sentences. No bullet points. Plain prose."""

    ai = JarvisAI()
    result = ai.respond(query=prompt, context=context, force_layer=3)
    briefing_text = html.escape(result.get("response", "Intelligence summary unavailable."))

    # ---- Build section HTML ----
    def _section(title: str, cat: str, open_attr: str) -> str:
        emails = by_cat[cat]
        if not emails:
            return ""
        cards = "".join(_email_card(e, cat) for e in emails)
        return f"""
  <section>
    <details {open_attr}>
      <summary>{title} &mdash; {len(emails)} item(s)</summary>
      {cards}
    </details>
  </section>"""

    urgent_section      = _section("Urgent Queue",     "urgent",       "open")
    reply_section       = _section("Reply Needed",     "reply_needed", "open")
    fyi_section         = _section("FYI",              "fyi",          "")
    ignore_section      = _section("Ignore",           "clean",        "")

    # ---- Intel table rows ----
    all_intel_rows = "".join(_intel_row(e, cat) for e, cat in categorized)
    intel_table = f"""
  <section>
    <div class="sec-label">Full Intel Feed</div>
    <details>
      <summary><span class="tag tag-ignore" style="letter-spacing:0.08em">ALL</span>&ensp;{len(categorized)} item(s)</summary>
      <table class="intel-table">
        <thead><tr>
          <th>Score</th><th>Subject</th><th>From</th><th>Assessment</th>
        </tr></thead>
        <tbody>{all_intel_rows}
        </tbody>
      </table>
    </details>
  </section>""" if categorized else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>J.A.R.V.I.S // EMAIL INTEL &mdash; {timestamp}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;0,700;1,400&display=swap" rel="stylesheet">
  <style>
    :root {{
      --fs-hero: 2.5rem; --fs-section: 0.75rem; --fs-stat: 2.5rem;
      --fs-body: 0.875rem; --fs-meta: 0.7rem;
      --bg: #050811; --bg-panel: #0a1020;
      --cyan: #00d4ff; --cyan-dim: rgba(78,201,255,0.4);
      --amber: #ffb84d; --red: #ff3860;
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
      border-top: 1px solid var(--cyan); border-left: 1px solid var(--cyan); opacity: 1;
    }}
    .hud-container::after {{
      content: ''; position: absolute; top: -4px; right: -4px; width: 24px; height: 24px;
      border-top: 1px solid var(--cyan); border-right: 1px solid var(--cyan); opacity: 1;
    }}
    .hud-corner-bl, .hud-corner-br {{
      position: absolute; bottom: -4px; width: 24px; height: 24px;
      border-style: solid; border-color: var(--cyan); opacity: 1; pointer-events: none;
    }}
    .hud-corner-bl {{ left: -4px; border-width: 0 0 1px 1px; }}
    .hud-corner-br {{ right: -4px; border-width: 0 1px 1px 0; }}
    .hud-header {{
      border: 1px solid var(--cyan-dim); border-top: 2px solid var(--cyan);
      background: linear-gradient(180deg, rgba(0,212,255,0.05) 0%, transparent 100%);
      padding: 1.5rem; margin-bottom: 3rem;
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
    .jarvis-core {{ width: 120px; height: 120px; flex-shrink: 0; }}
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
    section {{ margin-bottom: 3rem; }}
    .briefing-card {{ border: 1px solid var(--cyan-dim); background: var(--bg-panel); padding: 1.5rem; position: relative; }}
    .briefing-card::before {{
      content: '// INTELLIGENCE SUMMARY';
      position: absolute; top: -0.5rem; left: 1.5rem;
      font-size: var(--fs-meta); letter-spacing: 0.2em; text-transform: uppercase;
      color: var(--cyan); background: var(--bg); padding: 0 0.5rem;
    }}
    .briefing-text {{ font-size: var(--fs-body); line-height: 1.6; color: var(--text); font-style: italic; }}
    .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }}
    .stat {{ border: 1px solid var(--border); background: var(--bg-panel); padding: 1.5rem; text-align: center; }}
    .stat-n {{ font-size: var(--fs-stat); font-weight: 700; line-height: 1.2; display: block; }}
    .stat-l {{ font-size: var(--fs-section); letter-spacing: 0.2em; text-transform: uppercase; color: var(--text-dim); margin-top: 0.5rem; display: block; }}
    .stat-urgent {{ border-color: rgba(255,56,96,0.35); }}
    .stat-reply  {{ border-color: rgba(255,184,77,0.35); }}
    .stat-fyi    {{ border-color: var(--cyan-dim); }}
    .stat-ignore {{ border-color: rgba(108,128,144,0.3); }}
    .email-card {{ border: 1px solid var(--cyan-dim); background: var(--bg-panel); margin-bottom: 1rem; }}
    .email-card-urgent {{ border-color: rgba(255,56,96,0.5); animation: pulse-urgent 2.5s ease-in-out infinite; }}
    .email-card-reply  {{ border-color: rgba(255,184,77,0.4); }}
    .email-card-fyi    {{ border-color: var(--cyan-dim); }}
    .email-card-ignore {{ border-color: rgba(108,128,144,0.2); opacity: 0.7; }}
    @keyframes pulse-urgent {{ 0%, 100% {{ box-shadow: 0 0 10px rgba(255,56,96,0.08); }} 50% {{ box-shadow: 0 0 24px rgba(255,56,96,0.28); }} }}
    .card-header {{ padding: 1rem 1.5rem; border-bottom: 1px solid var(--border); display: flex; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }}
    .card-body {{ padding: 1rem 1.5rem; }}
    .email-subject {{ font-size: var(--fs-body); font-weight: 500; color: var(--text); flex: 1; min-width: 0; }}
    .email-sender {{ font-size: var(--fs-meta); color: var(--text-dim); margin-top: 0.5rem; }}
    .email-reason {{ font-size: var(--fs-meta); color: var(--text-dim); margin-top: 0.5rem; }}
    .score-num {{ font-size: var(--fs-meta); color: var(--text-dim); white-space: nowrap; flex-shrink: 0; }}
    .tag {{ font-size: var(--fs-meta); font-weight: 700; letter-spacing: 0.12em; padding: 0.15rem 0.5rem; white-space: nowrap; flex-shrink: 0; border: 1px solid; display: inline-block; }}
    .tag-urgent {{ border-color: rgba(255,56,96,0.5);   color: var(--red);      background: rgba(255,56,96,0.08); }}
    .tag-reply  {{ border-color: rgba(255,184,77,0.5);  color: var(--amber);    background: rgba(255,184,77,0.07); }}
    .tag-fyi    {{ border-color: var(--cyan-dim);       color: var(--cyan);     background: rgba(0,212,255,0.06); }}
    .tag-ignore {{ border-color: rgba(108,128,144,0.4); color: var(--text-dim); background: rgba(108,128,144,0.07); }}
    details {{ margin-bottom: 1.5rem; }}
    summary {{
      cursor: pointer; list-style: none; -webkit-user-select: none; user-select: none;
      display: flex; align-items: center; gap: 0.75rem;
      padding: 0.75rem 1rem; border-left: 2px solid var(--cyan-dim);
      background: var(--bg-panel); font-size: var(--fs-section); font-weight: 700;
      letter-spacing: 0.2em; text-transform: uppercase; color: var(--text-dim);
      transition: border-color 0.2s, box-shadow 0.2s, color 0.2s; margin-bottom: 1rem;
    }}
    summary::-webkit-details-marker, summary::marker {{ display: none; }}
    summary:hover {{ border-left-color: var(--cyan); box-shadow: -3px 0 16px rgba(0,212,255,0.12); color: var(--text); }}
    summary::before {{ content: '›'; font-size: 1.1rem; color: var(--cyan); display: inline-block; transition: transform 0.25s ease; line-height: 1; flex-shrink: 0; }}
    details[open] > summary::before {{ transform: rotate(90deg); }}
    .intel-table {{ width: 100%; border-collapse: collapse; font-size: var(--fs-body); }}
    .intel-table thead tr {{ border-bottom: 1px solid var(--border); background: rgba(0,212,255,0.02); }}
    .intel-table th {{ padding: 0.5rem 1rem; text-align: left; font-size: var(--fs-meta); letter-spacing: 0.2em; text-transform: uppercase; color: var(--text-dim); font-weight: 400; }}
    .intel-table td {{ padding: 0.75rem 1rem; border-bottom: 1px solid rgba(26,42,64,0.8); vertical-align: top; }}
    .intel-table tr:last-child td {{ border-bottom: none; }}
    .intel-table tr:hover td {{ background: rgba(0,212,255,0.02); }}
    .td-score  {{ text-align: center; font-weight: 700; width: 4rem; }}
    .td-sender {{ color: var(--text-dim); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .td-reason {{ color: var(--text-dim); font-size: var(--fs-meta); }}
    .hud-footer {{
      border-top: 1px solid var(--border); padding-top: 1.5rem; margin-top: 3rem;
      display: flex; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem;
      font-size: var(--fs-meta); color: var(--text-dim); letter-spacing: 0.1em; text-transform: uppercase;
    }}
    .hud-footer .ft-val {{ color: var(--cyan); }}
    @media (max-width: 700px) {{
      body {{ padding: 1rem; }}
      .stats {{ grid-template-columns: repeat(2, 1fr); }}
      .stat-n {{ font-size: 2rem; }}
      .hud-header {{ flex-direction: column; align-items: flex-start; }}
      .hud-meta {{ align-items: flex-start; }}
      .hud-meta-row {{ justify-content: flex-start; }}
      .hud-title {{ font-size: 1.25rem; }}
      .intel-table {{ font-size: var(--fs-meta); }}
      .td-sender {{ max-width: 100px; }}
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
        <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" class="jarvis-core" aria-hidden="true">
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
              <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur"/>
              <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
            </filter>
          </defs>
          <circle cx="60" cy="60" r="58" fill="url(#jc-halo)"/>
          <g class="ring-outer">
            <circle cx="60" cy="60" r="53" fill="none" stroke="#00d4ff" stroke-width="1" stroke-opacity="0.35" stroke-dasharray="10 6" stroke-linecap="round"/>
          </g>
          <g class="ring-mid">
            <circle cx="60" cy="60" r="41" fill="none" stroke="#00d4ff" stroke-width="1.5" stroke-opacity="0.55" stroke-dasharray="5 3" stroke-linecap="round"/>
          </g>
          <g class="ring-inner">
            <circle cx="60" cy="60" r="28" fill="none" stroke="#00d4ff" stroke-width="2" stroke-opacity="0.8" stroke-dasharray="4 2" stroke-linecap="round"/>
          </g>
          <circle cx="60" cy="60" r="16" fill="url(#jc-orb)" class="orb-pulse" filter="url(#jc-glow)"/>
          <circle cx="60" cy="60" r="4" fill="#ffffff" opacity="0.95" class="orb-pulse"/>
        </svg>
      </div>
      <div class="hud-brand">
        <div class="hud-title">J.A.R.V.I.S</div>
        <div class="hud-subtitle">Email Intelligence Briefing // Channel_01</div>
        <div class="status-row">
          <span class="status-item"><span class="status-dot dot-green"></span>Sys_Online</span>
          <span class="status-item"><span class="status-dot dot-cyan"></span>{unread_count} Unread</span>
          <span class="status-item"><span class="status-dot dot-amber"></span>{n_urgent} Urgent</span>
        </div>
      </div>
      <div class="hud-meta">
        <div class="hud-meta-row">
          <span class="hud-meta-item">Timestamp&ensp;<span class="val">{timestamp}</span></span>
          <span class="hud-meta-item">Processed&ensp;<span class="val">{len(categorized)}</span></span>
          <span class="hud-meta-item">Window&ensp;<span class="val">Recent</span></span>
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
      <div class="stat stat-urgent">
        <span class="stat-n" style="color:var(--red)">{n_urgent}</span>
        <span class="stat-l">Urgent</span>
      </div>
      <div class="stat stat-reply">
        <span class="stat-n" style="color:var(--amber)">{n_reply}</span>
        <span class="stat-l">Reply Needed</span>
      </div>
      <div class="stat stat-fyi">
        <span class="stat-n" style="color:var(--cyan)">{n_fyi}</span>
        <span class="stat-l">FYI</span>
      </div>
      <div class="stat stat-ignore">
        <span class="stat-n" style="color:var(--text-dim)">{n_ignore}</span>
        <span class="stat-l">Ignore</span>
      </div>
    </div>
  </section>

  {urgent_section}
  {reply_section}
  {fyi_section}
  {ignore_section}
  {intel_table}

  <footer>
    <div class="hud-footer">
      <span>J.A.R.V.I.S Email Triage&ensp;<span class="ft-val">v2.0</span></span>
      <span>Generated&ensp;<span class="ft-val">{timestamp}</span></span>
      <span>Processed&ensp;<span class="ft-val">{len(categorized)} emails</span></span>
    </div>
  </footer>

</div>
</body>
</html>"""
