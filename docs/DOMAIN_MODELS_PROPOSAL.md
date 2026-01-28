# Proposal: Clean Architecture for Core Layer

## Goal

Refactor the core layer (loop.py) to:
1. **Use repositories** for all database access (not crud.py)
2. **Work with domain models** throughout
3. **Split into focused modules** for maintainability
4. **Return session_id** (callers fetch SessionDetail to see result)

## Analysis: How Plans Work Today

### Planner Agent Output

The planner agent (druppie/agents/definitions/planner.yaml) outputs JSON:

```json
{
  "name": "Build Todo App",
  "description": "Design, implement, and deploy a todo application",
  "steps": [
    {
      "id": "step_1",
      "type": "agent",
      "agent_id": "architect",
      "prompt": "Design the architecture..."
    },
    {
      "id": "step_2",
      "type": "agent",
      "agent_id": "developer",
      "prompt": "Implement the Todo application..."
    },
    {
      "id": "step_3",
      "type": "mcp",
      "tool": "docker:build",
      "inputs": {"context": "."}
    }
  ]
}
```

### Current Database Storage

The plan is stored in `workflows` and `workflow_steps` tables:

```
workflows:
  - id, session_id, name, status, current_step, created_at

workflow_steps:
  - id, workflow_id, step_index, agent_id, description, status,
    result_summary, started_at, completed_at
```

### What's Lost

Currently we lose some planner output:
- `step.id` - We generate our own UUIDs
- `step.type` - Not stored (assumed to be "agent")
- For MCP steps: `tool` and `inputs` - Not supported yet

### What We Need

1. **Domain models** for Workflow/WorkflowStep
2. **WorkflowRepository** to replace crud.py workflow functions
3. **Support for both step types** (agent + mcp)

---

## Current Problems

```
core/loop.py (2000+ lines)
├── Uses crud.py directly ❌
├── Returns arbitrary dicts ❌
├── Mixed responsibilities ❌
│   ├── Session management
│   ├── Workflow execution
│   ├── Agent running (ALREADY EXISTS in agents/runtime.py!)
│   ├── Approval handling
│   └── Question handling
└── No clear boundaries ❌
```

---

## Key Design Decisions

### 1. Use Existing Agent Runtime

**DO NOT** create an AgentRunner class. We already have `druppie/agents/runtime.py` with the `Agent` class that handles:
- Agent execution loop
- Tool calling
- HITL questions
- Resumption from approval/questions

The core layer should USE the Agent class, not duplicate it.

### 2. No WorkspaceRepository

Workspace operations are handled by the **coding MCP server**, not the backend. The backend only stores a workspace reference (session_id, project_id, local_path) for tracking.

### 3. Combined Execution Repository

Instead of separate repos for AgentRun, ToolCall, and LLMCall, use ONE `ExecutionRepository`:

```python
class ExecutionRepository(BaseRepository):
    """Handles all execution-related records."""

    # Agent runs
    def create_agent_run(self, session_id, agent_id, ...) -> AgentRun
    def update_agent_run_status(self, run_id, status) -> None
    def get_agent_run(self, run_id) -> AgentRunDetail

    # Tool calls (linked to agent run)
    def create_tool_call(self, agent_run_id, tool, args) -> ToolCall
    def update_tool_result(self, call_id, result, status) -> None

    # LLM calls (linked to agent run)
    def create_llm_call(self, agent_run_id, model, messages) -> LLMCall
    def update_llm_response(self, call_id, response, tokens) -> None
```

### 4. Add Workflow Domain Models

New domain models for plans/workflows:

