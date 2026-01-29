# Execution Layer

This module coordinates agent runs and tool execution. It's the "engine" that processes user messages.

## Architecture

```
User Message
     │
     ▼
Orchestrator.process_message()
     │
     ├─► Create Session
     │
     ├─► Get user's projects
     │
     ├─► Run Router (with projects injected)
     │         │
     │         └─► done(summary='{"intent": "...", ...}')
     │
     ├─► Parse intent from done() result
     │
     ├─► Handle project (create/select based on intent)
     │
     ├─► Create Planner (with intent injected)
     │
     └─► execute_pending_runs()
             │
             ▼
       Planner → Architect → Developer → Deployer
```

## Files

| File | Purpose |
|------|---------|
| `orchestrator.py` | Entry point. Runs router, handles intent, creates planner |
| `tool_executor.py` | Executes ALL tools (builtin, HITL, MCP) |
| `mcp_http.py` | Simple HTTP client for MCP servers |

## Key Concepts

### 1. Router Intent Classification

Router is special - it runs first and determines the flow:

```
Router receives:
- User's existing projects (injected)
- User's message

Router outputs (via done tool):
- intent: create_project | update_project | general_chat
- project_name: for create_project
- project_id: for update_project
```

### 2. Project Handling

Based on router's intent:
- `create_project`: Orchestrator creates new project, sets session.project_id
- `update_project`: Orchestrator sets session.project_id from router's choice
- `general_chat`: No project needed

### 3. Planner Context Injection

Planner receives intent in its prompt:
```
INTENT: create_project
PROJECT_ID: uuid-here

USER REQUEST:
Build a todo app
```

### 4. Pending Runs Pattern

After router and project handling, remaining agents use pending runs:

```python
# Planner creates architect, developer, deployer as pending runs
make_plan(steps=[
    {"agent_id": "architect", "prompt": "..."},
    {"agent_id": "developer", "prompt": "..."},
    {"agent_id": "deployer", "prompt": "..."},
])

# Orchestrator executes them in sequence
await execute_pending_runs(session_id)
```

### 5. ToolExecutor as Single Entry Point

ALL tool execution goes through ToolExecutor:

```python
status = await tool_executor.execute(tool_call_id)

# Handle status
if status == ToolCallStatus.WAITING_APPROVAL:
    # Approval record was created, execution paused
elif status == ToolCallStatus.WAITING_ANSWER:
    # Question record was created, execution paused
elif status == ToolCallStatus.COMPLETED:
    # Tool executed, result in tool_call.result
```

## Flow Examples

### Create Project Flow

```
User: "Build a todo app"

1. process_message() creates session
2. Get user's projects for injection
3. Run router with projects in prompt
4. Router classifies as create_project, calls done(summary='{"intent": "create_project", "project_name": "todo-app"}')
5. Orchestrator parses intent from done() result
6. Orchestrator creates project "todo-app"
7. Orchestrator creates planner with intent injected
8. execute_pending_runs() runs planner
9. Planner calls make_plan with architect → developer → deployer
10. execute_pending_runs() runs each in sequence
11. Session completed
```

### Update Project Flow

```
User: "Fix the bug in todo-app"

1. process_message() creates session
2. Get user's projects: [todo-app (id: uuid-123)]
3. Run router with projects in prompt
4. Router classifies as update_project, calls done(summary='{"intent": "update_project", "project_id": "uuid-123"}')
5. Orchestrator parses intent
6. Orchestrator sets session.project_id = uuid-123
7. Orchestrator creates planner with intent injected
8. execute_pending_runs() runs planner
9. Planner calls make_plan with developer → deployer (skips architect)
10. Session completed
```

### General Chat Flow

```
User: "What is Python?"

1. process_message() creates session
2. Get user's projects
3. Run router with projects in prompt
4. Router uses hitl_ask_question to answer: "Python is a programming language..."
5. Router calls done(summary='{"intent": "general_chat"}')
6. Orchestrator parses intent
7. Orchestrator creates planner with intent injected
8. execute_pending_runs() runs planner
9. Planner sees general_chat, calls done() immediately
10. Session completed
```

## Usage

```python
from druppie.execution import Orchestrator
from druppie.repositories import SessionRepository, ExecutionRepository, ProjectRepository, QuestionRepository

# Create orchestrator with repositories
orchestrator = Orchestrator(
    session_repo=SessionRepository(db),
    execution_repo=ExecutionRepository(db),
    project_repo=ProjectRepository(db),
    question_repo=QuestionRepository(db),
)

# Process a message
session_id = await orchestrator.process_message(
    message="Build a todo API",
    user_id=user.id,
)

# Resume after approval
await orchestrator.resume_after_approval(session_id, approval_id)

# Resume after HITL answer
await orchestrator.resume_after_answer(session_id, question_id, answer)
```
