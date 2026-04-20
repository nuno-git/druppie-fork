# Services

Frontend service modules at `frontend/src/services/`.

## `api.js`

Base:
```js
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
async function request(path, opts = {}) {
  const token = getToken();
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...opts.headers }
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.message || `HTTP ${res.status}`);
  }
  return res.json();
}
```

Every exported function is a thin wrapper around `request(...)`.

### Exports — grouped

**User**
- `getUser()`

**Chat**
- `sendChat(message, session_id?, conversationHistory?)`
- `cancelChat(session_id)`

**Sessions** (new names; legacy aliases kept)
- `getSessions(page, limit)` / `getPlans(…)` / `getSessionTrace(…)`
- `getSession(session_id)` / `getPlan(session_id)`
- `resumeSession(session_id)`
- `deleteSession(session_id)`
- `retryFromRun(session_id, agent_run_id, planned_prompt?)`

**Approvals**
- `getApprovals()` / `getTasks()`
- `getApproval(id)`
- `approveApproval(id)` / `approveTask(id)`
- `rejectApproval(id, reason)` / `rejectTask(id, reason)`
- `getApprovalHistory(page, limit)`
- `getUsersByRole(role)`

**Questions (HITL)**
- `getQuestions(session_id?)`
- `getQuestion(id)`
- `answerQuestion(id, answer, selected_choices?)`
- `cancelQuestion(id)`
- `submitHITLResponse(request_id, answer, selected)` — microservices path

**MCP**
- `getMCPs()`
- `getMCPServers()`
- `getMCPTools()`
- `getMCPTool(id)`
- `checkMCPPermission({ server, tool })`
- `callMCPTool({ server, tool, arguments, session_id? })` (via `/api/mcp/call`)

**Workspace**
- `getWorkspaceFiles(session_id)`
- `getWorkspaceFile(path, session_id)`
- `getWorkspaceDownloadUrl(path, session_id)` → direct URL string

**Projects**
- `getProjects()`
- `getProject(id)`
- `buildProject(id)`, `runProject(id)`, `stopProject(id)`
- `deleteProject(id)`, `updateProject(id, data)`
- `getProjectStatus(id)`
- `getProjectCommits(id, branch, limit)`
- `getProjectBranches(id)`
- `getProjectSessions(id, limit)`
- `getProjectFiles(id, path, branch)`
- `getProjectFile(id, path, branch)`
- `getProjectDependencies(id)`

**Deployments**
- `getDeployments(project_id?)`
- `stopDeployment(container_name)`
- `getDeploymentLogs(container_name, tail)`

**Agents**
- `getAgents()` → `{agents: [...]}` (unwrapped by the caller)
- `getAgent(id)`

**Sandbox**
- `getSandboxEvents(session_id, message_id?)` — cursor-paginated, 500 at a time

**Admin database**
- `getAdminStats()`
- `getAdminTables()`
- `getAdminTableData(name, page, limit, options)`
- `getAdminRecord(name, id)`

**Evaluations (all admin)**
- **Benchmarks:** `getBenchmarkRuns(…)`, `getBenchmarkRun(id)`, `deleteBenchmarkRun(id)`, `triggerBenchmark(scenario, judge)`, `getEvaluationResults(…)`, `getEvaluationResult(id)`, `getAgentEvalSummary(agent_id)`, `getEvaluationConfig()`, `runUnitTests()`
- **Tests (v2):** `getAvailableTests()`, `getAvailableSetups()`, `seedSessions(names, user)`, `getTestRuns(…)`, `getTestRun(id)`, `getTags()`, `deleteTestUsers()`, `runTests(opts)`, `getRunStatus(batch_id)`, `getTestBatches(…)`
- **Analytics (v3):** `getAnalyticsSummary(days)`, `getAnalyticsTrends(days)`, `getAnalyticsByAgent(batch_id?)`, `getAnalyticsByEval(…)`, `getAnalyticsByTool(…)`, `getAnalyticsByTest(…)`, `getAnalyticsBatchDetail(batch_id)`, `getTestRunAssertions(id)`, `getBatchAssertions(batch_id, filters)`, `getBatchFilters(batch_id)`, `getActiveRun()`

**Cache**
- `getCachedPackages()`
- `getAllProjectDependencies()`
- `getPackageProjects(manager, name)`

**Health**
- `getHealth()` — `/health`
- `getStatus()` — `/api/status`

## `keycloak.js`

Configuration read from `import.meta.env`:
- `VITE_KEYCLOAK_URL` (default `http://localhost:8080`)
- `VITE_KEYCLOAK_REALM` (default `druppie`)
- `VITE_KEYCLOAK_CLIENT_ID` (default `druppie-frontend`)

Lifecycle:
- `initKeycloak()` — health-checks Keycloak (3×, 2 s each), then `keycloak.init({ onLoad: 'check-sso', silentCheckSsoRedirectUri: '/silent-check-sso.html', pkceMethod: 'S256' })`. Persists tokens to localStorage. Wires `onTokenExpired` → `updateToken(30)` auto-refresh. 30 s total timeout before failing.
- `getKeycloak()` — singleton accessor.
- `login()` — redirect to Keycloak.
- `logout()` — clear storage + redirect.
- `getToken()` — current access token.
- `isAuthenticated()` — token present + not expired.
- `getUserInfo()` → `{ id, username, email, firstName, lastName, roles }` from `realm_access.roles`.
- `hasRole(role)`, `hasAnyRole(...roles)` — admin bypass in both.
- `isKeycloakAvailable()` — cached health-check result.

## `AuthContext.jsx` (tangentially)

Defined in `App.jsx`. Provides:
```js
{ keycloakReady: boolean, authenticated: boolean, user: User|null }
```

`ProtectedRoute` consumes this context plus an optional `requiredRole`. All pages use `useAuth()` rather than calling `getKeycloak()` directly.

## Error handling conventions

- Any service function can `throw new Error(message)`.
- `useQuery` catches these → `error` field on the hook.
- `useMutation` has `onError` hooks that call `useToast().error(message)`.
- Unauthorized (401) triggers a `logout()` + redirect to login — there is no silent re-auth path beyond the token refresh.
