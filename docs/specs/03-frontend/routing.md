# Routing

React Router v6 route tree from `frontend/src/App.jsx:143-289`.

## Layouts

Two layouts switch based on path:

- **NavRail layout** — 48 px icon sidebar on the left + content. Default.
- **Full-bleed** — content fills the viewport. Used only by `/chat` so the SessionSidebar can be the "nav".

## Routes

| Path | Component | Layout | Auth | Notes |
|------|-----------|--------|------|-------|
| `/` | `<Dashboard>` | NavRail | Required | Stats + recent sessions + pending approvals |
| `/chat` | `<Chat>` | Full-bleed | Required | New session + SessionSidebar |
| `/chat?session={id}` | `<Chat>` → `<SessionDetail>` | Full-bleed | Required | Active chat; `&mode=inspect` shows debug event log |
| `/debug/{sessionId}` | Redirect | — | Required | → `/chat?session={id}&mode=inspect` |
| `/tasks` | `<Tasks>` | NavRail | Required | Approvals list + history |
| `/projects` | `<Projects>` | NavRail | Required | Project card grid with deployments |
| `/projects/{projectId}` | `<ProjectDetail>` | NavRail | Required | Overview / Conversations / Dependencies |
| `/settings` | `<Settings>` | NavRail | Required | User settings |
| `/tools/mcp` | `<DebugMCP>` | NavRail | Required | MCP tool explorer/runner |
| `/tools/infrastructure` | `<DebugProjects>` | NavRail | Required | Docker/deployment explorer |
| `/tools/cache` | `<CachedDependencies>` | NavRail | Required | Shared sandbox package cache |
| `/admin/database` | `<AdminDatabase>` | NavRail | Admin | Generic table browser |
| `/admin/evaluations` | `<Evaluations>` | NavRail | Admin | Test runs, benchmarks |
| `/admin/tests/analytics` | `<Analytics>` | NavRail | Admin | Aggregated eval metrics |
| `/admin/tests/batch/{batchId}` | `<BatchDetail>` | NavRail | Admin | Assertion explorer for one batch |
| `*` | `<Navigate to="/">` | — | — | 404 catch-all |

## ProtectedRoute

```jsx
function ProtectedRoute({ children, requiredRole }) {
  const { authenticated, user } = useAuth();
  if (!authenticated) return <LoginScreen />;
  if (requiredRole && !user.roles.includes(requiredRole) && !user.roles.includes("admin")) {
    return <AccessDenied required={requiredRole} />;
  }
  return children;
}
```

Admin bypass is explicit in the frontend check (mirrors the backend's `has_role` bypass). If a non-admin user navigates to `/admin/*`, they see an AccessDenied screen with their current roles.

## NavRail entries

`frontend/src/components/NavRail.jsx` renders the icon sidebar with:

- Logo (goes to `/`)
- Dashboard (`/`)
- Chat (`/chat`)
- Tasks (`/tasks`) — badge with pending approval count
- Projects (`/projects`)
- Divider
- Tools section:
  - MCP (`/tools/mcp`)
  - Infrastructure (`/tools/infrastructure`)
  - Cache (`/tools/cache`)
- Admin section (only if admin):
  - Database (`/admin/database`)
  - Evaluations (`/admin/evaluations`)
  - Analytics (`/admin/tests/analytics`)
- Bottom: User avatar + dropdown (profile, logout)

The badge on `/tasks` reads from `useQuery(['tasks'])` — same cache as the Tasks page, so the number stays consistent.

## URL state conventions

- `?session=X` — active session in Chat
- `?mode=inspect` — show the DebugEventLog panel (internal tooling)
- `?page=N&limit=20` — pagination wherever paginated lists exist
- `?tag=…` — filter test runs by tag
- `?batch_id=…` — scope analytics to one batch

Pagination and filters are read via `useSearchParams()`; updates use `setSearchParams(…, { replace: true })` so pagination doesn't spam the history.

## Deep-link behavior

- `/chat?session=X` on a session the user doesn't own → backend returns 403 → UI shows error state with "Return to dashboard" button.
- `/chat?session=X` on a session that's been deleted → 404 → UI shows "Session not found".
- Admin routes hit by non-admin → frontend blocks without hitting backend.
