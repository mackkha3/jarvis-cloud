# MCP server adapter

The second consumer of the retrieval core is a Model Context Protocol server.
MCP is an open standard for exposing tools and data to language-model clients in
a uniform way, so wrapping retrieval as an MCP server lets any MCP-aware client —
not only JARVIS — search the corpus through a single well-described tool.

The server exposes one primary tool, a search call that takes a query and
returns the retrieved snippets with their citations and the answer-or-abstain
decision. It holds a single instance of the retrieval service and does nothing
clever itself: it translates an MCP request into a core query and translates the
result back. All the real behaviour — thresholding, permission filtering,
auditing — lives in the core and is inherited for free.

This is what makes the retrieval core a reusable asset rather than a feature
bolted onto one app. The context hook and the MCP server are thin adapters over
the same code; adding a third consumer later means writing another thin adapter,
not another retrieval system.
