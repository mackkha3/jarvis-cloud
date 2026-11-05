# Three-layer query routing

JARVIS decides how much model to spend on each request with a three-layer
router. Layer one is a local regular-expression matcher that handles the most
common commands — greetings, "what's on my calendar", marking a task done —
with no model call at all, so they return in milliseconds and cost nothing.

Layer two sends everything the regex layer does not recognise to Claude Haiku,
a fast, inexpensive model that covers the bulk of ordinary conversation and
simple tool use. Layer three escalates to Claude Sonnet only when the request
looks genuinely complex: multi-step reasoning, ambiguous intent, or anything the
complexity heuristic flags.

The escalation decision is made by `_is_complex_query`, which scores length,
the presence of reasoning words, and whether multiple tools are likely involved.
Routing most traffic to the cheapest layer that can handle it keeps latency and
cost down while reserving the strongest model for the few requests that need it.
