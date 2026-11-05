"""
Document chunking for the RAG retrieval core.

Splits a document into overlapping, paragraph-aware windows and attaches the
metadata every downstream stage needs: the citation fields (title, link, date),
a permission tag for least-privilege filtering, and a content hash so re-indexing
can skip unchanged documents. Pure and deterministic — no I/O, no model calls.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

# ~800 tokens ≈ ~600 words; we count words to stay dependency-free and deterministic.
DEFAULT_CHUNK_WORDS = 180
DEFAULT_OVERLAP_WORDS = 40

_PARAGRAPH = re.compile(r"\n\s*\n")
_WS = re.compile(r"\s+")


def content_hash(text: str) -> str:
    """Stable SHA-256 of normalised text — identifies an unchanged document."""
    return hashlib.sha256(_WS.sub(" ", text).strip().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit, carrying everything needed to cite and authorise it."""
    text: str
    source_id: str
    ordinal: int
    title: str = ""
    link: str = ""
    date: str = ""
    permission_tag: str = "owner"
    doc_hash: str = ""

    @property
    def citation(self) -> dict:
        """The fields an answer must cite."""
        return {"title": self.title, "link": self.link, "date": self.date}


def chunk_document(
    text: str,
    *,
    source_id: str,
    title: str = "",
    link: str = "",
    date: str = "",
    permission_tag: str = "owner",
    chunk_words: int = DEFAULT_CHUNK_WORDS,
    overlap_words: int = DEFAULT_OVERLAP_WORDS,
) -> list[Chunk]:
    """
    Split ``text`` into overlapping word-windows that prefer paragraph breaks.

    Windows are filled paragraph by paragraph up to ``chunk_words``; the last
    ``overlap_words`` of one window seed the next so a fact split across a
    boundary is still retrievable. Empty/whitespace input yields no chunks.
    """
    if not text or not text.strip():
        return []
    if overlap_words >= chunk_words:
        raise ValueError("overlap_words must be smaller than chunk_words")

    doc_hash = content_hash(text)
    paragraphs = [p.strip() for p in _PARAGRAPH.split(text) if p.strip()]
    words: list[str] = []
    for p in paragraphs:
        words.extend(_WS.sub(" ", p).split(" "))
        words.append("\n")  # paragraph marker, preserved in the joined text

    chunks: list[Chunk] = []
    step = chunk_words - overlap_words
    ordinal = 0
    i = 0
    while i < len(words):
        window = words[i : i + chunk_words]
        chunk_text = " ".join(w for w in window).replace(" \n ", "\n\n").strip()
        if chunk_text:
            chunks.append(
                Chunk(
                    text=chunk_text,
                    source_id=source_id,
                    ordinal=ordinal,
                    title=title,
                    link=link,
                    date=date,
                    permission_tag=permission_tag,
                    doc_hash=doc_hash,
                )
            )
            ordinal += 1
        if i + chunk_words >= len(words):
            break
        i += step

    return chunks
