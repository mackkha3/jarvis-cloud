"""Encrypted SQLite event store for JARVIS Phase 2 Ambient Intelligence.

Uses SQLCipher for AES-256 encryption at rest. Key from EVENTS_DB_KEY env var.
Database file at /app/data/events.db — uses Railway volume when mounted.
"""
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
import logging

logger = logging.getLogger("jarvis.patterns.store")

# Try sqlcipher3-binary first (precompiled, reliable on Railway),
# fall back to pysqlcipher3 (requires system libsqlcipher-dev).
try:
    import sqlcipher3 as sqlcipher
except ImportError:
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher
    except ImportError:
        sqlcipher = None
        logger.error("No SQLCipher binding available — event store disabled")

DB_PATH = Path(os.environ.get("EVENTS_DB_PATH", "/app/data/events.db"))
DB_KEY = os.environ.get("EVENTS_DB_KEY", "")

_lock = threading.Lock()
_initialized = False


def _ensure_db() -> bool:
    """Initialize encrypted database on first use."""
    global _initialized
    if _initialized:
        return True
    if not DB_KEY:
        logger.error("EVENTS_DB_KEY not set — refusing to create unencrypted database")
        return False
    if sqlcipher is None:
        return False

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlcipher.connect(str(DB_PATH))
        conn.execute(f"PRAGMA key = '{DB_KEY}'")
        conn.execute("PRAGMA cipher_compatibility = 4")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp DATETIME DEFAULT (datetime('now')),
              event_type TEXT NOT NULL,
              entity_id TEXT,
              metadata_json TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_id)")
        conn.commit()
        conn.close()
        _initialized = True
        logger.info("Encrypted event store initialized at %s", DB_PATH)
        return True
    except Exception as e:
        logger.error("Event store init failed: %s", e)
        return False


def _connect():
    """Open encrypted connection. Caller responsible for closing."""
    if not _ensure_db():
        return None
    conn = sqlcipher.connect(str(DB_PATH))
    conn.execute(f"PRAGMA key = '{DB_KEY}'")
    conn.execute("PRAGMA cipher_compatibility = 4")
    return conn


def record(event_type: str, entity_id: str = None, metadata: dict = None) -> bool:
    """Record an event. Returns True on success, False on any failure.
    Failures NEVER raise — silent so main code path is never affected."""
    try:
        with _lock:
            conn = _connect()
            if not conn:
                return False
            meta_json = json.dumps(metadata or {}, default=str)
            conn.execute(
                "INSERT INTO events (event_type, entity_id, metadata_json) VALUES (?, ?, ?)",
                (event_type, entity_id, meta_json)
            )
            conn.commit()
            conn.close()
            return True
    except Exception as e:
        logger.error("Event record failed: %s", e)
        return False


def query_recent(event_type: str = None, entity_id: str = None, days: int = 30) -> list:
    """Query events from the last N days. Returns list of dicts."""
    try:
        with _lock:
            conn = _connect()
            if not conn:
                return []
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            sql = "SELECT timestamp, event_type, entity_id, metadata_json FROM events WHERE timestamp > ?"
            params = [cutoff]
            if event_type:
                sql += " AND event_type = ?"
                params.append(event_type)
            if entity_id:
                sql += " AND entity_id LIKE ?"
                params.append(f"%{entity_id}%")
            sql += " ORDER BY timestamp DESC"
            cur = conn.execute(sql, params)
            rows = cur.fetchall()
            conn.close()
            return [
                {
                    "timestamp": r[0],
                    "event_type": r[1],
                    "entity_id": r[2],
                    "metadata": json.loads(r[3] or "{}"),
                }
                for r in rows
            ]
    except Exception as e:
        logger.error("Event query failed: %s", e)
        return []


def count_recent(event_type: str, entity_id: str = None, days: int = 30) -> int:
    """Count matching events in the last N days."""
    return len(query_recent(event_type, entity_id, days))
