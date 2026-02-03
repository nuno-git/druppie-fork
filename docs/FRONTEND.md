# Frontend Architecture

Detailed architecture documentation for the Druppie frontend application.

## Component Hierarchy

```
main.jsx
└── QueryClientProvider (TanStack React Query)
    └── App.jsx
        └── ErrorBoundary
            └── AuthContext.Provider
                └── ToastProvider
                    └── BrowserRouter
                        ├── Navigation
                        └── Routes (ProtectedRoute wrappers)
                            ├── Dashboard
                            ├── Chat
                            ├── Tasks (Approvals)
                            ├── Projects
                            ├── ProjectDetail
                            ├── Settings
                            ├── Debug (execution trace)
                            ├── DebugChat        ─┐
                            ├── DebugApprovals    │ Debug dropdown
                            ├── DebugMCP          │
                            ├── DebugProjects    ─┘
                            └── AdminDatabase (admin only)
```

### Provider Stack (top to bottom)

1. **QueryClientProvider** (`main.jsx`) -- TanStack React Query with 60s `staleTime` and `refetchOnWindowFocus: false`
2. **ErrorBoundary** (`App.jsx`) -- Class-based error boundary with retry and expandable error details
3. **AuthContext.Provider** (`App.jsx`) -- Provides `{ authenticated, user }` via `useAuth()` hook
4. **ToastProvider** (`App.jsx`) -- Toast notifications via `useToast()` hook (success, error, warning, info)
5. **BrowserRouter** (`App.jsx`) -- React Router v6 with `Routes` and `Route` definitions

## State Management

### Server State (TanStack React Query)

All server data is managed through React Query. There is no Redux or other global client state store for API data. Patterns used throughout:

```javascript
// Read with polling
const { data, isLoading, error, refetch } = useQuery({
  queryKey: ['sessions'],
  queryFn: () => getSessions(),
  refetchInterval: 10000,  // Poll every 10s
})

// Mutations with cache invalidation
const mutation = useMutation({
  mutationFn: (data) => approveTask(taskId, data),
  onSuccess: () => {
    queryClient.invalidateQueries(['tasks'])
  },
})
```

**Query Client defaults** (configured in `main.jsx`):
- `staleTime`: 60 seconds -- data is considered fresh for 1 minute
- `refetchOnWindowFocus`: false -- no automatic refetch on tab focus

**Common polling intervals across pages**:
- Approvals/Tasks: 10 seconds
- Session data: 5 seconds
- Project status: 10-15 seconds
- System health: 30 seconds
- Plans list: 10 seconds

### Client State

- **React Context**: `AuthContext` for authentication state, `ToastContext` for notifications
- **Zustand**: Listed as dependency but primary usage is through React Query and local `useState`
- **Component-local state**: `useState` for UI state (active tabs, expanded sections, form inputs, selected items)

## Routing Structure

All routes are defined in `App.jsx` and wrapped with `ProtectedRoute`:

| Route Pattern | Component | Auth Required | Role Required | Nav Location |
|---------------|-----------|:---:|:---:|:---:|
| `/` | Dashboard | Yes | -- | Main nav |
| `/chat` | Chat | Yes | -- | Main nav |
| `/tasks` | Tasks | Yes | -- | Main nav |
| `/projects` | Projects | Yes | -- | Main nav |
| `/projects/:projectId` | ProjectDetail | Yes | -- | -- |
| `/settings` | Settings | Yes | -- | Main nav |
| `/debug-chat` | DebugChat | Yes | -- | Debug dropdown |
| `/debug-approvals` | DebugApprovals | Yes | -- | Debug dropdown |
| `/debug-mcp` | DebugMCP | Yes | -- | Debug dropdown |
| `/debug-projects` | DebugProjects | Yes | -- | Debug dropdown |
| `/debug/:sessionId` | Debug | Yes | -- | -- |
| `/admin/database` | AdminDatabase | Yes | admin | Admin nav |
| `*` | Redirect to `/` | -- | -- | -- |

### ProtectedRoute Behavior

