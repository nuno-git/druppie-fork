"""Database module for Druppie platform.

Database design principles:
- Tables for entities we need to query (sessions, approvals, questions, etc.)
- JSONB for display-only data (tool arguments, question choices)
- SQLAlchemy models in druppie/db/models/ are the source of truth

Use repositories (druppie/repositories/) for all database access.
"""

from .database import get_db, init_db, SessionLocal, engine

from .models import (
    # Base
    Base,
    # Users
    User,
    UserRole,
    UserToken,
    # Projects
    Project,
    # Sessions
    Session,
    # Agent Runs
    AgentRun,
    # Messages
    Message,
    # Tool Calls
    ToolCall,
    # Approvals
    Approval,
    # HITL
    HitlQuestion,
    # Workspaces
    Workspace,
    # Builds & Deployments
    Build,
    Deployment,
    # LLM Tracking
    LlmCall,
    # Session Events
    SessionEvent,
)

__all__ = [
    # Database
    "get_db",
    "init_db",
    "SessionLocal",
    "engine",
    # Base
    "Base",
    # Models
    "User",
    "UserRole",
    "UserToken",
    "Project",
    "Session",
    "AgentRun",
    "Message",
    "ToolCall",
    "Approval",
    "HitlQuestion",
    "Workspace",
    "Build",
    "Deployment",
    "LlmCall",
    "SessionEvent",
]
