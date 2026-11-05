# Deployment and runtime

JARVIS runs as a Flask application served by gunicorn inside a Docker container,
deployed on Railway. The container builds from a slim Python 3.11 base image and
installs only the runtime dependencies; heavy optional packages such as the
local voice stack are imported lazily so a standard deployment stays small and
starts quickly.

Persistent state lives under `/app/data` on a mounted volume: the usage tracker,
the event store, and the retrieval index all write there, so they survive
restarts and redeploys. Configuration comes entirely from environment variables,
following the bring-your-own-infrastructure model — each operator supplies their
own API keys and tokens, and nothing is baked into the image.

Health is exposed through a status endpoint that reports whether the database is
initialised, whether the data path exists, and a recent event count, which makes
it easy to confirm a deploy is live without inspecting any private data.
