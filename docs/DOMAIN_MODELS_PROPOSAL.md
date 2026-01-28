# Proposal: Clean Architecture for Core Layer

## Goal

Refactor the core layer (loop.py) to:
1. **Use repositories** for all database access (not crud.py)
2. **Work with domain models** throughout
3. **Split into focused modules** for maintainability
4. **Return session_id** (callers fetch SessionDetail to see result)

---

## Simplified Plan Storage

### Key Insight

Workflow steps ARE just agent runs that haven't started yet. Instead of separate Workflow/WorkflowStep tables, we use AgentRun with a `pending` status.

### Current (overcomplicated)
```
Session → Workflow → WorkflowStep → AgentRun
```

### New (simpler)
```
Session → AgentRun (status=pending for planned runs)
```

### How It Works

1. **Planner agent** gets a `make_plan` built-in tool
2. Tool creates AgentRun records with `status=pending`
3. Execution loop picks up pending runs in sequence order
4. No separate workflow tables needed

---

## AgentRun Changes

### Add PENDING status

```python
# domain/agent_run.py

class AgentRunStatus(str, Enum):
    """Agent run execution status."""
    PENDING = "pending"        # Created by planner, not started yet
    RUNNING = "running"        # Currently executing
    PAUSED_TOOL = "paused_tool"  # Waiting for tool approval
    PAUSED_HITL = "paused_hitl"  # Waiting for HITL answer
    COMPLETED = "completed"    # Finished successfully
    FAILED = "failed"          # Finished with error
```

### Add fields for planned runs

```python
# db/models.py - AgentRun model

class AgentRun(Base):
    __tablename__ = "agent_runs"

    # Existing fields
    id = Column(UUID, primary_key=True)
    session_id = Column(UUID, ForeignKey("sessions.id"))
    agent_id = Column(String(100), nullable=False)
    parent_run_id = Column(UUID, ForeignKey("agent_runs.id"))
    status = Column(String(20), default="running")
    iteration_count = Column(Integer, default=0)
    # ... tokens, timestamps, etc.

    # NEW: For pending runs created by planner
    planned_prompt = Column(Text)           # Task description for the agent
    sequence_number = Column(Integer)       # Execution order (0, 1, 2...)
```

### Database migration

```sql
-- Add columns to agent_runs table
ALTER TABLE agent_runs ADD COLUMN planned_prompt TEXT;
ALTER TABLE agent_runs ADD COLUMN sequence_number INTEGER;

-- Index for efficient pending run queries
CREATE INDEX idx_agent_runs_pending ON agent_runs (session_id, status, sequence_number)
    WHERE status = 'pending';
```

---

## The make_plan Tool

Built-in tool given to the planner agent:

```python
# agents/tools/plan.py

def make_plan(steps: list[dict]) -> str:
    """
    Create execution plan as pending agent runs.

    Called by planner agent to create the plan.

    Args:
        steps: List of steps, each with:
            - agent_id: Which agent to run (architect, developer, deployer)
            - prompt: Task description for the agent

    Example:
        make_plan([
            {"agent_id": "architect", "prompt": "Design the todo app architecture..."},
            {"agent_id": "developer", "prompt": "Implement based on architecture.md..."},
            {"agent_id": "deployer", "prompt": "Build and deploy the application..."}
        ])
    """
    session_id = get_current_session_id()

    for i, step in enumerate(steps):
        execution_repo.create_agent_run(
            session_id=session_id,
            agent_id=step["agent_id"],
            planned_prompt=step["prompt"],
            sequence_number=i,
            status=AgentRunStatus.PENDING,
        )

    execution_repo.commit()
    return f"Created plan with {len(steps)} steps"
```

### Planner agent config update

```yaml
# agents/definitions/planner.yaml

id: planner
name: Planner Agent
description: Creates execution plans from user intent

system_prompt: |
  You are the Planner Agent. Given a user's intent, create an execution plan
  using the make_plan tool.

  AVAILABLE AGENTS:
  - architect: Designs system architecture, creates architecture.md
  - developer: Writes code, creates files, implements features
  - deployer: Handles Docker build and deployment

  WORKFLOW FOR CREATE_PROJECT:
  Call make_plan with steps for architect → developer → deployer

  WORKFLOW FOR UPDATE_PROJECT:
  Call make_plan with developer step (and optionally deployer)

  Example for "build a todo app":

  make_plan([
    {"agent_id": "architect", "prompt": "Design architecture for a Todo app..."},
    {"agent_id": "developer", "prompt": "Implement the Todo app based on architecture.md..."},
    {"agent_id": "deployer", "prompt": "Build and deploy the Todo application..."}
  ])

# Planner gets the make_plan built-in tool
builtin_tools:
  - make_plan

model: glm-4
temperature: 0.1
```

---

## Execution Flow

### Process message

```python
# core/orchestrator.py

async def process_message(self, message: str, session_id: UUID) -> UUID:
    # 1. Run router
    router = Agent("router", session_id=session_id)
    router_result = await router.run(message)

    if router_result.paused:
        return session_id

    # 2. Run planner (creates pending AgentRuns via make_plan tool)
    planner = Agent("planner", session_id=session_id)
    await planner.run(f"User request: {message}")

    # 3. Execute pending runs
    await self.execute_pending_runs(session_id)

    return session_id
```

