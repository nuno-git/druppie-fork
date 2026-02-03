# Migration Plan

This document outlines the step-by-step migration from the current architecture to the clean architecture described in our documentation. Please also read all the other files in the /docs folder to find more details about the exact implementation. Here is a reference/summary for a plan but the other files are more important/leading.

## Philosophy: Foundation First

**Key Principle:** Build the clean architecture foundation BEFORE adding new features.

```
WRONG (old plan):
  Add execute_agent → Add Docker MCP features → THEN create layers
  (Building new features on messy code = more mess)

RIGHT (this plan):
  Create layers → Migrate existing code → THEN add new features
  (New features built on clean foundation)
```

## Understanding the Layers

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
PART A: FOUNDATION (Create Clean Architecture)
  Phase 1: Domain Layer (Pydantic Schemas)
  Phase 2: Repository Layer (Database Access)
  Phase 3: Service Layer (Business Logic)

PART B: MIGRATION (Move Existing Code)
  Phase 4: Migrate Sessions API
  Phase 5: Migrate Approvals API
  Phase 6: Migrate Projects API
  Phase 7: Migrate Questions API

PART C: BRIDGES (New API Patterns)
  Phase 8: Workspace Bridge (Coding MCP Proxy)
  Phase 9: Deployments Bridge (Docker MCP Proxy)

PART D: NEW FEATURES (Built on Clean Foundation)
  Phase 10: Database Schema Updates
  Phase 11: execute_agent Tool (Sub-Agent Support)
  Phase 12: Docker MCP (Git-Based)

PART E: CLEANUP
  Phase 13: Folder Rename & Remove Legacy
```

---

# PART A: FOUNDATION

## Phase 1: Domain Layer (Pydantic Schemas)

**Goal:** Create all data shapes in `domain/` folder FIRST.

### 1.1 Create folder structure

```
druppie/domain/
├── __init__.py
├── common.py
├── session.py
├── agent_run.py
├── tool_call.py
├── approval.py
├── question.py
├── project.py
└── user.py
```

### 1.2 Create common.py

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

### 1.3 Create session.py

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from .common import TokenUsage


class SessionSummary(BaseModel):
    """Lightweight session for lists."""
    id: UUID
    title: str
    status: str
    project_id: UUID | None
    token_usage: TokenUsage
    created_at: datetime
    updated_at: datetime | None


class ChatItem(BaseModel):
    """Single item in chat timeline."""
    type: str  # system_message, user_message, agent_run, assistant_message
    content: str | None = None
    agent_id: str | None = None
    timestamp: datetime
    # For agent_run type - nested structure
    agent_run: "AgentRunDetail | None" = None


class SessionDetail(BaseModel):
    """Full session with chat timeline."""
    id: UUID
    user_id: UUID
    title: str
    status: str
    token_usage: TokenUsage
    tokens_by_agent: dict[str, int]
    project: "ProjectSummary | None"
    chat: list[ChatItem]
    created_at: datetime
    updated_at: datetime | None


# Forward references
from .agent_run import AgentRunDetail
from .project import ProjectSummary
SessionDetail.model_rebuild()
ChatItem.model_rebuild()
```

### 1.4 Create agent_run.py

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from .common import TokenUsage


class LLMCallDetail(BaseModel):
    """Single LLM API call."""
    id: UUID
    model: str
    provider: str
    token_usage: TokenUsage
    duration_ms: int | None
    tools_decided: list[str]


class ToolExecutionDetail(BaseModel):
    """Single tool execution."""
    id: UUID
    tool: str  # "coding:write_file" or "builtin:done"
    tool_type: str  # "mcp" or "builtin"
    arguments: dict
    status: str  # pending, executing, completed, failed
    result: str | None
    error: str | None
    approval: "ApprovalSummary | None"  # Embedded if approval was needed


class AgentRunStep(BaseModel):
    """A step in an agent run (LLM call or tool execution)."""
    type: str  # "llm_call" or "tool_execution" or "hitl_question"
    llm_call: LLMCallDetail | None = None
    tool_execution: ToolExecutionDetail | None = None
    question: "QuestionDetail | None" = None


class AgentRunDetail(BaseModel):
    """Full agent run with steps."""
    id: UUID
    agent_id: str
    status: str
    token_usage: TokenUsage
    started_at: datetime
    completed_at: datetime | None
    steps: list[AgentRunStep]
    # Nested runs (from execute_agent)
    child_runs: list["AgentRunDetail"] = []


# Forward refs
from .approval import ApprovalSummary
from .question import QuestionDetail
AgentRunDetail.model_rebuild()
ToolExecutionDetail.model_rebuild()
AgentRunStep.model_rebuild()
```

### 1.5 Create approval.py

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class ApprovalSummary(BaseModel):
    """Lightweight approval for embedding."""
    id: UUID
    status: str  # pending, approved, rejected
    required_role: str
    resolved_by: UUID | None
    resolved_at: datetime | None


class ApprovalDetail(BaseModel):
    """Full approval with context."""
    id: UUID
    session_id: UUID
    agent_run_id: UUID | None
    tool_call_id: UUID | None
    approval_type: str  # tool_call, workflow_step
    mcp_server: str | None
    tool_name: str | None
    arguments: dict
    status: str
    required_role: str
    agent_id: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
    rejection_reason: str | None
    created_at: datetime


class PendingApprovalList(BaseModel):
    """Approvals the current user can act on."""
    items: list[ApprovalDetail]
    total: int
```

### 1.6 Create question.py

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class QuestionChoice(BaseModel):
    """A choice in a multiple-choice question."""
    index: int
    text: str
    is_selected: bool = False


class QuestionDetail(BaseModel):
    """HITL question."""
    id: UUID
    session_id: UUID
    agent_run_id: UUID | None
    agent_id: str
    question: str
    question_type: str  # text, multiple_choice
    choices: list[QuestionChoice] = []
    status: str  # pending, answered
    answer: str | None
    answered_at: datetime | None
    created_at: datetime


