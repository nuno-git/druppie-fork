# Druppie Database Documentation

## Overview

Druppie uses PostgreSQL with SQLAlchemy ORM. The database follows a **fully normalized design** with no JSON/JSONB columns for business data (only for debugging and state preservation).

**Source of Truth**: `druppie/db/schema.sql`

**Key Design Principles**:
1. No JSON/JSONB for business data - everything normalized into proper tables
2. Configuration stays in YAML files (agents, MCP tools, workflows)
3. Agent isolation - messages linked to `agent_run_id` for context separation
4. State preservation for workflow resumption

---

## Table of Contents

1. [Users & Authentication](#users--authentication)
2. [Projects](#projects)
3. [Sessions](#sessions)
4. [Workflows & Steps](#workflows--steps)
5. [Agent Runs](#agent-runs)
6. [Messages](#messages)
7. [Tool Calls](#tool-calls)
8. [Approvals](#approvals)
9. [HITL Questions](#hitl-questions)
10. [Workspaces](#workspaces)
11. [Builds & Deployments](#builds--deployments)
12. [LLM Calls](#llm-calls)
13. [Session Events](#session-events)
14. [Relationships Diagram](#relationships-diagram)
15. [Indexes](#indexes)
16. [Enums & Status Values](#enums--status-values)
17. [CRUD Operations](#crud-operations)

---

## Users & Authentication

### users

Primary user table synced from Keycloak.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Keycloak user ID |
| username | VARCHAR(255) | UNIQUE, NOT NULL | Username |
| email | VARCHAR(255) | | Email address |
| display_name | VARCHAR(255) | | Display name |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |
| updated_at | TIMESTAMP TZ | DEFAULT NOW() | Last update |

---

### user_roles

User role assignments (composite primary key).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| user_id | UUID | PK, FK → users | User reference |
| role | VARCHAR(50) | PK | Role name |

**Valid Roles**: `admin`, `architect`, `developer`, `infra_engineer`, `user`

---

### user_tokens

OAuth tokens for external services.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Token ID |
| user_id | UUID | FK → users | User reference |
| service | VARCHAR(100) | NOT NULL | Service name (gitea, sharepoint) |
| access_token | TEXT | NOT NULL | OAuth access token |
| refresh_token | TEXT | | OAuth refresh token |
| expires_at | TIMESTAMP TZ | | Token expiration |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |

**Constraint**: UNIQUE(user_id, service) - one token per service per user

---

## Projects

### projects

Gitea repository references.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Project ID |
| name | VARCHAR(255) | NOT NULL | Display name |
| description | TEXT | | Project description |
| repo_name | VARCHAR(255) | NOT NULL | Gitea repo (org/repo) |
| repo_url | VARCHAR(512) | | Gitea web URL |
| clone_url | VARCHAR(512) | | Git clone URL |
| owner_id | UUID | FK → users | Project owner |
| status | VARCHAR(20) | DEFAULT 'active' | active, archived |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |
| updated_at | TIMESTAMP TZ | DEFAULT NOW() | Last update |

**Index**: `idx_projects_owner` on `owner_id`

---

## Sessions

### sessions

Conversation sessions with AI agents.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Session ID |
| user_id | UUID | FK → users | Session owner |
| project_id | UUID | FK → projects | Associated project |
| title | VARCHAR(500) | | Auto-generated title |
| status | VARCHAR(20) | DEFAULT 'active' | Session status |
| prompt_tokens | INTEGER | DEFAULT 0 | Total prompt tokens |
| completion_tokens | INTEGER | DEFAULT 0 | Total completion tokens |
| total_tokens | INTEGER | DEFAULT 0 | Total tokens used |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |
| updated_at | TIMESTAMP TZ | DEFAULT NOW() | Last update |

**Status Values**: `active`, `paused_approval`, `paused_hitl`, `completed`, `failed`

**Indexes**:
- `idx_sessions_user` on `user_id`
- `idx_sessions_status` on `status`

---

## Workflows & Steps

### workflows

Execution plans created by the planner agent.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Workflow ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| name | VARCHAR(255) | | Plan name |
| status | VARCHAR(20) | DEFAULT 'pending' | Workflow status |
| current_step | INTEGER | DEFAULT 0 | Current step index |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |

**Status Values**: `pending`, `running`, `paused`, `completed`, `failed`

**Index**: `idx_workflows_session` on `session_id`

---

### workflow_steps

Individual steps within a workflow.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Step ID |
| workflow_id | UUID | FK → workflows CASCADE | Parent workflow |
| step_index | INTEGER | NOT NULL | Step order (0, 1, 2...) |
| agent_id | VARCHAR(100) | NOT NULL | Agent to execute |
| description | TEXT | | Step description |
| status | VARCHAR(20) | DEFAULT 'pending' | Step status |
| result_summary | TEXT | | Execution result |
| started_at | TIMESTAMP TZ | | Start time |
| completed_at | TIMESTAMP TZ | | Completion time |

**Status Values**: `pending`, `running`, `waiting_approval`, `completed`, `failed`, `skipped`

**Index**: `idx_workflow_steps_workflow` on `workflow_id`

---

## Agent Runs

### agent_runs

Individual agent executions within a session.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Run ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| workflow_step_id | UUID | FK → workflow_steps | Associated step |
| agent_id | VARCHAR(100) | NOT NULL | Agent name |
| parent_run_id | UUID | FK → agent_runs | Parent run (context chain) |
| status | VARCHAR(20) | DEFAULT 'running' | Run status |
| iteration_count | INTEGER | DEFAULT 0 | LLM call count |
| prompt_tokens | INTEGER | DEFAULT 0 | Tokens for this run |
| completion_tokens | INTEGER | DEFAULT 0 | Tokens for this run |
| total_tokens | INTEGER | DEFAULT 0 | Tokens for this run |
| started_at | TIMESTAMP TZ | DEFAULT NOW() | Start time |
| completed_at | TIMESTAMP TZ | | Completion time |

**Status Values**: `running`, `paused_tool`, `paused_hitl`, `completed`, `failed`

**Indexes**:
- `idx_agent_runs_session` on `session_id`
- `idx_agent_runs_parent` on `parent_run_id`

**Key Concept**: Messages are linked to `agent_run_id` for agent isolation. By default, agents only see their own messages.

---

## Messages

### messages

Conversation messages (user, assistant, system, tool).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Message ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| agent_run_id | UUID | FK → agent_runs | Associated agent run |
| role | VARCHAR(20) | NOT NULL | Message role |
| content | TEXT | NOT NULL | Message content |
| agent_id | VARCHAR(100) | | Agent name (for assistant) |
| tool_name | VARCHAR(200) | | Tool name (for tool) |
| tool_call_id | VARCHAR(100) | | Tool call reference |
| sequence_number | INTEGER | NOT NULL | Global order |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |

**Role Values**: `user`, `assistant`, `system`, `tool`

**Indexes**:
- `idx_messages_session` on `session_id`
- `idx_messages_agent_run` on `agent_run_id`
- `idx_messages_sequence` on `(session_id, sequence_number)`

---

## Tool Calls

### tool_calls

MCP tool invocations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Tool call ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| agent_run_id | UUID | FK → agent_runs | Agent that called |
| mcp_server | VARCHAR(100) | NOT NULL | MCP server (coding, docker) |
| tool_name | VARCHAR(200) | NOT NULL | Tool name |
| status | VARCHAR(20) | DEFAULT 'pending' | Execution status |
| result | TEXT | | Execution result |
| error_message | TEXT | | Error if failed |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |
| executed_at | TIMESTAMP TZ | | Execution time |

**Status Values**: `pending`, `executing`, `completed`, `failed`

**Indexes**:
- `idx_tool_calls_session` on `session_id`
- `idx_tool_calls_agent_run` on `agent_run_id`

---

### tool_call_arguments

Normalized tool arguments (one row per argument).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| tool_call_id | UUID | PK, FK → tool_calls CASCADE | Parent tool call |
| arg_name | VARCHAR(100) | PK | Argument name |
| arg_value | TEXT | | Argument value |

**Design**: Fully normalized - no JSON. Enables querying by specific arguments.

---

## Approvals

### approvals

Authorization gates for MCP tools and workflow steps.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Approval ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| agent_run_id | UUID | FK → agent_runs | Requesting agent |
| tool_call_id | UUID | FK → tool_calls | For tool approvals |
| workflow_step_id | UUID | FK → workflow_steps | For step approvals |
| approval_type | VARCHAR(20) | NOT NULL | Approval type |
| mcp_server | VARCHAR(100) | | MCP server name |
| tool_name | VARCHAR(200) | | Tool name |
| title | VARCHAR(500) | | Human-readable title |
| description | TEXT | | Detailed description |
| required_role | VARCHAR(50) | | Role required to approve |
| danger_level | VARCHAR(20) | | Risk level |
| status | VARCHAR(20) | DEFAULT 'pending' | Approval status |
| resolved_by | UUID | FK → users | User who resolved |
| resolved_at | TIMESTAMP TZ | | Resolution time |
| rejection_reason | TEXT | | Rejection reason |
| arguments | JSON | | Tool arguments (for execution) |
| agent_state | JSON | | Agent state (for resumption) |
| agent_id | VARCHAR(100) | | Agent that requested |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |

**Approval Types**: `tool_call`, `workflow_step`

**Status Values**: `pending`, `approved`, `rejected`

**Danger Levels**: `low`, `medium`, `high`

**Indexes**:
- `idx_approvals_session` on `session_id`
- `idx_approvals_status` on `status`

**Key Feature**: `agent_state` JSON preserves where the agent paused, enabling seamless resumption after approval.

---

## HITL Questions

### hitl_questions

Human-in-the-loop questions from agents.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Question ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| agent_run_id | UUID | FK → agent_runs | Asking agent |
| agent_id | VARCHAR(50) | | Agent name |
| question | TEXT | NOT NULL | Question text |
| question_type | VARCHAR(20) | DEFAULT 'text' | Question type |
| status | VARCHAR(20) | DEFAULT 'pending' | Question status |
| answer | TEXT | | User's answer |
| answered_at | TIMESTAMP TZ | | Answer time |
| agent_state | JSON | | Agent state (for resumption) |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |

**Question Types**: `text`, `single_choice`, `multiple_choice`

**Status Values**: `pending`, `answered`

**Indexes**:
- `idx_hitl_questions_session` on `session_id`
- `idx_hitl_questions_status` on `status`

**Key Feature**: `agent_state` JSON preserves where the agent paused, enabling seamless resumption after user answers.

---

### hitl_question_choices

Choices for multiple-choice questions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| question_id | UUID | PK, FK → hitl_questions CASCADE | Parent question |
| choice_index | INTEGER | PK | Choice order (0, 1, 2...) |
| choice_text | VARCHAR(500) | NOT NULL | Choice text |
| is_selected | BOOLEAN | DEFAULT FALSE | Selected in answer |

---

## Workspaces

### workspaces

Git workspace references for sessions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Workspace ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| project_id | UUID | FK → projects | Associated project |
| branch | VARCHAR(255) | DEFAULT 'main' | Git branch |
| local_path | VARCHAR(512) | | Filesystem path |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |

**Index**: `idx_workspaces_session` on `session_id`

---

## Builds & Deployments

### builds

Docker build records.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Build ID |
| project_id | UUID | FK → projects CASCADE | Parent project |
| session_id | UUID | FK → sessions | Creating session |
| branch | VARCHAR(255) | DEFAULT 'main' | Git branch |
| status | VARCHAR(20) | DEFAULT 'pending' | Build status |
| is_preview | BOOLEAN | DEFAULT FALSE | Preview vs main build |
| port | INTEGER | | Host port allocated |
| container_name | VARCHAR(255) | | Docker container name |
| app_url | VARCHAR(512) | | Application URL |
| build_logs | TEXT | | Build output logs |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |

**Status Values**: `pending`, `building`, `built`, `running`, `stopped`, `failed`

**Index**: `idx_builds_project` on `project_id`

---

### deployments

Running container instances.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Deployment ID |
| build_id | UUID | FK → builds | Source build |
| project_id | UUID | FK → projects CASCADE | Parent project |
| container_name | VARCHAR(255) | | Docker container name |
| container_id | VARCHAR(100) | | Docker container ID |
| host_port | INTEGER | | Exposed port |
| app_url | VARCHAR(512) | | Application URL |
| status | VARCHAR(20) | DEFAULT 'starting' | Deployment status |
| is_preview | BOOLEAN | DEFAULT TRUE | Preview deployment |
| started_at | TIMESTAMP TZ | DEFAULT NOW() | Start time |
| stopped_at | TIMESTAMP TZ | | Stop time |

**Status Values**: `starting`, `running`, `stopped`, `failed`

**Indexes**:
- `idx_deployments_project` on `project_id`
- `idx_deployments_status` on `status`

---

## LLM Calls

### llm_calls

LLM API call records for debugging and cost tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Call ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| agent_run_id | UUID | FK → agent_runs | Calling agent |
| provider | VARCHAR(50) | NOT NULL | LLM provider |
| model | VARCHAR(100) | NOT NULL | Model name |
| prompt_tokens | INTEGER | NOT NULL | Prompt tokens |
| completion_tokens | INTEGER | NOT NULL | Completion tokens |
| total_tokens | INTEGER | NOT NULL | Total tokens |
| duration_ms | INTEGER | | Call duration (ms) |
| request_messages | JSON | | Full request payload |
| response_content | TEXT | | Response text |
| response_tool_calls | JSON | | Tool calls in response |
| tools_provided | JSON | | Available tools |
| created_at | TIMESTAMP TZ | DEFAULT NOW() | Creation time |

**Providers**: `deepinfra`, `zai`, `openai`

**Indexes**:
- `idx_llm_calls_session` on `session_id`
- `idx_llm_calls_agent_run` on `agent_run_id`

**Note**: JSON columns used here for debugging data only - not business logic.

---

## Session Events

### session_events

Unified timeline of all session activity.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Event ID |
| session_id | UUID | FK → sessions CASCADE | Parent session |
| event_type | VARCHAR(50) | NOT NULL | Event type |
| agent_id | VARCHAR(100) | | Agent that triggered |
| title | VARCHAR(500) | | Human-readable title |
| tool_name | VARCHAR(200) | | Tool name (for tool events) |
| agent_run_id | UUID | FK → agent_runs | For drill-down |
| tool_call_id | UUID | FK → tool_calls | For drill-down |
| approval_id | UUID | FK → approvals | For drill-down |
| hitl_question_id | UUID | FK → hitl_questions | For drill-down |
| event_data | JSON | | Variable metadata |
| timestamp | TIMESTAMP TZ | DEFAULT NOW() | Event time |

**Event Types**:
- `agent_started`, `agent_completed`
- `tool_call`, `tool_result`
- `approval_pending`, `approval_granted`, `approval_rejected`
- `hitl_question`, `hitl_answered`
- `deployment_started`, `deployment_complete`
- `error`

**Indexes**:
- `idx_session_events_session` on `session_id`
- `idx_session_events_timestamp` on `(session_id, timestamp)`
- `idx_session_events_type` on `event_type`

**Design**: Single source of truth for session timeline. Denormalized for display performance with references for drill-down.

---

## Relationships Diagram

```
users
  ├── user_roles (1:N)
  ├── user_tokens (1:N)
  ├── projects (1:N, owner)
  └── sessions (1:N)

projects
  ├── sessions (1:N)
  ├── workspaces (1:N)
  ├── builds (1:N)
  └── deployments (1:N)

sessions
  ├── workflows (1:N)
  ├── agent_runs (1:N)
  ├── messages (1:N)
  ├── tool_calls (1:N)
  ├── approvals (1:N)
  ├── hitl_questions (1:N)
  ├── workspaces (1:N)
  ├── llm_calls (1:N)
  └── session_events (1:N)

workflows
  └── workflow_steps (1:N, CASCADE)

agent_runs
  ├── messages (1:N)
  ├── tool_calls (1:N)
  ├── approvals (1:N)
  ├── hitl_questions (1:N)
  ├── llm_calls (1:N)
  └── agent_runs (self-reference, parent)

tool_calls
  ├── tool_call_arguments (1:N, CASCADE)
  └── approvals (1:1)

hitl_questions
  └── hitl_question_choices (1:N, CASCADE)

builds
  └── deployments (1:N)
```

---

## Indexes

### User & Project Indexes

| Table | Index | Columns | Purpose |
|-------|-------|---------|---------|
| projects | idx_projects_owner | owner_id | Find projects by owner |

### Session Indexes

| Table | Index | Columns | Purpose |
|-------|-------|---------|---------|
| sessions | idx_sessions_user | user_id | Find sessions by user |
| sessions | idx_sessions_status | status | Filter by status |
| workflows | idx_workflows_session | session_id | Get workflow for session |
| workflow_steps | idx_workflow_steps_workflow | workflow_id | Get steps for workflow |
| workspaces | idx_workspaces_session | session_id | Get workspace for session |

### Agent & Message Indexes

| Table | Index | Columns | Purpose |
|-------|-------|---------|---------|
| agent_runs | idx_agent_runs_session | session_id | Get runs for session |
| agent_runs | idx_agent_runs_parent | parent_run_id | Context chain lookup |
| messages | idx_messages_session | session_id | Get messages for session |
| messages | idx_messages_agent_run | agent_run_id | Get messages for run |
| messages | idx_messages_sequence | (session_id, sequence_number) | Ordered retrieval |

### Tool & Approval Indexes

| Table | Index | Columns | Purpose |
|-------|-------|---------|---------|
| tool_calls | idx_tool_calls_session | session_id | Get calls for session |
| tool_calls | idx_tool_calls_agent_run | agent_run_id | Get calls for agent |
| approvals | idx_approvals_session | session_id | Get approvals for session |
| approvals | idx_approvals_status | status | Find pending approvals |
| hitl_questions | idx_hitl_questions_session | session_id | Get questions for session |
| hitl_questions | idx_hitl_questions_status | status | Find pending questions |

### Build & Deployment Indexes

| Table | Index | Columns | Purpose |
|-------|-------|---------|---------|
| builds | idx_builds_project | project_id | Get builds for project |
| deployments | idx_deployments_project | project_id | Get deployments for project |
| deployments | idx_deployments_status | status | Find running deployments |

### LLM & Event Indexes

| Table | Index | Columns | Purpose |
|-------|-------|---------|---------|
| llm_calls | idx_llm_calls_session | session_id | Get calls for session |
| llm_calls | idx_llm_calls_agent_run | agent_run_id | Get calls for agent |
| session_events | idx_session_events_session | session_id | Get events for session |
| session_events | idx_session_events_timestamp | (session_id, timestamp) | Timeline queries |
| session_events | idx_session_events_type | event_type | Filter by type |

---

## Enums & Status Values

### User Roles

| Role | Description |
|------|-------------|
| admin | Full system access |
| architect | Can approve architecture decisions |
| developer | Can approve code and deployments |
| infra_engineer | Can approve infrastructure changes |
| user | Basic access |

### Session Status

| Status | Description |
|--------|-------------|
| active | Currently executing |
| paused_approval | Waiting for approval |
| paused_hitl | Waiting for user answer |
| completed | Successfully finished |
| failed | Error occurred |

### Workflow Status

| Status | Description |
|--------|-------------|
| pending | Not started |
| running | Currently executing |
| paused | Waiting for input |
| completed | All steps done |
| failed | Error occurred |

### Workflow Step Status

| Status | Description |
|--------|-------------|
| pending | Not started |
| running | Currently executing |
| waiting_approval | Needs approval |
| completed | Successfully finished |
| failed | Error occurred |
| skipped | Bypassed |

### Agent Run Status

| Status | Description |
|--------|-------------|
| running | Currently executing |
| paused_tool | Waiting for tool approval |
| paused_hitl | Waiting for user answer |
| completed | Successfully finished |
| failed | Error occurred |

### Tool Call Status

| Status | Description |
|--------|-------------|
| pending | Not executed yet |
| executing | Currently running |
| completed | Successfully finished |
| failed | Error occurred |

### Approval Status

| Status | Description |
|--------|-------------|
| pending | Awaiting decision |
| approved | Granted |
| rejected | Denied |

### Build Status

| Status | Description |
|--------|-------------|
| pending | Not started |
| building | Docker build in progress |
| built | Image built, not running |
| running | Container is running |
| stopped | Container stopped |
| failed | Build or run failed |

### Deployment Status

| Status | Description |
|--------|-------------|
| starting | Container starting |
| running | Container is running |
| stopped | Container stopped |
| failed | Deployment failed |

---

## CRUD Operations

All CRUD operations are in `druppie/db/crud.py`.

### User Operations

```python
get_or_create_user(db, user_id, username, email, display_name, roles)
get_user(db, user_id)
get_user_roles(db, user_id)
get_users_by_role(db, role)
```

### Session Operations

```python
create_session(db, user_id, project_id=None, title=None, session_id=None)
get_session(db, session_id)
update_session(db, session_id, **kwargs)  # status, title, project_id
update_session_tokens(db, session_id, prompt_tokens, completion_tokens)
list_sessions(db, user_id=None, status=None, limit=50, offset=0)
count_sessions(db, user_id=None, status=None)
```

### Workflow Operations

```python
create_workflow(db, session_id, name, steps)
get_workflow(db, workflow_id)
get_workflow_for_session(db, session_id)
update_workflow(db, workflow_id, **kwargs)  # status, current_step
update_workflow_step(db, step_id, **kwargs)  # status, result_summary, timestamps
```

### Agent Run Operations

```python
create_agent_run(db, session_id, agent_id, workflow_step_id=None, parent_run_id=None)
get_agent_run(db, run_id)
get_active_agent_run(db, session_id)
update_agent_run(db, run_id, **kwargs)  # status, iteration_count, completed_at
update_agent_run_tokens(db, run_id, prompt_tokens, completion_tokens)
```

### Message Operations

```python
create_message(db, session_id, role, content, agent_run_id=None, agent_id=None, tool_name=None, tool_call_id=None)
get_messages_for_session(db, session_id)
get_messages_for_agent_run(db, agent_run_id)
```

### Tool Call Operations

```python
create_tool_call(db, session_id, agent_run_id, mcp_server, tool_name, arguments)
get_tool_call(db, tool_call_id)
update_tool_call(db, tool_call_id, **kwargs)  # status, result, error_message
```

### Approval Operations

```python
create_approval(db, session_id, agent_run_id, approval_type, **kwargs)
get_approval(db, approval_id)
get_pending_approval_for_tool_call(db, tool_call_id)
update_approval(db, approval_id, **kwargs)  # any field including agent_state
resolve_approval(db, approval_id, status, resolved_by, rejection_reason=None)
list_pending_approvals(db, required_role=None)
list_approvals(db, session_id=None, status=None)
```

### HITL Question Operations

```python
create_hitl_question(db, session_id, agent_run_id, question, question_type='text', choices=None, agent_id=None)
get_hitl_question(db, question_id)
get_pending_hitl_question(db, session_id)
answer_hitl_question(db, question_id, answer, selected_choices=None)
update_hitl_question_state(db, question_id, agent_state)
list_pending_hitl_questions(db, user_id=None)
get_hitl_questions_for_session(db, session_id, status=None)
```

### Project Operations

```python
create_project(db, name, repo_name, owner_id, description=None, repo_url=None, clone_url=None)
get_project(db, project_id)
get_project_by_repo(db, repo_name)
list_projects(db, owner_id=None, status=None, limit=50, offset=0)
update_project(db, project_id, **kwargs)  # name, description, status
```

### Workspace Operations

```python
create_workspace(db, session_id, project_id, branch='main', local_path=None)
get_workspace(db, workspace_id)
get_workspace_for_session(db, session_id)
```

### Build Operations

```python
create_build(db, project_id, session_id=None, branch='main', is_preview=False)
get_build(db, build_id)
update_build(db, build_id, **kwargs)  # status, port, container_name, app_url, build_logs
list_builds(db, project_id=None, status=None, limit=50)
```

### Deployment Operations

```python
create_deployment(db, build_id, project_id, **kwargs)
get_deployment(db, deployment_id)
update_deployment(db, deployment_id, **kwargs)  # status, container_id, host_port, app_url
get_running_deployments(db, project_id=None)
```

### LLM Call Operations

```python
create_llm_call(db, session_id, agent_run_id, provider, model, prompt_tokens, completion_tokens, total_tokens, duration_ms=None, request_messages=None, response_content=None, response_tool_calls=None, tools_provided=None)
get_llm_calls_for_session(db, session_id)
```

### Session Event Operations

```python
create_session_event(db, session_id, event_type, agent_id=None, title=None, tool_name=None, agent_run_id=None, tool_call_id=None, approval_id=None, hitl_question_id=None, event_data=None)
get_session_events(db, session_id, event_type=None)
```

---

## Design Patterns

### 1. Message Isolation

Agents only see messages from their own `agent_run_id` by default:

```python
# Get messages for a specific agent run
messages = get_messages_for_agent_run(db, agent_run_id)

# To expand context, include parent runs
messages = db.query(Message).filter(
    Message.agent_run_id.in_([current_run_id, parent_run_id])
).order_by(Message.sequence_number).all()
```

### 2. State Preservation for Resumption

Both `approvals` and `hitl_questions` have `agent_state` JSON columns that save the exact point where an agent paused:

```python
# Save state when pausing
update_approval(db, approval_id, agent_state={
    "agent_id": "developer",
    "iteration": 3,
    "pending_tool_calls": [...],
    "context": {...}
})

# Restore state when resuming
approval = get_approval(db, approval_id)
agent_state = approval.agent_state  # Resume from here
```

### 3. Token Aggregation

Tokens are tracked at three levels for transparency:

```python
# Individual LLM calls
create_llm_call(db, ..., prompt_tokens=100, completion_tokens=50, total_tokens=150)

# Agent run totals
update_agent_run_tokens(db, run_id, prompt_tokens=100, completion_tokens=50)

# Session totals
update_session_tokens(db, session_id, prompt_tokens=100, completion_tokens=50)
```

### 4. Normalized Arguments

Tool arguments are stored in a normalized table, not JSON:

```python
# Creating a tool call with arguments
create_tool_call(db, session_id, agent_run_id, "coding", "write_file", {
    "path": "src/main.py",
    "content": "print('hello')"
})
# Creates one row in tool_calls and two rows in tool_call_arguments
```

### 5. Unified Event Timeline

All session activity is recorded in `session_events` for a single source of truth:

```python
# Record an event
create_session_event(db, session_id,
    event_type="tool_call",
    agent_id="developer",
    tool_name="coding:write_file",
    tool_call_id=tool_call.id,
    title="Writing src/main.py"
)

# Get timeline
events = get_session_events(db, session_id)
```

---

## Database Connection

Connection management is in `druppie/db/database.py`:

```python
from druppie.db.database import get_db, engine, SessionLocal

# FastAPI dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Direct usage
with SessionLocal() as db:
    session = get_session(db, session_id)
```

---

## Statistics

| Category | Count |
|----------|-------|
| Tables | 18 |
| Columns | ~180 |
| Foreign Keys | 35+ |
| Indexes | 25 |
| CRUD Functions | 45+ |
| JSON Columns | 8 (debug/state only) |
| Status Enums | 9 |
