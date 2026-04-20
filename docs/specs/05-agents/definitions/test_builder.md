# test_builder

File: `druppie/agents/definitions/test_builder.yaml` (324 lines).

## Role

TDD Red phase. Generates comprehensive test files in the workspace before the builder writes implementation. No test execution, no implementation — only test authoring.

## Config

| Field | Value |
|-------|-------|
| category | execution |
| llm_profile | standard |
| temperature | 0.1 |
| max_tokens | 16384 |
| max_iterations | 30 |
| MCPs | `coding` (read_file, write_file, batch_write_files, list_dir, run_git, get_test_framework, install_test_dependencies) |

## Framework support

### Python / pytest
- Files: `test_*.py`, `conftest.py`, `pytest.ini`.
- Coverage: `pytest-cov`.

### Frontend / vitest
- Files: `*.test.jsx` / `*.test.tsx`.
- Config: `vite.config.js` with `test: { ... }` section.
- Coverage: `@vitest/coverage-v8`.

### Node.js / jest
- Files: `*.test.js`, `*.spec.js`.
- Config: `jest.config.js`.
- Companions: `supertest` for HTTP.

### E2E / Playwright
- Files: `tests/e2e/*.spec.js`.
- Config: `playwright.config.js`.

## Flow

1. `coding:run_git(command="pull")`.
2. Read design docs.
3. `coding:get_test_framework()` to auto-detect or confirm from `builder_plan.md`.
4. If missing deps → `coding:install_test_dependencies()`.
5. Generate tests via `batch_write_files` (multiple files in one call).
6. Commit + push.
7. `done()`.

## Mandatory test

Every Python backend must include:
```python
def test_health_endpoint_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

The prompt explicitly says: "include a test that GET /health returns 200 with status 'ok' — this endpoint is critical for deployment and must never be removed."

## Output

```
Agent test_builder: wrote tests/test_tasks.py (5 cases), tests/test_health.py (1 case),
tests/conftest.py, tests/test_auth.py (3 cases). Framework: pytest. Coverage config
in pytest.ini. All committed and pushed.
```

## Relationship to builder

Tests run first (Red). Builder implements to pass them (Green). test_executor reports PASS/FAIL. Planner loops builder if FAIL.