class PendingQuestionList(BaseModel):
    """Questions waiting for user answer."""
    items: list[QuestionDetail]
    total: int
```

### 1.7 Create project.py

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from .common import TokenUsage


class DeploymentInfo(BaseModel):
    """Deployment status (from Docker MCP labels)."""
    status: str  # running, stopped
    container_name: str
    app_url: str | None
    host_port: int | None
    started_at: datetime | None


class ProjectSummary(BaseModel):
    """Lightweight project for lists and embedding."""
    id: UUID
    name: str
    description: str | None
    repo_url: str | None
    status: str
    created_at: datetime


class ProjectDetail(BaseModel):
    """Full project with stats."""
    id: UUID
    owner_id: UUID
    name: str
    description: str | None
    repo_name: str | None
    repo_url: str | None
    status: str
    token_usage: TokenUsage
    session_count: int
    deployment: DeploymentInfo | None
    created_at: datetime
```

### 1.8 Create user.py

```python
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class UserInfo(BaseModel):
    """Current user info."""
    id: UUID
    username: str
    email: str | None
    display_name: str | None
    roles: list[str]
```

### 1.9 Create __init__.py

```python
"""Domain models for Druppie API responses."""

from .common import TokenUsage, TimestampMixin
from .session import SessionSummary, SessionDetail, ChatItem
from .agent_run import AgentRunDetail, AgentRunStep, LLMCallDetail, ToolExecutionDetail
from .approval import ApprovalSummary, ApprovalDetail, PendingApprovalList
from .question import QuestionDetail, QuestionChoice, PendingQuestionList
from .project import ProjectSummary, ProjectDetail, DeploymentInfo
from .user import UserInfo

__all__ = [
    "TokenUsage",
    "TimestampMixin",
    "SessionSummary",
    "SessionDetail",
    "ChatItem",
    "AgentRunDetail",
    "AgentRunStep",
    "LLMCallDetail",
    "ToolExecutionDetail",
    "ApprovalSummary",
    "ApprovalDetail",
    "PendingApprovalList",
    "QuestionDetail",
    "QuestionChoice",
    "PendingQuestionList",
    "ProjectSummary",
    "ProjectDetail",
    "DeploymentInfo",
    "UserInfo",
]
```

### Verification
- [ ] All domain files created
- [ ] No business logic in domain (pure data shapes)
- [ ] Pydantic validation works
- [ ] Forward references resolved

---

## Phase 2: Repository Layer (Database Access)

**Goal:** Create all repositories that query database and return domain objects.

### 2.1 Create folder structure

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

### 2.2 Create base.py

```python
from sqlalchemy.orm import Session


class BaseRepository:
    """Base class for all repositories."""

    def __init__(self, db: Session):
        self.db = db

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()

    def flush(self):
        self.db.flush()
```

### 2.3 Create session_repository.py

```python
from uuid import UUID
from sqlalchemy import func
from sqlalchemy.orm import Session

from .base import BaseRepository
from ..domain import (
    SessionSummary,
    SessionDetail,
    ChatItem,
    TokenUsage,
    AgentRunDetail,
)
from ..db.models import Session as SessionModel, AgentRun, Message, ToolCall, LLMCall


class SessionRepository(BaseRepository):
    """Database access for sessions."""

    def get_by_id(self, session_id: UUID) -> SessionModel | None:
        """Get raw session model."""
        return self.db.query(SessionModel).filter_by(id=session_id).first()

    def list_for_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> tuple[list[SessionSummary], int]:
        """List sessions for a user with pagination."""
        query = self.db.query(SessionModel).filter_by(user_id=user_id)

        if status:
            query = query.filter_by(status=status)

        total = query.count()
        sessions = (
            query.order_by(SessionModel.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

        return [self._to_summary(s) for s in sessions], total

    def get_with_chat(self, session_id: UUID) -> SessionDetail | None:
        """Get session with full chat timeline."""
        session = self.get_by_id(session_id)
        if not session:
            return None

        chat = self._build_chat_timeline(session_id)
        tokens_by_agent = self._get_tokens_by_agent(session_id)

        return SessionDetail(
            id=session.id,
            user_id=session.user_id,
            title=session.title or "Untitled",
            status=session.status,
            token_usage=TokenUsage(
                prompt_tokens=session.prompt_tokens or 0,
                completion_tokens=session.completion_tokens or 0,
                total_tokens=session.total_tokens or 0,
            ),
            tokens_by_agent=tokens_by_agent,
            project=self._get_project_summary(session.project_id) if session.project_id else None,
            chat=chat,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def create(
        self,
        user_id: UUID,
        title: str,
        project_id: UUID | None = None,
    ) -> SessionModel:
        """Create a new session."""
        session = SessionModel(
            user_id=user_id,
            title=title,
            project_id=project_id,
            status="active",
        )
        self.db.add(session)
        self.db.flush()
        return session

    def update_status(self, session_id: UUID, status: str) -> None:
        """Update session status."""
        self.db.query(SessionModel).filter_by(id=session_id).update({"status": status})

    def delete(self, session_id: UUID) -> None:
        """Delete session (cascades to related data)."""
        self.db.query(SessionModel).filter_by(id=session_id).delete()

    def _to_summary(self, session: SessionModel) -> SessionSummary:
        return SessionSummary(
            id=session.id,
            title=session.title or "Untitled",
            status=session.status,
            project_id=session.project_id,
            token_usage=TokenUsage(
                prompt_tokens=session.prompt_tokens or 0,
                completion_tokens=session.completion_tokens or 0,
                total_tokens=session.total_tokens or 0,
            ),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def _build_chat_timeline(self, session_id: UUID) -> list[ChatItem]:
        """Build chronological chat timeline from messages and agent runs."""
        # Implementation: merge messages and agent_runs by timestamp
        # This is the complex query logic centralized in ONE place
        items = []

        # Get messages
        messages = (
            self.db.query(Message)
            .filter_by(session_id=session_id)
            .order_by(Message.created_at)
            .all()
        )

        for msg in messages:
            items.append(ChatItem(
                type=f"{msg.role}_message",
                content=msg.content,
                timestamp=msg.created_at,
            ))

        # Get agent runs (top-level only)
        agent_runs = (
            self.db.query(AgentRun)
            .filter_by(session_id=session_id, parent_run_id=None)
            .order_by(AgentRun.started_at)
            .all()
        )

        for run in agent_runs:
            items.append(ChatItem(
                type="agent_run",
                agent_id=run.agent_id,
                timestamp=run.started_at,
                agent_run=self._build_agent_run_detail(run),
            ))

        # Sort by timestamp
        items.sort(key=lambda x: x.timestamp)
        return items

    def _build_agent_run_detail(self, run: AgentRun) -> AgentRunDetail:
        """Build full agent run detail with steps."""
        # Get steps (LLM calls and tool calls)
        # This recursively builds nested runs
        pass  # Implemented in agent_run_repository

    def _get_tokens_by_agent(self, session_id: UUID) -> dict[str, int]:
        """Get token usage grouped by agent."""
        results = (
            self.db.query(
                AgentRun.agent_id,
                func.sum(AgentRun.total_tokens).label("total"),
            )
            .filter_by(session_id=session_id)
            .group_by(AgentRun.agent_id)
            .all()
        )
        return {r.agent_id: r.total or 0 for r in results}

    def _get_project_summary(self, project_id: UUID):
        """Get project summary (implemented in project_repository)."""
        from ..db.models import Project
        project = self.db.query(Project).filter_by(id=project_id).first()
        if not project:
            return None
        from ..domain import ProjectSummary
        return ProjectSummary(
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=project.repo_url,
            status=project.status,
            created_at=project.created_at,
        )
```

