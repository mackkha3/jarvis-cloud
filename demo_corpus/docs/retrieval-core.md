# Retrieval core design

The retrieval system is built as one core with two adapters. The core —
chunking, embedding, storage, search, and observability — depends on nothing
above it: no Flask, no event store, no assistant code. The same core is consumed
unchanged by the JARVIS context hook, which injects retrieved snippets into the
system prompt, and by a Model Context Protocol server that exposes search as a
tool to any MCP client. Writing it once and consuming it twice is the point.

Embeddings sit behind a small protocol so the backend is swappable. The default
is a deterministic offline embedder that uses hashed words and subword character
n-grams, which makes retrieval fully reproducible in continuous integration with
no API key and no network. A production embedder backed by OpenAI
text-embedding-3-small is a one-line configuration change and nothing else in
the core moves.

Search is cosine similarity computed with numpy over vectors stored in SQLite.
For a personal corpus of hundreds to low thousands of chunks this is faster than
standing up a vector database and carries no native-extension risk on the
deployment platform. Every result carries the citations of the documents behind
it, so an answer can always be traced to its sources.
