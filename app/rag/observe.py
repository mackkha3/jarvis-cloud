"""
Per-query observability and audit, with data minimisation by design.

Every retrieval emits one structured record: latency, top score, how many
chunks cleared the threshold, the answer/abstain decision, which collection
served it, and which document *ids* were used. It deliberately never stores the
query text or any chunk contents — only hashes and ids — so the audit trail is
useful for debugging and least-privilege review without becoming a second copy
of the corpus. This mirrors the event store's existing data-minimisation stance.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.rag.retrieve import Result


def _qhash(query: str) -> str:
    """Short stable fingerprint of a query — lets us group repeats, not read them."""
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:16]


@dataclass
class QueryRecord:
    ts: float
    query_hash: str
    decision: str
    top_score: float
    n_hits: int
    elapsed_ms: float
    index_id: str | None
    source_ids: list[str] = field(default_factory=list)   # ids only, never text
    caller: str = "context_hook"

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


def record_from_result(result: Result, *, caller: str = "context_hook") -> QueryRecord:
    return QueryRecord(
        ts=time.time(),
        query_hash=_qhash(result.query),
        decision=result.decision,
        top_score=round(result.hits[0].score, 4) if result.hits else 0.0,
        n_hits=len(result.hits),
        elapsed_ms=round(result.elapsed_ms, 2),
        index_id=result.index_id,
        source_ids=sorted({h.chunk.source_id for h in result.hits}),
        caller=caller,
    )


class AuditLog:
    """Append-only query log in SQLite. Contents-free by construction."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS rag_audit (
                 ts REAL, query_hash TEXT, decision TEXT, top_score REAL,
                 n_hits INTEGER, elapsed_ms REAL, index_id TEXT,
                 source_ids TEXT, caller TEXT
               )"""
        )
        self._conn.commit()

    def write(self, rec: QueryRecord) -> None:
        self._conn.execute(
            """INSERT INTO rag_audit
               (ts, query_hash, decision, top_score, n_hits, elapsed_ms, index_id, source_ids, caller)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (rec.ts, rec.query_hash, rec.decision, rec.top_score, rec.n_hits,
             rec.elapsed_ms, rec.index_id, json.dumps(rec.source_ids), rec.caller),
        )
        self._conn.commit()

    def recent(self, limit: int = 50) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM rag_audit ORDER BY ts DESC LIMIT ?", (limit,)
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            r["source_ids"] = json.loads(r["source_ids"])
        return rows

    def stats(self) -> dict:
        row = self._conn.execute(
            """SELECT COUNT(*) AS n,
                      AVG(elapsed_ms) AS avg_ms,
                      SUM(CASE WHEN decision='abstain' THEN 1 ELSE 0 END) AS abstains
               FROM rag_audit"""
        ).fetchone()
        n, avg_ms, abstains = row[0], row[1], row[2]
        return {
            "queries": n,
            "avg_latency_ms": round(avg_ms, 2) if avg_ms else 0.0,
            "abstain_rate": round(abstains / n, 4) if n else 0.0,
        }

    def close(self) -> None:
        self._conn.close()