### 2.4 Create approval_repository.py

```python
from uuid import UUID
from sqlalchemy.orm import Session

from .base import BaseRepository
from ..domain import ApprovalDetail, ApprovalSummary, PendingApprovalList
from ..db.models import Approval


class ApprovalRepository(BaseRepository):
    """Database access for approvals."""

    def get_by_id(self, approval_id: UUID) -> Approval | None:
        return self.db.query(Approval).filter_by(id=approval_id).first()

    def get_pending_for_roles(self, roles: list[str]) -> PendingApprovalList:
        """Get pending approvals that the user's roles can approve."""
        approvals = (
            self.db.query(Approval)
            .filter(Approval.status == "pending")
            .filter(Approval.required_role.in_(roles))
            .order_by(Approval.created_at.desc())
            .all()
        )
        return PendingApprovalList(
            items=[self._to_detail(a) for a in approvals],
            total=len(approvals),
        )

    def get_for_session(self, session_id: UUID) -> list[ApprovalDetail]:
        """Get all approvals for a session."""
        approvals = (
            self.db.query(Approval)
            .filter_by(session_id=session_id)
            .order_by(Approval.created_at)
            .all()
        )
        return [self._to_detail(a) for a in approvals]

    def update_status(
        self,
        approval_id: UUID,
        status: str,
        resolved_by: UUID | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        """Update approval status."""
        from datetime import datetime, timezone
        updates = {
            "status": status,
            "resolved_by": resolved_by,
            "resolved_at": datetime.now(timezone.utc) if resolved_by else None,
        }
        if rejection_reason:
            updates["rejection_reason"] = rejection_reason
        self.db.query(Approval).filter_by(id=approval_id).update(updates)

    def _to_detail(self, approval: Approval) -> ApprovalDetail:
        return ApprovalDetail(
            id=approval.id,
            session_id=approval.session_id,
            agent_run_id=approval.agent_run_id,
            tool_call_id=approval.tool_call_id,
            approval_type=approval.approval_type or "tool_call",
            mcp_server=approval.mcp_server,
            tool_name=approval.tool_name,
            arguments=approval.mcp_arguments or {},
            status=approval.status,
            required_role=approval.required_role or "admin",
            agent_id=approval.agent_id,
            resolved_by=approval.resolved_by,
            resolved_at=approval.resolved_at,
            rejection_reason=approval.rejection_reason,
            created_at=approval.created_at,
        )

    def _to_summary(self, approval: Approval) -> ApprovalSummary:
        return ApprovalSummary(
            id=approval.id,
            status=approval.status,
            required_role=approval.required_role or "admin",
            resolved_by=approval.resolved_by,
            resolved_at=approval.resolved_at,
        )
```

### 2.5 Create question_repository.py

