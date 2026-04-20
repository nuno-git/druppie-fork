# Pytest

Path: `druppie/tests/*.py`. Backend unit tests, run with `pytest`.

Current coverage is intentionally focused on the pure logic that pays for isolated tests:
- Assertion matcher
- Schema parsing
- Seed ID generation

Everything workflow-heavy is exercised via the evaluation framework (tool tests + agent tests).

## Files

### `test_assertions.py` (~300 lines)

Tests `druppie/testing/assertions.match_assertions`. Uses an in-memory SQLite DB:

```python
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # UUID shim for SQLite
    yield session
    session.close()
```

Helpers:
- `_seed_session(db, user_id, ...)` — inserts a Session row.
- `_seed_agent_run(db, session_id, agent_id, status)` — inserts an AgentRun.

Cases:
- Exact tool match: `{agent: X, tool: coding:write_file}` matches a tool call with that agent + tool.
- Wildcard: `tool: *` matches any tool.
- Multi-assertion: list of tools to match any-of.
- Dynamic refs: `@project:todo` resolves to the project UUID.
- Status filtering: `status: completed` matches only completed calls.
- Negative cases: no match → assertion fails with clear message.

### `test_schema.py` (~250 lines)

Tests Pydantic validation of:
- `ToolTestDefinition` parsing.
- `AgentTestDefinition` parsing.
- `ChainStep` with various combinations of `mock`, `execute`, `approval`.
- Invalid YAML (missing required fields) raises ValidationError with helpful messages.

### `test_seed_ids.py` (~40 lines)

Tests `fixture_uuid(name)` is deterministic:
- Same input → same UUID.
- Different inputs → different UUIDs.
- UUIDv5 format (uppercase, hyphens).

## Running

```bash
cd druppie && pytest
```

Or via docker:
```bash
docker compose exec druppie-backend-dev pytest /app/druppie/tests/
```

## Configuration

`druppie/pyproject.toml` has pytest configuration:
- Test discovery: `druppie/tests/`, `druppie/testing/tests/` (if present).
- Markers: none custom.
- Async: pytest-asyncio auto mode.

## Ruff + black

The project also uses `ruff` for linting and `black` for formatting (per `CLAUDE.md`). Not enforced in CI today but expected locally:
```bash
cd druppie && ruff check .
cd druppie && black .
```

## What's NOT unit-tested

- API routes. Covered by integration through the frontend e2e tests and by tool tests at the orchestrator level.
- Services. Same reason.
- Repositories. Same.
- Orchestrator. Covered by agent tests.

This means isolated backend regressions can slip through pytest. The evaluation framework is the real test suite — pytest catches the small pieces whose correctness is easy to assert without spinning up Docker.
