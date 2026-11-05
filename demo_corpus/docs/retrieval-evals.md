# Retrieval evaluation gate

Retrieval quality is measured, not assumed. A labelled evaluation set pairs
realistic queries with the document that should be retrieved for each, plus a
set of off-topic negative queries that should retrieve nothing. On every index
build the evaluation runs and computes recall at five, mean reciprocal rank, and
a false-answer rate — how often the retriever confidently returns a chunk for a
query that has no good answer in the corpus.

These metrics are a gate in continuous integration. If recall or MRR falls below
the configured floor, or the false-answer rate rises above its ceiling, the
build fails. That turns "the search still works" from a hope into a check that
blocks a regression from merging, the same way the unit and integration tests
block a logic regression.

The deterministic offline embedder is what makes this possible: because the same
input always produces the same vector, the eval numbers are stable across
machines and runs, so a threshold is meaningful rather than noisy. When the
corpus changes, the eval is what tells us whether retrieval got better or worse.
