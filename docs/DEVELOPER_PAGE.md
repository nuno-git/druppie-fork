# Developer Page — Quick Sandbox-Based Execution Testing

## 1. Purpose
A dedicated page for quickly testing sandbox-based execution flows without going through the full Druppie agent pipeline (router → BA → architect → planner → developer). Select a project, pick a flow, enter a task prompt, and execute directly. The execute_coding_task tool triggers the developer agent in a sandbox container.

## 2. User Flow
```
[Select Project] → [Select Branch] → [Pick Flow] → [Enter Prompt] → [Execute]
                                                                           ↓
                                                           Backend creates session
                                                                           ↓
                                                           Retry-from developer agent
                                                                           ↓
                                                     Sandbox-based run starts via execute_coding_task
                                                                           ↓
                                                        PiCodingRunLiveCard renders
```

## 3. Page Layout (ASCII)
```
┌─────────────────────────────────────────────────────────────────────┐
│  Developer Console                                                   │
├──────────────────┬──────────────────────────────────────────────────┤
│  ┌──────────────┐│  ┌──────────────────────────────────────────────┐│
│  │ Project      ││  │  Execute a sandbox-based run to see results here  ││
│  │ [dropdown  ▼]││  │                                              ││
│  │              ││  │        [Code2 icon]                          ││
│  │ Branch       ││  │   Select a project, branch, flow,            ││
│  │ [dropdown  ▼]││  │   enter a task prompt, and click Execute.    ││
│  │              ││  │                                              ││
│  │ Flow         ││  └──────────────────────────────────────────────┘│
│  │ ○ planner    ││  ┌──────────────────────────────────────────────┐│
│  │   TDD flow   ││  │  [PiCodingRunLiveCard after execution]      ││
│  │ ○ router     ││  │  - builder-1  ✓ 15t 14tc 1m30s              ││
│  │   Explore    ││  │  - builder-2  ✓ 9t 8tc 1m12s                ││
│  │              ││  │  - builder-3  ✓ ...                         ││
│  │ Task Prompt  ││  │  - pusher-1   ✓ 2t 3tc 10s                  ││
│  │ ┌──────────┐ ││  └──────────────────────────────────────────────┘│
│  │ │          │ ││                                                  │
│  │ │          │ ││                                                  │
│  │ └──────────┘ ││                                                  │
│  │              ││                                                  │
│  │ [▶ Execute]  ││                                                  │
│  └──────────────┘│                                                  │
├──────────────────┴──────────────────────────────────────────────────┤
│  Status: Ready · 0 active runs                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## 4. Component Tree
```
DeveloperPage
├── PageHeader "Developer Console"
├── div.two-column
│   ├── FormPanel (sticky, w-96)
│   │   ├── ProjectSelector — dropdown, fetches GET /api/projects
│   │   ├── BranchSelector — dropdown, fetches GET /api/projects/{id}/branches
│   │   ├── FlowSelector — radio buttons (planner | router)
│   │   ├── PromptInput — textarea, 5 rows
│   │   └── ExecuteButton — disabled states for loading/executing
│   └── ResultsPanel (flex-1)
│       ├── EmptyState — when no run active
│       ├── LoadingState — spinner with status text
│       └── PiCodingRunLiveCard — when toolCallId is available
└── StatusBar — "Ready · N active runs"
```

## 5. API Endpoints
| Endpoint | Method | Purpose |
|----------|--------|---------|
| /api/projects | GET | List all projects for dropdown |
| /api/projects/{id}/branches | GET | List branches for selected project |
| /api/sessions | POST | Create a new session (with pending developer) |
| /api/sessions/{id} | GET | Poll session state for tool calls |
| /api/sessions/{id}/retry-from/{agentRunId} | POST | Trigger developer with execute_coding_task |
| /api/pi-agent-runs/by-tool-call/{tcId} | GET | Get sandbox execution events for LiveCard |

## 6. Execution Sequence (Detailed)
1. User fills form → clicks Execute
2. Frontend creates a session via POST /api/sessions (or runs setup test)
3. Frontend finds the pending developer agent_run in the session timeline
4. Frontend calls retryFromRun(sessionId, agentRunId, plannedPrompt)
5. Poll GET /api/sessions/{id} every 2s for max 30s, looking for execute_coding_task in agent run tool calls
6. Once toolCallId is found, set it → PiCodingRunLiveCard renders and starts polling /by-tool-call
7. Show status updates: "Creating session..." → "Starting sandbox execution..." → "Running..." → "Completed"

## 7. Edge Cases
- **No projects**: Show "No projects found" empty state
- **No branches**: Show "No branches" with disabled execute button
- **Session creation fails**: Red error banner with retry button
- **Sandbox execution fails**: PiCodingRunLiveCard shows failure state
- **Timeout polling**: Show "Timed out waiting for sandbox execution to start" with retry
- **Network error**: Show error with retry button

## 8. Future Improvements
- Run history sidebar (recent executions with status)
- Save favorite prompts per project
- Compare runs across branches/flows
- Support druppie_core repo_target
- Custom model selection per run
- Export run logs/summaries
