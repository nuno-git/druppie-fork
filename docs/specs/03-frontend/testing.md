# Frontend Testing

Two separate stacks: **Vitest** for component/unit tests, **Playwright** for e2e.

## Vitest (unit / component)

Config in `frontend/vite.config.js`:
```js
test: {
  environment: "jsdom",
  globals: true,
  exclude: ["tests/e2e/**", "node_modules/**", "dist/**"],
}
```

Runner: `npm run test`.

Current coverage is intentionally light — the design bet is that the SPA is thin (pages, components, formatters) and that e2e plus a type-checked backend catches the interesting breakage. Utility functions like `formatTokens`, `formatCost`, `formatDuration` in `src/utils/` have unit tests where edge cases matter.

## Playwright (e2e)

Config in `frontend/playwright.config.js`:
```js
{
  testDir: "./tests/e2e",
  timeout: 60_000,
  workers: 1,                 // single worker, no parallel
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:5273",
    trace: "on-retry",
    screenshot: "only-on-failure",
    video: "retry-with-video",
  },
  webServer: process.env.USE_DEV_SERVER ? { command: "npm run dev", port: 5173 } : undefined,
}
```

Why single worker: the suite shares state in Keycloak + Gitea + the Druppie DB. Parallel tests would step on each other (duplicate test users, duplicate projects).

### `tests/e2e/auth.spec.js`

Login matrix across test users from `iac/users.yaml`:
- `admin / Admin123!` — sees all features
- `developer` — limited routes (not admin)
- `infra-engineer` — sees role banner
- `product-owner` — accesses dashboard

Flow:
1. `page.goto('/')`
2. Click "Login" → redirected to Keycloak
3. Fill username + password
4. Submit → redirect back to `/`
5. Assert on NavRail items or role displayed

`loginUser(page, user)` helper abstracts the Keycloak form filling.

### `tests/e2e/chat.spec.js`

Happy-path chat:
1. Log in as developer.
2. Navigate to `/chat`.
3. Fill the chat input with a minimal prompt (e.g. "Hello").
4. Submit.
5. Wait for an `assistant` message to appear in the timeline (polling until visible or 60 s timeout).

### `tests/e2e/deployment-approval.spec.js`

End-to-end approval gate test:
1. Start a session that produces a deployment tool call (requires `developer` approval).
2. Verify session pauses on `PAUSED_APPROVAL`.
3. Open `/tasks` as the developer.
4. Click Approve.
5. Return to session, wait for it to proceed past the approval.

## CLAUDE.md rule

From this repo's CLAUDE.md:
> **Always use subagents for ANY Playwright MCP interaction.**

This rule targets Claude Code agents running Playwright MCP tools in this repo — it doesn't constrain humans running `npm run test:e2e`. The motivation: Playwright sessions in MCP mode can leak browser state between calls; subagents start with a clean context.

## Running tests locally

```bash
# Ensure Druppie stack is up
docker compose --profile dev up -d

# Unit
cd frontend && npm run test

# E2E
cd frontend && BASE_URL=http://localhost:5273 npm run test:e2e
```

For headed debugging:
```bash
npm run test:e2e:headed
```

HTML reports are written to `playwright-report/` (gitignored).

## Seeding test users

The Playwright test users exist in Keycloak because `setup_keycloak.py` creates them from `iac/users.yaml`. If a reset-hard was run, they will be recreated. Avoid creating your own manual users with the same names — they will be overwritten.

## Gaps

- No visual regression suite. Screenshots on failure only.
- No accessibility audit. `eslint-plugin-jsx-a11y` is not configured (on the backlog).
- No performance budgets. Vite produces a fairly large bundle due to Mermaid + Recharts; code-splitting is only default via route chunks.