```
if (!authenticated) -> Show "Log in with Keycloak" prompt
if (requiredRole && !hasRole(role)) -> Show "Access Denied" with role requirement
else -> Render children
```

### Navigation

The `Navigation` component renders a sticky header bar with:
- Logo linking to `/`
- Main nav items: Dashboard, Chat, Approvals, Projects, Settings
- **Debug dropdown** (orange-themed): Debug Chat, Debug Approvals, Debug MCP, Debug Projects -- these are raw API testing pages for development
- Admin-only items (Database) shown conditionally when `user.roles.includes('admin')`
- Pending approvals badge count (polled every 30s)
- User info display with username and admin badge
- Login/Logout button

## API Integration Patterns

### API Client (`src/services/api.js`)

Central `request()` function that all endpoints use:

```javascript
const request = async (endpoint, options = {}) => {
  const token = getToken()  // From Keycloak service
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
  }
  const response = await fetch(`${API_URL}${endpoint}`, { ...options, headers })
  // Error handling, JSON parsing, console logging
}
```

### API Endpoint Groups

**Chat** -- Primary user interaction
- `POST /api/chat` -- Send message (with optional session_id for continuation)
- `POST /api/chat/{sessionId}/cancel` -- Cancel running execution
- `POST /api/chat/{sessionId}/resume` -- Resume after HITL pause

**Sessions** -- Conversation history
- `GET /api/sessions` -- Paginated session list (for sidebar)
- `GET /api/sessions/{id}` -- Full session detail (messages, LLM calls, events, approvals)

**Approvals** -- HITL governance
- `GET /api/approvals` -- Pending approvals list
- `GET /api/approvals?status=approved` -- Completed approvals
- `POST /api/approvals/{id}/approve` -- Approve or reject (with `approved: true/false`)

**Questions** -- HITL questions from agents
- `GET /api/questions` -- Pending questions (optionally filtered by session_id)
- `POST /api/questions/{id}/answer` -- Submit answer
- `POST /api/questions/{id}/cancel` -- Cancel question

**Projects** -- Git-backed project management
- `GET /api/projects` -- All projects
- `GET /api/projects/{id}` -- Project detail
- `POST /api/projects/{id}/build` -- Docker build
- `POST /api/projects/{id}/run` -- Docker run
- `POST /api/projects/{id}/stop` -- Stop container
- `PATCH /api/projects/{id}` -- Update name/description
- `DELETE /api/projects/{id}` -- Delete project
- `GET /api/projects/{id}/commits` -- Git commits (with branch/limit params)
- `GET /api/projects/{id}/branches` -- Git branches
- `GET /api/projects/{id}/sessions` -- Linked conversations

**MCP Registry** -- Tool transparency
- `GET /api/mcps/servers` -- MCP server list
- `GET /api/mcps/tools` -- All available tools

**Agents** -- AI agent transparency
- `GET /api/agents` -- All configured agents with model info

**Workspace** -- File access
- `GET /api/workspace` -- File listing
- `GET /api/workspace/file` -- File content
- `GET /api/workspace/download` -- File download URL

**Admin** -- Database browser (admin-only)
- `GET /api/admin/tables` -- Table list
- `GET /api/admin/table/{name}` -- Paginated table data
- `GET /api/admin/table/{name}/{id}` -- Single record with relations

**System**
- `GET /api/status` -- Health check (Keycloak, DB, LLM, Gitea)
- `GET /health` -- Simple health endpoint

## Keycloak Authentication Flow

### Initialization Sequence

```
1. App mounts
2. initKeycloak() called in useEffect
3. Health check: fetch /realms/druppie (up to 3 retries, 2s apart)
4. If unreachable:
   - Return mock keycloak object (authenticated: false)
   - Show "Authentication Server Unavailable" UI
5. If reachable:
   - new Keycloak(config)
   - Init with check-sso mode (silent SSO via hidden iframe)
   - Load saved tokens from localStorage
   - 30-second timeout on init
6. If authenticated:
   - Save tokens to localStorage
   - Parse user info from JWT (sub, username, email, roles)
   - Set up onTokenExpired handler for auto-refresh
7. AuthContext provides { authenticated, user } to app
```

