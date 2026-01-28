# Proposal: Clean Architecture for Core Layer

## Goal

Refactor the core layer (loop.py) to:
1. **Use repositories** for all database access (not crud.py)
2. **Work with domain models** throughout
3. **Split into focused modules** for maintainability
4. **Return domain models** (or UUIDs that callers use to fetch domain models)

## Current Problems

```
core/loop.py (2000+ lines)
├── Uses crud.py directly ❌
├── Returns arbitrary dicts ❌
├── Mixed responsibilities ❌
│   ├── Session management
│   ├── Workflow execution
│   ├── Agent running
│   ├── Approval handling
│   └── Question handling
└── No clear boundaries ❌
```

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
│   QuestionRepository    │     │     ├── SessionManager              │
│   AgentRunRepository    │     │     ├── WorkflowExecutor            │
│   MessageRepository     │     │     ├── AgentRunner                 │
│                         │     │     ├── ApprovalHandler             │
│   All return domain     │     │     └── QuestionHandler             │
│   models                │     │                                     │
└─────────────────────────┘     │   All use repositories              │
                                │   All work with domain models       │
                                └─────────────────────────────────────┘
```

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
│                         # run_workflow, execute_step
│                         # Uses WorkflowRepository
│
├── agent_runner.py       # Runs individual agents
│                         # run_agent, handle_tool_calls
│                         # Uses AgentRunRepository, MessageRepository
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
        agent_runner: AgentRunner,
    ):
        self.session_manager = session_manager
        self.workflow_executor = workflow_executor
        self.agent_runner = agent_runner

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

        # 3. Run router agent
        router_result = await self.agent_runner.run(
            session_id=session.id,
            agent_id="router",
            prompt=message,
        )

        # 4. If paused (approval/question), return session_id
        #    Session status is already updated in DB
        if router_result.status in (AgentRunStatus.PAUSED_TOOL, AgentRunStatus.PAUSED_HITL):
            return session.id

        # 5. Run planner and workflow
        workflow = await self.workflow_executor.create_and_run(
            session_id=session.id,
            intent=router_result.intent,
            message=message,
        )

        # 6. Update session status based on workflow result
        self.session_manager.update_status(
            session_id=session.id,
            status=SessionStatus.COMPLETED if workflow.completed else SessionStatus.PAUSED_APPROVAL,
        )

        return session.id
```

### Example: SessionManager using repositories

```python
# core/session_manager.py

class SessionManager:
    """Manages session lifecycle."""

    def __init__(
        self,
        session_repo: SessionRepository,
        message_repo: MessageRepository,
        workspace_repo: WorkspaceRepository,
    ):
        self.session_repo = session_repo
        self.message_repo = message_repo
        self.workspace_repo = workspace_repo

    def get_or_create(
        self,
        session_id: UUID | None,
        user_id: UUID | None,
        project_id: UUID | None,
        title: str,
    ) -> Session:
        """Get existing session or create new one."""
        if session_id:
            session = self.session_repo.get_by_id(session_id)
            if session:
                return session

        # Create new session
        session = self.session_repo.create(
            user_id=user_id,
            project_id=project_id,
            title=title,
        )
        self.session_repo.commit()

        # Initialize workspace
        self.workspace_repo.create_for_session(session.id)
        self.workspace_repo.commit()

        return session

    def add_message(
        self,
        session_id: UUID,
        role: str,
        content: str,
        agent_id: str | None = None,
    ) -> Message:
        """Add a message to the session."""
        message = self.message_repo.create(
            session_id=session_id,
            role=role,
            content=content,
            agent_id=agent_id,
        )
        self.message_repo.commit()
        return message

    def update_status(self, session_id: UUID, status: SessionStatus) -> None:
        """Update session status."""
        self.session_repo.update_status(session_id, status)
        self.session_repo.commit()
```

### Example: AgentRunner using repositories

