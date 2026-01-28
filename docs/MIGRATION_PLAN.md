# Migration Plan

This document outlines the step-by-step migration from the current architecture to the clean architecture described in our documentation.

## Understanding the Layers

Before we start, let's clarify what each layer does:

```
┌─────────────────────────────────────────────────────────────────────┐
│                         API ROUTES                                   │
│  • Receive HTTP requests                                             │
│  • Validate input                                                    │
│  • Call services                                                     │
│  • Return responses                                                  │
│  Example: @router.get("/sessions/{id}") → calls SessionService      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      SERVICE LAYER (NEW)                             │
│  • Permission checks (can user X see session Y?)                    │
│  • Business validation (is this action allowed?)                    │
│  • Orchestrate repository calls                                     │
│  Example: SessionService.get_detail() checks ownership              │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     REPOSITORY LAYER (NEW)                           │
│  • Database queries only                                             │
│  • Returns domain objects                                            │
│  • No business logic                                                 │
│  Example: SessionRepository.get_with_chat() builds ChatItem[]       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      DOMAIN LAYER (NEW)                              │
│  • Pydantic schemas (data shapes)                                   │
│  • No logic, just structure                                          │
│  Example: SessionDetail, ChatItem, AgentRunDetail                   │
└─────────────────────────────────────────────────────────────────────┘


SEPARATE from the above (NOT being replaced):

┌─────────────────────────────────────────────────────────────────────┐
│                      CORE LAYER (loop.py)                            │
│  • AI orchestration engine                                          │
│  • Agent execution (router → planner → workflow)                    │
│  • MCP tool calls                                                   │
│  • Pause/resume handling                                            │
│  • Token tracking                                                   │
│  Example: loop.py runs agents, handles approvals                    │
└─────────────────────────────────────────────────────────────────────┘
```

**Key insight:**
- Service layer = "who can do what" (web app permissions)
- Core layer = "how agents execute" (AI orchestration)

Both are needed. We're adding services, not replacing loop.py.

---

## Overview

```
Phase 1: Database Schema Updates
Phase 2: execute_agent Tool (Sub-Agent Support)  ← NEW
Phase 3: Docker MCP (Git-Based)
Phase 4: Domain Layer (Pydantic Schemas)
Phase 5: Repository Layer (Database Access)
Phase 6: Service Layer (Business Logic)
Phase 7: API Routes (Thin Handlers)
Phase 8: API Bridge (MCP Proxy)
Phase 9: Folder Rename & Cleanup
```

---

## Phase 1: Database Schema Updates

**Goal:** Update database to match DATABASE.md

### 1.1 Add new columns to agent_runs

```sql
ALTER TABLE agent_runs ADD COLUMN run_index INTEGER DEFAULT 0;
```

### 1.2 Add new columns to tool_calls

```sql
ALTER TABLE tool_calls ADD COLUMN tool_type VARCHAR(50) DEFAULT 'mcp';
ALTER TABLE tool_calls ADD COLUMN child_agent_run_id UUID REFERENCES agent_runs(id);
```

### 1.3 Remove builds and deployments tables

```sql
-- First remove foreign key constraints if any
DROP TABLE IF EXISTS deployments;
DROP TABLE IF EXISTS builds;
```

### 1.4 Update migration file

File: `druppie/db/migrations.py`
- Add migration function for each change
- Register in migrations list

### Verification
- [ ] `run_index` column exists in agent_runs
- [ ] `tool_type` column exists in tool_calls
- [ ] `child_agent_run_id` column exists in tool_calls
- [ ] builds table removed
- [ ] deployments table removed

---

## Phase 2: execute_agent Tool (Sub-Agent Support)

**Goal:** Allow agents to spawn sub-agents dynamically

**Current state:** `execute_agent` is documented but does NOT exist. The `parent_run_id` column exists but is never used.

### 2.1 Add tool definition to builtin_tools.py

```python
# Add to BUILTIN_TOOLS list
{
    "type": "function",
    "function": {
        "name": "execute_agent",
        "description": "Execute another agent to perform a sub-task. The sub-agent will run with full context and return its result. Use this to delegate specialized work.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent to execute (e.g., 'developer', 'reviewer', 'tester')",
                },
                "task": {
                    "type": "string",
                    "description": "Description of the task for the sub-agent to perform",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context to pass to the sub-agent",
                },
            },
            "required": ["agent_id", "task"],
        },
    },
},
```

