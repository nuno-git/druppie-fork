# Database Schema

Druppie uses PostgreSQL with a normalized schema.

## Design Principles

1. **No JSON columns for operational data** - Everything normalized into proper tables
2. **JSON only for debug/resume data** - `agent_state`, `request_messages`, `event_data`
3. **Cascade deletes** - Deleting a session cleans up all related data
4. **Agent isolation** - Messages linked to `agent_run_id` so agents don't share history
5. **Nested execution** - Agent runs can be nested via `parent_run_id` for full traceability

## Execution Model

Understanding the nested execution flow is critical. Here's how a chat works:

```
SESSION
│
├── [system_message] "I am Druppie..."
├── [user_message] "Build me a todo app"
│
└── agent_runs[] ─────────────────────────────────────────────────────────────
    │
    ├── [run_index=0] ROUTER AGENT (always first)
    │   ├── llm_calls[0]: decides intent
    │   └── tool_calls[]: (usually none, just thinking)
    │
    ├── [run_index=1] PLANNER AGENT (always second)
    │   ├── llm_calls[0]: creates plan
    │   └── decides: create workflow OR call agents directly
    │
    └── [run_index=2+] EXECUTION (one of these patterns):
        │
        ├─────────────────────────────────────────────────────────────────────
        │ PATTERN A: Workflow Created
        │
        │ workflow
        │ └── workflow_steps[]
        │     ├── [step_index=0] "architect"
        │     │   └── agent_run (workflow_step_id set)
        │     │       ├── llm_calls[]
        │     │       └── tool_calls[]
        │     │           ├── coding:write_file → approval?
        │     │           └── execute_agent("reviewer") ──┐
        │     │               └── child_agent_run_id ─────┤
        │     │                   (nested agent run) ◄────┘
        │     │                   ├── parent_run_id = architect's run
        │     │                   ├── llm_calls[]
        │     │                   └── tool_calls[]
        │     │
        │     ├── [step_index=1] "developer"
        │     │   └── agent_run
        │     │       └── ...
        │     │
        │     └── [step_index=2] "deployer"
        │         └── agent_run
        │             ├── tool_calls[]
        │             │   ├── docker:build → approval required
        │             │   └── docker:run → approval required
        │             └── ...
        │
        ├─────────────────────────────────────────────────────────────────────
        │ PATTERN B: Direct Agent Calls (no workflow)
        │
        │ agent_run [run_index=2] "developer"
        │ ├── llm_calls[]
        │ └── tool_calls[]
        │     └── execute_agent("tester") ──┐
        │         └── child_agent_run_id ───┤
        │             (nested agent run) ◄──┘
        │             ├── parent_run_id = developer's run
        │             └── ...
        │
        └─────────────────────────────────────────────────────────────────────
```

### Key Relationships

| Field | Purpose |
|-------|---------|
| `agent_runs.run_index` | Order within parent (0=router, 1=planner, 2+=execution) |
| `agent_runs.parent_run_id` | Points to parent agent_run when nested via execute_agent |
| `agent_runs.workflow_step_id` | Links to workflow_step when running as part of workflow |
| `tool_calls.child_agent_run_id` | When tool is execute_agent, points to the spawned agent_run |

### Nesting Rules

1. **Top-level runs**: `parent_run_id = NULL`, `workflow_step_id = NULL`
2. **Workflow step runs**: `parent_run_id = NULL`, `workflow_step_id = <step_id>`
3. **Nested via execute_agent**: `parent_run_id = <caller's run_id>`
4. **Double nested**: Both `parent_run_id` AND `workflow_step_id` can be set

## Entity Relationship Diagram