### Execute pending runs

```python
# core/orchestrator.py

async def execute_pending_runs(self, session_id: UUID) -> None:
    """Execute all pending agent runs in sequence."""

    while True:
        # Get next pending run
        next_run = self.execution_repo.get_next_pending(session_id)

        if not next_run:
            break  # All done

        # Update status to running
        self.execution_repo.update_status(next_run.id, AgentRunStatus.RUNNING)

        # Execute using existing Agent class
        agent = Agent(
            next_run.agent_id,
            session_id=session_id,
            agent_run_id=next_run.id,  # Reuse the pending run record
        )
        result = await agent.run(next_run.planned_prompt)

        if result.paused:
            # Agent paused for approval or HITL - stop here
            # Will resume later via resume_from_approval/resume_from_question
            return

        # Agent completed - loop continues to next pending run
```

### Resume after approval

```python
# core/orchestrator.py

async def resume_from_approval(self, session_id: UUID, approval_id: UUID) -> UUID:
    """Resume execution after approval."""

    # Get the paused agent run
    paused_run = self.execution_repo.get_paused_run(session_id)

    if paused_run:
        # Resume the agent
        agent = Agent(paused_run.agent_id, session_id=session_id)
        result = await agent.resume_from_approval(approval_id)

        if not result.paused:
            # Agent completed - continue with remaining pending runs
            await self.execute_pending_runs(session_id)

    return session_id
```

---

## Repository Changes

### ExecutionRepository additions

```python
# repositories/execution_repository.py

class ExecutionRepository(BaseRepository):
    """Combined repository for execution records."""

    # ... existing methods ...

    def get_next_pending(self, session_id: UUID) -> AgentRun | None:
        """Get next pending agent run for a session."""
        return (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == "pending",
            )
            .order_by(AgentRun.sequence_number)
            .first()
        )

    def get_pending_runs(self, session_id: UUID) -> list[AgentRunSummary]:
        """Get all pending runs (the 'plan') for a session."""
        runs = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status == "pending",
            )
            .order_by(AgentRun.sequence_number)
            .all()
        )
        return [self._to_summary(r) for r in runs]

    def get_paused_run(self, session_id: UUID) -> AgentRun | None:
        """Get the paused agent run for a session."""
        return (
            self.db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.status.in_(["paused_tool", "paused_hitl"]),
            )
            .first()
        )
```

### SessionRepository - building the chat list

```python
# repositories/session_repository.py

def get_detail(self, session_id: UUID) -> SessionDetail:
    """Get session with chat items in chronological order."""
    session = self.get_by_id(session_id)

    # Get messages
    messages = self.db.query(Message).filter(
        Message.session_id == session_id
    ).all()

    # Get agent runs
    agent_runs = self.db.query(AgentRun).filter(
        AgentRun.session_id == session_id
    ).all()

    # Combine into chat items and sort by created_at
    chat_items = []

    for msg in messages:
        chat_items.append(ChatItem(
            type=ChatItemType.MESSAGE,
            message=self._to_message_summary(msg),
            created_at=msg.created_at,
        ))

    for run in agent_runs:
        chat_items.append(ChatItem(
            type=ChatItemType.AGENT_RUN,
            agent_run=self._to_agent_run_summary(run),
            created_at=run.started_at or run.created_at,
        ))

    # Sort by time
    chat_items.sort(key=lambda x: x.created_at)

    return SessionDetail(
        id=session.id,
        # ... other fields ...
        chat=chat_items,
    )
```

---

## Domain Model Updates

### ChatItem (unified)

```python
# domain/session.py

class ChatItemType(str, Enum):
    """Type of chat item."""
    MESSAGE = "message"
    AGENT_RUN = "agent_run"

class ChatItem(BaseModel):
    """A chat item - either a message or an agent run."""
    type: ChatItemType

    # For messages (user input, assistant response)
    message: MessageSummary | None = None

    # For agent runs (pending, running, completed, paused...)
    agent_run: AgentRunSummary | None = None

    # For ordering
    created_at: datetime
```

### AgentRunSummary (updated)

```python
# domain/agent_run.py

class AgentRunSummary(BaseModel):
    """Agent run for list views."""
    id: UUID
    session_id: UUID
    agent_id: str
    status: AgentRunStatus

    # For pending runs (the plan)
    planned_prompt: str | None
    sequence_number: int | None

    # For completed runs
    iteration_count: int
    total_tokens: int
    started_at: datetime | None
    completed_at: datetime | None
```

### SessionDetail (simplified)

```python
# domain/session.py

class SessionDetail(BaseModel):
    """Full session with chat history."""
    id: UUID
    user_id: UUID | None
    project_id: UUID | None
    title: str | None
    status: SessionStatus

    # Everything in chronological order
    # Messages and agent runs (pending, running, completed) all together
    chat: list[ChatItem]

    # Token usage
    total_tokens: int

    created_at: datetime
    updated_at: datetime
```

