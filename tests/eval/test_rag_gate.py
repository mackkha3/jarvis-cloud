"""
Retrieval evaluation gate — runs in CI.

This is the test that turns "search still works" into a blocking check. It
reindexes the demo corpus with the deterministic offline embedder and asserts
that recall@5, MRR and the false-answer rate meet their configured floors. A
regression in chunking, embedding, the store, or the abstain threshold will
move one of these numbers through its bound and fail the build.

Because the embedder is deterministic, these numbers are stable across machines,
so the thresholds are meaningful rather than flaky.
"""

from pathlib import Path

import pytest

from app.rag.corpus import reindex
from app.rag.evaluate import (
    MAX_FALSE_ANSWER_RATE,
    MIN_MRR,
    MIN_RECALL_AT_5,
    evaluate,
    gate,
    load_evalset,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = str(ROOT / "demo_corpus")
EVALSET = str(ROOT / "demo_corpus" / "evalset.json")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from app.rag import RagStore

    db = str(tmp_path_factory.mktemp("rag") / "rag.db")
    store = RagStore(db)
    result = reindex(CORPUS, store=store, activate=True)
    yield store, result
    store.close()


def test_corpus_indexes(built):
    _, result = built
    assert result["documents"] >= 10
    assert result["chunks"] >= result["documents"]


def test_recall_meets_floor(built):
    store, result = built
    report = evaluate(load_evalset(EVALSET), store=store, index_id=result["index_id"])
    assert report.recall_at_k >= MIN_RECALL_AT_5, report.as_dict()


def test_mrr_meets_floor(built):
    store, result = built
    report = evaluate(load_evalset(EVALSET), store=store, index_id=result["index_id"])
    assert report.mrr >= MIN_MRR, report.as_dict()


def test_false_answer_rate_within_ceiling(built):
    store, result = built
    report = evaluate(load_evalset(EVALSET), store=store, index_id=result["index_id"])
    assert report.false_answer_rate <= MAX_FALSE_ANSWER_RATE, report.as_dict()


def test_gate_passes_overall(built):
    store, result = built
    ok, metrics = gate(store, result["index_id"], evalset_path=EVALSET)
    assert ok, metrics
