# Frontend Architecture

Single-page React app served from Vite 5 dev server (port 5273) or from a production build under nginx-alpine (same port). Authenticates via Keycloak, talks to the FastAPI backend over REST + polling.

## Stack

| Concern | Choice | Version |
|---------|--------|---------|
| UI framework | React | 18.2.0 |
| Build/dev | Vite | 5.0.0 |
| Routing | React Router | 6.21.0 |
| Auth | `keycloak-js` | 23.0.0 |
| Server state | TanStack React Query | 5.17.0 |
| Client state | Zustand | 4.4.0 |
| Styling | Tailwind CSS | 3.4.0 |
| Icons | Lucide React | 0.303.0 |
| Markdown | `react-markdown` + `remark-gfm` | 10.1.0 + 4.0.1 |
| Code highlighting | Prism.js | 1.30.0 |
| Diagrams | Mermaid | 11.13.0 |
| Charts | Recharts | 2.15.0 |
| E2E tests | Playwright | 1.40.0 |
| Unit tests | Vitest + Testing Library | 1.1.0 |

There is **no TypeScript** in the app code — all source is `.jsx`. The project template (`druppie/templates/project/frontend/`) that agents generate for user projects **does** use TypeScript + shadcn/ui, but the Druppie UI itself is plain JSX.

## Project shape

```
frontend/
├── index.html            ← entry, loads /src/main.jsx
├── vite.config.js        ← dev server on 0.0.0.0:5173, jsdom test env
├── tailwind.config.js
├── postcss.config.js
├── playwright.config.js  ← baseURL localhost:5273, KC on 8180
├── package.json
├── public/
│   └── silent-check-sso.html  ← Keycloak silent SSO iframe
├── src/
│   ├── main.jsx          ← ReactDOM render, QueryClientProvider
│   ├── App.jsx           ← Keycloak init, auth context, <Routes>
│   ├── index.css         ← Tailwind + CSS vars + Prism theme
│   ├── pages/            ← one file per route
│   ├── components/       ← chat/, shared/, plus top-level NavRail etc.
│   ├── services/         ← api.js, keycloak.js
│   └── utils/            ← formatters, agentConfig
└── tests/
    └── e2e/              ← Playwright specs
```

## Data-fetching strategy

All server state is managed by **React Query**. Queries use stable keys and short stale times; long-running lists poll on intervals.

Examples:
- `['plans']` / `['sessions']` — Dashboard, SessionSidebar — refetch every 5 s while sidebar open.
- `['status']` — system status tile — refetch every 30 s.
- `['tasks']` / `['approvals']` — Tasks page, Dashboard — refetch every 5 s.
- `['sandbox-events', sessionId]` — paginated, cursor-based, refetched on interval while agent is running.

There is no WebSocket. Real-time feel comes from polling — the control plane exposes an SSE stream but the Druppie UI consumes sandbox events through the backend `/api/sandbox-sessions/{id}/events` endpoint which internally proxies or reads from the snapshot.

## Auth flow

1. On mount, `App.jsx` calls `initKeycloak()` in `src/services/keycloak.js`.
2. `initKeycloak` health-checks the Keycloak URL (3 retries × 2 s), then calls `keycloak.init({ onLoad: 'check-sso', silentCheckSsoRedirectUri: '/silent-check-sso.html', pkceMethod: 'S256' })`.
3. If authenticated, tokens are saved to `localStorage` (`kc_token`, `kc_refresh_token`); `onTokenExpired` auto-refreshes with a 30 s leeway.
4. `getUserInfo()` parses the token: `{ id: sub, username, email, roles: realm_access.roles }`.
5. `api.js` reads `getToken()` on every request and adds `Authorization: Bearer …`.
6. `ProtectedRoute` wraps authenticated routes. It blocks render until `keycloakReady`; shows an error screen if a `requiredRole` isn't satisfied.

Config is read from Vite env (`import.meta.env.VITE_KEYCLOAK_*`). In production builds these are baked into the dist bundle by build args.

## Routing

React Router v6 with a three-level layout:

- **`/chat`** — full-bleed two-panel layout (sidebar + detail). No `NavRail` margin.
- **`/debug/{sessionId}`** — redirect to `/chat?session={id}&mode=inspect`.
- **All other routes** — `NavRail` 48 px icon sidebar + page content.

Admin routes (`/admin/database`, `/admin/evaluations`, `/admin/tests/analytics`, `/admin/tests/batch/{batchId}`) use `<ProtectedRoute requiredRole="admin">`.

Catch-all `*` → `<Navigate to="/" />`.

## Component layering

- **Pages** (`src/pages/`) own React Query keys, page-level state, URL params.
- **Shared components** (`src/components/shared/`) — skeletons, empty states, copy buttons, logs modal, page header.
- **Chat components** (`src/components/chat/`) — everything session/approval-shaped: `SessionDetail`, `SessionSidebar`, `ApprovalCard`, `ToolDecisionCard`, `SandboxEventCard`, `HITLQuestionMessage`, `WorkflowPipeline`, `DebugEventLog`.
- **Top-level** (`src/components/`) — `NavRail`, `ErrorBoundary`, `Toast`, `CodeBlock`, `MermaidBlock`.

No Redux. Global state that outlives a page (sidebar open/closed, toast stack, auth) is either Zustand stores or React context.

## Styling

- Tailwind utility classes everywhere. No CSS modules.
- `src/index.css` defines CSS custom properties for theme colors (`--primary`, `--success`, `--danger`) and the Prism Tomorrow Night token palette.
- `.markdown-content` class in `index.css` styles h1–h6, lists, tables, `code`/`pre`, blockquotes, images — applied by wrapping `<ReactMarkdown>` output.
- Custom `animate-slide-in` keyframe for toast notifications.

## Build

- `npm run dev` — Vite dev server, HMR, port 5273 (docker-compose remaps 5173 → 5273).
- `npm run build` — Vite build → `dist/`. Production Dockerfile copies `dist/` into `nginx:alpine`.
- `npm run lint` — ESLint with `react`, `react-hooks` plugins.
- `npm run test` — Vitest; jsdom env; excludes `tests/e2e/`.
- `npm run test:e2e` — Playwright; `--config playwright.config.js`.

## Testing

E2E tests (`frontend/tests/e2e/*.spec.js`) run against a live stack:
- `auth.spec.js` — Keycloak login/logout, role verification per test user (from `iac/users.yaml`).
- `chat.spec.js` — send message → wait for agent reply.
- `deployment-approval.spec.js` — end-to-end approval gate for a deployment tool call.

Playwright is single-worker (no parallelism — shared state in Keycloak/Gitea/DB makes parallel runs flaky). `CLAUDE.md` enforces: **always use the Playwright sub-agent for any MCP Playwright interaction** — this rule is for Claude Code, not users.
