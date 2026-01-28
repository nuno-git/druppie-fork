# Database Schema

Druppie uses PostgreSQL with a normalized schema.

## Design Principles

1. **No JSON columns for operational data** - Everything normalized into proper tables
2. **JSON only for debug/resume data** - `agent_state`, `request_messages`, `event_data`
3. **Cascade deletes** - Deleting a session cleans up all related data
4. **Agent isolation** - Messages linked to `agent_run_id` so agents don't share history

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
        ┌───────────┼───────────┐          │
        │           │           │          │
        ▼           ▼           ▼          │
┌───────────┐ ┌───────────┐ ┌───────────┐  │
│  builds   │ │deployments│ │ workspaces│  │
└───────────┘ └───────────┘ └───────────┘  │
                                           │
        ┌──────────────────────────────────┤
        │                                  │
        ▼                                  ▼
┌───────────────┐                  ┌───────────────┐
│   workflows   │                  │  agent_runs   │◄──┐
└───────┬───────┘                  └───────┬───────┘   │
        │                                  │           │
        ▼                    ┌─────────────┼───────────┤
┌───────────────┐            │             │           │
│workflow_steps │            ▼             ▼           │
└───────────────┘    ┌───────────┐  ┌───────────┐     │
                     │ messages  │  │ llm_calls │     │
                     └───────────┘  └───────────┘     │
                                                       │
        ┌─────────────────────────────────────────────┤
        │                     │                        │
        ▼                     ▼                        │
┌───────────────┐     ┌───────────────┐               │
│  tool_calls   │     │   approvals   │───────────────┘
└───────┬───────┘     └───────────────┘
        │
        ▼
┌───────────────────┐
│tool_call_arguments│
└───────────────────┘

┌───────────────┐     ┌─────────────────────┐
│hitl_questions │────▶│hitl_question_choices│
└───────────────┘     └─────────────────────┘

┌───────────────┐
│session_events │ (timeline/audit log)
└───────────────┘
```

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

Individual agent executions within a session.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| workflow_step_id | UUID | FK to workflow_steps (optional) |
| agent_id | VARCHAR(100) | Agent identifier (router, developer, etc.) |
| parent_run_id | UUID | FK to agent_runs (for nested runs) |
| status | VARCHAR(50) | running, paused_tool, paused_hitl, completed, failed |
| iteration_count | INTEGER | LLM call count |
| prompt_tokens | INTEGER | Tokens for this run |
| completion_tokens | INTEGER | |
| total_tokens | INTEGER | |
| started_at | TIMESTAMP | |
| completed_at | TIMESTAMP | |

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

MCP tool invocations.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| agent_run_id | UUID | FK to agent_runs |
| mcp_server | VARCHAR(100) | Server name (coding, docker) |
| tool_name | VARCHAR(100) | Tool name (write_file, build) |
| status | VARCHAR(50) | pending, executing, completed, failed |
| result | TEXT | Tool result (optional) |
| error | TEXT | Error message (if failed) |
| created_at | TIMESTAMP | |

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

### workspaces

Local git sandboxes for sessions.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| project_id | UUID | FK to projects |
| branch | VARCHAR(255) | Git branch |
| local_path | VARCHAR(500) | Filesystem path |
| created_at | TIMESTAMP | |

### builds

Docker builds.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| project_id | UUID | FK to projects |
| branch | VARCHAR(255) | |
| status | VARCHAR(50) | building, running, stopped, failed |
| image_name | VARCHAR(255) | Docker image name |
| container_name | VARCHAR(255) | Container name |
| port | INTEGER | Container internal port |
| host_port | INTEGER | Exposed host port |
| app_url | VARCHAR(500) | Access URL |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### deployments

Running containers.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| build_id | UUID | FK to builds |
| project_id | UUID | FK to projects |
| container_name | VARCHAR(255) | |
| host_port | INTEGER | |
| status | VARCHAR(50) | running, stopped |
| started_at | TIMESTAMP | |
| stopped_at | TIMESTAMP | |

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

### session_events

Timeline/audit log.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| session_id | UUID | FK to sessions |
| event_type | VARCHAR(100) | agent_started, tool_call, approval_required, etc. |
| agent_id | VARCHAR(100) | |
| title | VARCHAR(500) | Event title |
| tool_name | VARCHAR(100) | |
| approval_id | UUID | FK to approvals |
| question_id | UUID | FK to hitl_questions |
| llm_call_id | UUID | FK to llm_calls |
| tool_call_id | UUID | FK to tool_calls |
| event_data | JSONB | Additional data |
| duration_ms | INTEGER | |
| timestamp | TIMESTAMP | |

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

### Session timeline

```sql
SELECT event_type, agent_id, tool_name, timestamp
FROM session_events
WHERE session_id = $1
ORDER BY timestamp;
```

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
| AgentRun → LlmCalls | NO CASCADE (audit) |
| Project → Sessions | SET NULL (orphans) |
| HitlQuestion → Choices | CASCADE |
| ToolCall → Arguments | CASCADE |
