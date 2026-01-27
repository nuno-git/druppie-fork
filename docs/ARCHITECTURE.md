# Druppie Architecture & Data Flow Documentation

This document provides a complete overview of how data flows through the Druppie system, from user input to database persistence.

## Table of Contents

1. [System Overview](#system-overview)
2. [Database Schema](#database-schema)
3. [Data Flow Patterns](#data-flow-patterns)
4. [API Endpoints](#api-endpoints)
5. [Debugging Guide](#debugging-guide)

---

## System Overview

Druppie is a governance platform where AI agents execute tasks through MCP (Model Context Protocol) tools with approval workflows.

### Key Principles

1. **Agents only act through MCP tools** - No direct file writes
2. **Normalized database** - No JSON columns for operational data
3. **Config in YAML files** - Agents and MCPs defined in YAML, not database
4. **Incremental persistence** - Data saved continuously, not just at end
5. **Resumable workflows** - Full state saved on pause for exact resumption

### Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         FastAPI Backend                          │
│  ┌─────────────────┐   ┌─────────────────┐   ┌───────────────┐  │
│  │   API Routes    │   │   Main Loop     │   │  MCP Client   │  │
│  │  /api/chat      │──▶│  (LangGraph)    │──▶│  HTTP calls   │  │
│  │  /api/approvals │   │  process_msg()  │   │  to MCP svcs  │  │
│  └─────────────────┘   └─────────────────┘   └───────────────┘  │
│           │                    │                     │           │
│           ▼                    ▼                     ▼           │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    PostgreSQL Database                       ││
│  │  sessions │ workflows │ agent_runs │ messages │ approvals   ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
     │  MCP Coding  │  │  MCP Docker  │  │  MCP HITL    │
     │  Port 9001   │  │  Port 9002   │  │  Port 9003   │
     │  File/Git    │  │  Containers  │  │  Questions   │
     └──────────────┘  └──────────────┘  └──────────────┘
```

---

## Database Schema

### Entity Relationship Diagram

```
┌─────────┐     ┌─────────────┐     ┌──────────────┐
│  users  │────▶│   sessions  │────▶│   workflows  │
└─────────┘     └─────────────┘     └──────────────┘
     │                │                    │
     │                │                    ▼
     ▼                │            ┌──────────────────┐
┌────────────┐        │            │  workflow_steps  │
│ user_roles │        │            └──────────────────┘
└────────────┘        │                    │
                      ├────────────────────┤
                      │                    │
                      ▼                    ▼
              ┌──────────────┐     ┌──────────────┐
              │  agent_runs  │◀────│  agent_runs  │
              │              │     │ (parent_run) │
              └──────────────┘     └──────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│  messages  │ │ tool_calls │ │ llm_calls  │
└────────────┘ └────────────┘ └────────────┘
                     │
                     ▼
           ┌─────────────────────┐
           │ tool_call_arguments │
           └─────────────────────┘
```

### All Tables (24 total)

#### Core Execution Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `sessions` | Chat conversations | `id`, `user_id`, `project_id`, `status`, `title`, `total_tokens` |
| `workflows` | Execution plans | `id`, `session_id`, `name`, `status`, `current_step` |
| `workflow_steps` | Individual steps | `id`, `workflow_id`, `step_index`, `agent_id`, `status` |
| `agent_runs` | Agent executions | `id`, `session_id`, `agent_id`, `status`, `total_tokens` |
| `messages` | Chat history | `id`, `session_id`, `agent_run_id`, `role`, `content` |

#### Tool Execution Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `tool_calls` | MCP tool invocations | `id`, `agent_run_id`, `mcp_server`, `tool_name`, `status` |
| `tool_call_arguments` | Normalized tool args | `tool_call_id`, `arg_name`, `arg_value` |
| `llm_calls` | LLM requests (debug) | `id`, `agent_run_id`, `model`, `provider`, `tokens` |

#### Approval & HITL Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `approvals` | Approval requests | `id`, `session_id`, `tool_name`, `status`, `required_role`, `agent_state` |
| `hitl_questions` | User questions | `id`, `session_id`, `question`, `answer`, `agent_state` |
| `hitl_question_choices` | Question options | `question_id`, `choice_index`, `choice_text` |

#### Project & Build Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `projects` | Git repositories | `id`, `owner_id`, `name`, `repo_url`, `status` |
| `workspaces` | Local git sandboxes | `id`, `session_id`, `project_id`, `branch`, `local_path` |
| `builds` | Container builds | `id`, `project_id`, `status`, `container_name`, `app_url` |
| `deployments` | Deployment records | `id`, `build_id`, `status`, `host_port` |

#### Event & User Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `session_events` | Execution timeline | `id`, `session_id`, `event_type`, `agent_id`, `timestamp` |
| `users` | User accounts | `id`, `username`, `email` |
| `user_roles` | Role assignments | `user_id`, `role` |
| `user_tokens` | OBO tokens | `user_id`, `service`, `access_token` |

### Session Status Values

| Status | Meaning |
|--------|---------|
| `active` | Currently executing |
| `paused_approval` | Waiting for MCP tool approval |
| `paused_hitl` | Waiting for user to answer question |
| `completed` | Successfully finished |
| `failed` | Error occurred |
| `cancelled` | User cancelled |

### Agent Run Status Values

| Status | Meaning |
|--------|---------|
| `running` | Currently executing |
| `paused_tool` | Waiting for MCP tool approval |
| `paused_hitl` | Waiting for HITL answer |
| `completed` | Successfully finished |
| `failed` | Error occurred |

---

## Data Flow Patterns

### 1. Session Lifecycle

```
User sends message
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 1. CREATE SESSION                                             │
│    - create_session(user_id, project_id, title)               │
│    - Session.status = "active"                                │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 2. INITIALIZE WORKSPACE                                       │
│    - create_workspace(session_id, project_id, branch)         │
│    - Clone/init git repository                                │
│    - Set workspace context in ExecutionContext                │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 3. RUN ROUTER AGENT                                           │
│    - create_agent_run(session_id, agent_id="router")          │
│    - Classify intent: simple | clarification | planning       │
│    - create_llm_call() for each LLM request                   │
│    - update_agent_run_tokens()                                │
│    - update_session_tokens()                                  │
└───────────────────────────────────────────────────────────────┘
        │
        ├─── simple_response ───▶ Return and complete
        │
        ├─── needs_clarification ───▶ HITL question (pause)
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 4. RUN PLANNER AGENT (if needs_planning)                      │
│    - create_agent_run(agent_id="planner")                     │
│    - Generate workflow: [architect, developer, deployer]      │
│    - create_workflow(session_id, name)                        │
│    - create_workflow_step() for each step                     │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 5. EXECUTE WORKFLOW STEPS                                     │
│    For each step:                                             │
│    - update_workflow_step(status="running")                   │
│    - create_agent_run(agent_id=step.agent_id)                 │
│    - Agent runs, may call MCP tools                           │
│    - If tool needs approval: PAUSE (see Approval Flow)        │
│    - If agent asks HITL: PAUSE (see HITL Flow)                │
│    - On completion: update_workflow_step(status="completed")  │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ 6. COMPLETE SESSION                                           │
│    - update_workflow(status="completed")                      │
│    - update_session(status="completed")                       │
│    - Final token aggregation                                  │
└───────────────────────────────────────────────────────────────┘
```

### 2. MCP Tool Approval Flow

```
Agent calls MCP tool
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ MCP Client checks approval rules                              │
│ (from mcp_config.yaml + agent approval_overrides)             │
│                                                               │
│ if requires_approval:                                         │
│    - create_approval(                                         │
│        session_id, tool_name, mcp_server,                     │
│        required_role, arguments, status="pending"             │
│      )                                                        │
│    - Return {status: "paused", approval_id: UUID}             │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ Agent pauses, returns to loop.py                              │
│ - update_approval() with agent_state JSON                     │
│ - update_agent_run(status="paused_tool")                      │
│ - update_session(status="paused_approval")                    │
│ - _persist_agent_data() saves LLM calls to database           │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
    [User approves in UI]
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ POST /api/approvals/{id}/approve                              │
│ - Check user has required_role                                │
│ - Execute the MCP tool                                        │
│ - update_approval(status="approved", resolved_by, resolved_at)│
│ - If docker:run success: create_build_record()                │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ resume_from_step_approval()                                   │
│ - Get agent_state from approval record                        │
│ - Restore messages, iteration count, context                  │
│ - Call Agent.resume_from_approval(tool_result)                │
│ - Agent continues from exact pause point                      │
└───────────────────────────────────────────────────────────────┘
```

### 3. HITL Question Flow

```
Agent calls hitl_ask_question
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ Built-in HITL tool (not MCP)                                  │
│ - create_hitl_question(                                       │
│     session_id, agent_id, question, question_type             │
│   )                                                           │
│ - If choices: create_hitl_question_choices()                  │
│ - Return {status: "paused", question_id: UUID}                │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ Agent pauses, returns to loop.py                              │
│ - update_hitl_question_state() with agent_state JSON          │
│ - update_agent_run(status="paused_hitl")                      │
│ - update_session(status="paused_hitl")                        │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
    [User answers in UI]
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ POST /api/questions/{id}/answer                               │
│ - answer_hitl_question(question_id, answer, selected_choices) │
│ - update_hitl_question(status="answered")                     │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ resume_from_question_answer()                                 │
│ - Get agent_state from hitl_question record                   │
│ - Restore messages, iteration count, context                  │
│ - Append answer to clarifications                             │
│ - Call Agent.resume(answer)                                   │
│ - Agent continues with answer as tool_response                │
└───────────────────────────────────────────────────────────────┘
```

### 4. Token Tracking Flow

Tokens are tracked at 4 levels with aggregation:

```
┌─────────────────────────────────────────────────────────────────┐
│ Level 1: LLM Response                                           │
│ - LLM returns: {prompt_tokens: 100, completion_tokens: 50}      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Level 2: ExecutionContext (in-memory)                           │
│ - exec_ctx.add_llm_call() extracts tokens                       │
│ - Accumulates: exec_ctx.prompt_tokens += 100                    │
│ - Stores in: exec_ctx.llm_calls[i].usage                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Level 3: Agent Run (database)                                   │
│ - _persist_agent_data() called on agent complete/pause          │
│ - For each llm_call: create_llm_call() record                   │
│ - update_agent_run_tokens(agent.prompt, agent.completion)       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Level 4: Session (database)                                     │
│ - update_session_tokens() called after each agent               │
│ - session.total_tokens += agent_run.total_tokens                │
│ - Available immediately in dashboard                            │
└─────────────────────────────────────────────────────────────────┘
```

**Key guarantee**: Tokens are saved after each agent completes OR pauses, never lost.

### 5. Message Isolation

Messages are isolated per `agent_run_id`:

```
Session (has many agents)
    │
    ├── Router (agent_run_id = #1)
    │   └── Messages: WHERE agent_run_id = #1
    │       - System prompt
    │       - User message
    │       - Assistant response
    │
    ├── Planner (agent_run_id = #2)
    │   └── Messages: WHERE agent_run_id = #2
    │       - System prompt (different from router)
    │       - User context
    │       - Plan response
    │
    └── Developer (agent_run_id = #3)
        └── Messages: WHERE agent_run_id = #3
            - System prompt (developer-specific)
            - Task from planner
            - Tool calls and results
```

**Pattern**: Each agent only sees its own messages by default. Use `parent_run_id` to allow context chaining if needed.

---

## API Endpoints

### Chat Endpoints

| Endpoint | Method | Description | DB Operations |
|----------|--------|-------------|---------------|
| `/api/chat` | POST | Send message, start/continue session | `create_session`, `create_agent_run`, `create_llm_call` |
| `/api/chat/{id}/status` | GET | Get session status | `get_session`, `list_pending_approvals` |
| `/api/chat/{id}/cancel` | POST | Cancel execution | `update_session(status="cancelled")` |

### Session Endpoints

| Endpoint | Method | Description | DB Operations |
|----------|--------|-------------|---------------|
| `/api/sessions` | GET | List sessions (paginated) | `query(Session)` with pagination |
| `/api/sessions/{id}` | GET | Get session details | `get_session`, `query(Message)`, `query(Approval)` |
| `/api/sessions/{id}/trace` | GET | Get execution trace | `query(SessionEvent)`, `query(LlmCall)` |
| `/api/sessions/{id}/delete` | DELETE | Delete session | Cascade deletes all related records |

### Approval Endpoints

| Endpoint | Method | Description | DB Operations |
|----------|--------|-------------|---------------|
| `/api/approvals` | GET | List pending approvals | `query(Approval)` filtered by role |
| `/api/approvals/{id}` | GET | Get approval details | `get_approval()` |
| `/api/approvals/{id}/approve` | POST | Approve tool execution | `update_approval`, execute MCP, `resume_from_step_approval` |

### Project Endpoints

| Endpoint | Method | Description | DB Operations |
|----------|--------|-------------|---------------|
| `/api/projects` | GET | List projects with stats | `query(Project)`, aggregate tokens |
| `/api/projects/{id}` | GET | Get project details | `get_project`, `get_builds` |
| `/api/projects/{id}/run` | POST | Build and run project | `create_build`, Docker operations |
| `/api/apps/running` | GET | List running apps | `query(Build).filter(status="running")` |

### Question Endpoints

| Endpoint | Method | Description | DB Operations |
|----------|--------|-------------|---------------|
| `/api/questions` | GET | List pending questions | `list_pending_hitl_questions` |
| `/api/questions/{id}/answer` | POST | Answer question | `answer_hitl_question`, `resume_from_question_answer` |

---

## Debugging Guide

### Where to Look for Issues

| Symptom | Check | Location |
|---------|-------|----------|
| Session stuck at "active" | Pending approvals | `approvals` table, status="pending" |
| Session stuck at "paused_hitl" | Unanswered questions | `hitl_questions` table, status="pending" |
| Agent not continuing | agent_state saved? | `approvals.agent_state` or `hitl_questions.agent_state` |
| Tokens showing 0 | Persistence timing | Check if `_persist_agent_data()` was called |
| Missing messages | Message isolation | Check `agent_run_id` matches |
| Approval lost | Workflow resumed wrong | Check `current_step` in workflow |

### Key Tables to Query

```sql
-- Find stuck sessions
SELECT id, status, title, created_at
FROM sessions
WHERE status IN ('active', 'paused_approval', 'paused_hitl')
ORDER BY created_at DESC;

-- Find pending approvals
SELECT a.id, a.tool_name, a.required_role, a.status, s.title as session
FROM approvals a
JOIN sessions s ON a.session_id = s.id
WHERE a.status = 'pending';

-- Check agent_state exists for resumption
SELECT id, tool_name,
       CASE WHEN agent_state IS NOT NULL THEN 'YES' ELSE 'NO' END as has_state
FROM approvals
WHERE status = 'pending';

-- Token breakdown by agent
SELECT ar.agent_id,
       SUM(ar.prompt_tokens) as prompt,
       SUM(ar.completion_tokens) as completion,
       SUM(ar.total_tokens) as total
FROM agent_runs ar
WHERE ar.session_id = '<session_id>'
GROUP BY ar.agent_id;

-- Execution timeline
SELECT event_type, agent_id, tool_name, timestamp
FROM session_events
WHERE session_id = '<session_id>'
ORDER BY timestamp;
```

### Debug Page

Access `/debug/:sessionId` in the frontend to see:
- Complete event timeline
- Per-agent token breakdown with costs
- Raw LLM calls with request/response
- Tool call parameters and results

### Common Issues & Fixes

#### 1. Agent asks same HITL question twice after approval

**Cause**: `agent_state` not saved to the NEW approval when agent pauses again.

**Check**: After first approval, if agent pauses for second approval:
```sql
SELECT id, agent_state IS NOT NULL as has_state
FROM approvals
WHERE session_id = '<session_id>'
ORDER BY created_at DESC;
```

**Fix**: In `resume_from_step_approval()`, save agent_state to new approval:
```python
if result.get("paused") and result.get("approval_id"):
    if result.get("agent_state"):
        update_approval(db, result["approval_id"], {"agent_state": result["agent_state"]})
```

#### 2. Tokens not showing in dashboard

**Cause**: `update_session_tokens()` only called at end, not during pause.

**Check**:
```sql
SELECT total_tokens FROM sessions WHERE id = '<session_id>';
-- Compare with:
SELECT SUM(total_tokens) FROM agent_runs WHERE session_id = '<session_id>';
```

**Fix**: Call `update_session_tokens()` in `_persist_agent_data()` (which runs on pause too).

#### 3. Debug page shows incomplete events

**Cause**: ExecutionContext created fresh on resume, doesn't restore previous events.

**Check**: Count events in database vs. shown:
```sql
SELECT COUNT(*) FROM session_events WHERE session_id = '<session_id>';
```

**Fix**: In resume functions, restore `workflow_events` from `session_events` table.

#### 4. Approval shows "Unknown tool"

**Cause**: `approval_type` not included in API response.

**Check**: Look at `approval_type` column:
```sql
SELECT id, tool_name, approval_type FROM approvals;
```

**Fix**: Include `approval_type` in `ApprovalResponse` model.

### Logging Locations

| Component | Log Source | What to Look For |
|-----------|------------|------------------|
| API | `docker logs druppie-new-backend` | Request/response, errors |
| Execution | Same as above | `agent_started`, `agent_completed`, `tool_call` |
| MCP Coding | `docker logs mcp-coding` | File operations, git commands |
| MCP Docker | `docker logs mcp-docker` | Container builds, port allocation |

### Key Log Patterns

```bash
# Find approval-related logs
docker logs druppie-new-backend 2>&1 | grep -i approval

# Find tool execution logs
docker logs druppie-new-backend 2>&1 | grep -i tool_call

# Find resumption logs
docker logs druppie-new-backend 2>&1 | grep -i resume

# Find token-related logs
docker logs druppie-new-backend 2>&1 | grep -i token
```

---

## File Locations

| Component | Path |
|-----------|------|
| Database Schema | `druppie/db/schema.sql` |
| SQLAlchemy Models | `druppie/db/models.py` |
| CRUD Operations | `druppie/db/crud.py` |
| Main Loop | `druppie/core/loop.py` |
| Agent Runtime | `druppie/agents/runtime.py` |
| Execution Context | `druppie/core/execution_context.py` |
| API Routes | `druppie/api/routes/*.py` |
| Agent Definitions | `druppie/agents/definitions/*.yaml` |
| MCP Config | `druppie/core/mcp_config.yaml` |

---

## Quick Reference

### Status Transitions

```
Session: active → paused_approval → active → paused_hitl → active → completed
                                                                  → failed
AgentRun: running → paused_tool → running → completed
                  → paused_hitl → running → failed
Workflow: pending → running → completed
                           → failed
WorkflowStep: pending → running → completed
                               → failed
                               → skipped
Approval: pending → approved
                  → rejected
HitlQuestion: pending → answered
```

### Foreign Key Cascade Behavior

| Relationship | On Delete |
|--------------|-----------|
| Session → Workflow | CASCADE (deletes workflow) |
| Session → AgentRuns | CASCADE (deletes runs) |
| Session → Messages | CASCADE (deletes messages) |
| Session → Approvals | CASCADE (deletes approvals) |
| Workflow → Steps | CASCADE (deletes steps) |
| AgentRun → LlmCalls | NO CASCADE (keeps for audit) |
| Project → Sessions | NO CASCADE (orphans session) |
