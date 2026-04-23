# Frontend E2E Tests

See also `03-frontend/testing.md`. Summary here.

Path: `frontend/tests/e2e/*.spec.js`. Runner: Playwright. Single worker, 60 s timeout per test.

## Tests shipped

### `auth.spec.js` (~140 lines)

Login flow per test user (from `iac/users.yaml`):
- admin / Admin123!
- developer / Developer123!
- infra-engineer / (password)
- product-owner / (password)
- analyst / Analyst123!

Helper `loginUser(page, user)`:
1. `page.goto('/')`.
2. Click the Login button.
3. Wait for Keycloak form.
4. Fill credentials, submit.
5. Wait for redirect back to `/`.

Tests verify:
- Unauthenticated state shows login button.
- Login redirects to Keycloak.
- After login, user's roles control which routes are visible.
- Logout clears session.

### `chat.spec.js` (~80 lines)

Happy-path chat:
1. Log in as developer.
2. Navigate to `/chat`.
3. Use `getChatInput()` to find the input (matches placeholder text).
4. Fill a prompt ("hello").
5. Submit.
6. Wait for an assistant message to appear (poll until visible or 60s).

This test does NOT complete a full pipeline — it verifies the frontend can kick off a session and see the backend respond. Full pipeline coverage is in the agent tests.

### `deployment-approval.spec.js` (~350 lines)

End-to-end approval gate exercise:
1. Start a session whose pipeline includes a deployment tool call.
2. Wait for the session to pause on `PAUSED_APPROVAL` for `docker:compose_up`.
3. Navigate to `/tasks`.
4. Assert the approval card is present.
5. Click Approve.
6. Navigate back to the session.
7. Wait for the session to proceed past the approval (status leaves `PAUSED_APPROVAL`).

Long-running. Designed as a single comprehensive smoke test for the approval workflow.

## Playwright config

`frontend/playwright.config.js`:
- `baseURL`: `http://localhost:5273` (via env `BASE_URL`).
- Keycloak: `http://localhost:8180` (via env `KEYCLOAK_URL`).
- Single worker. No parallelism.
- Artifacts: HTML reports, traces on retry, screenshots on failure, video on retry.
- Conditional webServer only if `USE_DEV_SERVER=true`.

## Running

```bash
docker compose --profile dev up -d      # ensure stack is up
cd frontend && npm run test:e2e         # headless
cd frontend && npm run test:e2e:headed  # visible browser for debug
```

## Cleanup

Tests leave sessions, approvals, and Gitea repos behind. To reset between runs:
```bash
docker compose --profile reset-db run --rm reset-db
```

Test users are re-created automatically by `setup_keycloak.py` on next up.

## Why so few

E2E tests are slow and flaky by nature. Druppie's strategy:
- Comprehensive coverage via tool tests + agent tests + judge checks.
- Minimal e2e as smoke tests for the full stack integration.
- Unit tests in pytest (backend) + vitest (frontend) for small pieces.

The comment "Always use subagents for ANY Playwright MCP interaction" in `CLAUDE.md` is guidance for the Claude Code agent that edits the codebase, not for the test runner itself.