```python
from uuid import UUID
from .base import BaseRepository
from ..domain import QuestionDetail, QuestionChoice, PendingQuestionList
from ..db.models import HitlQuestion, HitlQuestionChoice


class QuestionRepository(BaseRepository):
    """Database access for HITL questions."""

    def get_by_id(self, question_id: UUID) -> HitlQuestion | None:
        return self.db.query(HitlQuestion).filter_by(id=question_id).first()

    def get_pending_for_session(self, session_id: UUID) -> PendingQuestionList:
        """Get pending questions for a session."""
        questions = (
            self.db.query(HitlQuestion)
            .filter_by(session_id=session_id, status="pending")
            .order_by(HitlQuestion.created_at)
            .all()
        )
        return PendingQuestionList(
            items=[self._to_detail(q) for q in questions],
            total=len(questions),
        )

    def get_pending_for_user(self, user_id: UUID) -> PendingQuestionList:
        """Get all pending questions for sessions owned by user."""
        from ..db.models import Session
        questions = (
            self.db.query(HitlQuestion)
            .join(Session, HitlQuestion.session_id == Session.id)
            .filter(Session.user_id == user_id)
            .filter(HitlQuestion.status == "pending")
            .order_by(HitlQuestion.created_at)
            .all()
        )
        return PendingQuestionList(
            items=[self._to_detail(q) for q in questions],
            total=len(questions),
        )

    def update_answer(
        self,
        question_id: UUID,
        answer: str,
        selected_choices: list[int] | None = None,
    ) -> None:
        """Update question with answer."""
        from datetime import datetime, timezone
        self.db.query(HitlQuestion).filter_by(id=question_id).update({
            "answer": answer,
            "status": "answered",
            "answered_at": datetime.now(timezone.utc),
        })
        if selected_choices:
            for idx in selected_choices:
                self.db.query(HitlQuestionChoice).filter_by(
                    question_id=question_id,
                    choice_index=idx,
                ).update({"is_selected": True})

    def _to_detail(self, question: HitlQuestion) -> QuestionDetail:
        choices = (
            self.db.query(HitlQuestionChoice)
            .filter_by(question_id=question.id)
            .order_by(HitlQuestionChoice.choice_index)
            .all()
        )
        return QuestionDetail(
            id=question.id,
            session_id=question.session_id,
            agent_run_id=question.agent_run_id,
            agent_id=question.agent_id,
            question=question.question,
            question_type=question.question_type or "text",
            choices=[
                QuestionChoice(
                    index=c.choice_index,
                    text=c.choice_text,
                    is_selected=c.is_selected or False,
                )
                for c in choices
            ],
            status=question.status,
            answer=question.answer,
            answered_at=question.answered_at,
            created_at=question.created_at,
        )
```

### 2.6 Create project_repository.py

```python
from uuid import UUID
from sqlalchemy import func
from .base import BaseRepository
from ..domain import ProjectSummary, ProjectDetail, TokenUsage
from ..db.models import Project, Session


class ProjectRepository(BaseRepository):
    """Database access for projects."""

    def get_by_id(self, project_id: UUID) -> Project | None:
        return self.db.query(Project).filter_by(id=project_id).first()

    def list_for_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ProjectSummary], int]:
        """List projects for a user."""
        query = self.db.query(Project).filter_by(owner_id=user_id)
        total = query.count()
        projects = (
            query.order_by(Project.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return [self._to_summary(p) for p in projects], total

    def get_detail(self, project_id: UUID) -> ProjectDetail | None:
        """Get full project detail with stats."""
        project = self.get_by_id(project_id)
        if not project:
            return None

        # Get token stats from sessions
        stats = (
            self.db.query(
                func.coalesce(func.sum(Session.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(Session.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(Session.completion_tokens), 0).label("completion_tokens"),
                func.count(Session.id).label("session_count"),
            )
            .filter(Session.project_id == project_id)
            .first()
        )

        return ProjectDetail(
            id=project.id,
            owner_id=project.owner_id,
            name=project.name,
            description=project.description,
            repo_name=project.repo_name,
            repo_url=project.repo_url,
            status=project.status,
            token_usage=TokenUsage(
                prompt_tokens=stats.prompt_tokens,
                completion_tokens=stats.completion_tokens,
                total_tokens=stats.total_tokens,
            ),
            session_count=stats.session_count,
            deployment=None,  # Filled by service via Docker MCP
            created_at=project.created_at,
        )

    def _to_summary(self, project: Project) -> ProjectSummary:
        return ProjectSummary(
            id=project.id,
            name=project.name,
            description=project.description,
            repo_url=project.repo_url,
            status=project.status,
            created_at=project.created_at,
        )
```

### 2.7 Create __init__.py

```python
"""Repository layer for database access."""

from .base import BaseRepository
from .session_repository import SessionRepository
from .approval_repository import ApprovalRepository
from .question_repository import QuestionRepository
from .project_repository import ProjectRepository

__all__ = [
    "BaseRepository",
    "SessionRepository",
    "ApprovalRepository",
    "QuestionRepository",
    "ProjectRepository",
]
```

### Verification
- [ ] All repositories created
- [ ] Repositories return domain objects (not SQLAlchemy models)
- [ ] No business logic in repositories (just queries)
- [ ] Complex queries centralized (e.g., chat timeline in SessionRepository)

---

## Phase 3: Service Layer (Business Logic)

**Goal:** Create services that handle permissions and business rules.

### 3.1 Create folder structure

```
druppie/services/
├── __init__.py
├── session_service.py
├── approval_service.py
├── question_service.py
├── project_service.py
└── deployment_service.py
```

### 3.2 Create session_service.py

```python
from uuid import UUID
import structlog

from ..repositories import SessionRepository, ApprovalRepository
from ..domain import SessionDetail, SessionSummary
from ..api.errors import NotFoundError, AuthorizationError

logger = structlog.get_logger()


class SessionService:
    """Business logic for sessions."""

    def __init__(
        self,
        session_repo: SessionRepository,
        approval_repo: ApprovalRepository,
    ):
        self.session_repo = session_repo
        self.approval_repo = approval_repo

    def get_detail(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> SessionDetail:
        """Get session detail with access check."""
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", session_id)

        if not self._can_access(session, user_id, user_roles):
            raise AuthorizationError("Cannot access this session")

        return self.session_repo.get_with_chat(session_id)

    def list_for_user(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
        status: str | None = None,
    ) -> tuple[list[SessionSummary], int]:
        """List sessions for a user."""
        offset = (page - 1) * limit
        return self.session_repo.list_for_user(user_id, limit, offset, status)

    def delete(
        self,
        session_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> None:
        """Delete session (owner or admin only)."""
        session = self.session_repo.get_by_id(session_id)
        if not session:
            raise NotFoundError("session", session_id)

        is_owner = session.user_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can delete")

        self.session_repo.delete(session_id)
        self.session_repo.commit()
        logger.info("session_deleted", session_id=str(session_id), by_user=str(user_id))

    def _can_access(self, session, user_id: UUID, user_roles: list[str]) -> bool:
        """Check if user can access session."""
        # Owner can access
        if session.user_id == user_id:
            return True

        # Admin can access
        if "admin" in user_roles:
            return True

        # User with pending approval for this session can access
        pending = self.approval_repo.get_for_session(session.id)
        for approval in pending:
            if approval.status == "pending" and approval.required_role in user_roles:
                return True

        return False
```