### Frontend usage

```tsx
// Just iterate through chat items in order
{session.chat.map(item =>
    item.type === "message"
        ? <Message data={item.message} />
        : <AgentRun data={item.agent_run} />
)}
```

Pending agent runs appear in the chat at the position they were created (right after the planner ran), giving a natural timeline view.

---

## What Gets Deleted

No need for:
- `workflows` table
- `workflow_steps` table
- `WorkflowRepository`
- `WorkflowDetail`, `WorkflowStepSummary` domain models
- Workflow-related crud.py functions

---

## Current Problems (unchanged)

```
core/loop.py (2000+ lines)
├── Uses crud.py directly ❌
├── Returns arbitrary dicts ❌
├── Mixed responsibilities ❌
│   ├── Session management
│   ├── Workflow execution (simplified!)
│   ├── Agent running (use existing runtime.py)
│   ├── Approval handling
│   └── Question handling
└── No clear boundaries ❌
```

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           API LAYER                                  │
│                                                                      │
│   Routes receive/return domain models                               │
│   chat.py → SessionDetail (chat: list[ChatItem] in order)           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        SERVICE LAYER                                 │
│                                                                      │
│   SessionService, ApprovalService, QuestionService                  │
│   Coordinates repositories + core orchestrator                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────────────────┐
│   REPOSITORY LAYER      │     │         CORE LAYER (refactored)     │
│                         │     │                                     │
│   SessionRepository     │◄────┤   Orchestrator                      │
│   ApprovalRepository    │     │     │                               │
│   QuestionRepository    │     │     ├── execute_pending_runs()      │
│   ExecutionRepository   │     │     ├── resume_from_approval()      │
│   (AgentRun+ToolCall+   │     │     └── resume_from_question()      │
│    LLMCall combined)    │     │                                     │
│   MessageRepository     │     │   Uses existing Agent class from    │
│                         │     │   druppie/agents/runtime.py         │
│   All return domain     │     │                                     │
│   models                │     │   Planner uses make_plan tool to    │
│                         │     │   create pending AgentRuns          │
└─────────────────────────┘     └─────────────────────────────────────┘
```

---

## New Core Structure

```
druppie/core/
├── __init__.py
├── orchestrator.py       # Main entry point
│                         # process_message, execute_pending_runs
│                         # resume_from_approval, resume_from_question
│
├── mcp_client.py         # MCP tool calls (already exists)
├── execution_context.py  # Execution context (already exists)
└── config.py             # Settings (already exists)

druppie/agents/
├── runtime.py            # Agent class (already exists, use as-is)
├── tools/
│   └── plan.py           # make_plan built-in tool (NEW)
└── definitions/
    └── planner.yaml      # Updated to use make_plan tool
```

**Much simpler than before!** No separate session_manager, workflow_executor, etc.

---

## Migration Plan

### Phase 1: Database & Domain Models
1. Add `planned_prompt`, `sequence_number` to AgentRun model
2. Add `PENDING` to AgentRunStatus enum
3. Run migration
4. Update AgentRunSummary domain model

### Phase 2: Create make_plan Tool
1. Create `agents/tools/plan.py` with make_plan function
2. Update planner.yaml to use make_plan tool
3. Register make_plan as built-in tool in agent runtime

### Phase 3: Create Orchestrator
1. Create `core/orchestrator.py`
2. Implement `process_message`, `execute_pending_runs`
3. Implement `resume_from_approval`, `resume_from_question`

### Phase 4: Update Routes & Services
1. Update chat.py to use Orchestrator
2. SessionRepository builds chat list (messages + agent runs sorted by created_at)

### Phase 5: Cleanup
1. Delete Workflow/WorkflowStep models
2. Delete workflow crud functions
3. Delete old loop.py code

---

## File Changes Summary

| Action | File | Notes |
|--------|------|-------|
| UPDATE | `db/models.py` | Add planned_prompt, sequence_number to AgentRun |
| UPDATE | `domain/agent_run.py` | Add PENDING status, update AgentRunSummary |
| UPDATE | `domain/session.py` | Add ChatItem, SessionDetail.chat |
| CREATE | `agents/tools/plan.py` | make_plan built-in tool (~30 lines) |
| UPDATE | `agents/definitions/planner.yaml` | Use make_plan tool |
| UPDATE | `repositories/execution_repository.py` | Add get_next_pending, get_pending_runs |
| CREATE | `core/orchestrator.py` | Main entry point (~150 lines) |
| UPDATE | `api/routes/chat.py` | Use Orchestrator |
| DELETE | `db/models.py` | Remove Workflow, WorkflowStep |
| DELETE | `db/crud.py` | Remove workflow functions |

**Net result:** Simpler schema, less code, same functionality.

---

## Benefits

1. **Simpler mental model** - Plan = pending agent runs
2. **No extra tables** - Reuse AgentRun for planning
3. **Tool-based planning** - Planner uses make_plan like any other tool
4. **Easy to query** - Get plan = get pending runs for session
5. **Unified tracking** - All agent runs (planned or not) in one place
6. **Less code** - No workflow executor, just execute_pending_runs loop
