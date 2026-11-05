# Event store and data minimisation

JARVIS keeps a lightweight event store so it can answer questions about recent
activity, but it is built around data minimisation. The store records the type
of each event and its timestamp — a calendar event was created, a task was
completed, a briefing was generated — but it never writes the message contents
or any personal detail into the log.

The retrieval layer follows the same rule. Its per-query audit log records a
hash of the query, the latency, the confidence score, the abstain-or-answer
decision, and the document ids that were used. It deliberately never stores the
query text or the retrieved chunk contents, so the audit trail is useful for
debugging and review without becoming a second, unprotected copy of the corpus.

This stance means logs can be shared with reviewers or kept for longer windows
without widening the system's exposure. The information needed to debug a bad
answer — which collection served it, which documents, how confident it was — is
all present; the sensitive content is not.