### 2.2 Implement execute_agent function

```python
async def execute_agent(
    agent_id: str,
    task: str,
    context: "ExecutionContext",
    calling_agent_id: str,
    task_context: str | None = None,
) -> dict:
    """Execute a sub-agent to perform a task.

    Creates a nested agent_run with parent_run_id pointing to the caller.
    """
    from druppie.agents import Agent
    from druppie.api.deps import get_db
    from druppie.db.crud import create_agent_run, update_tool_call

    logger.info(
        "execute_agent_start",
        calling_agent=calling_agent_id,
        target_agent=agent_id,
        task=task[:100],
        parent_run_id=context.current_agent_run_id,
    )

    db = next(get_db())
    try:
        # Create nested agent run with parent_run_id
        child_run = create_agent_run(
            db=db,
            session_id=UUID(context.session_id),
            agent_id=agent_id,
            parent_run_id=UUID(context.current_agent_run_id),  # Key: links to parent
            status="running",
        )
        db.commit()
        child_run_id = str(child_run.id)

        # Update tool_call with child_agent_run_id
        if context.current_tool_call_id:
            update_tool_call(
                db=db,
                tool_call_id=UUID(context.current_tool_call_id),
                child_agent_run_id=child_run.id,
            )
            db.commit()
    finally:
        db.close()

    # Create child context
    child_context = context.create_child_context(
        agent_run_id=child_run_id,
        agent_id=agent_id,
    )

    # Build prompt with task
    prompt = f"{task}"
    if task_context:
        prompt = f"{task_context}\n\n{prompt}"

    # Run the sub-agent
    agent = Agent(agent_id)
    result = await agent.run(prompt, child_context)

    logger.info(
        "execute_agent_complete",
        calling_agent=calling_agent_id,
        target_agent=agent_id,
        child_run_id=child_run_id,
        result_status=result.get("status"),
    )

    return {
        "status": "completed",
        "agent_id": agent_id,
        "child_run_id": child_run_id,
        "result": result,
    }
```

### 2.3 Update execute_builtin_tool dispatcher

```python
async def execute_builtin_tool(...) -> dict:
    # ... existing code ...
    elif tool_name == "execute_agent":
        return await execute_agent(
            agent_id=tool_args.get("agent_id", ""),
            task=tool_args.get("task", ""),
            context=context,
            calling_agent_id=agent_id,
            task_context=tool_args.get("context"),
        )
    # ... rest of code ...
```

### 2.4 Update is_builtin_tool check

```python
def is_builtin_tool(tool_name: str) -> bool:
    return tool_name in (
        "hitl_ask_question",
        "hitl_ask_multiple_choice_question",
        "done",
        "execute_agent",  # Add this
    )
```

### 2.5 Add create_child_context to ExecutionContext

File: `druppie/core/execution_context.py`

```python
def create_child_context(self, agent_run_id: str, agent_id: str) -> "ExecutionContext":
    """Create a child context for a nested agent run."""
    child = ExecutionContext(
        session_id=self.session_id,
        user_id=self.user_id,
        workspace_id=self.workspace_id,
        project_id=self.project_id,
    )
    child.current_agent_run_id = agent_run_id
    child.parent_context = self  # Keep reference to parent
    child.emit_event = self.emit_event  # Share event emitter
    return child
```

### 2.6 Update crud.py for child_agent_run_id

```python
def update_tool_call(
    db: Session,
    tool_call_id: UUID,
    child_agent_run_id: UUID | None = None,
    # ... other fields ...
) -> ToolCall:
    tool_call = db.query(ToolCall).filter_by(id=tool_call_id).first()
    if child_agent_run_id:
        tool_call.child_agent_run_id = child_agent_run_id
    db.commit()
    return tool_call
```

### Verification
- [ ] `execute_agent` tool definition added
- [ ] `execute_agent` function implemented
- [ ] Creates agent_run with `parent_run_id` set
- [ ] Updates tool_call with `child_agent_run_id`
- [ ] Child context created correctly
- [ ] Sub-agent runs and returns result
- [ ] Nested runs visible in debug page