### 3.3 Create approval_service.py

```python
from uuid import UUID
import structlog

from ..repositories import ApprovalRepository, SessionRepository
from ..domain import ApprovalDetail, PendingApprovalList
from ..api.errors import NotFoundError, AuthorizationError
from ..core.loop import resume_from_step_approval

logger = structlog.get_logger()


class ApprovalService:
    """Business logic for approvals."""

    def __init__(
        self,
        approval_repo: ApprovalRepository,
        session_repo: SessionRepository,
    ):
        self.approval_repo = approval_repo
        self.session_repo = session_repo

    def get_pending_for_user(
        self,
        user_id: UUID,
        user_roles: list[str],
    ) -> PendingApprovalList:
        """Get approvals user can act on based on their roles."""
        # Admin sees all, others see only matching roles
        if "admin" in user_roles:
            roles_to_check = ["admin", "architect", "developer"]  # All roles
        else:
            roles_to_check = user_roles

        return self.approval_repo.get_pending_for_roles(roles_to_check)

    def get_detail(
        self,
        approval_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> ApprovalDetail:
        """Get approval detail with access check."""
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            raise NotFoundError("approval", approval_id)

        # Check user can see this approval
        required_role = approval.required_role or "admin"
        if required_role not in user_roles and "admin" not in user_roles:
            raise AuthorizationError(
                f"Requires {required_role} role",
                required_roles=[required_role],
            )

        return self.approval_repo._to_detail(approval)

    async def approve(
        self,
        approval_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        comment: str | None = None,
    ) -> dict:
        """Approve and execute the tool."""
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            raise NotFoundError("approval", approval_id)

        # Check role
        required_role = approval.required_role or "admin"
        if required_role not in user_roles and "admin" not in user_roles:
            raise AuthorizationError(
                f"Requires {required_role} role to approve",
                required_roles=[required_role],
            )

        if approval.status != "pending":
            raise AuthorizationError(f"Approval already {approval.status}")

        # Update status
        self.approval_repo.update_status(
            approval_id=approval_id,
            status="approved",
            resolved_by=user_id,
        )
        self.approval_repo.commit()

        logger.info(
            "approval_approved",
            approval_id=str(approval_id),
            by_user=str(user_id),
            tool=f"{approval.mcp_server}:{approval.tool_name}",
        )

        # Resume execution
        result = await resume_from_step_approval(
            session_id=str(approval.session_id),
            approval_id=str(approval_id),
            approved=True,
        )

        return {
            "success": True,
            "status": "approved",
            "tool_result": result,
        }

    async def reject(
        self,
        approval_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        reason: str,
    ) -> dict:
        """Reject the approval."""
        approval = self.approval_repo.get_by_id(approval_id)
        if not approval:
            raise NotFoundError("approval", approval_id)

        required_role = approval.required_role or "admin"
        if required_role not in user_roles and "admin" not in user_roles:
            raise AuthorizationError(f"Requires {required_role} role to reject")

        if approval.status != "pending":
            raise AuthorizationError(f"Approval already {approval.status}")

        self.approval_repo.update_status(
            approval_id=approval_id,
            status="rejected",
            resolved_by=user_id,
            rejection_reason=reason,
        )
        self.approval_repo.commit()

        logger.info(
            "approval_rejected",
            approval_id=str(approval_id),
            by_user=str(user_id),
            reason=reason,
        )

        # Resume with rejection
        result = await resume_from_step_approval(
            session_id=str(approval.session_id),
            approval_id=str(approval_id),
            approved=False,
        )

        return {
            "success": True,
            "status": "rejected",
            "result": result,
        }
```

### 3.4 Create question_service.py

```python
from uuid import UUID
import structlog

from ..repositories import QuestionRepository, SessionRepository
from ..domain import QuestionDetail, PendingQuestionList
from ..api.errors import NotFoundError, AuthorizationError
from ..core.loop import resume_from_question_answer

logger = structlog.get_logger()


class QuestionService:
    """Business logic for HITL questions."""

    def __init__(
        self,
        question_repo: QuestionRepository,
        session_repo: SessionRepository,
    ):
        self.question_repo = question_repo
        self.session_repo = session_repo

    def get_pending_for_user(self, user_id: UUID) -> PendingQuestionList:
        """Get pending questions for user's sessions."""
        return self.question_repo.get_pending_for_user(user_id)

    def get_detail(
        self,
        question_id: UUID,
        user_id: UUID,
    ) -> QuestionDetail:
        """Get question detail with ownership check."""
        question = self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundError("question", question_id)

        session = self.session_repo.get_by_id(question.session_id)
        if not session or session.user_id != user_id:
            raise AuthorizationError("Can only answer questions in your own sessions")

        return self.question_repo._to_detail(question)

    async def answer(
        self,
        question_id: UUID,
        user_id: UUID,
        answer: str,
        selected_choices: list[int] | None = None,
    ) -> dict:
        """Answer a question and resume execution."""
        question = self.question_repo.get_by_id(question_id)
        if not question:
            raise NotFoundError("question", question_id)

        session = self.session_repo.get_by_id(question.session_id)
        if not session or session.user_id != user_id:
            raise AuthorizationError("Can only answer questions in your own sessions")

        if question.status != "pending":
            raise AuthorizationError(f"Question already {question.status}")

        # Update answer
        self.question_repo.update_answer(
            question_id=question_id,
            answer=answer,
            selected_choices=selected_choices,
        )
        self.question_repo.commit()

        logger.info(
            "question_answered",
            question_id=str(question_id),
            by_user=str(user_id),
        )

        # Resume execution
        result = await resume_from_question_answer(
            session_id=str(question.session_id),
            question_id=str(question_id),
            answer=answer,
        )

        return {
            "success": True,
            "status": "answered",
            "result": result,
        }
```

