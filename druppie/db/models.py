"""SQLAlchemy database models for Druppie platform.

DEPRECATED: Import from druppie.db.models package instead.
This file re-exports all models for backward compatibility.

Models are now organized in druppie/db/models/:
- base.py - Base, utcnow, new_uuid
- user.py - User, UserRole, UserToken
- project.py - Project
- session.py - Session
- agent_run.py - AgentRun, Message
- tool_call.py - ToolCall
- llm_call.py - LlmCall
- approval.py - Approval
- question.py - HitlQuestion
- workspace.py - Workspace
- build.py - Build, Deployment
- event.py - SessionEvent
"""

# Re-export everything from the models package
from druppie.db.models import (
    # Base
    Base,
    utcnow,
    new_uuid,
    # User
    User,
    UserRole,
    UserToken,
    # Project
    Project,
    # Session
    Session,
    # Agent execution
    AgentRun,
    Message,
    ToolCall,
    LlmCall,
    # Approval
    Approval,
    # HITL
    HitlQuestion,
    # Workspace
    Workspace,
    # Build/Deployment
    Build,
    Deployment,
    # Event
    SessionEvent,
)

__all__ = [
    # Base
    "Base",
    "utcnow",
    "new_uuid",
    # User
    "User",
    "UserRole",
    "UserToken",
    # Project
    "Project",
    # Session
    "Session",
    # Agent execution
    "AgentRun",
    "Message",
    "ToolCall",
    "LlmCall",
    # Approval
    "Approval",
    # HITL
    "HitlQuestion",
    # Workspace
    "Workspace",
    # Build/Deployment
    "Build",
    "Deployment",
    # Event
    "SessionEvent",
]