---

## Phase 3: Docker MCP (Git-Based)

**Goal:** Docker MCP clones from git, uses labels, no workspace dependency

### 3.1 Update build tool

File: `druppie/mcp-servers/docker/server.py`

**Remove:**
- `workspace_id` parameter
- `workspace_path` parameter
- `resolve_workspace_path()` function

**Add:**
- `git_url` parameter (required)
- `branch` parameter (default: "main")
- `project_id` parameter (required)

**New flow:**
```python
@mcp.tool()
async def build(
    image_name: str,
    git_url: str,
    branch: str = "main",
    project_id: str = None,
    dockerfile: str = "Dockerfile",
) -> dict:
    # 1. Create temp directory
    # 2. git clone <git_url> --branch <branch> --depth 1 <temp_dir>
    # 3. docker build -t <image_name> <temp_dir>
    # 4. rm -rf <temp_dir>
    # 5. Return result
```

### 3.2 Update run tool

Add label parameters and apply them:

```python
@mcp.tool()
async def run(
    image_name: str,
    container_name: str,
    # ... existing params ...
    # NEW: Druppie context
    project_id: str = None,
    session_id: str = None,
    branch: str = None,
    git_url: str = None,
) -> dict:
    # Build command with labels
    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "--label", f"druppie.project_id={project_id}",
        "--label", f"druppie.session_id={session_id}",
        "--label", f"druppie.branch={branch}",
        "--label", f"druppie.git_url={git_url}",
        # ... rest of command
    ]
```

### 3.3 Update list_containers tool

Add project_id filtering and return labels:

```python
@mcp.tool()
async def list_containers(
    all: bool = False,
    project_id: str = None,  # NEW: filter by project
) -> dict:
    cmd = ["docker", "ps", "--format", "json"]
    if all:
        cmd.append("-a")
    if project_id:
        cmd.extend(["--filter", f"label=druppie.project_id={project_id}"])

    # Parse and return with labels
```

### 3.4 Remove workspace registry

Remove:
- `workspaces` dict
- `register_workspace()` tool
- `resolve_workspace_path()` function

### Verification
- [ ] build tool accepts git_url, branch, project_id
- [ ] build tool clones repo and cleans up
- [ ] run tool adds druppie.* labels
- [ ] list_containers filters by project_id
- [ ] list_containers returns labels in response
- [ ] No workspace dependency

---

## Phase 3: Domain Layer

**Goal:** Create Pydantic schemas in `domain/` folder

### 3.1 Create folder structure

```
druppie/domain/
├── __init__.py
├── session.py
├── agent_run.py
├── tool_call.py
├── approval.py
├── question.py
├── project.py
├── user.py
└── common.py
```

### 3.2 Create common.py

```python
from pydantic import BaseModel
from datetime import datetime
from uuid import UUID

class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: datetime | None = None
```

### 3.3 Create session.py

```python
from pydantic import BaseModel
from uuid import UUID
from .common import TokenUsage
from .agent_run import AgentRunDetail
from .project import ProjectSummary

class SessionSummary(BaseModel):
    id: UUID
    title: str
    status: str
    token_usage: TokenUsage
    created_at: datetime

class SessionDetail(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    status: str
    token_usage: TokenUsage
    tokens_by_agent: dict[str, int]
    project: ProjectSummary | None
    chat: list[ChatItem]
    created_at: datetime
    updated_at: datetime

class ChatItem(BaseModel):
    type: str  # system_message, user_message, agent_run, assistant_message
    content: str | None = None
    agent_id: str | None = None
    timestamp: datetime
    # For agent_run type:
    agent_run: AgentRunDetail | None = None
```

### 3.4 Create remaining domain files

Similar pattern for:
- `agent_run.py` - AgentRunSummary, AgentRunDetail, LLMCall, ToolExecution
- `tool_call.py` - ToolCallDetail, ToolCallArgument
- `approval.py` - ApprovalSummary, ApprovalDetail
- `question.py` - HITLQuestion, QuestionChoice
- `project.py` - ProjectSummary, ProjectDetail, DeploymentInfo
- `user.py` - UserInfo, UserRole