```python
# domain/workflow.py

class WorkflowStepType(str, Enum):
    """Type of workflow step."""
    AGENT = "agent"
    MCP = "mcp"

class WorkflowStatus(str, Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"

class WorkflowStepStatus(str, Enum):
    """Step execution status."""
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class WorkflowStepSummary(BaseModel):
    """Workflow step for list views."""
    id: UUID
    step_index: int
    step_type: WorkflowStepType
    agent_id: str | None  # For agent steps
    tool_name: str | None  # For MCP steps (e.g., "docker:build")
    description: str
    status: WorkflowStepStatus
    result_summary: str | None

class WorkflowSummary(BaseModel):
    """Workflow for list views."""
    id: UUID
    session_id: UUID
    name: str
    status: WorkflowStatus
    current_step: int
    total_steps: int
    created_at: datetime

class WorkflowDetail(BaseModel):
    """Full workflow with steps."""
    id: UUID
    session_id: UUID
    name: str
    status: WorkflowStatus
    current_step: int
    steps: list[WorkflowStepSummary]
    created_at: datetime
```

---

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           API LAYER                                  │
│                                                                      │
│   Routes receive/return domain models                               │
│   chat.py → SessionDetail                                           │
│   approvals.py → ApprovalDetail                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        SERVICE LAYER                                 │
│                                                                      │
│   SessionService, ApprovalService, QuestionService, WorkflowService │
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
│   QuestionRepository    │     │     ├── SessionManager              │
│   WorkflowRepository    │     │     ├── WorkflowExecutor            │
│   ExecutionRepository   │     │     ├── ApprovalHandler             │
│   (AgentRun+ToolCall+   │     │     └── QuestionHandler             │
│    LLMCall combined)    │     │                                     │
│                         │     │   Uses existing Agent class from    │
│   All return domain     │     │   druppie/agents/runtime.py         │
│   models                │     │                                     │
└─────────────────────────┘     └─────────────────────────────────────┘
```

---

## New Core Structure

Split `loop.py` (2000 lines) into focused modules:

```
druppie/core/
├── __init__.py
├── orchestrator.py       # Main entry point (replaces MainLoop class)
│                         # ~200 lines - coordinates the flow
│
├── session_manager.py    # Session lifecycle
│                         # create_session, update_status, get_state
│                         # Uses SessionRepository
│
├── workflow_executor.py  # Executes workflow steps
│                         # create_from_plan(), execute_steps()
│                         # Uses WorkflowRepository
│                         # Uses Agent from agents/runtime.py
│
├── approval_handler.py   # Approval pause/resume
│                         # create_approval, resume_from_approval
│                         # Uses ApprovalRepository
│
├── question_handler.py   # HITL question pause/resume
│                         # create_question, resume_from_question
│                         # Uses QuestionRepository
│
├── mcp_client.py         # MCP tool calls (already exists)
├── execution_context.py  # Execution context (already exists)
└── config.py             # Settings (already exists)
```

**Note:** No `agent_runner.py` - we use existing `agents/runtime.py`!

---

## How Modules Work Together

### Example: process_message flow

```python
# core/orchestrator.py

class Orchestrator:
    """Main entry point for processing messages."""

    def __init__(
        self,
        session_manager: SessionManager,
        workflow_executor: WorkflowExecutor,
    ):
        self.session_manager = session_manager
        self.workflow_executor = workflow_executor

    async def process_message(
        self,
        message: str,
        session_id: UUID | None,
        user_id: UUID | None,
        project_id: UUID | None,
    ) -> UUID:
        """Process a user message.

        Returns:
            session_id - Caller fetches SessionDetail to see result
        """
        # 1. Create or get session
        session = self.session_manager.get_or_create(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
            title=message[:100],
        )

        # 2. Save user message
        self.session_manager.add_message(
            session_id=session.id,
            role="user",
            content=message,
        )

        # 3. Run router agent (uses Agent from runtime.py)
        from druppie.agents.runtime import Agent
        router = Agent("router", db=self.db, session_id=session.id)
        router_result = await router.run(message)

        # 4. If paused (approval/question), return session_id
        if router_result.paused:
            return session.id

        # 5. Run planner and create workflow
        planner = Agent("planner", db=self.db, session_id=session.id)
        plan_result = await planner.run(f"User request: {message}")

        plan = self._extract_plan(plan_result)
        workflow = self.workflow_executor.create_from_plan(session.id, plan)

        # 6. Execute workflow steps
        await self.workflow_executor.execute_steps(workflow)

        return session.id
```

### Example: WorkflowExecutor using Agent

```python
# core/workflow_executor.py