### 3.5 Create project_service.py

```python
from uuid import UUID
import structlog

from ..repositories import ProjectRepository
from ..domain import ProjectDetail, ProjectSummary
from ..api.errors import NotFoundError, AuthorizationError

logger = structlog.get_logger()


class ProjectService:
    """Business logic for projects."""

    def __init__(self, project_repo: ProjectRepository):
        self.project_repo = project_repo

    def list_for_user(
        self,
        user_id: UUID,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[ProjectSummary], int]:
        """List projects for a user."""
        offset = (page - 1) * limit
        return self.project_repo.list_for_user(user_id, limit, offset)

    def get_detail(
        self,
        project_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> ProjectDetail:
        """Get project detail with access check."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("project", project_id)

        is_owner = project.owner_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can view project")

        return self.project_repo.get_detail(project_id)

    def delete(
        self,
        project_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> None:
        """Delete project (owner or admin only)."""
        project = self.project_repo.get_by_id(project_id)
        if not project:
            raise NotFoundError("project", project_id)

        is_owner = project.owner_id == user_id
        is_admin = "admin" in user_roles

        if not is_owner and not is_admin:
            raise AuthorizationError("Only owner or admin can delete")

        # TODO: Also delete Gitea repo?
        self.project_repo.db.query(type(project)).filter_by(id=project_id).delete()
        self.project_repo.commit()

        logger.info("project_deleted", project_id=str(project_id), by_user=str(user_id))
```

### 3.6 Create deployment_service.py (MCP Bridge)

```python
from uuid import UUID
import structlog

from ..repositories import ProjectRepository
from ..domain import DeploymentInfo
from ..core.mcp_client import MCPClient
from ..api.errors import NotFoundError, AuthorizationError, ExternalServiceError

logger = structlog.get_logger()


class DeploymentService:
    """Bridge to Docker MCP for deployment operations."""

    def __init__(
        self,
        project_repo: ProjectRepository,
        mcp_client: MCPClient,
    ):
        self.project_repo = project_repo
        self.mcp_client = mcp_client

    async def list_for_user(self, user_id: UUID) -> list[DeploymentInfo]:
        """List all running deployments for user's projects."""
        projects, _ = self.project_repo.list_for_user(user_id, limit=100, offset=0)

        deployments = []
        for project in projects:
            result = await self.mcp_client.call_tool(
                "docker",
                "list_containers",
                {"project_id": str(project.id)},
            )
            if result.get("success") and result.get("containers"):
                for container in result["containers"]:
                    deployments.append(self._container_to_deployment(container, project))

        return deployments

    async def stop(
        self,
        container_name: str,
        user_id: UUID,
    ) -> dict:
        """Stop a container (with ownership check)."""
        # Verify ownership via labels
        if not await self._user_owns_container(container_name, user_id):
            raise AuthorizationError("Can only stop your own containers")

        result = await self.mcp_client.call_tool(
            "docker",
            "stop",
            {"container_name": container_name},
        )

        if not result.get("success"):
            raise ExternalServiceError("docker", result.get("error", "Failed to stop"))

        logger.info("container_stopped", container_name=container_name, by_user=str(user_id))
        return {"success": True, "status": "stopped"}

    async def get_logs(
        self,
        container_name: str,
        user_id: UUID,
        tail: int = 100,
    ) -> dict:
        """Get container logs (with ownership check)."""
        if not await self._user_owns_container(container_name, user_id):
            raise AuthorizationError("Can only view logs for your own containers")

        result = await self.mcp_client.call_tool(
            "docker",
            "logs",
            {"container_name": container_name, "tail": tail},
        )

        if not result.get("success"):
            raise ExternalServiceError("docker", result.get("error", "Failed to get logs"))

        return {
            "container_name": container_name,
            "logs": result.get("logs", ""),
        }

    async def _user_owns_container(self, container_name: str, user_id: UUID) -> bool:
        """Check if user owns the container via project_id label."""
        result = await self.mcp_client.call_tool(
            "docker",
            "inspect",
            {"container_name": container_name},
        )
        if not result.get("success"):
            return False

        labels = result.get("labels", {})
        project_id = labels.get("druppie.project_id")
        if not project_id:
            return False

        project = self.project_repo.get_by_id(UUID(project_id))
        return project and project.owner_id == user_id

    def _container_to_deployment(self, container: dict, project) -> DeploymentInfo:
        """Convert Docker container info to DeploymentInfo."""
        return DeploymentInfo(
            status=container.get("status", "unknown"),
            container_name=container.get("name", ""),
            app_url=container.get("app_url"),
            host_port=container.get("host_port"),
            started_at=container.get("started_at"),
        )
```

### 3.7 Create __init__.py

```python
"""Service layer for business logic."""

from .session_service import SessionService
from .approval_service import ApprovalService
from .question_service import QuestionService
from .project_service import ProjectService
from .deployment_service import DeploymentService

__all__ = [
    "SessionService",
    "ApprovalService",
    "QuestionService",
    "ProjectService",
    "DeploymentService",
]
```

### Verification
- [ ] All services created
- [ ] Services use repositories (not direct DB queries)
- [ ] Permission checks in services
- [ ] Services raise appropriate errors
- [ ] MCP bridge calls in deployment_service

---

# PART B: MIGRATION