### Verification
- [ ] All domain classes created
- [ ] No business logic in domain (pure data shapes)
- [ ] Can be imported by services and repositories

---

## Phase 4: Repository Layer

**Goal:** Move all database queries to `repositories/` folder

### 4.1 Create folder structure

```
druppie/repositories/
├── __init__.py
├── base.py
├── session_repository.py
├── agent_run_repository.py
├── approval_repository.py
├── question_repository.py
├── project_repository.py
└── user_repository.py
```

### 4.2 Create base.py

```python
from sqlalchemy.orm import Session

class BaseRepository:
    def __init__(self, db: Session):
        self.db = db

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()
```

### 4.3 Create session_repository.py

```python
from uuid import UUID
from .base import BaseRepository
from ..domain.session import SessionDetail, SessionSummary, ChatItem
from ..db.models import Session, AgentRun, Message, ToolCall

class SessionRepository(BaseRepository):

    def get_by_id(self, session_id: UUID) -> Session | None:
        return self.db.query(Session).filter_by(id=session_id).first()

    def list_for_user(self, user_id: UUID, limit: int = 20, offset: int = 0) -> list[SessionSummary]:
        sessions = (
            self.db.query(Session)
            .filter_by(user_id=user_id)
            .order_by(Session.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(s) for s in sessions]

    def get_with_chat(self, session_id: UUID) -> SessionDetail | None:
        session = self.get_by_id(session_id)
        if not session:
            return None

        # Build chat timeline
        chat = self._build_chat_timeline(session_id)

        return SessionDetail(
            id=session.id,
            # ... map all fields
            chat=chat,
        )

    def _build_chat_timeline(self, session_id: UUID) -> list[ChatItem]:
        # Query messages, agent_runs, merge chronologically
        # This is where the complex query logic lives
        pass

    def _to_summary(self, session: Session) -> SessionSummary:
        pass
```

### 4.4 Create remaining repositories

Similar pattern for:
- `agent_run_repository.py` - get nested runs, get with tool calls
- `approval_repository.py` - get pending for user roles
- `question_repository.py` - get pending for session
- `project_repository.py` - get with deployment info (from Docker MCP)
- `user_repository.py` - get by id, get roles

### Verification
- [ ] All database queries moved to repositories
- [ ] Repositories return domain objects (not SQLAlchemy models)
- [ ] No business logic in repositories (just queries)

---

## Phase 5: Service Layer

**Goal:** Move business logic to `services/` folder

### 5.1 Create folder structure

```
druppie/services/
├── __init__.py
├── session_service.py
├── approval_service.py
├── question_service.py
├── project_service.py
├── deployment_service.py
└── mcp_bridge_service.py
```

### 5.2 Create session_service.py

```python
from uuid import UUID
from ..repositories.session_repository import SessionRepository
from ..domain.session import SessionDetail, SessionSummary
from ..api.errors import NotFoundError, AuthorizationError

class SessionService:
    def __init__(self, repo: SessionRepository):
        self.repo = repo

    def get_detail(self, session_id: UUID, user_id: UUID) -> SessionDetail:
        session = self.repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", session_id)

        if not self._can_access(session, user_id):
            raise AuthorizationError("Cannot access this session")

        return self.repo.get_with_chat(session_id)

    def _can_access(self, session, user_id: UUID) -> bool:
        # Owner can access
        if session.user_id == user_id:
            return True
        # Admin can access (check roles)
        # Approver can access (check pending approvals)
        return False

    def list_for_user(self, user_id: UUID, page: int, limit: int) -> list[SessionSummary]:
        offset = (page - 1) * limit
        return self.repo.list_for_user(user_id, limit, offset)

    def delete(self, session_id: UUID, user_id: UUID) -> None:
        session = self.repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", session_id)
        if session.user_id != user_id:
            raise AuthorizationError("Only owner can delete")
        self.repo.delete(session_id)
```

### 5.3 Create approval_service.py