```python
# core/agent_runner.py

class AgentRunner:
    """Runs individual agents."""

    def __init__(
        self,
        agent_run_repo: AgentRunRepository,
        message_repo: MessageRepository,
        tool_call_repo: ToolCallRepository,
        llm_call_repo: LLMCallRepository,
        mcp_client: MCPClient,
        approval_handler: ApprovalHandler,
        question_handler: QuestionHandler,
    ):
        self.agent_run_repo = agent_run_repo
        self.message_repo = message_repo
        self.tool_call_repo = tool_call_repo
        self.llm_call_repo = llm_call_repo
        self.mcp_client = mcp_client
        self.approval_handler = approval_handler
        self.question_handler = question_handler

    async def run(
        self,
        session_id: UUID,
        agent_id: str,
        prompt: str,
        context: dict | None = None,
        parent_run_id: UUID | None = None,
    ) -> AgentRunDetail:
        """Run an agent and return the result as domain model."""

        # Create agent run record
        agent_run = self.agent_run_repo.create(
            session_id=session_id,
            agent_id=agent_id,
            parent_run_id=parent_run_id,
        )
        self.agent_run_repo.commit()

        try:
            # Load agent config
            agent_config = load_agent_config(agent_id)

            # Build messages
            messages = self._build_messages(agent_config, prompt, context)

            # Run LLM loop
            while True:
                # Call LLM
                llm_response = await self._call_llm(agent_run.id, agent_config, messages)

                # Check for tool calls
                if not llm_response.tool_calls:
                    # No tools, agent is done
                    break

                # Execute tool calls
                for tool_call in llm_response.tool_calls:
                    result = await self._execute_tool(agent_run.id, tool_call)

                    # Check if paused for approval
                    if result.status == ToolCallStatus.WAITING_APPROVAL:
                        self.agent_run_repo.update_status(
                            agent_run.id,
                            AgentRunStatus.PAUSED_TOOL,
                        )
                        self.agent_run_repo.commit()
                        return self.agent_run_repo.get_detail(agent_run.id)

                    # Check if paused for HITL
                    if result.status == ToolCallStatus.WAITING_HITL:
                        self.agent_run_repo.update_status(
                            agent_run.id,
                            AgentRunStatus.PAUSED_HITL,
                        )
                        self.agent_run_repo.commit()
                        return self.agent_run_repo.get_detail(agent_run.id)

                    # Add tool result to messages
                    messages.append(self._tool_result_message(tool_call, result))

            # Agent completed
            self.agent_run_repo.update_status(agent_run.id, AgentRunStatus.COMPLETED)
            self.agent_run_repo.commit()

            return self.agent_run_repo.get_detail(agent_run.id)

        except Exception as e:
            self.agent_run_repo.update_status(agent_run.id, AgentRunStatus.FAILED)
            self.agent_run_repo.commit()
            raise
```

## New Repositories Needed

Add these to support the core layer:

```python
# repositories/message_repository.py
class MessageRepository(BaseRepository):
    def create(self, session_id, role, content, agent_id=None) -> Message
    def get_for_session(self, session_id) -> list[Message]
    def get_for_agent_run(self, agent_run_id) -> list[Message]

# repositories/agent_run_repository.py
class AgentRunRepository(BaseRepository):
    def create(self, session_id, agent_id, parent_run_id=None) -> AgentRun
    def get_by_id(self, agent_run_id) -> AgentRun
    def get_detail(self, agent_run_id) -> AgentRunDetail  # Domain model!
    def update_status(self, agent_run_id, status) -> None
    def update_tokens(self, agent_run_id, tokens) -> None

# repositories/tool_call_repository.py
class ToolCallRepository(BaseRepository):
    def create(self, agent_run_id, tool_name, arguments) -> ToolCall
    def update_result(self, tool_call_id, result, status) -> None
    def get_detail(self, tool_call_id) -> ToolCallDetail  # Domain model!

# repositories/llm_call_repository.py
class LLMCallRepository(BaseRepository):
    def create(self, agent_run_id, model, provider, messages) -> LLMCall
    def update_response(self, llm_call_id, response, tokens, duration) -> None

# repositories/workspace_repository.py
class WorkspaceRepository(BaseRepository):
    def create_for_session(self, session_id) -> Workspace
    def get_for_session(self, session_id) -> Workspace
```

## Migration Plan