### Silent SSO

Keycloak is configured with `onLoad: 'check-sso'` and a `silentCheckSsoRedirectUri` pointing to `/silent-check-sso.html`. This enables:
- Automatic session detection without full page redirect
- Seamless authentication when the user has an active Keycloak session
- Token persistence across page reloads via localStorage

### Token Management

- Tokens stored in localStorage (`kc_token`, `kc_refresh_token`)
- `getToken()` provides the current access token to `api.js` for Bearer auth
- Auto-refresh via `keycloakInstance.onTokenExpired` with 30-second buffer
- Tokens cleared on logout or refresh failure

### Role-Based Access

```javascript
// Check single role (admin always passes)
hasRole('developer')  // true if user has 'developer' or 'admin' role

// Check any role
hasAnyRole('architect', 'developer')  // true if user has any listed role or 'admin'
```

User info extracted from the JWT token:
```javascript
{
  id: tokenParsed.sub,
  username: tokenParsed.preferred_username,
  email: tokenParsed.email,
  firstName: tokenParsed.given_name,
  lastName: tokenParsed.family_name,
  roles: tokenParsed.realm_access.roles,
}
```

## Key Pages in Detail

### Chat (`/chat`)

The primary user interaction page. Features:

- **Conversation Sidebar**: Lists all sessions with preview text and status, supports creating new conversations
- **Message Thread**: Displays user messages, agent responses, workflow events, tool executions, approval cards, HITL questions, and deployment cards in a unified timeline
- **Message Input**: Text input with send button, suggestion buttons for quick actions
- **Agent Attribution**: Each agent response shows the agent name, icon, and color coding (e.g., Router = purple, Developer = green, DevOps = orange)
- **Real-time Updates**: Polling via React Query for live workflow events and session updates
- **Session Management**: URL parameter `?session=<id>` for deep linking to specific conversations

Chat components (from `src/components/chat/`):
- `Message` -- Text message bubble with markdown support
- `WorkflowTimeline` -- Collapsible timeline of execution events
- `WorkflowEvent` / `WorkflowEventMessage` -- Individual event display
- `ToolExecutionCard` -- Shows MCP tool calls with arguments and results
- `ToolDecisionCard` -- Shows tool approval decisions
- `ApprovalCard` -- Inline approval request
- `QuestionCard` / `HITLQuestionMessage` -- HITL question with options or free text
- `DeploymentCard` -- Deployment success with app URL
- `AgentAttribution` -- Agent name badge with icon
- `TypingIndicator` -- Animated typing dots
- `ConversationSidebar` -- Session list with search
- `DebugPanel` -- Expandable debug information

### Tasks / Approvals (`/tasks`)

The HITL governance page with two sections:

**Pending Questions**:
- Agent questions requiring human input
- Support for predefined options or free-text answers
- Linked to originating session

**Pending Approvals**:
- Grouped by required role
- Each `TaskCard` shows:
  - Tool name with icon (write_file, run_command, commit_and_push, etc.)
  - Danger level badge (low/medium/high/critical)
  - Code preview for file write operations (expandable)
  - Command preview for shell commands
  - Commit message preview for git operations
  - Multi-approval progress bar (when multiple roles must approve)
  - Approve/Reject buttons (only for users with matching roles)
  - Link to originating conversation
- Approval history section (expandable, lazy-loaded)

### Projects (`/projects` and `/projects/:projectId`)

**Projects List** (`Projects.jsx`):
- Grid of project cards showing name, description, status, repo URL, app URL
- Token usage display with cost estimation
- Build/Run/Stop controls per project
- File browser when a project is selected (directories, files with preview and download)
- Delete project with confirmation dialog

**Project Detail** (`ProjectDetail.jsx`):
- Tabbed interface with four tabs:
  - **Overview**: Project info, Git repository URL with clone command, running app URL, build/run/stop actions
  - **Repository**: Branch selector, commit history with author/date/SHA
  - **Conversations**: Linked chat sessions with status indicators
  - **Settings**: Edit project name and description