```python
class ApprovalService:
    def get_pending_for_user(self, user_id: UUID, user_roles: list[str]):
        # Only return approvals user can act on
        pass

    def approve(self, approval_id: UUID, user_id: UUID, user_roles: list[str]):
        # Check user has required role
        # Execute tool
        # Resume agent
        pass

    def reject(self, approval_id: UUID, user_id: UUID, reason: str):
        pass
```

### 5.4 Create deployment_service.py (MCP Bridge)

```python
from ..core.mcp_client import MCPClient

class DeploymentService:
    def __init__(self, mcp_client: MCPClient, project_repo: ProjectRepository):
        self.mcp = mcp_client
        self.project_repo = project_repo

    async def list_for_user(self, user_id: UUID) -> list[DeploymentInfo]:
        # Get user's project IDs
        projects = self.project_repo.list_for_user(user_id)
        project_ids = [p.id for p in projects]

        # Query Docker MCP for each project
        deployments = []
        for project_id in project_ids:
            result = await self.mcp.call_tool(
                "docker", "list_containers",
                {"project_id": str(project_id)}
            )
            if result.get("success"):
                for container in result.get("containers", []):
                    deployments.append(self._to_deployment_info(container))

        return deployments

    async def stop(self, container_name: str, user_id: UUID):
        # Verify user owns this container (check labels)
        # Call docker:stop
        pass
```

### Verification
- [ ] All business logic in services
- [ ] Services use repositories (not direct DB queries)
- [ ] Permission checks in services
- [ ] MCP bridge calls in deployment_service

---

## Phase 6: API Routes (Thin Handlers)

**Goal:** Simplify routes to just HTTP handling

### 6.1 Update routes/sessions.py

**Before (776 lines):**
```python
@router.get("/{session_id}")
async def get_session(session_id: UUID, db: Session, user: dict):
    session = db.query(Session).filter_by(id=session_id).first()
    if not session:
        raise HTTPException(404)
    # 500 more lines of queries and logic...
```

**After (~30 lines):**
```python
@router.get("/{session_id}")
async def get_session(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
) -> SessionDetail:
    return service.get_detail(session_id, user["id"])
```

### 6.2 Update dependency injection

File: `druppie/api/deps.py`

```python
def get_session_repository(db: Session = Depends(get_db)) -> SessionRepository:
    return SessionRepository(db)

def get_session_service(
    repo: SessionRepository = Depends(get_session_repository),
) -> SessionService:
    return SessionService(repo)
```

### 6.3 Update all route files

- `routes/sessions.py` → use SessionService
- `routes/approvals.py` → use ApprovalService
- `routes/questions.py` → use QuestionService
- `routes/projects.py` → use ProjectService
- `routes/deployments.py` → use DeploymentService (MCP bridge)
- `routes/workspace.py` → use MCPBridgeService

### Verification
- [ ] Routes are < 50 lines each
- [ ] No database queries in routes
- [ ] No business logic in routes
- [ ] Proper dependency injection

---

## Phase 7: API Bridge (MCP Proxy)

**Goal:** Implement workspace and deployment bridges

### 7.1 Create routes/workspace.py

```python
@router.get("/files")
async def list_files(
    session_id: UUID,
    path: str = "",
    service: MCPBridgeService = Depends(get_mcp_bridge_service),
    user: dict = Depends(get_current_user),
):
    # Verify user can access session
    # Call coding:list_dir
    return await service.list_workspace_files(session_id, path, user["id"])

@router.get("/file")
async def get_file(
    session_id: UUID,
    path: str,
    service: MCPBridgeService = Depends(get_mcp_bridge_service),
    user: dict = Depends(get_current_user),
):
    return await service.read_workspace_file(session_id, path, user["id"])
```

### 7.2 Create routes/deployments.py

```python
@router.get("")
async def list_deployments(
    service: DeploymentService = Depends(get_deployment_service),
    user: dict = Depends(get_current_user),
):
    return await service.list_for_user(user["id"])

@router.post("/{container_name}/stop")
async def stop_deployment(
    container_name: str,
    service: DeploymentService = Depends(get_deployment_service),
    user: dict = Depends(get_current_user),
):
    return await service.stop(container_name, user["id"])

@router.get("/{container_name}/logs")
async def get_logs(
    container_name: str,
    tail: int = 100,
    service: DeploymentService = Depends(get_deployment_service),
    user: dict = Depends(get_current_user),
):
    return await service.get_logs(container_name, tail, user["id"])
```

