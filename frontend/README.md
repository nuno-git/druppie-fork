# Druppie Frontend

React-based web application for the Druppie AI Governance Platform. Provides a chat interface for interacting with AI agents, approval workflows for human-in-the-loop (HITL) governance, project management with Git integration, and administrative tools.

## Tech Stack

| Category | Technology | Version |
|----------|-----------|---------|
| Framework | React | 18.2 |
| Build Tool | Vite | 5.x |
| Styling | Tailwind CSS | 3.4 |
| Routing | React Router DOM | 6.21 |
| Server State | TanStack React Query | 5.17 |
| Client State | Zustand | 4.4 |
| Authentication | Keycloak JS | 23.x |
| Icons | Lucide React | 0.303 |
| Code Highlighting | PrismJS | 1.30 |
| Unit Testing | Vitest | 1.1 |
| E2E Testing | Playwright | 1.40 |

## Getting Started

### Prerequisites

- Node.js (18+)
- Backend running on port 8000 (or set `VITE_API_URL`)
- Keycloak running on port 8080 (or set `VITE_KEYCLOAK_URL`)

### Install and Run

```bash
cd frontend
npm install
npm run dev      # Dev server on port 5173
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | Backend API base URL |
| `VITE_KEYCLOAK_URL` | `http://localhost:8080` | Keycloak server URL |
| `VITE_KEYCLOAK_REALM` | `druppie` | Keycloak realm name |
| `VITE_KEYCLOAK_CLIENT_ID` | `druppie-frontend` | Keycloak client ID |

### Available Scripts

```bash
npm run dev      # Start Vite dev server (port 5173)
npm run build    # Production build to dist/
npm run preview  # Preview production build
npm run lint     # ESLint check
npm test         # Run Vitest unit tests
npm run test:e2e # Run Playwright E2E tests
```

## Project Structure

```
frontend/
├── src/
│   ├── main.jsx                 # Entry point, QueryClient setup
│   ├── App.jsx                  # Root component, routing, auth context
│   ├── index.css                # Tailwind imports
│   ├── pages/
│   │   ├── Dashboard.jsx        # Home page with welcome and stats
│   │   ├── Chat.jsx             # Main chat interface with sessions
│   │   ├── Tasks.jsx            # Approval queue (HITL approvals + questions)
│   │   ├── Projects.jsx         # Project grid with file browser
│   │   ├── ProjectDetail.jsx    # Single project with tabs (overview/repo/conversations/settings)
│   │   ├── Plans.jsx            # Execution plans viewer
│   │   ├── Debug.jsx            # Execution trace viewer (per session)
│   │   ├── Settings.jsx         # System status, MCP servers, agents
│   │   ├── AdminDatabase.jsx    # Admin-only database browser
│   │   ├── DebugChat.jsx        # Debug: raw API testing for chat
│   │   ├── DebugApprovals.jsx   # Debug: raw API testing for approvals
│   │   ├── DebugMCP.jsx         # Debug: raw API testing for MCP
│   │   └── DebugProjects.jsx    # Debug: raw API testing for projects
│   ├── components/
│   │   ├── Toast.jsx            # Toast notification system (context-based)
│   │   ├── ErrorBoundary.jsx    # Error boundary with retry
│   │   ├── CodeBlock.jsx        # Syntax-highlighted code display
│   │   └── chat/
│   │       ├── index.js              # Barrel exports
│   │       ├── Message.jsx           # Chat message bubble
│   │       ├── WorkflowEvent.jsx     # Single workflow event display
│   │       ├── WorkflowTimeline.jsx  # Timeline of workflow events
│   │       ├── WorkflowEventMessage.jsx # Event as chat message
│   │       ├── QuestionCard.jsx      # HITL question display
│   │       ├── ApprovalCard.jsx      # Approval request card
│   │       ├── ToolExecutionCard.jsx # MCP tool execution display
│   │       ├── ToolDecisionCard.jsx  # Tool approval decision UI
│   │       ├── DeploymentCard.jsx    # Deployment status card
│   │       ├── HITLQuestionMessage.jsx # HITL question in chat
│   │       ├── AgentAttribution.jsx  # Agent name/icon badge
│   │       ├── TypingIndicator.jsx   # Typing animation
│   │       ├── ConversationSidebar.jsx # Session list sidebar
│   │       └── DebugPanel.jsx        # Inline debug panel
│   ├── services/
│   │   ├── api.js               # HTTP API client (all backend endpoints)
│   │   └── keycloak.js          # Keycloak auth (init, login, logout, tokens, roles)
│   └── utils/
│       ├── agentConfig.js       # Agent icons, colors, and display names
│       ├── eventUtils.jsx       # Workflow event formatting and categorization
│       └── tokenUtils.js        # Token count formatting and cost estimation
├── tests/
│   └── e2e/
│       ├── auth.spec.js              # Auth flow tests (login, logout, roles)
│       ├── chat.spec.js              # Chat interaction tests
│       └── deployment-approval.spec.js # Deployment approval workflow tests
├── public/
│   └── silent-check-sso.html   # Keycloak silent SSO check
├── package.json
├── vite.config.js
├── tailwind.config.js
├── playwright.config.js
└── postcss.config.js
```