from druppie.agents.runtime import Agent

class WorkflowExecutor:
    """Executes workflow plans."""

    def __init__(
        self,
        workflow_repo: WorkflowRepository,
        execution_repo: ExecutionRepository,
    ):
        self.workflow_repo = workflow_repo
        self.execution_repo = execution_repo

    def create_from_plan(
        self,
        session_id: UUID,
        plan: dict,
    ) -> WorkflowDetail:
        """Create workflow from planner output."""
        workflow = self.workflow_repo.create(
            session_id=session_id,
            name=plan.get("name", "Execution Plan"),
        )

        for i, step in enumerate(plan.get("steps", [])):
            step_type = WorkflowStepType(step.get("type", "agent"))

            self.workflow_repo.add_step(
                workflow_id=workflow.id,
                step_index=i,
                step_type=step_type,
                agent_id=step.get("agent_id") if step_type == WorkflowStepType.AGENT else None,
                tool_name=step.get("tool") if step_type == WorkflowStepType.MCP else None,
                description=step.get("prompt", step.get("description", "")),
                tool_inputs=step.get("inputs") if step_type == WorkflowStepType.MCP else None,
            )

        self.workflow_repo.commit()
        return self.workflow_repo.get_detail(workflow.id)

    async def execute_steps(
        self,
        workflow: WorkflowDetail,
        start_from: int = 0,
    ) -> WorkflowDetail:
        """Execute workflow steps from a given index."""

        for step in workflow.steps[start_from:]:
            self.workflow_repo.update_step_status(step.id, WorkflowStepStatus.RUNNING)

            if step.step_type == WorkflowStepType.AGENT:
                # Use Agent class from runtime.py
                agent = Agent(
                    step.agent_id,
                    db=self.db,
                    session_id=workflow.session_id,
                    workflow_step_id=step.id,
                )
                result = await agent.run(step.description)

                if result.paused:
                    # Agent paused for approval or HITL
                    self.workflow_repo.update_step_status(
                        step.id,
                        WorkflowStepStatus.WAITING_APPROVAL
                    )
                    self.workflow_repo.update_status(
                        workflow.id,
                        WorkflowStatus.PAUSED,
                        current_step=step.step_index,
                    )
                    return self.workflow_repo.get_detail(workflow.id)

            else:  # MCP step
                # Direct MCP call (with approval if needed)
                result = await self._execute_mcp_step(step)

            self.workflow_repo.update_step_status(
                step.id,
                WorkflowStepStatus.COMPLETED,
                result_summary=str(result)[:500],
            )

        # All steps completed
        self.workflow_repo.update_status(workflow.id, WorkflowStatus.COMPLETED)
        return self.workflow_repo.get_detail(workflow.id)
```

---

## New Repositories Needed

### WorkflowRepository (NEW)

```python
# repositories/workflow_repository.py

class WorkflowRepository(BaseRepository):
    """Repository for workflow operations."""

    def create(self, session_id: UUID, name: str) -> Workflow:
        """Create a new workflow."""

    def add_step(
        self,
        workflow_id: UUID,
        step_index: int,
        step_type: WorkflowStepType,
        agent_id: str | None,
        tool_name: str | None,
        description: str,
        tool_inputs: dict | None = None,
    ) -> WorkflowStep:
        """Add a step to a workflow."""

    def get_by_id(self, workflow_id: UUID) -> Workflow | None:
        """Get workflow by ID."""

    def get_for_session(self, session_id: UUID) -> Workflow | None:
        """Get the active workflow for a session."""

    def get_detail(self, workflow_id: UUID) -> WorkflowDetail:
        """Get full workflow with steps (domain model)."""

    def update_status(
        self,
        workflow_id: UUID,
        status: WorkflowStatus,
        current_step: int | None = None,
    ) -> None:
        """Update workflow status."""

    def update_step_status(
        self,
        step_id: UUID,
        status: WorkflowStepStatus,
        result_summary: str | None = None,
    ) -> None:
        """Update step status and result."""
```

### ExecutionRepository (Combined)

```python
# repositories/execution_repository.py

