# Testing strategy

The test suite is organised in three layers. Unit tests cover pure logic in
isolation — the complexity heuristic, date handling, the usage tracker, feature
flags — and run in milliseconds. Integration tests exercise the Google Calendar,
Tasks, Gmail and Drive wrappers and the Claude API client with every external
boundary mocked, so the suite needs no network access and no real credentials.
Evaluation tests check higher-level behaviour such as the shape of the system
prompt and, when keys are present, a small set of live model checks.

All third-party effects are mocked at the boundary: the Google API client, the
Anthropic and OpenAI SDKs, and the OpenWeather client are replaced with fakes
that return fixtures, so tests are deterministic and fast. Heavy optional
dependencies — the local voice and audio stack — are stubbed in `conftest.py`
before import so they never need to be installed in CI.

Coverage is measured with pytest-cov against an explicit include list that
excludes untestable glue, and CI fails if coverage drops below its floor. A
regression test pins the timezone-aware date bug that previously put tomorrow's
events in today's briefing, so it cannot silently return.
