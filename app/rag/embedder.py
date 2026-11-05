"""
Embedding backends behind one interface.

The retrieval core never imports a specific provider — it depends on the
``Embedder`` protocol. Two implementations ship:

* ``HashingEmbedder`` — deterministic, offline, zero-dependency (numpy only). It
  uses the hashing trick with L2 normalisation, so retrieval is reproducible in
  CI and a reviewer can clone-and-run the demo with no API key. This is the
  default.
* ``OpenAIEmbedder`` — ``text-embedding-3-small`` for production quality. The
  ``openai`` import is lazy so the module (and CI) load without it installed.

Swapping backends is a one-line config change; nothing else in the core moves.
This is the "reusable, swappable asset" the retrieval core is built to be.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

import numpy as np

_TOKEN = re.compile(r"[a-z0-9]+")

# A small stop list so ubiquitous words ("the", "of") don't dominate the cosine
# and let off-topic queries score as matches.
_STOP = frozenset(
    "a an and are as at be by for from has have in into is it its of on or that "
    "the to was were will with how what why when where which who does do".split()
)


@runtime_checkable
class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one L2-normalised vector per input text."""
        ...


def _tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _char_ngrams(tok: str, lo: int = 3, hi: int = 5) -> list[str]:
    """Subword n-grams of a token, bracketed so prefixes/suffixes are distinct."""
    w = f"<{tok}>"
    grams: list[str] = []
    for n in range(lo, hi + 1):
        if len(w) < n:
            continue
        grams.extend(w[i : i + n] for i in range(len(w) - n + 1))
    return grams


class HashingEmbedder:
    """
    Deterministic embedding via the hashing trick over words *and* subword
    character n-grams.

    Each content word contributes its own hashed feature plus hashed 3–5 char
    n-grams, so morphological variants ("route"/"routing"/"routes") and typos
    still land on shared dimensions. Features use the hashing trick's signed
    accumulation and the vector is L2-normalised. No training, no network, no
    randomness — identical input always yields an identical vector, which is
    what makes the retrieval eval reproducible in CI.
    """

    name = "hashing-v2-subword"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _add(self, vec: np.ndarray, feature: str, weight: float) -> None:
        # blake2b keeps this stable across processes (independent of PYTHONHASHSEED).
        # Unsigned accumulation makes cosine track term/subword overlap, which is
        # what we want for keyword retrieval; at dim=1024 over a personal corpus
        # collisions are negligible, so the usual sign trick isn't needed.
        h = int.from_bytes(_blake(feature), "little")
        vec[h % self.dim] += weight

    def _one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for tok in _tokenize(text):
            if tok in _STOP:
                continue
            self._add(vec, tok, 1.0)                       # exact word dominates
            for g in _char_ngrams(tok):                    # morphological bonus
                self._add(vec, g, 0.25)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t).tolist() for t in texts]


def _blake(tok: str) -> bytes:
    import hashlib

    return hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()


class OpenAIEmbedder:
    """Production embedder — OpenAI ``text-embedding-3-small`` (1536-dim)."""

    name = "openai-text-embedding-3-small"
    dim = 1536

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", batch_size: int = 100):
        self._api_key = api_key
        self._model = model
        self._batch_size = batch_size
        self._client = None

    def _lazy_client(self):
        if self._client is None:
            import openai  # lazy: keeps the module importable without openai

            self._client = openai.OpenAI(api_key=self._api_key)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._lazy_client()
        out: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            resp = client.embeddings.create(model=self._model, input=batch)
            out.extend(d.embedding for d in resp.data)
        return out


def default_embedder() -> Embedder:
    """
    Pick the embedder from the environment. Offline hashing by default so the
    demo and CI always work; OpenAI only when explicitly configured.
    """
    import os

    if os.environ.get("RAG_EMBEDDER", "hashing").lower() == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            return OpenAIEmbedder(api_key=key)
    return HashingEmbedder()