### Phase 1: Add New Repositories
1. Create `message_repository.py`
2. Create `agent_run_repository.py`
3. Create `tool_call_repository.py`
4. Create `llm_call_repository.py`
5. Create `workspace_repository.py`

### Phase 2: Create Core Modules
1. Create `core/session_manager.py`
2. Create `core/agent_runner.py`
3. Create `core/workflow_executor.py`
4. Create `core/approval_handler.py`
5. Create `core/question_handler.py`
6. Create `core/orchestrator.py`

### Phase 3: Update Dependency Injection
1. Add repository dependencies in `deps.py`
2. Add core module dependencies
3. Wire everything together

### Phase 4: Migrate loop.py
1. Move code from loop.py to new modules one piece at a time
2. Each module uses repositories
3. Each module returns domain models
4. Keep loop.py working during migration (facade pattern)

### Phase 5: Update Routes
1. `chat.py` calls Orchestrator, returns SessionDetail
2. `approvals.py` uses ApprovalHandler
3. `questions.py` uses QuestionHandler

### Phase 6: Cleanup
1. Delete old crud.py functions that are now in repositories
2. Delete loop.py (replaced by orchestrator + modules)

## File Changes Summary

| Action | File | Lines |
|--------|------|-------|
| CREATE | `repositories/message_repository.py` | ~50 |
| CREATE | `repositories/agent_run_repository.py` | ~80 |
| CREATE | `repositories/tool_call_repository.py` | ~50 |
| CREATE | `repositories/llm_call_repository.py` | ~40 |
| CREATE | `repositories/workspace_repository.py` | ~30 |
| CREATE | `core/session_manager.py` | ~100 |
| CREATE | `core/agent_runner.py` | ~300 |
| CREATE | `core/workflow_executor.py` | ~200 |
| CREATE | `core/approval_handler.py` | ~100 |
| CREATE | `core/question_handler.py` | ~100 |
| CREATE | `core/orchestrator.py` | ~200 |
| UPDATE | `api/deps.py` | Add new dependencies |
| UPDATE | `api/routes/chat.py` | Use Orchestrator |
| DELETE | `core/loop.py` | -2000 (moved to modules) |
| DELETE | `db/crud.py` | -1200 (moved to repositories) |

**Net change:** More files, but each is small and focused (~50-300 lines)

## Benefits

1. **Single Responsibility** - Each module does one thing
2. **Testable** - Can unit test each module with mock repositories
3. **Type Safe** - Domain models everywhere
4. **Maintainable** - 200-line files instead of 2000-line file
5. **Consistent** - Same patterns in API and Core layers
6. **No Duplication** - crud.py and repositories merged

## Diagram: Full Architecture

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
│  ProjectRepository            │   │  │  resume_from_approval() → UUID       │ │
│  MessageRepository            │   │  │  resume_from_question() → UUID       │ │
│  AgentRunRepository           │   │  └─────────────────────────────────────┘ │
│  ToolCallRepository           │   │              │                           │
│  LLMCallRepository            │   │              ▼                           │
│  WorkspaceRepository          │   │  ┌─────────────────────────────────────┐ │
│                               │   │  │  SessionManager                     │ │
│  All return domain models     │   │  │  WorkflowExecutor                   │ │
│                               │   │  │  AgentRunner                        │ │
└───────────────────────────────┘   │  │  ApprovalHandler                    │ │
              │                     │  │  QuestionHandler                    │ │
              │                     │  └─────────────────────────────────────┘ │
              │                     │              │                           │
              ▼                     │              ▼                           │
┌───────────────────────────────┐   │  ┌─────────────────────────────────────┐ │
│        DATABASE               │   │  │         MCP Client                  │ │
│  PostgreSQL                   │   │  │  Calls coding/docker MCP servers    │ │
└───────────────────────────────┘   │  └─────────────────────────────────────┘ │
                                    └───────────────────────────────────────────┘
```

## Ready to Implement?

This is a significant refactor. Suggested approach:
1. Start with Phase 1 (new repositories) - low risk
2. Then Phase 2 (new core modules) - parallel to existing loop.py
3. Then Phase 3-5 (wire together) - gradual migration
4. Finally Phase 6 (cleanup) - delete old code

Each phase can be tested independently before moving to the next.