### Debug / Execution Trace (`/debug/:sessionId`)

Detailed execution trace viewer for a single session:

- **Trace Events**: Expandable tree of all execution events (agent starts, LLM calls, tool executions, completions, errors)
- **Raw LLM Call Viewer**: Tabbed view showing:
  - Messages sent to the LLM (system prompt, user messages, tool results)
  - Tool definitions provided
  - LLM response text
  - Token usage stats (prompt tokens, completion tokens, total)
- **Trace Summary**: Aggregate stats -- total events, tokens used by agent, duration
- **JSON Viewer**: Raw JSON display for any event data

### Settings (`/settings`)

Admin configuration and system transparency page:

- **User Profile**: Name, username, email, assigned roles with color-coded badges
- **System Info**: Health status of Keycloak, Database, LLM Service, Gitea (with refresh). Shows environment, version, LLM provider, and model name.
- **MCP Servers**: List of registered MCP servers with status and their available tools
- **Configured Agents**: All AI agents with their category (system/execution/quality/deployment), model name, temperature, max tokens, and MCP access list

### Admin Database (`/admin/database`)

Admin-only database browser (requires `admin` role):

- **Table Navigation**: Tab bar listing all database tables
- **Data Grid**: Paginated table view with sortable columns
- **Record Detail**: Click any row to see full record with:
  - All field values
  - Foreign key links (clickable to navigate to related records)
  - Reverse relations (records that reference this record)
- **Navigation History**: Back button stack for navigating through foreign key relationships

## Utility Modules

### Agent Configuration (`src/utils/agentConfig.js`)

Maps agent IDs to display properties:

| Agent | Icon | Color | Description |
|-------|------|-------|-------------|
| router | Brain | purple | Intent analysis |
| planner | Clock | blue | Execution planning |
| business_analyst | ClipboardList | teal | Requirements gathering |
| architect | Brain | indigo | System design |
| developer / code_generator | FileCode | green | Code generation |
| devops / deployer | Hammer | orange | Build and deploy |
| git_agent | GitBranch | gray | Version control |
| reviewer | CheckCircle | teal | Code review |
| tester | CheckCircle | cyan | Testing |

Exports: `getAgentConfig(agentId)`, `getAgentColorClasses(color)`, `getAgentMessageColors(color)`

### Event Utilities (`src/utils/eventUtils.jsx`)

Workflow event display logic:

- `getEventIcon(eventType, status)` -- Maps event types to Lucide icons
- `getStatusColors(status)` -- CSS classes for success/error/warning/working states
- `formatEventTitle(event)` -- Human-readable event titles (e.g., "Starting developer agent", "Calling LLM [model-name]")
- `getEventDescription(event)` -- Detailed descriptions with model info for transparency
- `getEventCategory(eventType)` -- Categorizes into: agent, tool, llm, workflow, approval, result
- `getCategoryStyles(category)` -- Color scheme per category (purple for agents, orange for tools, indigo for LLM, etc.)
- `processWorkflowEvents(events)` -- Marks "working" events as complete when subsequent events exist

### Token Utilities (`src/utils/tokenUtils.js`)

Token count formatting and cost estimation:

- `formatTokens(count)` -- Formats as "141.8K" or "1.2M"
- `calculateCost(tokens)` -- Estimated cost at $0.40/million tokens
- `formatCost(cost)` -- Formats as "$0.05" or "<$0.01"
- `formatTokensWithCost(tokens)` -- Returns `{ tokens, cost, rawCost }`

## E2E Testing

Playwright tests cover key user workflows:

**Authentication** (`tests/e2e/auth.spec.js`):
- Login flow through Keycloak
- Logout and session cleanup
- Role-based page access (admin vs non-admin)
- Multiple user roles (admin, seniordev, infra, productowner)

**Chat** (`tests/e2e/chat.spec.js`):
- Sending messages and receiving responses
- Suggestion button interactions
- Session creation and switching

**Deployment Approval** (`tests/e2e/deployment-approval.spec.js`):
- End-to-end deployment approval workflow
- Multi-user approval scenarios
- Role-based approval restrictions