## Phase 4: Migrate Sessions API

**Goal:** Refactor routes/sessions.py from 776 lines to ~50 lines.

### 4.1 Update api/deps.py with dependency injection

```python
from sqlalchemy.orm import Session
from fastapi import Depends

from ..db.session import get_db
from ..repositories import SessionRepository, ApprovalRepository
from ..services import SessionService


def get_session_repository(db: Session = Depends(get_db)) -> SessionRepository:
    return SessionRepository(db)


def get_approval_repository(db: Session = Depends(get_db)) -> ApprovalRepository:
    return ApprovalRepository(db)


def get_session_service(
    session_repo: SessionRepository = Depends(get_session_repository),
    approval_repo: ApprovalRepository = Depends(get_approval_repository),
) -> SessionService:
    return SessionService(session_repo, approval_repo)
```

### 4.2 Refactor routes/sessions.py

**Before (776 lines):**
```python
@router.get("/{session_id}")
async def get_session(session_id: UUID, db: Session, user: dict):
    session = db.query(Session).filter_by(id=session_id).first()
    if not session:
        raise HTTPException(404)
    # 500 more lines of queries and permission checks...
```

**After (~50 lines):**
```python
from fastapi import APIRouter, Depends
from uuid import UUID

from ..deps import get_current_user, get_session_service, get_user_roles
from ...services import SessionService
from ...domain import SessionDetail, SessionSummary

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """List sessions for current user."""
    sessions, total = service.list_for_user(
        user_id=UUID(user["sub"]),
        page=page,
        limit=limit,
        status=status,
    )
    return {"items": sessions, "total": total, "page": page, "limit": limit}


@router.get("/{session_id}")
async def get_session(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
) -> SessionDetail:
    """Get session detail with chat timeline."""
    return service.get_detail(
        session_id=session_id,
        user_id=UUID(user["sub"]),
        user_roles=get_user_roles(user),
    )


@router.delete("/{session_id}")
async def delete_session(
    session_id: UUID,
    service: SessionService = Depends(get_session_service),
    user: dict = Depends(get_current_user),
):
    """Delete session."""
    service.delete(
        session_id=session_id,
        user_id=UUID(user["sub"]),
        user_roles=get_user_roles(user),
    )
    return {"success": True}
```

### Verification
- [ ] All session endpoints work
- [ ] Permission checks maintained
- [ ] E2E tests pass
- [ ] Route file < 100 lines

---

## Phase 5: Migrate Approvals API

Similar pattern - update deps.py, refactor routes/approvals.py.

### Verification
- [ ] List pending approvals works
- [ ] Approve flow works (tool executes, agent resumes)
- [ ] Reject flow works
- [ ] Role checks maintained
- [ ] E2E tests pass

---

## Phase 6: Migrate Projects API

Similar pattern - refactor routes/projects.py.

### Verification
- [ ] List projects works
- [ ] Project detail works with token stats
- [ ] Delete works
- [ ] E2E tests pass

---

## Phase 7: Migrate Questions API

Similar pattern - refactor routes/questions.py.

### Verification
- [ ] List pending questions works
- [ ] Answer flow works (agent resumes)
- [ ] Ownership checks maintained
- [ ] E2E tests pass

---

# PART C: BRIDGES

## Phase 8: Workspace Bridge (Coding MCP Proxy)

**Goal:** Frontend can browse files via REST API that calls Coding MCP.

### 8.1 Create routes/workspace.py

```python
from fastapi import APIRouter, Depends
from uuid import UUID

from ..deps import get_current_user, get_mcp_bridge_service
from ...services import MCPBridgeService

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("/files")
async def list_files(
    session_id: UUID,
    path: str = "",
    service: MCPBridgeService = Depends(get_mcp_bridge_service),
    user: dict = Depends(get_current_user),
):
    """List files in workspace directory."""
    return await service.list_workspace_files(
        session_id=session_id,
        path=path,
        user_id=UUID(user["sub"]),
    )


@router.get("/file")
async def get_file(
    session_id: UUID,
    path: str,
    service: MCPBridgeService = Depends(get_mcp_bridge_service),
    user: dict = Depends(get_current_user),
):
    """Get file content."""
    return await service.read_workspace_file(
        session_id=session_id,
        path=path,
        user_id=UUID(user["sub"]),
    )
```

### Verification
- [ ] /api/workspace/files works
- [ ] /api/workspace/file works
- [ ] Session ownership verified
- [ ] Path traversal prevented

---

## Phase 9: Deployments Bridge (Docker MCP Proxy)

**Goal:** Frontend can manage containers via REST API that calls Docker MCP.

### 9.1 Create routes/deployments.py

```python
from fastapi import APIRouter, Depends
from uuid import UUID

from ..deps import get_current_user, get_deployment_service
from ...services import DeploymentService

router = APIRouter(prefix="/deployments", tags=["deployments"])


@router.get("")
async def list_deployments(
    service: DeploymentService = Depends(get_deployment_service),
    user: dict = Depends(get_current_user),
):
    """List running deployments for user."""
    deployments = await service.list_for_user(UUID(user["sub"]))
    return {"items": deployments, "total": len(deployments)}


@router.post("/{container_name}/stop")
async def stop_deployment(
    container_name: str,
    service: DeploymentService = Depends(get_deployment_service),
    user: dict = Depends(get_current_user),
):
    """Stop a deployment."""
    return await service.stop(container_name, UUID(user["sub"]))


@router.get("/{container_name}/logs")
async def get_logs(
    container_name: str,
    tail: int = 100,
    service: DeploymentService = Depends(get_deployment_service),
    user: dict = Depends(get_current_user),
):
    """Get container logs."""
    return await service.get_logs(container_name, UUID(user["sub"]), tail)
```

### Verification
- [ ] /api/deployments returns user's containers only
- [ ] /api/deployments/{name}/stop works
- [ ] /api/deployments/{name}/logs works
- [ ] Ownership verified via labels