```
                                    ┌─────────────┐
                                    │    users    │
                                    └──────┬──────┘
                                           │
                    ┌──────────────────────┼──────────────────────┐
                    │                      │                      │
                    ▼                      ▼                      ▼
            ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
            │   projects    │      │   sessions    │      │  user_roles   │
            └───────┬───────┘      └───────┬───────┘      └───────────────┘
                    │                      │
        ┌───────────┴───────────┐          │
        │                       │          │
        ▼                       ▼          │
┌───────────────────────────────────────┐   │
│  (containers managed by Docker MCP)   │   │
│  (no database tables - uses labels)   │   │
└───────────────────────────────────────┘   │
                                           │
        ┌──────────────┬───────────────────┼───────────────────┐
        │              │                   │                   │
        ▼              ▼                   ▼                   ▼
┌───────────────┐ ┌───────────┐   ┌───────────────┐   ┌───────────────┐
│   workflows   │ │ messages  │   │  agent_runs   │◄─┐│ hitl_questions│
└───────┬───────┘ └───────────┘   └───────┬───────┘  ││ └───────┬───────┘
        │                                 │          ││         │
        │                                 │ parent_  ││         ▼
        │                                 │ run_id   ││ ┌───────────────────┐
        │                                 └──────────┘│ │hitl_question_choices│
        │                                             │ └───────────────────┘
        ▼                   ┌──────────────┬──────────┘
┌───────────────┐           │              │
│workflow_steps │◄──────────│──────────────│─────────────────────┐
└───────────────┘           │              │                     │
        │                   ▼              ▼                     │
        │           ┌───────────┐  ┌───────────────┐             │
        │           │ llm_calls │  │  tool_calls   │─────────────┤
        │           └───────────┘  └───────┬───────┘             │
        │                                  │                     │
        │                                  │ child_agent_run_id  │
        │                                  │ (execute_agent)     │
        │                                  ▼                     │
        │                          ┌───────────────┐             │
        │                          │  agent_runs   │ (nested)    │
        │                          └───────────────┘             │
        │                                                        │
        │         ┌──────────────────────┬───────────────────────┘
        │         │                      │
        │         ▼                      ▼
        │ ┌───────────────────┐  ┌───────────────┐
        │ │tool_call_arguments│  │   approvals   │
        │ └───────────────────┘  └───────────────┘
        │
        └─── workflow_step_id ───► agent_runs
```

**Key relationships for nesting:**
- `agent_runs.parent_run_id` → Self-reference for execute_agent nesting
- `agent_runs.workflow_step_id` → Links to workflow_steps for workflow execution
- `tool_calls.child_agent_run_id` → Points to spawned agent_run when execute_agent is called

**Note:** Workspaces (file storage) are managed by the Coding MCP server, not the database.

## Tables

### users

User accounts (synced from Keycloak).

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| username | VARCHAR(255) | Unique username |
| email | VARCHAR(255) | Email address |
| display_name | VARCHAR(255) | Display name |
| created_at | TIMESTAMP | Created timestamp |

### user_roles

Role assignments (normalized, not JSON array).

| Column | Type | Description |
|--------|------|-------------|
| user_id | UUID | FK to users |
| role | VARCHAR(50) | Role name (admin, developer, etc.) |

### sessions

Chat conversations.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| user_id | UUID | FK to users (owner) |
| project_id | UUID | FK to projects (optional) |
| title | VARCHAR(500) | Session title |
| status | VARCHAR(50) | active, paused_approval, paused_hitl, completed, failed |
| prompt_tokens | INTEGER | Total prompt tokens used |
| completion_tokens | INTEGER | Total completion tokens used |
| total_tokens | INTEGER | Total tokens used |
| created_at | TIMESTAMP | Created timestamp |
| updated_at | TIMESTAMP | Last update timestamp |

**Status values:**
- `active` - Currently executing
- `paused_approval` - Waiting for tool approval
- `paused_hitl` - Waiting for user answer
- `completed` - Successfully finished
- `failed` - Error occurred
- `cancelled` - User cancelled

### agent_runs

Individual agent executions within a session. Can be nested.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| workflow_step_id | UUID | FK to workflow_steps (if part of workflow) |
| agent_id | VARCHAR(100) | Agent identifier (router, developer, etc.) |
| parent_run_id | UUID | FK to agent_runs (if spawned by execute_agent) |
| run_index | INTEGER | Order within parent scope (0=router, 1=planner, 2+=execution) |
| status | VARCHAR(50) | running, paused_tool, paused_hitl, completed, failed |
| iteration_count | INTEGER | LLM call count |
| prompt_tokens | INTEGER | Tokens for this run |
| completion_tokens | INTEGER | |
| total_tokens | INTEGER | |
| started_at | TIMESTAMP | |
| completed_at | TIMESTAMP | |

**Nesting explained:**
- `parent_run_id = NULL` → Top-level run (router, planner, or direct agent)
- `parent_run_id = <uuid>` → Spawned by another agent via `execute_agent` tool
- `workflow_step_id = <uuid>` → Running as part of a workflow step

### messages

Conversation messages.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| agent_run_id | UUID | FK to agent_runs (isolates messages per agent) |
| role | VARCHAR(50) | system, user, assistant, tool |
| content | TEXT | Message content |
| sequence_number | INTEGER | Order within agent run |
| created_at | TIMESTAMP | |

### tool_calls

