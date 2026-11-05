"""
Vector store with versioned collections.

Vectors live in SQLite (the same ``/app/data`` convention as the event store and
usage tracker), one row per chunk, grouped by an ``index_id`` — a *collection*.
Re-indexing writes a brand-new collection and only flips the ``active`` pointer
once its evals pass, so a bad re-index can never replace a good index and
rollback is a single pointer flip. Similarity is cosine over numpy; for a
personal corpus (hundreds–low-thousands of chunks) this is faster than standing
up a vector database and has zero native-extension risk on Railway.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

import numpy as np

from app.rag.chunker import Chunk


class RagStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS collections (
                index_id   TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                embedder   TEXT NOT NULL,
                active     INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS chunks (
                index_id       TEXT NOT NULL,
                source_id      TEXT NOT NULL,
                ordinal        INTEGER NOT NULL,
                title          TEXT, link TEXT, date TEXT,
                permission_tag TEXT NOT NULL DEFAULT 'owner',
                doc_hash       TEXT,
                text           TEXT NOT NULL,
                vector         TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_index ON chunks(index_id);
            """
        )
        self._conn.commit()

    # ---- collection lifecycle --------------------------------------------
    def new_index(self, embedder_name: str) -> str:
        index_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO collections(index_id, created_at, embedder, active) VALUES (?,?,?,0)",
            (index_id, time.time(), embedder_name),
        )
        self._conn.commit()
        return index_id

    def upsert(self, index_id: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors length mismatch")
        self._conn.executemany(
            """INSERT INTO chunks
               (index_id, source_id, ordinal, title, link, date, permission_tag, doc_hash, text, vector)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    index_id, c.source_id, c.ordinal, c.title, c.link, c.date,
                    c.permission_tag, c.doc_hash, c.text, json.dumps(v),
                )
                for c, v in zip(chunks, vectors)
            ],
        )
        self._conn.commit()

    def activate(self, index_id: str) -> None:
        """Atomically make ``index_id`` the live collection (the rollback point)."""
        with self._conn:
            self._conn.execute("UPDATE collections SET active = 0")
            self._conn.execute("UPDATE collections SET active = 1 WHERE index_id = ?", (index_id,))

    def active_index(self) -> str | None:
        row = self._conn.execute(
            "SELECT index_id FROM collections WHERE active = 1 LIMIT 1"
        ).fetchone()
        return row["index_id"] if row else None

    def count(self, index_id: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) AS n FROM chunks WHERE index_id = ?", (index_id,)
        ).fetchone()["n"]

    # ---- search ----------------------------------------------------------
    def search(
        self,
        query_vec: list[float],
        k: int = 5,
        index_id: str | None = None,
        permission_tags: list[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        """Cosine top-k over a collection, optionally filtered to allowed tags."""
        index_id = index_id or self.active_index()
        if not index_id:
            return []

        sql = "SELECT * FROM chunks WHERE index_id = ?"
        params: list = [index_id]
        if permission_tags is not None:
            sql += f" AND permission_tag IN ({','.join('?' * len(permission_tags))})"
            params.extend(permission_tags)
        rows = self._conn.execute(sql, params).fetchall()
        if not rows:
            return []

        mat = np.array([json.loads(r["vector"]) for r in rows], dtype=np.float32)
        q = np.array(query_vec, dtype=np.float32)
        qn = np.linalg.norm(q)
        if qn > 0:
            q = q / qn
        norms = np.linalg.norm(mat, axis=1)
        norms[norms == 0] = 1.0
        scores = (mat @ q) / norms

        top = np.argsort(-scores)[:k]
        out: list[tuple[Chunk, float]] = []
        for i in top:
            r = rows[int(i)]
            out.append(
                (
                    Chunk(
                        text=r["text"], source_id=r["source_id"], ordinal=r["ordinal"],
                        title=r["title"] or "", link=r["link"] or "", date=r["date"] or "",
                        permission_tag=r["permission_tag"], doc_hash=r["doc_hash"] or "",
                    ),
                    float(scores[int(i)]),
                )
            )
        return out

    def close(self) -> None:
        self._conn.close()
