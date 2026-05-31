"""Recorder functions for Phase 2 event capture.

Each recorder:
1. Checks FEATURE_EVENTS flag — no-op if disabled
2. Applies data minimization (no email bodies, no doc contents)
3. Wraps store.record() in try/except — never raises
"""
import hashlib
import logging

from app.config.features import is_enabled
from app.patterns import store

logger = logging.getLogger("jarvis.patterns.recorders")


def _hash_entity(text: str) -> str:
    """Hash sensitive entity text to short identifier."""
    if not text:
        return ""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _safe_record(event_type, entity_id=None, metadata=None):
    if not is_enabled('event_recording'):
        return
    try:
        store.record(event_type, entity_id, metadata)
    except Exception as e:
        logger.error("Recorder failed for %s: %s", event_type, e)


def task_created(task_title: str, due_date: str = None):
    _safe_record('task_created',
                 entity_id=task_title[:200],
                 metadata={"due_date": due_date})


def task_completed(task_title: str):
    _safe_record('task_completed', entity_id=task_title[:200])


def task_postponed(task_title: str, old_due: str, new_due: str):
    _safe_record('task_postponed',
                 entity_id=task_title[:200],
                 metadata={"old_due": old_due, "new_due": new_due})


def event_created(summary: str, start_time: str, attendees_count: int = 0):
    _safe_record('event_created',
                 entity_id=summary[:200],
                 metadata={"start_time": start_time, "attendees_count": attendees_count})


def email_received(sender: str, subject: str):
    """Records metadata only — never the email body."""
    _safe_record('email_received',
                 entity_id=_hash_entity(sender),
                 metadata={"sender_hash": _hash_entity(sender), "subject_length": len(subject or "")})


def email_responded(sender: str, hours_to_respond: float):
    _safe_record('email_responded',
                 entity_id=_hash_entity(sender),
                 metadata={"hours_to_respond": round(hours_to_respond, 2)})


def voice_query(transcript: str, intent: str = "general"):
    """Records intent and entity hash — NOT raw transcript."""
    _safe_record('voice_query',
                 entity_id=_hash_entity(transcript),
                 metadata={"intent": intent, "transcript_length": len(transcript or "")})
