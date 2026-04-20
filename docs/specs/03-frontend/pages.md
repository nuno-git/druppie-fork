# Pages

One file per route in `frontend/src/pages/`. Every page owns its React Query keys, URL state, and top-level layout choices.

## Dashboard (`Dashboard.jsx`)

**Route:** `/`
**Data:**
- `useQuery(['plans'])` → `getPlans()` → `/api/sessions` (legacy name kept for stability)
- `useQuery(['tasks'])` → `getTasks()` → `/api/approvals`
- `useQuery(['status'], { refetchInterval: 30_000 })` → `/api/status`
- `useQuery(['projects'])` → `/api/projects`

**UI:**
- 4 stat cards: Total sessions, Completed, Pending approvals, Total tokens+cost (computed via `calculateCost` at $0.40/M tokens).
- Recent Sessions grid (last 5).
- Pending Approvals grid (last 5, link → `/tasks`).
- System status dots (Keycloak, DB, LLM).
- Empty states with CTA buttons ("Start a new session").

## Chat (`Chat.jsx`)

**Route:** `/chat` and `/chat?session={id}`
**Layout:** Two panels.
- Left: `<SessionSidebar>` (collapsible via `druppie-chat-sidebar` localStorage flag).
- Right: `<SessionDetail>` if session is present, else `<NewSessionPanel>`.

`<SessionSidebar>` polls `useQuery(['sessions'], { refetchInterval: 5_000 })` while open.

`<SessionDetail>` is the workhorse:
- Renders the session timeline (messages + agent runs).
- Embeds `<ApprovalCard>`, `<ToolDecisionCard>`, `<HITLQuestionMessage>`, `<SandboxEventCard>` inline where appropriate.
- `?mode=inspect` toggles `<DebugEventLog>` — full LLM call traces with prompts and tool-call schemas.

Message streaming effect: the page polls the session detail every few seconds; new timeline entries appear naturally.

## Tasks (`Tasks.jsx`)

**Route:** `/tasks`
**Data:**
- `getTasks()` (pending)
- `getApprovalHistory(page, limit)` (resolved, paginated)

**UI:**
- Toggle between Pending and History.
- Each card: tool name (formatted via `formatToolName`), arguments (JSON pretty-print), required role, status pill.
- Inline actions: Approve / Reject.
- Reject opens a modal for the reason (1–1000 chars).
- File preview modal for `.md` arguments (rendered via `<MermaidBlock>` and markdown).

## Projects (`Projects.jsx`)

**Route:** `/projects`
**Data:** `getProjects()`, `getDeployments()`

**UI:**
- Card grid: one per project with name, repo URL copy button, last-updated, token/cost, deployment status badge (Running/Ready/Created).
- Per card buttons: View Details, Stop (if running), Delete.

## ProjectDetail (`ProjectDetail.jsx`)

**Route:** `/projects/{id}`
**Tabs:**
- Overview — metadata, repo URL, token usage, deployment cards (with container log modals), LLM usage breakdown.
- Conversations — `getProjectSessions(id)` → session list scoped to this project.
- Dependencies — `getProjectDependencies(id)` → packages with manager/name/version.

## DebugMCP (`DebugMCP.jsx`)

**Route:** `/tools/mcp`
Purpose: call any MCP tool directly for debugging.

- `getMCPServers()` list.
- Expand a server → tool list with descriptions.
- Expand a tool → JSON argument editor + "Call" button → `POST /api/mcp/call`.
- Result panel shows returned JSON.
- Container logs modal for docker tool output.

## DebugProjects (`DebugProjects.jsx`)

**Route:** `/tools/infrastructure`
Purpose: see all running containers across all projects, filter by project/user, inspect labels.

## CachedDependencies (`CachedDependencies.jsx`)

**Route:** `/tools/cache`
Purpose: visualise the shared `druppie_sandbox_dep_cache` volume. Grouped by manager (npm, pnpm, bun, uv, pip). Click a package → list of projects using it.

## AdminDatabase (`AdminDatabase.jsx`)

**Route:** `/admin/database`
**Role:** admin

Generic table browser:
- Dropdown of all tables (`getAdminTables()`).
- Paginated grid view with per-column `order_by`/`order_dir`/`filter_field`/`filter_value`.
- Smart cell rendering: UUID → clickable breadcrumb link, timestamps → localized, status → badge, arrays → pill list.
- Click UUID → `getAdminRecord(table, id)` → detail view with breadcrumb of visited records.

## Evaluations (`Evaluations.jsx`)

**Route:** `/admin/evaluations`
**Role:** admin

- Test selector modal: list from `getAvailableTests()`, filter by mode (live/record_only/replay/manual) and tag.
- Run button triggers `POST /api/evaluations/run-tests` → returns `batch_id`.
- Progress panel: polls `getRunStatus(batch_id)` every 2 s — shows current test, completed/total, status.
- Results: grouped by batch; expand → test runs → assertion results.
- Actions: delete batch, export assertions, seed test users.

## Analytics (`Analytics.jsx`)

**Route:** `/admin/tests/analytics`
**Role:** admin

Tabs: Summary, Trends, By Agent, By Eval, By Tool, By Test.
Batch selector on top scopes most views to a single batch.
Filter panel per assertion type (completed/tool/verify/judge_check/judge_eval).
Charts: Recharts BarChart + LineChart.

## BatchDetail (`BatchDetail.jsx`)

**Route:** `/admin/tests/batch/{batchId}`
**Role:** admin

- Metrics strip: pass/total per assertion type.
- Table of assertions filterable by `assertion_type`, `agent_id`, `tool_name`, `check_text`.
- Click row → modal with full `judge_raw_input`, `judge_raw_output`, `judge_reasoning`.

## Settings (`Settings.jsx`)

**Route:** `/settings`
User preferences. Currently minimal — theme selection, token display. Expected to grow with per-user agent defaults, LLM overrides, etc.
