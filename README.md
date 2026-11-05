# JARVIS Cloud

[![CI](https://github.com/mackkha3/jarvis-cloud/actions/workflows/ci.yml/badge.svg)](https://github.com/mackkha3/jarvis-cloud/actions/workflows/ci.yml)
![coverage](https://img.shields.io/badge/coverage-%E2%89%A580%25-brightgreen)
![python](https://img.shields.io/badge/python-3.11-blue)

A personal, voice-first AI assistant — a mobile PWA backed by a Python/Flask
API that routes requests across three tiers of Claude, and wires in Google
Calendar, Tasks, Gmail, and Drive. Deployed on Railway; bring-your-own-API-keys.

---

## What it is

JARVIS Cloud is a production assistant (not a demo) that:

- **Talks.** A hands-free voice loop in the browser: speech-in, Claude, speech-out
  (OpenAI TTS with a local Kokoro fallback).
- **Briefs.** Generates tactical morning and evening briefings from the owner's
  live calendar, tasks, and inbox.
- **Acts.** Creates calendar events and tasks, completes tasks by fuzzy match,
  and schedules meeting-prep briefings — driven by `<action>` tags the model
  emits and the backend executes.
- **Watches cost.** Every Claude and TTS call is priced and tracked so the
  dashboard shows real spend.

## Architecture

```
PWA (voice UI, dashboard)
        │  X-API-Key
        ▼
Flask API ── auth ── 3-layer Claude router ──► Anthropic (Haiku / Sonnet)
        │                                  └──► Layer 1: local regex (free, instant)
        ├── Google integrations (Calendar · Tasks · Gmail · Drive)
        ├── Retrieval / RAG (cited context, flag-gated) ──► also an MCP server
        ├── Briefings (morning / evening / meeting-prep)
        ├── Usage tracker (per-call cost)
        └── Voice (OpenAI TTS → Kokoro fallback)
```

**Three-layer routing** keeps latency and cost down: Layer 1 answers
deterministic queries (time, date, greetings) with local regex and never calls
the API; Layer 2 uses Claude Haiku for routine requests; Layer 3 escalates to
Sonnet for planning, analysis, and briefings. The router
(`app/core/claude.py`) decides the layer; everything downstream is structured
around that single decision.

- **Backend:** Python 3.11 + Flask, gunicorn on Railway (Docker).
- **Frontend:** mobile-first PWA (`pwa/`).
- **Config:** a single Pydantic-validated settings object (`app/config/`) that
  fails fast on a bad key or timezone rather than silently in production.

## Retrieval (RAG)

JARVIS can ground its answers in a document corpus. The retrieval layer
(`app/rag/`) is built as **one core with two adapters** — the design goal was a
reusable, swappable asset, not a feature welded to one endpoint.

```
chunker ─► embedder ─► store ─► retrieve ─► observe      (the core, app/rag/)
                                   │
                 ┌─────────────────┴─────────────────┐
                 ▼                                     ▼
        JARVIS context hook                       MCP server
     (app/core/claude.py, flag-gated)        (any MCP client, same core)
```

The core depends on nothing above it — no Flask, no assistant code — so the same
`retrieve()` path serves both adapters unchanged: the in-process JARVIS context
hook, and an `mcp` server (`app/rag/mcp_server.py`) that exposes retrieval as a
single `search` tool to any Model Context Protocol client. The MCP adapter is a
thin wrapper — thresholding, permission filtering, citations and auditing all
live in the core and are inherited, not reimplemented.

What makes it production-shaped rather than a demo:

- **Cited answers, or none.** Every hit carries its source's title/link/date, and
  a confidence threshold produces an explicit *abstain* ("I don't know") decision
  rather than returning a weak match. The context hook injects nothing on abstain,
  so the assistant never answers off noise.
- **A retrieval eval gate in CI.** A labelled eval set (`demo_corpus/evalset.json`)
  measures recall@5, MRR, and a false-answer rate on off-topic negatives. These
  are **floors in CI** (`tests/eval/test_rag_gate.py`): a regression in chunking,
  embedding, or the threshold fails the build. On the seed corpus the gate holds
  recall@5 = 1.0, MRR = 0.95, false-answer rate = 0.0.
- **Reproducible without an API key.** The default embedder is deterministic and
  offline (hashed words + subword n-grams, numpy only), so the evals are stable
  across machines and a reviewer can clone-and-run. Swapping in OpenAI
  `text-embedding-3-small` for production is a one-line config change
  (`RAG_EMBEDDER=openai`) and nothing else in the core moves.
- **Observable, with data minimisation.** Every query writes one audit record —
  latency, confidence, decision, collection, and the document *ids* used — and
  deliberately **never the query text or chunk contents**, mirroring the event
  store's stance.
- **Least-privilege access.** Chunks carry permission tags; search filters to the
  caller's allowed tags before scoring. Drive indexing uses read-only scopes.
- **Safe rollback.** Re-indexing writes a new, inactive collection, runs the eval
  gate against it, and only flips a single `active` pointer if it passes. Rollback
  is flipping the pointer back; the previous index is never overwritten.

The whole layer is behind the `FEATURE_RAG` flag and off by default, so a
deployment with no corpus behaves exactly as before.

```bash
# Build/activate an index from the seed corpus (offline embedder, no key)
python -m app.rag.corpus demo_corpus --db /tmp/rag.db
FEATURE_RAG=true RAG_DB_PATH=/tmp/rag.db <run the app>

# Or expose the same core to any MCP client as a `search` tool:
pip install -r requirements-mcp.txt        # optional SDK, runtime-only
RAG_DB_PATH=/tmp/rag.db python -m app.rag.mcp_server
```

## Running the tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-ci.txt      # slim: no torch/kokoro needed for tests
pytest
```

The live, model-in-the-loop evals are opt-in (they cost money and hit the real
API):

```bash
RUN_LLM_EVALS=1 ANTHROPIC_API_KEY=sk-ant-... pytest -m llm -v
```

## Test design

The suite is built around one idea: **isolate the deterministic business logic
from the ML/audio runtime and external APIs, and pin it hard.**

- **Boundary mocking.** `tests/conftest.py` injects a deterministic environment
  and stubs the heavy voice stack (torch, kokoro, transformers, soundfile,
  sounddevice, SQLCipher) in `sys.modules`. CI then installs a slim
  `requirements-ci.txt` and runs in seconds instead of pulling a multi-hundred-MB
  torch wheel. Anthropic and Google are mocked at their client boundaries — **no
  test makes a network call.**
- **Layers of tests.**
  - *Unit* — pure logic: routing heuristics (Haiku vs Sonnet), config
    validators, cost-rate resolution, feature flags, briefing formatters, and a
    regression test that pins a timezone bug (below).
  - *Integration* — the wrappers with their SDKs mocked: the full Claude
    `respond()` path (model selection, token parsing, history trimming, graceful
    error fallbacks), the Google Calendar/Tasks/Gmail/Drive request-building, the
    auth decorator, and the briefing pipeline end-to-end.
  - *Eval* — the system prompt is JARVIS's behaviour contract, so
    `tests/eval/test_system_prompt.py` asserts its invariants (persona
    guardrails, the `<action>` schemas the voice layer parses, context
    injection) with zero API calls, catching silent prompt regressions. A
    second, opt-in layer runs fixed prompts through the real model.
- **A real bug, pinned.** `get_todays_events()` built "today" from UTC midnight,
  so after ~6pm Central the window rolled into the next UTC day and tomorrow's
  events leaked into tonight's briefing. The fix anchors the day to the owner's
  timezone; `tests/unit/test_dates.py` freezes the clock at 10pm Central and
  fails if the UTC anchor is ever reintroduced.

Coverage is measured on that business-logic surface (~82%, enforced at ≥80% in
CI via `.coveragerc`). Pure runtime glue — the Kokoro daemon, HTML renderers,
Flask route wiring, the SQLCipher store — is explicitly excluded and documented
in `.coveragerc`, not hidden.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request: it installs the
slim deps, runs the suite with coverage, enforces the ≥80% floor, and uploads
the coverage report. A coverage drop fails the build the same as a failing test.

To make CI a merge gate, enable branch protection (one-time, needs admin):

```bash
gh api -X PUT repos/mackkha3/jarvis-cloud/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  -f 'required_status_checks[strict]=true' \
  -f 'required_status_checks[checks][][context]=Test (Python 3.11)' \
  -f 'enforce_admins=false' \
  -f 'required_pull_request_reviews[required_approving_review_count]=0' \
  -f 'restrictions='
```

## Deployment

Containerised (`Dockerfile`) and deployed on Railway (`railway.json`); gunicorn
serves `run:app`. Runtime configuration — API keys, the owner's identity and
timezone, the base64 Google OAuth token — comes from environment variables and
is validated on startup.

## License

© The project authors. All rights reserved.
