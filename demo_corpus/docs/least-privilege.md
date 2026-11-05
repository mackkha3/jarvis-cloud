# Least-privilege and auditable access

Retrieval is designed so that access is narrow by default and reviewable after
the fact. Every chunk carries a permission tag describing who may see it, and
search accepts the caller's allowed tags and filters to them before scoring, so
a caller can only ever match content it is entitled to. The default tag is
owner, and broadening it is a deliberate choice rather than the starting point.

Where JARVIS reads from external sources such as Google Drive, it uses read-only
scopes: it can list and read documents to index them, but it cannot modify or
delete anything in the source. The principle is that an indexing job should
never be able to damage the thing it indexes.

Every query is written to an append-only audit log that records the decision,
the confidence, the collection, and the document ids used, but never the content
or the query text. Together these give a reviewer a clear answer to "what could
this query have reached, and what did it actually use" without exposing the
underlying data — least privilege at retrieval time and accountability
afterwards.