## Authentication

Authentication is handled by **Keycloak** using the `keycloak-js` adapter:

1. On app load, `initKeycloak()` checks if the Keycloak server is reachable (with retries)
2. If available, initializes with `check-sso` mode for silent single sign-on
3. Tokens are persisted to `localStorage` for session persistence across page reloads
4. Automatic token refresh is configured via `onTokenExpired`
5. The `AuthContext` (exported as `useAuth`) provides `{ authenticated, user }` to all components
6. `ProtectedRoute` wraps all routes, optionally checking for specific roles (e.g., `requiredRole="admin"`)

### Test Users

| User | Password | Roles |
|------|----------|-------|
| admin | Admin123! | admin |
| architect | Architect123! | architect, developer |
| seniordev | Developer123! | developer |

## Pages Overview

**Main pages** (in navigation bar):

| Route | Page | Description |
|-------|------|-------------|
| `/` | Dashboard | Welcome page with system overview |
| `/chat` | Chat | Main chat interface with AI agents |
| `/tasks` | Tasks | Approval queue with HITL questions and tool approvals |
| `/projects` | Projects | Project grid with file browser and build/run controls |
| `/projects/:projectId` | ProjectDetail | Tabbed project view (overview, repository, conversations, settings) |
| `/settings` | Settings | User profile, system health, MCP servers, agents |
| `/debug/:sessionId` | Debug | Execution trace viewer with LLM call details |
| `/admin/database` | AdminDatabase | Admin-only database browser (requires admin role) |

**Debug pages** (in Debug dropdown, for raw API testing):

| Route | Page | Description |
|-------|------|-------------|
| `/debug-chat` | DebugChat | Raw API debug interface for chat endpoints |
| `/debug-approvals` | DebugApprovals | Raw API debug interface for approvals |
| `/debug-mcp` | DebugMCP | Raw API debug interface for MCP servers and tools |
| `/debug-projects` | DebugProjects | Raw API debug interface for projects and deployments |

## API Integration

All API calls go through `src/services/api.js`, which provides:

- Automatic Bearer token injection from Keycloak
- Centralized error handling with structured error messages
- Console logging for debugging (grouped by request)
- Configurable base URL via `VITE_API_URL`

Key API domains: Chat, Sessions, Approvals, Questions, MCP Registry, Projects, Workspace, Agents, Admin.

## Real-time Updates

The frontend uses polling (via TanStack React Query `refetchInterval`) to detect state changes from the backend. WebSocket-based real-time push is planned as a future improvement.

## Testing

### Unit Tests (Vitest)

```bash
npm test
```

### E2E Tests (Playwright)

```bash
npm run test:e2e
```

E2E tests cover:
- Keycloak login/logout flows
- Role-based access control
- Chat message sending and suggestions
- Deployment approval workflows
- Multi-user approval scenarios