class ExecutionRepository(BaseRepository):
    """Combined repository for execution records (agent_runs, tool_calls, llm_calls)."""

    # Agent runs
    def create_agent_run(
        self,
        session_id: UUID,
        agent_id: str,
        workflow_step_id: UUID | None = None,
        parent_run_id: UUID | None = None,
    ) -> AgentRun:
        """Create an agent run record."""

    def update_agent_run(
        self,
        run_id: UUID,
        status: str | None = None,
        iteration_count: int | None = None,
        tokens: dict | None = None,
    ) -> None:
        """Update agent run."""

    def get_agent_run_detail(self, run_id: UUID) -> AgentRunDetail:
        """Get agent run as domain model."""

    # Tool calls
    def create_tool_call(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        mcp_server: str,
        tool_name: str,
        arguments: dict,
    ) -> ToolCall:
        """Create a tool call record."""

    def update_tool_result(
        self,
        call_id: UUID,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update tool call result."""

    # LLM calls
    def create_llm_call(
        self,
        session_id: UUID,
        agent_run_id: UUID,
        provider: str,
        model: str,
        messages: list[dict],
    ) -> LLMCall:
        """Create an LLM call record."""

    def update_llm_response(
        self,
        call_id: UUID,
        response_content: str,
        response_tool_calls: list[dict] | None,
        tokens: dict,
        duration_ms: int,
    ) -> None:
        """Update LLM call response."""
```

### MessageRepository (NEW)

```python
# repositories/message_repository.py

class MessageRepository(BaseRepository):
    """Repository for session messages."""

    def create(
        self,
        session_id: UUID,
        role: str,
        content: str,
        agent_run_id: UUID | None = None,
        agent_id: str | None = None,
    ) -> Message:
        """Create a message."""

    def get_for_session(self, session_id: UUID) -> list[MessageSummary]:
        """Get all messages for a session."""

    def get_for_agent_run(self, agent_run_id: UUID) -> list[MessageSummary]:
        """Get messages for an agent run (for isolation)."""
```

---

## Database Schema Changes

Add `step_type` and `tool_inputs` to workflow_steps:

```sql
-- Add to workflow_steps table
ALTER TABLE workflow_steps ADD COLUMN step_type VARCHAR(20) DEFAULT 'agent';
ALTER TABLE workflow_steps ADD COLUMN tool_name VARCHAR(200);
ALTER TABLE workflow_steps ADD COLUMN tool_inputs JSONB;

-- Update constraint: either agent_id (for agent steps) or tool_name (for mcp steps)
ALTER TABLE workflow_steps ALTER COLUMN agent_id DROP NOT NULL;
ALTER TABLE workflow_steps ADD CONSTRAINT step_type_check
    CHECK (
        (step_type = 'agent' AND agent_id IS NOT NULL) OR
        (step_type = 'mcp' AND tool_name IS NOT NULL)
    );
```

---

## Migration Plan

### Phase 1: Add New Domain Models & Repositories
1. Create `domain/workflow.py` with WorkflowDetail, WorkflowStepSummary
2. Create `repositories/workflow_repository.py`
3. Create `repositories/execution_repository.py` (combined)
4. Create `repositories/message_repository.py`

### Phase 2: Create Core Modules
1. Create `core/session_manager.py`
2. Create `core/workflow_executor.py` (uses Agent from runtime.py)
3. Create `core/approval_handler.py`
4. Create `core/question_handler.py`
5. Create `core/orchestrator.py`

### Phase 3: Update Dependency Injection
1. Add repository dependencies in `deps.py`
2. Add core module dependencies
3. Wire everything together

### Phase 4: Migrate loop.py
1. Move code from loop.py to new modules one piece at a time
2. Each module uses repositories
3. Each module returns domain models (or UUIDs)
4. Keep loop.py working during migration (facade pattern)

### Phase 5: Update Routes
1. `chat.py` calls Orchestrator, fetches SessionDetail
2. `approvals.py` uses ApprovalHandler
3. `questions.py` uses QuestionHandler

### Phase 6: Cleanup
1. Delete old crud.py workflow functions (moved to WorkflowRepository)
2. Delete loop.py (replaced by orchestrator + modules)

---

## File Changes Summary

| Action | File | Lines |
|--------|------|-------|
| CREATE | `domain/workflow.py` | ~80 |
| CREATE | `repositories/workflow_repository.py` | ~100 |
| CREATE | `repositories/execution_repository.py` | ~120 |
| CREATE | `repositories/message_repository.py` | ~50 |
| CREATE | `core/session_manager.py` | ~100 |
| CREATE | `core/workflow_executor.py` | ~200 |
| CREATE | `core/approval_handler.py` | ~100 |
| CREATE | `core/question_handler.py` | ~100 |
| CREATE | `core/orchestrator.py` | ~200 |
| UPDATE | `api/deps.py` | Add new dependencies |
| UPDATE | `api/routes/chat.py` | Use Orchestrator |
| UPDATE | `db/models.py` | Add step_type, tool_inputs |
| DELETE | `core/loop.py` | -2000 (moved to modules) |
| UPDATE | `db/crud.py` | Remove workflow functions |

**Net change:** More files, but each is small and focused (~50-200 lines)

---

## Benefits

1. **Single Responsibility** - Each module does one thing
2. **No Duplication** - Uses existing Agent class from runtime.py
3. **Type Safe** - Domain models everywhere
4. **Maintainable** - 200-line files instead of 2000-line file
5. **Consistent** - Same patterns in API and Core layers
6. **Plan Storage** - Full planner output saved (including MCP steps)

---

## Full Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                         │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTTP
┌──────────────────────────────────────────────────────────────────────────────┐
│                           API ROUTES                                          │
│  chat.py, sessions.py, approvals.py, questions.py, projects.py               │
│  All return domain models (SessionDetail, ApprovalDetail, etc.)              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                           SERVICES                                            │
│  SessionService, ApprovalService, QuestionService, ProjectService            │
│  Business logic, permissions, coordinates repos + core                       │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
┌───────────────────────────────┐   ┌───────────────────────────────────────────┐
│        REPOSITORIES           │   │              CORE                          │
│                               │   │                                           │
│  SessionRepository            │   │  ┌─────────────────────────────────────┐ │
│  ApprovalRepository           │◄──┼──│         Orchestrator                 │ │
│  QuestionRepository           │   │  │  process_message() → UUID            │ │
│  WorkflowRepository           │   │  │  resume_from_approval() → UUID       │ │
│  ExecutionRepository          │   │  │  resume_from_question() → UUID       │ │
│  MessageRepository            │   │  └─────────────────────────────────────┘ │
│                               │   │              │                           │
│  All return domain models     │   │              ▼                           │
│                               │   │  ┌─────────────────────────────────────┐ │
└───────────────────────────────┘   │  │  SessionManager                     │ │
              │                     │  │  WorkflowExecutor                   │ │
              │                     │  │  ApprovalHandler                    │ │
              │                     │  │  QuestionHandler                    │ │
              │                     │  └─────────────────────────────────────┘ │
              │                     │              │                           │
              │                     │              ▼                           │
              │                     │  ┌─────────────────────────────────────┐ │
              ▼                     │  │  Agent (from agents/runtime.py)     │ │
┌───────────────────────────────┐   │  │  Already exists - handles execution │ │
│        DATABASE               │   │  │  run(), resume(), tool_calls, etc.  │ │
│  PostgreSQL                   │   │  └─────────────────────────────────────┘ │
└───────────────────────────────┘   │              │                           │
                                    │              ▼                           │
                                    │  ┌─────────────────────────────────────┐ │
                                    │  │         MCP Client                  │ │
                                    │  │  Calls coding/docker MCP servers    │ │
                                    │  └─────────────────────────────────────┘ │
                                    └───────────────────────────────────────────┘
```

---

## Ready to Implement?

This is a significant refactor. Suggested approach:
1. Start with Phase 1 (domain models + repositories) - low risk
2. Then Phase 2 (new core modules using existing Agent class)
3. Then Phase 3-5 (wire together)
4. Finally Phase 6 (cleanup)

Each phase can be tested independently before moving to the next.