### Verification
- [ ] /api/workspace/files works
- [ ] /api/workspace/file works
- [ ] /api/deployments returns user's containers only
- [ ] /api/deployments/{name}/stop works
- [ ] /api/deployments/{name}/logs works

---

## Phase 9: Folder Rename & Cleanup

**Goal:** Clean up folder structure

### 9.1 Rename folders

```bash
# Rename backend folder
mv druppie druppie-backend

# Rename frontend folder
mv frontend druppie-frontend

# Update docker-compose.yml paths
# Update import paths
# Update CLAUDE.md references
```

### 9.2 Remove old files

```bash
# Remove old crud.py (replaced by repositories)
rm druppie-backend/db/crud.py

# Remove old schemas from api/ (moved to domain/)
rm druppie-backend/api/schemas.py
```

### 9.3 Update imports

Update all imports to use new paths:
- `from druppie.` → `from druppie_backend.`
- `from db.crud import` → `from repositories.X_repository import`

### Verification
- [ ] All imports work
- [ ] Docker builds work
- [ ] Tests pass

---

## Migration Checklist

### Phase 1: Database ⬜
- [ ] Migration 006: Add run_index to agent_runs
- [ ] Migration 007: Add tool_type, child_agent_run_id to tool_calls
- [ ] Migration 008: Drop builds, deployments tables

### Phase 2: execute_agent Tool ⬜
- [ ] Add execute_agent to BUILTIN_TOOLS
- [ ] Implement execute_agent function
- [ ] Update execute_builtin_tool dispatcher
- [ ] Update is_builtin_tool check
- [ ] Add create_child_context to ExecutionContext
- [ ] Update crud.py for child_agent_run_id
- [ ] Test nested agent runs

### Phase 3: Docker MCP ⬜
- [ ] build() uses git_url instead of workspace
- [ ] run() adds druppie.* labels
- [ ] list_containers() filters by project_id
- [ ] Remove workspace registry

### Phase 4: Domain ⬜
- [ ] domain/__init__.py
- [ ] domain/common.py
- [ ] domain/session.py
- [ ] domain/agent_run.py
- [ ] domain/tool_call.py
- [ ] domain/approval.py
- [ ] domain/question.py
- [ ] domain/project.py
- [ ] domain/user.py

### Phase 5: Repository ⬜
- [ ] repositories/base.py
- [ ] repositories/session_repository.py
- [ ] repositories/agent_run_repository.py
- [ ] repositories/approval_repository.py
- [ ] repositories/question_repository.py
- [ ] repositories/project_repository.py
- [ ] repositories/user_repository.py

### Phase 6: Service ⬜
- [ ] services/session_service.py
- [ ] services/approval_service.py
- [ ] services/question_service.py
- [ ] services/project_service.py
- [ ] services/deployment_service.py
- [ ] services/mcp_bridge_service.py

### Phase 7: Routes ⬜
- [ ] Simplify routes/sessions.py
- [ ] Simplify routes/approvals.py
- [ ] Simplify routes/questions.py
- [ ] Simplify routes/projects.py
- [ ] Update api/deps.py

### Phase 8: API Bridge ⬜
- [ ] routes/workspace.py
- [ ] routes/deployments.py

### Phase 9: Cleanup ⬜
- [ ] Rename druppie → druppie-backend
- [ ] Rename frontend → druppie-frontend
- [ ] Remove old files
- [ ] Update docker-compose.yml
- [ ] Update all imports
- [ ] All tests pass

---

## Rollback Plan

If issues occur, each phase can be rolled back:

1. **Database:** Migrations have down() functions
2. **Docker MCP:** Revert server.py changes
3. **Domain/Repository/Service:** Old code still works until routes updated
4. **Routes:** Revert to direct queries
5. **Folder rename:** Rename back

## Testing Strategy

After each phase:
1. Run unit tests
2. Run E2E tests: `cd frontend && npm run test:e2e`
3. Manual smoke test: create session, run agent, approve, check debug page
