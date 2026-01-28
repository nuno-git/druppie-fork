# Druppie Frontend Documentation

## Overview

The Druppie frontend is a React + Vite single-page application providing a real-time governance interface for AI agents. It features approval workflows, execution tracing, and project management.

**Tech Stack**:
- React 18 with Vite 5
- TailwindCSS for styling
- React Query for server state
- Native WebSocket for real-time updates
- Keycloak for authentication

**Default Port**: 5173 (development), 5273 (production)

---

## Table of Contents

1. [Pages & Routes](#pages--routes)
2. [Services](#services)
3. [Components](#components)
4. [State Management](#state-management)
5. [Real-Time Communication](#real-time-communication)
6. [Authentication](#authentication)
7. [Build & Development](#build--development)
8. [Key Features](#key-features)

---

## Pages & Routes

All pages are defined in `App.jsx`:

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | Dashboard | Overview with stats, running apps, pending approvals |
| `/chat` | Chat | Main AI conversation interface |
| `/tasks` | Tasks | Approval/rejection management |
| `/projects` | Projects | Project list with file browsing |
| `/projects/:projectId` | ProjectDetail | Project view with tabs |
| `/debug/:sessionId` | Debug | Execution trace viewer |
| `/settings` | Settings | System configuration |
| `/admin/database` | AdminDatabase | Database browser (admin only) |

All routes except `/admin/database` require authentication. The admin route also requires the `admin` role.

---

## Services

### API Service (`services/api.js`)

HTTP client with 50+ endpoints. Authentication via Bearer token.

**Base URL**: `VITE_API_URL` or `http://localhost:8000`

#### Chat & Sessions

```javascript
sendChat(message, sessionId?, projectId?, projectName?)
getSessions(page?, limit?, projectId?, status?)
getSession(sessionId)          // Full session with execution tree
resumeSession(sessionId, answer?, approved?)
cancelChat(sessionId)
```

#### Approvals

```javascript
getApprovals()                 // Pending approvals for user's roles
approveApproval(approvalId, comment?)
rejectApproval(approvalId, reason?)
```

#### Projects

```javascript
getProjects()
getProject(projectId)
createProject(name, description?)
updateProject(projectId, data)
deleteProject(projectId)
getProjectFiles(projectId, path?, branch?)
getProjectFile(projectId, path, branch?)
getProjectBranches(projectId)
getProjectCommits(projectId, branch?, limit?)
getProjectSessions(projectId)
buildProject(projectId, branch?)
```

#### Workspace

```javascript
getWorkspaceFiles(sessionId, path?, recursive?)
getWorkspaceFile(sessionId, path)
getWorkspaceDownloadUrl(sessionId, path)
```

#### HITL Questions

```javascript
getQuestions()                 // Pending questions
answerQuestion(questionId, answer)
```

#### MCP & Agents

```javascript
getMCPs()                      // Servers with tools
getMCPServers()               // Server health status
getMCPTools()                 // All tools
getAgents()                   // Agent configurations
```

#### Running Apps

```javascript
getRunningApps()
```

#### Admin

```javascript
getAdminStats()
getAdminTables()
getAdminTableData(tableName, page?, limit?, filters?)
getAdminRecord(tableName, recordId)
```

---

### Keycloak Service (`services/keycloak.js`)

OAuth2/OpenID Connect authentication.

**Configuration**:
```javascript
{
  url: 'http://localhost:8080',
  realm: 'druppie',
  clientId: 'druppie-frontend'
}
```

**Key Functions**:

```javascript
initKeycloak()                // Initialize with retry logic
login()                       // Redirect to Keycloak login
logout()                      // Clear session and redirect
getToken()                    // Get access token
isAuthenticated()             // Check auth status
getUserInfo()                 // Get user details
hasRole(role)                 // Check single role
hasAnyRole(roles)             // Check multiple roles
```

**Token Management**:
- Stored in localStorage (`kc_token`, `kc_refresh_token`)
- Auto-refreshed 30 seconds before expiry
- Cleared on logout

**Health Check**:
- 3 retries with 2-second delay
- Falls back to unauthenticated mode if Keycloak unavailable

---

### WebSocket Service (`services/socket.js`)

Real-time updates using native WebSocket.

**Endpoints**:
- `/ws` - Global connection
- `/ws/session/{sessionId}` - Session-specific

**Connection Management**:
```javascript
connect()                     // Establish connection
disconnect()                  // Close connection
getStatus()                   // 'connected' | 'connecting' | 'disconnected' | 'reconnecting'
joinPlanRoom(planId)          // Subscribe to session updates
joinApprovalsRoom(roles)      // Subscribe to approval events
```

**Event Subscriptions**:
```javascript
onSessionUpdated(callback)
onWorkflowEvent(callback)
onApprovalRequested(callback)
onApprovalStatusChanged(callback)
onQuestionPending(callback)
onDeploymentComplete(callback)
onExecutionCancelled(callback)
```

**Reconnection**:
- Exponential backoff with jitter
- Max 10 retries
- Auto-reconnect on unexpected close

---

## Components

### Chat Components (`components/chat/`)

| Component | Purpose |
|-----------|---------|
| `Message` | User/assistant message with markdown |
| `ApprovalCard` | Inline approval UI with code preview |
| `DeploymentCard` | Success card with app URL |
| `WorkflowEventMessage` | Agent lifecycle badges |
| `ToolDecisionCard` | Tool call decision display |
| `HITLQuestionMessage` | Question prompt with input |
| `QuestionCard` | Multi-choice or text answer |
| `ConversationSidebar` | Session history with search/filter |
| `TypingIndicator` | "Agent is working..." animation |
| `DebugPanel` | Collapsible execution trace |
| `AgentAttribution` | Agent name badge |

### Core Components

| Component | Purpose |
|-----------|---------|
| `ErrorBoundary` | Error fallback with retry |
| `ConnectionStatus` | WebSocket status indicator |
| `Toast` | Notification system |
| `CodeBlock` | Syntax-highlighted code |

---

## State Management

### Auth Context

```javascript
const { authenticated, user } = useAuth()

// user object:
{
  id: 'uuid',
  username: 'string',
  email: 'string',
  firstName: 'string',
  lastName: 'string',
  roles: ['admin', 'developer']
}
```

### Toast Context

```javascript
const toast = useToast()

toast.success('Title', 'Message')
toast.error('Title', 'Message')
toast.warning('Title', 'Message')
toast.info('Title', 'Message')
toast.dismiss(id)
```

### React Query

Server state with automatic caching and refetching.

**Query Keys**:
- `['sessions']` - Session list
- `['session', sessionId]` - Single session
- `['tasks']` / `['approvals']` - Pending approvals
- `['running-apps']` - Running applications
- `['projects']` - Project list
- `['mcp-servers']`, `['mcp-tools']` - MCP config
- `['agents']` - Agent config

**Refetch Intervals**:
- Approvals: 30 seconds
- Running apps: 15 seconds
- Status: 30 seconds

---

## Real-Time Communication

### WebSocket Event Flow

**Client Joins Session**:
```javascript
socket.joinPlanRoom(sessionId)
// Server confirms: { type: 'joined_session', session_id: '...' }
```

**Client Joins Approval Rooms**:
```javascript
socket.joinApprovalsRoom(['admin', 'developer'])
// Server confirms: { type: 'joined_approvals', roles: [...] }
```

### Event Types

| Event | Description |
|-------|-------------|
| `session_updated` | Session status changed |
| `workflow_event` | Agent/tool execution event |
| `approval_requested` | New approval needed |
| `approval_approved` | Approval granted |
| `approval_rejected` | Approval denied |
| `question_pending` | HITL question waiting |
| `question_answered` | Question answered |
| `deployment_complete` | App deployed with URL |
| `execution_cancelled` | User cancelled |

### Data Flow

1. **Session Loading**: Fetch session → render messages + events → subscribe to WebSocket
2. **Approval Flow**: Agent pauses → approval_requested → UI shows card → user approves → workflow continues
3. **HITL Flow**: Agent asks → question_pending → UI shows input → user answers → workflow continues

---

## Authentication

### Flow

1. App mounts → `initKeycloak()`
2. Check Keycloak health (retry 3x)
3. Initialize Keycloak with silent SSO
4. Token stored in localStorage
5. Token attached to all API requests
6. Auto-refresh before expiry

### Protected Routes

```jsx
<ProtectedRoute>
  <SomeComponent />
</ProtectedRoute>
```

Redirects to login if not authenticated.

### Role Checks

```javascript
// In components
const { user } = useAuth()
const isAdmin = user?.roles?.includes('admin')

// In Keycloak service
keycloak.hasRole('admin')
keycloak.hasAnyRole(['admin', 'developer'])
```

---

## Build & Development

### Scripts

```bash
npm run dev          # Start dev server (port 5173)
npm run build        # Build to dist/
npm run preview      # Preview production build
npm run lint         # ESLint
npm run test         # Vitest unit tests
npm run test:e2e     # Playwright E2E tests
```

### Environment Variables

```bash
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_KEYCLOAK_URL=http://localhost:8080
VITE_KEYCLOAK_REALM=druppie
VITE_KEYCLOAK_CLIENT_ID=druppie-frontend
```

### Dependencies

**Core**:
- `react@18.2.0`
- `react-dom@18.2.0`
- `react-router-dom@6.21.0`

**State**:
- `@tanstack/react-query@5.17.0`

**Auth**:
- `keycloak-js@23.0.0`

**UI**:
- `tailwindcss@3.4.0`
- `lucide-react@0.303.0`
- `prismjs@1.30.0`

**Dev**:
- `vite@5.0.0`
- `vitest@1.1.0`
- `@playwright/test@1.40.0`

---

## Key Features

### Dashboard

- Stat cards: Sessions, Completed, Running Apps, Approvals, Tokens
- Running Applications with stop button
- Token tracking with cost estimates
- Quick links to recent sessions

### Chat Interface

- **Sidebar**: Session history with search, status filter
- **Messages**: Markdown rendering, inline events
- **Workflow Events**: Colored agent badges, tool calls
- **Approvals**: Code preview, diff view
- **HITL Questions**: Text or multi-choice input
- **Deployment**: Success card with app URL

### Tasks Page

- Pending approvals with role requirements
- Code preview for file operations
- Approve/reject with comments
- Approval history

### Projects Page

- Project cards with status badges
- File browser with icons
- Build/Run/Stop actions
- Token usage per project

### Project Detail

- **Overview**: Info, build status, actions
- **Repository**: Branches, commits, files
- **Conversations**: Linked sessions
- **Settings**: Edit name/description

### Debug Page

- Event tree (expandable)
- Timeline with durations
- Per-agent token breakdown
- Raw data viewer

### Settings Page

- User profile and roles
- System health status
- MCP server status
- Agent configurations

---

## Utility Functions

### Token Formatting (`utils/tokenUtils.js`)

```javascript
formatTokens(141832)           // "141.8K"
calculateCost(1000000)         // 0.40 (dollars)
formatCost(0.056)              // "$0.06"
formatTokensWithCost(141832)   // { formatted: "141.8K", cost: "$0.06" }
```

### Agent Config (`utils/agentConfig.js`)

```javascript
getAgentConfig('developer')
// { name: 'Developer', icon: FileCode, color: 'green' }

getAgentColorClasses('green')
// 'bg-green-100 text-green-800'

getAgentMessageColors('green')
// { bg: 'bg-green-50', border: 'border-green-200', ... }
```

**Agent Colors**:
- router: purple
- planner: blue
- architect: indigo
- developer: green
- deployer: orange
- reviewer: teal
- tester: cyan

---

## File Structure

```
frontend/
├── src/
│   ├── pages/
│   │   ├── Dashboard.jsx
│   │   ├── Chat.jsx
│   │   ├── Tasks.jsx
│   │   ├── Projects.jsx
│   │   ├── ProjectDetail.jsx
│   │   ├── Debug.jsx
│   │   ├── Settings.jsx
│   │   └── AdminDatabase.jsx
│   ├── services/
│   │   ├── api.js
│   │   ├── keycloak.js
│   │   └── socket.js
│   ├── components/
│   │   ├── chat/
│   │   │   ├── Message.jsx
│   │   │   ├── ApprovalCard.jsx
│   │   │   ├── DeploymentCard.jsx
│   │   │   ├── WorkflowEventMessage.jsx
│   │   │   ├── HITLQuestionMessage.jsx
│   │   │   ├── ConversationSidebar.jsx
│   │   │   ├── DebugPanel.jsx
│   │   │   └── ...
│   │   ├── ErrorBoundary.jsx
│   │   ├── ConnectionStatus.jsx
│   │   ├── Toast.jsx
│   │   └── CodeBlock.jsx
│   ├── utils/
│   │   ├── agentConfig.js
│   │   ├── tokenUtils.js
│   │   └── eventUtils.jsx
│   ├── App.jsx
│   ├── main.jsx
│   └── index.css
├── tests/e2e/
├── package.json
├── vite.config.js
├── tailwind.config.js
└── Dockerfile
```

---

## Testing

### Unit Tests (Vitest)

```bash
npm run test
```

### E2E Tests (Playwright)

```bash
npm run test:e2e                    # Full suite
npx playwright test tests/e2e/chat.spec.js  # Specific file
```

**Test Ports**:
- Frontend: 5273
- Backend: 8100
- Keycloak: 8180

### Playwright Tips

Handle multiple element matches:
```javascript
// Use .first() for first match
await page.getByText('Deploy').first().click()

// Use exact matching
await page.getByRole('link', { name: 'Chat', exact: true }).click()
```