Tool invocations (MCP tools and built-in tools).

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| agent_run_id | UUID | FK to agent_runs (who called this tool) |
| tool_type | VARCHAR(50) | `mcp` or `builtin` |
| mcp_server | VARCHAR(100) | Server name (coding, docker) - NULL for builtin |
| tool_name | VARCHAR(100) | Tool name (write_file, execute_agent, done) |
| child_agent_run_id | UUID | FK to agent_runs - set when tool_name=execute_agent |
| status | VARCHAR(50) | pending, executing, completed, failed |
| result | TEXT | Tool result |
| error | TEXT | Error message (if failed) |
| created_at | TIMESTAMP | |

**Tool types:**
- `mcp` tools: `coding:write_file`, `docker:build`, etc.
- `builtin` tools: `execute_agent`, `done`, `hitl_ask_question`, `hitl_ask_multiple_choice_question`

**execute_agent nesting:**
When `tool_name = 'execute_agent'`, the `child_agent_run_id` points to the spawned agent's run.
This creates the nested structure visible in the execution trace.

### tool_call_arguments

Normalized tool arguments (not JSON).

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| tool_call_id | UUID | FK to tool_calls |
| arg_name | VARCHAR(255) | Argument name |
| arg_value | TEXT | Argument value |

### approvals

Approval requests for tools.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| agent_run_id | UUID | FK to agent_runs |
| tool_call_id | UUID | FK to tool_calls (optional) |
| workflow_step_id | UUID | FK to workflow_steps (optional) |
| approval_type | VARCHAR(50) | tool_call, workflow_step |
| mcp_server | VARCHAR(100) | |
| tool_name | VARCHAR(100) | |
| required_role | VARCHAR(50) | Role required to approve |
| status | VARCHAR(50) | pending, approved, rejected |
| arguments | JSONB | Tool arguments (for display) |
| agent_state | JSONB | Saved state for resumption |
| agent_id | VARCHAR(100) | Agent that requested |
| resolved_by | UUID | FK to users (who approved/rejected) |
| resolved_at | TIMESTAMP | |
| rejection_reason | TEXT | |
| created_at | TIMESTAMP | |

### hitl_questions

Human-in-the-loop questions.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| agent_run_id | UUID | FK to agent_runs |
| agent_id | VARCHAR(100) | Agent that asked |
| question | TEXT | Question text |
| question_type | VARCHAR(50) | text, multiple_choice |
| status | VARCHAR(50) | pending, answered |
| answer | TEXT | User's answer |
| agent_state | JSON | Saved state for resumption |
| answered_at | TIMESTAMP | |
| created_at | TIMESTAMP | |

### hitl_question_choices

Choices for multiple-choice questions (normalized).

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| question_id | UUID | FK to hitl_questions |
| choice_index | INTEGER | Order (0, 1, 2...) |
| choice_text | TEXT | Choice text |
| is_selected | BOOLEAN | Whether selected |

### llm_calls

LLM API call records (for debugging/audit).

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| agent_run_id | UUID | FK to agent_runs |
| agent_id | VARCHAR(100) | |
| provider | VARCHAR(50) | zai, deepinfra, mock |
| model | VARCHAR(100) | Model name |
| prompt_tokens | INTEGER | |
| completion_tokens | INTEGER | |
| total_tokens | INTEGER | |
| duration_ms | INTEGER | Call duration |
| request_messages | JSON | Full request (debug) |
| response_content | TEXT | LLM response |
| response_tool_calls | JSON | Tool calls in response |
| tools_provided | JSON | Tools available to LLM |
| created_at | TIMESTAMP | |

### projects

Git repositories.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| owner_id | UUID | FK to users |
| name | VARCHAR(255) | Project name |
| description | TEXT | |
| repo_name | VARCHAR(255) | Gitea repo name |
| repo_url | VARCHAR(500) | Gitea URL |
| status | VARCHAR(50) | active, archived |
| created_at | TIMESTAMP | |

### Container Management (No Database Tables)

Containers are **NOT** stored in the database. Docker MCP is the source of truth.

**How it works:**
- Docker MCP clones git repo, builds, and runs containers
- Containers are labeled with Druppie metadata
- Backend queries Docker MCP to list containers

**Docker labels:**
```
druppie.project_id=<uuid>
druppie.session_id=<uuid>
druppie.branch=main
druppie.git_url=http://gitea:3000/org/todo-app
```

**API Bridge:**
```
GET /api/deployments
  → Backend gets user's project IDs
  → Calls Docker MCP: list_containers(project_id=xxx)
  → Returns only containers user owns
```

This approach:
- No stale database state (Docker is source of truth)
- Works with Kubernetes (no shared volumes)
- User isolation via project_id label filtering

### workflows

Execution plans.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| name | VARCHAR(255) | Workflow name |
| status | VARCHAR(50) | pending, running, completed, failed |
| current_step | INTEGER | Current step index |
| created_at | TIMESTAMP | |

