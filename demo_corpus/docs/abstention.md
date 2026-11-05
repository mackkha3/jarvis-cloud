# Confidence threshold and abstention

A retriever that always returns its best match will happily hand back an
irrelevant chunk for a question the corpus cannot answer, and an assistant that
trusts it will then answer confidently from noise. JARVIS avoids this with an
explicit confidence threshold.

After scoring, the top result's cosine similarity is compared to a minimum. If
it clears the bar, the retriever returns the hits with an "answer" decision. If
it does not, the retriever returns an "abstain" decision and no chunks, which is
the "I don't know" path. The context hook treats abstain as a signal to add no
retrieved context at all, so the assistant answers from its general ability
rather than from a weak match.

The threshold is calibrated against the demo corpus, where off-topic queries
score far below on-topic ones, and the retrieval evaluation measures the
false-answer rate directly so the setting stays honest as the corpus grows.
Abstaining when unsure is treated as correct behaviour, not a failure.
