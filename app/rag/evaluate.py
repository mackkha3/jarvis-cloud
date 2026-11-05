"""
Retrieval evaluation and the CI gate.

Runs a labelled eval set against a collection and reports recall@k, MRR on the
positives, and a false-answer rate on the negatives (how often the retriever
answers instead of abstaining on an off-topic query). ``gate`` turns those
numbers into a pass/fail against configured floors so CI can block a retrieval
regression the same way it blocks a failing unit test.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.rag import RagStore
from app.rag.embedder import Embedder, default_embedder
from app.rag.retrieve import retrieve

# CI floors/ceilings. Calibrated for the offline HashingEmbedder on the demo
# corpus; a real regression (bad chunking, wrong embedder, broken threshold)
# drops recall/MRR or lifts the false-answer rate through these.
MIN_RECALL_AT_5 = 0.90
MIN_MRR = 0.75
MAX_FALSE_ANSWER_RATE = 0.0


@dataclass
class EvalReport:
    recall_at_k: float
    mrr: float
    false_answer_rate: float
    k: int
    n_positives: int
    n_negatives: int

    def as_dict(self) -> dict:
        return {
            "recall_at_%d" % self.k: round(self.recall_at_k, 4),
            "mrr": round(self.mrr, 4),
            "false_answer_rate": round(self.false_answer_rate, 4),
            "n_positives": self.n_positives,
            "n_negatives": self.n_negatives,
        }


def load_evalset(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate(
    evalset: dict,
    *,
    store: RagStore,
    embedder: Embedder | None = None,
    index_id: str | None = None,
    k: int = 5,
) -> EvalReport:
    embedder = embedder or default_embedder()
    positives = evalset.get("positives", [])
    negatives = evalset.get("negatives", [])

    hits_at_k = 0
    reciprocal_ranks = 0.0
    for case in positives:
        res = retrieve(case["query"], store=store, embedder=embedder, k=k, index_id=index_id)
        ranked = [h.chunk.source_id for h in res.hits]
        rank = next((i + 1 for i, sid in enumerate(ranked) if sid == case["expected"]), None)
        if rank is not None:
            hits_at_k += 1
            reciprocal_ranks += 1.0 / rank

    false_answers = 0
    for case in negatives:
        res = retrieve(case["query"], store=store, embedder=embedder, k=k, index_id=index_id)
        if res.decision == "answer":
            false_answers += 1

    n_pos = len(positives) or 1
    n_neg = len(negatives) or 1
    return EvalReport(
        recall_at_k=hits_at_k / n_pos,
        mrr=reciprocal_ranks / n_pos,
        false_answer_rate=(false_answers / n_neg) if negatives else 0.0,
        k=k,
        n_positives=len(positives),
        n_negatives=len(negatives),
    )


def gate(store: RagStore, index_id: str, *, evalset_path: str, embedder: Embedder | None = None):
    """Eval-as-gate: ``(ok, metrics)`` for ``corpus.reindex`` and for CI."""
    report = evaluate(load_evalset(evalset_path), store=store, embedder=embedder, index_id=index_id)
    ok = (
        report.recall_at_k >= MIN_RECALL_AT_5
        and report.mrr >= MIN_MRR
        and report.false_answer_rate <= MAX_FALSE_ANSWER_RATE
    )
    return ok, report.as_dict()