---

# PART D: NEW FEATURES

## Phase 10: Database Schema Updates

**Goal:** Update database for new features (now built on clean foundation).

### 10.1 Add new columns to agent_runs

```sql
ALTER TABLE agent_runs ADD COLUMN run_index INTEGER DEFAULT 0;
```

### 10.2 Add new columns to tool_calls

```sql
ALTER TABLE tool_calls ADD COLUMN tool_type VARCHAR(50) DEFAULT 'mcp';
ALTER TABLE tool_calls ADD COLUMN child_agent_run_id UUID REFERENCES agent_runs(id);
```

### 10.3 Update migration file

File: `druppie/db/migrations.py`
- Add migration function for each change
- Register in migrations list

### Verification
- [ ] `run_index` column exists in agent_runs
- [ ] `tool_type` column exists in tool_calls
- [ ] `child_agent_run_id` column exists in tool_calls
- [ ] All migrations run successfully

---

## Phase 11: execute_agent Tool (Sub-Agent Support)

**Goal:** Allow agents to spawn sub-agents dynamically.

### 11.1 Add tool definition to builtin_tools.py

```python
{
    "type": "function",
    "function": {
        "name": "execute_agent",
        "description": "Execute another agent to perform a sub-task.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "ID of the agent to execute",
                },
                "task": {
                    "type": "string",
                    "description": "Task for the sub-agent",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context",
                },
            },
            "required": ["agent_id", "task"],
        },
    },
}
```

### 11.2 Implement execute_agent function

```python
async def execute_agent(
    agent_id: str,
    task: str,
    context: "ExecutionContext",
    calling_agent_id: str,
    task_context: str | None = None,
) -> dict:
    """Execute a sub-agent to perform a task."""
    # Creates nested agent_run with parent_run_id
    # Updates tool_call with child_agent_run_id
    # Runs sub-agent and returns result
    pass
```

### 11.3 Update ExecutionContext

Add `create_child_context` method for nested runs.

### Verification
- [ ] execute_agent tool works
- [ ] Creates agent_run with parent_run_id
- [ ] Updates tool_call with child_agent_run_id
- [ ] Nested runs visible in debug page

---

## Phase 12: Docker MCP (Git-Based)

**Goal:** Docker MCP clones from git, uses labels, no workspace dependency.

### 12.1 Update build tool

Remove workspace dependency, add git_url parameter:

```python
@mcp.tool()
async def build(
    image_name: str,
    git_url: str,
    branch: str = "main",
    project_id: str = None,
    dockerfile: str = "Dockerfile",
) -> dict:
    # 1. git clone <git_url> --branch <branch> /tmp/build-xxx
    # 2. docker build -t <image_name> /tmp/build-xxx
    # 3. rm -rf /tmp/build-xxx
    pass
```

### 12.2 Update run tool with labels

```python
@mcp.tool()
async def run(
    image_name: str,
    container_name: str,
    project_id: str = None,
    session_id: str = None,
    branch: str = None,
    git_url: str = None,
) -> dict:
    # Add --label druppie.project_id=xxx etc.
    pass
```

### 12.3 Update list_containers with project filter

```python
@mcp.tool()
async def list_containers(
    all: bool = False,
    project_id: str = None,
) -> dict:
    # Filter by label if project_id provided
    pass
```

### Verification
- [ ] build() clones from git URL
- [ ] run() adds druppie.* labels
- [ ] list_containers() filters by project_id
- [ ] No workspace dependency

---

# PART E: CLEANUP

## Phase 13: Folder Rename & Remove Legacy

**Goal:** Clean folder structure, remove old code.

### 13.1 Rename folders

```bash
mv druppie druppie-backend
mv frontend druppie-frontend
```

### 13.2 Remove old files

```bash
rm druppie-backend/db/crud.py  # Replaced by repositories
rm druppie-backend/api/schemas.py  # Moved to domain
```

### 13.3 Update imports and configs

- Update docker-compose.yml paths
- Update all import statements
- Update CLAUDE.md references

### Verification
- [ ] All imports work
- [ ] Docker builds work
- [ ] All tests pass
- [ ] No references to old paths

---

## Migration Checklist

### PART A: Foundation ⬜
- [ ] Phase 1: Domain Layer complete
- [ ] Phase 2: Repository Layer complete
- [ ] Phase 3: Service Layer complete

### PART B: Migration ⬜
- [ ] Phase 4: Sessions API migrated
- [ ] Phase 5: Approvals API migrated
- [ ] Phase 6: Projects API migrated
- [ ] Phase 7: Questions API migrated

### PART C: Bridges ⬜
- [ ] Phase 8: Workspace Bridge complete
- [ ] Phase 9: Deployments Bridge complete

### PART D: New Features ⬜
- [ ] Phase 10: Database schema updated
- [ ] Phase 11: execute_agent implemented
- [ ] Phase 12: Docker MCP git-based

### PART E: Cleanup ⬜
- [ ] Phase 13: Folders renamed, legacy removed

---

## Rollback Plan

Each part can be rolled back independently:

1. **Foundation:** Delete new folders, old code still works
2. **Migration:** Revert route files to direct queries
3. **Bridges:** Remove new route files
4. **New Features:** Revert MCP/core changes
5. **Cleanup:** Rename folders back

## Testing Strategy

After each phase:
1. Run unit tests
2. Run E2E tests: `cd frontend && npm run test:e2e`
3. Manual smoke test: create session, run agent, approve, check debug page

## Why This Order?

1. **Foundation first** - Clean architecture before new code
2. **Migrate before adding** - Validate architecture with existing features
3. **Bridges enable UI** - Frontend can interact with MCP tools
4. **Features last** - Built on solid foundation
5. **Cleanup at end** - Only when everything works
