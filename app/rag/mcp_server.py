"""
MCP server adapter — the second consumer of the retrieval core.

Model Context Protocol is an open standard for exposing tools to language-model
clients. This module wraps the retrieval core as one MCP tool, ``search``, so any
MCP-aware client can query the same corpus the JARVIS context hook uses, with the
same thresholding, permission filtering, citations and auditing — all inherited
from the core, not reimplemented here.

The design keeps the testable logic free of the MCP SDK. ``handle_search`` is a
pure function that takes a plain arguments dict and returns a plain, JSON-ready
dict; every test exercises it directly. ``build_server`` / ``main`` are the thin
stdio entrypoint and import the ``mcp`` SDK lazily, so the SDK is a runtime-only
dependency: CI (which never launches the server) needs neither the package nor a
network. Run it with ``python -m app.rag.mcp_server``.
"""

from __future__ import annotations

from app.rag import RagService

SEARCH_TOOL_NAME = "search"

SEARCH_TOOL_SCHEMA: dict = {
    "name": SEARCH_TOOL_NAME,
    "description": (
        "Search the JARVIS knowledge corpus and return cited snippets. Returns an "
        "explicit abstain decision (no results) when nothing clears the confidence "
        "threshold, so the caller can say 'I don't know' rather than answer off a "
        "weak match."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The natural-language query."},
            "k": {
                "type": "integer",
                "description": "Max number of snippets to return (default 5).",
                "default": 5,
                "minimum": 1,
                "maximum": 20,
            },
            "permission_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Restrict results to chunks carrying one of these permission tags.",
            },
        },
        "required": ["query"],
    },
}

_service: RagService | None = None


def _get_service() -> RagService:
    global _service
    if _service is None:
        _service = RagService()
    return _service


def handle_search(arguments: dict, *, service: RagService | None = None) -> dict:
    """
    Run the retrieval core for one MCP ``search`` call.

    Pure and SDK-free: takes the tool arguments, returns a JSON-serialisable dict
    with the answer/abstain decision, citations, and per-hit snippets. On abstain
    the results and citations are empty so the client never answers off noise.
    """
    query = (arguments or {}).get("query", "")
    k = int((arguments or {}).get("k", 5))
    permission_tags = (arguments or {}).get("permission_tags")

    svc = service or _get_service()
    result = svc.query(query, k=k, permission_tags=permission_tags, caller="mcp")

    if not result.answerable:
        return {
            "decision": "abstain",
            "answerable": False,
            "elapsed_ms": round(result.elapsed_ms, 2),
            "citations": [],
            "results": [],
            "message": "No sufficiently relevant results; the corpus does not answer this.",
        }

    return {
        "decision": "answer",
        "answerable": True,
        "elapsed_ms": round(result.elapsed_ms, 2),
        "citations": result.citations,
        "results": [
            {
                "title": h.chunk.title,
                "link": h.chunk.link,
                "date": h.chunk.date,
                "score": round(h.score, 4),
                "text": h.chunk.text,
            }
            for h in result.hits
        ],
    }


def render_text(payload: dict) -> str:
    """Human-readable rendering of a search payload for MCP text content."""
    if not payload.get("answerable"):
        return payload.get("message", "No relevant results.")
    lines = []
    for i, r in enumerate(payload["results"], 1):
        label = r["title"] or r["link"] or "source"
        lines.append(f"[{i}] {label} ({r['link']}) — score {r['score']}\n{r['text']}")
    return "\n\n".join(lines)


def build_server():  # pragma: no cover - thin SDK wrapper, exercised at runtime
    """Construct the MCP stdio server. Imports the ``mcp`` SDK lazily."""
    from mcp.server import Server
    from mcp.types import TextContent, Tool

    server = Server("jarvis-rag")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**SEARCH_TOOL_SCHEMA)]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        if name != SEARCH_TOOL_NAME:
            raise ValueError(f"Unknown tool: {name}")
        payload = handle_search(arguments)
        return [TextContent(type="text", text=render_text(payload))]

    return server


def main() -> None:  # pragma: no cover - process entrypoint
    import asyncio

    async def _run() -> None:
        from mcp.server.stdio import stdio_server

        server = build_server()
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    main()