### workflow_steps

Steps in a workflow.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| workflow_id | UUID | FK to workflows |
| step_index | INTEGER | Order (0, 1, 2...) |
| agent_id | VARCHAR(100) | Agent to run |
| description | TEXT | Step description |
| status | VARCHAR(50) | pending, running, completed, failed, skipped |
| result_summary | TEXT | Output summary |
| created_at | TIMESTAMP | |

## Common Queries

### Get session with all data

```sql
SELECT s.*,
       w.name as workflow_name,
       w.status as workflow_status
FROM sessions s
LEFT JOIN workflows w ON w.session_id = s.id
WHERE s.id = $1;
```

### Get pending approvals for user role

```sql
SELECT a.*
FROM approvals a
WHERE a.status = 'pending'
  AND a.required_role = ANY($1)  -- user's roles
ORDER BY a.created_at;
```

### Token usage by agent

```sql
SELECT ar.agent_id,
       SUM(ar.prompt_tokens) as prompt,
       SUM(ar.completion_tokens) as completion,
       SUM(ar.total_tokens) as total
FROM agent_runs ar
WHERE ar.session_id = $1
GROUP BY ar.agent_id;
```

### Get execution tree (top-level runs only)

```sql
-- Get top-level agent runs (router, planner, direct agents)
SELECT ar.*
FROM agent_runs ar
WHERE ar.session_id = $1
  AND ar.parent_run_id IS NULL
  AND ar.workflow_step_id IS NULL
ORDER BY ar.run_index;
```

### Get workflow with steps and their agent runs

```sql
SELECT
    w.id as workflow_id,
    w.name as workflow_name,
    ws.step_index,
    ws.agent_id as step_agent,
    ws.status as step_status,
    ar.id as agent_run_id,
    ar.status as run_status
FROM workflows w
JOIN workflow_steps ws ON ws.workflow_id = w.id
LEFT JOIN agent_runs ar ON ar.workflow_step_id = ws.id
WHERE w.session_id = $1
ORDER BY ws.step_index;
```

### Get nested agent runs (execute_agent tree)

```sql
-- Recursive query to get all nested runs
WITH RECURSIVE run_tree AS (
    -- Base: top-level run
    SELECT id, agent_id, parent_run_id, 0 as depth
    FROM agent_runs
    WHERE id = $1

    UNION ALL

    -- Recursive: children via parent_run_id
    SELECT ar.id, ar.agent_id, ar.parent_run_id, rt.depth + 1
    FROM agent_runs ar
    JOIN run_tree rt ON ar.parent_run_id = rt.id
)
SELECT * FROM run_tree ORDER BY depth;
```

### Get tool calls with child agent runs

```sql
-- Find all execute_agent calls and their spawned runs
SELECT
    tc.id as tool_call_id,
    tc.tool_name,
    tc.child_agent_run_id,
    child.agent_id as spawned_agent,
    child.status as spawned_status
FROM tool_calls tc
LEFT JOIN agent_runs child ON tc.child_agent_run_id = child.id
WHERE tc.agent_run_id = $1
ORDER BY tc.created_at;
```

### Build full chat timeline

```sql
-- Step 1: Get messages
SELECT 'message' as item_type, role, content, created_at, NULL as agent_run_id
FROM messages WHERE session_id = $1

UNION ALL

-- Step 2: Get agent runs as timeline items
SELECT 'agent_run' as item_type, agent_id as role, NULL as content,
       started_at as created_at, id as agent_run_id
FROM agent_runs
WHERE session_id = $1 AND parent_run_id IS NULL

ORDER BY created_at;
```

The application layer then:
1. Fetches tool_calls, llm_calls, hitl_questions for each agent_run
2. Recursively fetches child agent_runs via parent_run_id
3. Merges everything into a nested chat array

## Cascade Behavior

| Relationship | On Delete |
|--------------|-----------|
| Session → Workflow | CASCADE |
| Session → AgentRuns | CASCADE |
| Session → Messages | CASCADE |
| Session → Approvals | CASCADE |
| Session → HitlQuestions | CASCADE |
| Session → ToolCalls | CASCADE |
| Workflow → Steps | CASCADE |
| WorkflowStep → AgentRuns | CASCADE |
| AgentRun → Child AgentRuns | CASCADE (via parent_run_id) |
| AgentRun → ToolCalls | CASCADE |
| AgentRun → LlmCalls | NO CASCADE (audit) |
| ToolCall → Child AgentRun | SET NULL (don't delete spawned run) |
| ToolCall → Arguments | CASCADE |
| Project → Sessions | SET NULL (orphans) |
| HitlQuestion → Choices | CASCADE |
